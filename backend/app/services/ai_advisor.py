"""Gemini advisor (advisory only: it never changes a decision, a level or a risk limit).

  * rationale for each newly logged tradable call: 2-3 plain sentences built only from the engine's own numbers;
  * a regime label (stored and shown, never used by the decision);
  * a suggestion for the give-back / trail parameters, clamped to the hard limits, applied only with AI_PARAMS=1;
  * a 1-2 sentence review when a call closes.
Only market / engine numbers are sent - never user data. Without GEMINI_API_KEY the advisor is off and everything
else works. Budget: GEMINI_DAILY_LIMIT calls per UTC day (app_settings), circuit breaker (3 failures in a row or a
429 -> pause 30 min), results cached per signal id, at most MAX_PER_TICK calls per engine cycle.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from .. import brand
from ..config import LIMITS
from ..db import Database, dumps, loads, now_ms

log = logging.getLogger(__name__)
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-2.5-flash-lite"]
TIMEOUT_S = 12.0
DAILY_LIMIT_DEFAULT = 150
MAX_PER_TICK = 8
BREAKER_FAILS = 3
PAUSE_MS = 30 * 60_000
MAX_RATIONALE = 480
MAX_REVIEW = 300
MAX_REGIME = 40

SYSTEM_PROMPT = (
    f"You are the analysis assistant of {brand.NAME} ({brand.DISPLAY_URL}, {brand.SUPPORT_EMAIL}). "
    "You write short, plain-language notes about crypto market analyses for members. Analysis only, not financial "
    "advice. Never promise or imply guaranteed profit, certainty or safety. Use ONLY the numbers given in the input; "
    "never invent prices, percentages, probabilities or facts that are not in it. Never mention any other website, "
    "email address, phone number, social media account or contact. No emojis, no hashtags. Answer in the JSON schema.")

BANNED = re.compile(
    r"guarantee|risk[\s-]*free|sure[\s-]*(profit|win|thing|bet)|can'?t lose|cannot lose|no[\s-]*risk|"
    r"certain(ly)? (profit|win|gain)|100\s*%\s*(win|profit|sure|safe)|easy money|get rich|financial advice is|"
    r"double your", re.I)
URL_RE = re.compile(r"(https?://|www\.)\S+|\b[\w.-]+\.(com|net|org|io|ai|co|xyz|app|me|gg|ly)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CONTACT_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)|@\w{3,}|telegram|whatsapp|discord|twitter|instagram|t\.me", re.I)


def clean_text(text: Any, cap: int) -> str | None:
    """Post-filter: drop text with promises of profit, foreign links, emails or contacts; enforce the length cap."""
    if not isinstance(text, str):
        return None
    t = " ".join(text.split()).strip()
    if not t:
        return None
    if BANNED.search(t):
        return None
    allowed_urls = {brand.DISPLAY_URL.lower(), "cryptointelai.com", brand.URL.lower()}
    for m in URL_RE.finditer(t):
        if m.group(0).lower().rstrip(".,)") not in allowed_urls:
            return None
    for m in EMAIL_RE.finditer(t):
        if m.group(0).lower().rstrip(".,)") != brand.SUPPORT_EMAIL:
            return None
    t_no_brand = t.replace(brand.SUPPORT_EMAIL, "")
    if CONTACT_RE.search(t_no_brand):
        return None
    if len(t) > cap:
        cut = t[:cap]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        t = cut[:end + 1] if end > cap // 3 else cut.rstrip() + "…"
    return t


def clamp_params(sug: Any) -> dict[str, float] | None:
    if not isinstance(sug, dict):
        return None
    out = {}
    for k in ("giveback_arm_r", "giveback_frac", "trail_atr_k"):
        v = sug.get(k)
        if isinstance(v, (int, float)) and v == v:
            lo, hi = LIMITS[k]
            out[k] = float(min(hi, max(lo, float(v))))
    return out or None


class Advisor:
    def __init__(self, db: Database, api_key: str | None = None, model: str | None = None, client: Any = None,
                 daily_limit: int | None = None):
        self.db = db
        self.key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = (model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL).strip()
        try:
            self.daily_limit = int(daily_limit if daily_limit is not None else os.environ.get("GEMINI_DAILY_LIMIT", DAILY_LIMIT_DEFAULT))
        except ValueError:
            self.daily_limit = DAILY_LIMIT_DEFAULT
        self._client = client
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    # ---- budget and breaker ---------------------------------------------------------------------------------
    def _state(self) -> dict[str, Any]:
        return self.db.get_setting("gemini_state", {}) or {}

    def _save(self, st: dict[str, Any]) -> None:
        self.db.set_setting("gemini_state", st)

    def available(self, now: int | None = None) -> bool:
        if not self.enabled:
            return False
        now = now or now_ms()
        st = self._state()
        if int(st.get("paused_until") or 0) > now:
            return False
        day = time.strftime("%Y-%m-%d", time.gmtime(now / 1000))
        used = int(st.get("count") or 0) if st.get("day") == day else 0
        return used < self.daily_limit

    def _spend(self, now: int) -> None:
        st = self._state()
        day = time.strftime("%Y-%m-%d", time.gmtime(now / 1000))
        if st.get("day") != day:
            st = {**st, "day": day, "count": 0}
        st["count"] = int(st.get("count") or 0) + 1
        self._save(st)

    def _result(self, ok: bool, now: int, rate_limited: bool = False) -> None:
        st = self._state()
        if ok:
            st["fails"] = 0
        else:
            st["fails"] = int(st.get("fails") or 0) + 1
            if rate_limited or st["fails"] >= BREAKER_FAILS:
                st["paused_until"] = now + PAUSE_MS
                st["fails"] = 0
        self._save(st)

    # ---- one call -----------------------------------------------------------------------------------------------
    def _http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=TIMEOUT_S)
        return self._client

    def generate(self, task: str, data: dict[str, Any], schema: dict[str, Any], now: int | None = None) -> dict[str, Any] | None:
        """One JSON answer, or None (disabled, over budget, paused, HTTP / parse failure)."""
        now = now or now_ms()
        if not self.available(now):
            return None
        body = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": f"{task}\nINPUT (engine numbers only):\n{dumps(data)}"}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                     "responseSchema": schema, "maxOutputTokens": 400}}
        # the configured model first; only if it answers 404 (unknown model) are the fallbacks tried, once each
        models = [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        r = None
        for i, model in enumerate(models):
            if i > 0 and not self.available(now):
                return None
            self._spend(now)
            self.calls += 1
            try:
                r = self._http().post(ENDPOINT.format(model=model), json=body,
                                      headers={"x-goog-api-key": self.key, "Content-Type": "application/json"},
                                      timeout=TIMEOUT_S)
            except Exception as exc:
                log.warning("gemini request failed: %s", type(exc).__name__)
                self._result(False, now)
                return None
            if getattr(r, "status_code", 0) != 404:
                self.model = model
                break
        code = getattr(r, "status_code", 0)
        if code == 429:
            self._result(False, now, rate_limited=True)
            return None
        if code != 200:
            self._result(False, now)
            return None
        out = self._parse(r)
        self._result(out is not None, now)
        return out

    @staticmethod
    def _parse(r: Any) -> dict[str, Any] | None:
        try:
            j = r.json()
            text = j["candidates"][0]["content"]["parts"][0]["text"]
            out = json.loads(text)
            return out if isinstance(out, dict) else None
        except Exception:
            return None

    # ---- uses -------------------------------------------------------------------------------------------------
    def rationale(self, inputs: dict[str, Any], now: int | None = None) -> dict[str, Any] | None:
        schema = {"type": "OBJECT", "properties": {"rationale": {"type": "STRING"}, "regime": {"type": "STRING"},
                                                   "params": {"type": "OBJECT", "properties": {
                                                       "giveback_arm_r": {"type": "NUMBER"}, "giveback_frac": {"type": "NUMBER"},
                                                       "trail_atr_k": {"type": "NUMBER"}}}},
                  "required": ["rationale", "regime"]}
        lim = {k: LIMITS[k] for k in ("giveback_arm_r", "giveback_frac", "trail_atr_k")}
        out = self.generate(
            "Write 'rationale': 2-3 plain sentences explaining this trade call to a member, using only the input values "
            "(decision, grade, confidence, regime, trend and momentum scores, entry/stop/targets in R, risk notes). "
            "Write 'regime': a market-regime label of at most 4 words. Optionally 'params': trade-management values "
            f"within these limits {dumps(lim)}.", inputs, schema, now)
        if not out:
            return None
        rat = clean_text(out.get("rationale"), MAX_RATIONALE)
        if not rat:
            return None
        return {"rationale": rat, "regime": clean_text(out.get("regime"), MAX_REGIME), "params": clamp_params(out.get("params")),
                "model": self.model, "at": now or now_ms()}

    def review(self, inputs: dict[str, Any], now: int | None = None) -> str | None:
        schema = {"type": "OBJECT", "properties": {"review": {"type": "STRING"}}, "required": ["review"]}
        out = self.generate("Write 'review': 1-2 plain sentences reviewing how this closed call went, using only the "
                            "input values (status, exit reason, return in R and %, best open profit).", inputs, schema, now)
        return clean_text((out or {}).get("review"), MAX_REVIEW)


def _inputs(s: dict[str, Any], pay: dict[str, Any]) -> dict[str, Any]:
    risk = abs(float(s["entry"]) - float(s["stop"])) if s.get("entry") and s.get("stop") else None
    r_of = (lambda px: round((px - s["entry"]) * s["side"] / risk, 2) if px and risk else None)
    ai_in = pay.get("ai_inputs") or {}
    return {"symbol": s["symbol"].split("/")[0], "timeframe": s["timeframe"], "decision": s["decision"],
            "grade": pay.get("grade"), "confidence": s.get("confidence"), "regime": s.get("regime"),
            "trend_score": ai_in.get("trend"), "momentum_score": ai_in.get("momentum"),
            "volatility": ai_in.get("volatility"), "risk_pct": ai_in.get("risk_pct"),
            "stop_r": -1.0, "targets_r": [r_of(s.get("tp1")), r_of(s.get("tp2")), r_of(s.get("tp3"))],
            "risk_reward": s.get("rr"), "fill": s.get("fill_status"),
            "risk_notes": (ai_in.get("warnings") or [])[:4]}


def run(db: Database, advisor: Advisor | None = None, max_calls: int = MAX_PER_TICK, now: int | None = None) -> dict[str, Any]:
    """Engine tick: notes for new calls and reviews for closed ones (bounded; cached in the signal payload)."""
    from . import tracking
    adv = advisor or Advisor(db)
    out = {"enabled": adv.enabled, "rationales": 0, "reviews": 0, "params_applied": 0}
    if not adv.enabled:
        return out
    now = now or now_ms()
    since = now - 2 * 86_400_000
    todo = db.query("SELECT * FROM signals WHERE side != 0 AND (created_at >= ? OR closed_at >= ?) "
                    "ORDER BY created_at DESC LIMIT 60", (since, since))
    for s in todo:
        if adv.calls >= max_calls or not adv.available(now):
            break
        pay = loads(s.get("payload"), {}) or {}
        ai = pay.get("ai") or {}
        changed = False
        if not ai.get("rationale") and not ai.get("failed_rationale"):
            res = adv.rationale(_inputs(s, pay), now)
            if res:
                params = res.pop("params", None)
                ai = {**ai, **res}
                out["rationales"] += 1
                tracking.log_decision(db, "ai_rationale", s["symbol"], s["timeframe"], s["id"],
                                      {"regime": res.get("regime"), "model": res["model"]}, ai_rationale=res["rationale"], ts=now)
                if params:
                    from ..config import settings
                    db.set_setting("ai_manage_suggestion", {**params, "at": now, "signal_id": s["id"]})
                    if settings.ai_params:
                        db.set_setting("ai_manage_params", params)
                        out["params_applied"] += 1
                    tracking.log_decision(db, "ai_params_applied" if settings.ai_params else "ai_params_suggested",
                                          s["symbol"], s["timeframe"], s["id"], {"params": params}, ts=now)
            else:
                ai = {**ai, "failed_rationale": now}
            changed = True
        elif s["status"] not in ("OPEN", "INFO") and s.get("return_pct") is not None and not ai.get("review") \
                and not ai.get("failed_review") and ai.get("rationale"):
            risk_pct = abs(s["entry"] - s["stop"]) / s["entry"] * 100 if s.get("entry") and s.get("stop") else None
            rev = adv.review({**_inputs(s, pay), "status": s["status"], "exit_reason": s.get("exit_reason"),
                              "return_pct": round(s["return_pct"], 3),
                              "return_r": round(s["return_pct"] / risk_pct, 2) if risk_pct else None,
                              "peak_r": s.get("peak_r")}, now)
            ai = {**ai, "review": rev} if rev else {**ai, "failed_review": now}
            out["reviews"] += int(bool(rev))
            changed = True
        if changed:
            pay["ai"] = {k: v for k, v in ai.items()}
            db.execute("UPDATE signals SET payload = ? WHERE id = ?", (dumps(pay), s["id"]))
    out["calls"] = adv.calls
    return out
