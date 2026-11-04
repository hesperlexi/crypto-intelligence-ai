"""v2.19 Trade Guardian (owner-approved 4 Nov 2026): RECOMMEND-ONLY early warnings on open public calls, for the admin.

Every engine tick (GitHub Actions: about every 5 minutes; it cannot reliably run more often) the Guardian looks at each
OPEN, FILLED public call (`signals`, also after TP1) and asks: is this trade turning against us before the stop is hit?

1. Detection - the RULES decide (deterministic; thresholds below):
   * fresh 1-minute candles (Binance spot data-api through the engine's provider; only coins with open calls + BTC; an
     incremental SQLite cache `guardian_m1`, so each request returns a handful of new candles);
   * adverse move over the last 5 / 15 / 60 minutes in ATR (15m ATR, the record's path timeframe) and in R;
   * distance to the stop in force (admin stop, break-even after TP1, TP1 after TP2 - engine/manage rules) in R;
   * give-back from the best open profit (peak R) after TP1;
   * BTC shock against the trade (1-minute and 15-minute BTC move), not for BTC / gold calls;
   * volatility spike (1m realised volatility of the last 15 minutes vs the 60 minutes before) while moving against us;
   * momentum flip on the call's own timeframe (the latest analysis now calls the opposite side, or the grade is lost);
   * funding shock (optional, estimate: the latest stored funding vs its 30-day spread, against the position).
   Points add up to a severity 0-100 with transparent reasons. <50 nothing, 50-74 TIGHTEN (a proposed stop that only
   tightens, from 1m structure / ATR, validated), >=75 CLOSE NOW.
2. Gemini (services/ai_advisor.Advisor): second opinion and plain-English explanation only, from the computed numbers.
   It may DOWNGRADE (CLOSE -> TIGHTEN, TIGHTEN -> no action) but never upgrade or invent a level; an answer with numbers
   not in the input, predictions or advice language is rejected (briefing.acceptable-style checks). Gemini unavailable /
   over budget (briefing.ai_room keeps the daily reserve) -> the rules' recommendation with a template explanation. The
   path used is stored (`ai.path`: ai_agreed | ai_downgraded | rules_only | ai_rejected).
3. Validation before the admin sees it: 1m data <= 3 min old, the call's analysis no older than its refresh interval
   (stale -> NO recommendation, counted "skipped: stale"), the 1m price within 2 % of the engine's price, the proposed
   stop strictly tighter than the stop in force, on the right side of the price by >= 0.2 ATR and accepted by
   adjust.validate (what Apply will run). Recommendations expire after 30 minutes.
4. Approval: the admin page sends the normal `adjust_signal` job (stop, or action close) with `guardian_id`. The engine
   re-validates (admin only, still live and not expired, call still open, not changed since, levels still valid at its
   price) and then runs exactly adjust.apply / adjust.close (same checks, bots, Hesper, member notifications). The
   recommendation is marked applied or rejected with the reason. "Dismiss" = job `guardian_dismiss` (admin only).
5. Never automatic: nothing here changes a call, a stop, a target or a time limit. Errors are caught and counted.
6. Dedupe: one recommendation per call per escalation level; a new one only when the level rises, or after the previous
   one expired / was rejected while the conditions persisted for PERSIST_TICKS ticks. Stored in SQLite and mirrored in
   the admin-only `views/guardian` document (restored once if the engine state is lost).
7. Shadow evidence: when a call closes, every recommendation (applied or not) gets the call's net R with vs without
   it (tracking.evaluate_signal with / without the change at the recommendation's time). Never touches the record.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from typing import Any, Callable

from ..db import Database, dumps, loads, new_id, now_ms
from ..pricefmt import fmt_price

log = logging.getLogger(__name__)

# ---- switches and thresholds (config constants) --------------------------------------------------------------------
ENABLED = os.environ.get("GUARDIAN", "1") != "0"     # admin-only output, recommend-only; GUARDIAN=0 switches it off
MIN = 60_000
M1_BARS = 100                       # 1-minute candles used per coin (60-minute window + 15/60 volatility baseline)
M1_KEEP_MS = 3 * 3_600_000          # cache kept this long
FRESH_M1_MS = 3 * MIN               # the newest 1m candle must have closed within 3 minutes
# the call's analysis must be no older than its refresh interval (15m / 1h / 4h every tick, 12h / 1d / 3d hourly) + slack
ANALYSIS_MAX_AGE_MS = {"15m": 20 * MIN, "1h": 20 * MIN, "4h": 20 * MIN, "12h": 75 * MIN, "1d": 75 * MIN,
                       "3d": 75 * MIN}
PRICE_SANITY_PCT = 2.0              # 1m price vs the engine's live / 15m price
ATR_TF = "15m"
ATR_N = 14

WINDOWS = (5, 15, 60)                                  # minutes
MOVE_ATR = {5: 0.6, 15: 1.0, 60: 1.5}                  # adverse move (ATR) that earns the full MOVE_PTS
MOVE_PTS = 30
NEAR_STOP = ((0.25, 25), (0.5, 15), (0.75, 5))         # distance to the stop in force (R) -> points (halved after TP1)
GIVEBACK_MIN_PEAK_R = 1.0
GIVEBACK = ((0.75, 25), (0.5, 15))                     # share of the peak given back after TP1 -> points
BTC_1M_PCT, BTC_1M_PTS = 0.6, 15
BTC_15M_PCT, BTC_15M_PTS = 1.5, 20
NO_BTC_FACTOR = ("BTC/USDT", "PAXG/USDT")
VOL_RECENT, VOL_BASE = 15, 60
VOL_SPIKE = ((4.0, 15), (2.5, 10))                     # realised-vol ratio -> points (only while moving against)
FLIP_PTS, GRADE_LOST_PTS = 25, 8
FUNDING_Z, FUNDING_PTS = 3.0, 5
TIGHTEN_AT, CLOSE_AT = 50, 75

STRUCT_BARS = 15                    # proposed stop: beyond the 15-minute 1m extreme ...
STRUCT_BUF_ATR = 0.1                # ... by 0.1 ATR, or 1 ATR from the price - whichever is tighter
TIGHT_ATR_K = 1.0
PROPOSE_GAP_ATR = 0.3               # never proposed closer than 0.3 ATR to the price
MIN_GAP_ATR = 0.2                   # validated (and re-validated at approval) at >= 0.2 ATR from the price
MIN_IMPROVE_R = 0.05                # at least 0.05 R tighter than the stop in force

EXPIRES_MS = 30 * MIN
APPROVE_GRACE_MS = 10 * MIN         # a click before expiry is still honoured by the next tick (re-validated)
PERSIST_TICKS = 3
MAX_AI_PER_TICK = 3
MAX_EXPLAIN = 420
HISTORY_IN_VIEW = 50
VIEW = "guardian"
STATE = "guardian_state"
MIRROR_CHECKED = "guardian_mirror_checked"
LEVELS = ("TIGHTEN", "CLOSE")
RANK = {"NONE": 0, "TIGHTEN": 1, "CLOSE": 2}
SHADOW_GIVE_UP_MS = 3 * 86_400_000
NOTE_TIGHTEN = "Trade Guardian: stop tightened after a sharp move against the trade."
NOTE_CLOSE = "Trade Guardian: closed early after a sharp move against the trade."

ADVICE_RE = re.compile(
    r"\b(you should|you must|i (would )?(recommend|suggest|advise)|we (recommend|suggest|advise)|my advice|"
    r"buy now|sell now|go (long|short)|open a (new )?(long|short)|add to the position|double down|re-?enter|"
    r"upgrade)\b", re.I)


class GuardianError(ValueError):
    """A plain-language reason a Guardian approval was refused."""


# ---- small helpers ------------------------------------------------------------------------------------------------
def _f(v: Any, dp: int = 2) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, dp) if math.isfinite(x) else None


def _sig_round(x: float, sig: int = 6) -> float:
    if not x or not math.isfinite(x):
        return x
    return round(x, max(0, sig - 1 - int(math.floor(math.log10(abs(x))))))


def coin(sym: str) -> str:
    b = str(sym).split("/")[0]
    return "GOLD" if b == "PAXG" else b


def band_of(sev: int) -> str | None:
    return "CLOSE" if sev >= CLOSE_AT else "TIGHTEN" if sev >= TIGHTEN_AT else None


def _day(now: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now / 1000))


def stop_in_force(sig: dict[str, Any], adj: list[dict[str, Any]]) -> float:
    """The stop the record applies now: the published stop, the admin's stop before TP1, after TP1 the more protective
    of the admin stop and the rule stop (break-even after TP1, TP1 after TP2; runner: TP2 after TP3)."""
    from ..engine import manage as M
    from . import tracking
    side = int(sig["side"])
    cur = tracking.current_levels(sig, adj)
    pay = loads(sig.get("payload"), {}) if isinstance(sig.get("payload"), str) else (sig.get("payload") or {})
    runner = bool(((pay or {}).get("runner") or {}).get("on"))
    if runner and sig.get("tp3_hit"):
        rule = float(sig["tp2"])
    elif sig.get("tp2_hit"):
        rule = float(cur["tp1"])
    elif sig.get("tp1_hit"):
        rule = float(sig["entry"])
    else:
        rule = float(sig["stop"])
    admin = next((float(a["new"]) for a in reversed(adj) if a["field"] == "stop"), None)
    return float(M.effective_stop(side, rule, admin, bool(sig.get("tp1_hit"))))


def atr_of(df: Any, n: int = ATR_N) -> float | None:
    """Simple ATR (mean true range of the last n closed candles)."""
    if df is None or len(df) < n + 1:
        return None
    h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(len(df) - n, len(df))]
    v = sum(tr) / n
    return v if v > 0 and math.isfinite(v) else None


def _rows(m1: Any) -> list[tuple[int, float, float, float, float]]:
    if m1 is None:
        return []
    if hasattr(m1, "itertuples"):
        return [(int(t), float(o), float(h), float(l), float(c))
                for t, o, h, l, c in zip(m1["ts"], m1["open"], m1["high"], m1["low"], m1["close"])]
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in m1]


def _close_ago(rows: list[tuple], minutes: int) -> float | None:
    """Close of the candle `minutes` before the newest one (nearest earlier candle if one is missing)."""
    if not rows:
        return None
    target = rows[-1][0] - minutes * MIN
    best = None
    for r in rows:
        if r[0] <= target:
            best = r[4]
        else:
            break
    return best


def realised_vol_ratio(rows: list[tuple]) -> float | None:
    """Std of 1m log returns of the last VOL_RECENT minutes / the VOL_BASE minutes before them."""
    closes = [r[4] for r in rows]
    if len(closes) < VOL_RECENT + VOL_BASE + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0 and closes[i] > 0]
    recent, base = rets[-VOL_RECENT:], rets[-(VOL_RECENT + VOL_BASE):-VOL_RECENT]

    def sd(x: list[float]) -> float:
        m = sum(x) / len(x)
        return math.sqrt(sum((v - m) ** 2 for v in x) / max(1, len(x) - 1))
    b = sd(base)
    return sd(recent) / b if b > 0 else None


def fresh(rows: list[tuple], now: int) -> bool:
    """The newest 1m candle closed no more than FRESH_M1_MS ago (the forming candle counts as fresh)."""
    return bool(rows) and now - (rows[-1][0] + MIN) <= FRESH_M1_MS


def side_of(decision: Any) -> int:
    d = str(decision or "")
    return 1 if d in ("BUY", "BUY ON PULLBACK") else -1 if d == "SELL" else 0


# ---- 1. detection (pure) ------------------------------------------------------------------------------------------
def assess(call: dict[str, Any], rows: list[tuple], atr: float, stop_if: float, memo: dict[str, Any] | None,
           btc_rows: list[tuple] | None = None, funding_z: float | None = None) -> dict[str, Any]:
    """Severity 0-100, reasons [{code, label, points}] and the numbers behind them. Pure and deterministic.
    `call`: signal row (side, entry, stop = ORIGINAL stop, tp1_hit, peak_r, timeframe, symbol, payload grade)."""
    side, entry = int(call["side"]), float(call["entry"])
    risk = abs(entry - float(call["stop"]))
    price = rows[-1][4]
    r_now = side * (price - entry) / risk if risk else 0.0
    tp1 = bool(call.get("tp1_hit"))
    reasons: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"coin": coin(call["symbol"]), "timeframe": str(call["timeframe"]).upper(),
                             "side": "long" if side > 0 else "short", "tp1_hit": tp1, "price": _sig_round(price),
                             "entry": _sig_round(entry), "stop_in_force": _sig_round(stop_if),
                             "r_now": _f(r_now), "atr_15m": _sig_round(atr)}

    # adverse moves (5 / 15 / 60 min) in ATR and R
    moves, best = {}, (0.0, None, 0.0)
    for w in WINDOWS:
        c0 = _close_ago(rows, w)
        if c0 is None:
            continue
        adv = -side * (price - c0)
        moves[f"{w}m"] = {"atr": _f(adv / atr), "r": _f(adv / risk) if risk else None}
        ratio = (adv / atr) / MOVE_ATR[w]
        if ratio > best[0]:
            best = (ratio, w, adv / atr)
    facts["moves_against"] = moves
    if best[1] is not None and best[0] >= 0.5:
        pts = min(MOVE_PTS, int(round(MOVE_PTS * (best[0] - 0.5) / 0.5)))
        if pts > 0:
            reasons.append({"code": "move", "points": pts,
                            "label": f"Moved {abs(best[2]):.2f} ATR against in {best[1]} min"})

    # distance to the stop in force (R); after TP1 the stop is at least break-even, so it weighs half
    dist_r = side * (price - stop_if) / risk if risk else None
    facts["stop_distance_r"] = _f(dist_r)
    if dist_r is not None:
        for lim, pts in NEAR_STOP:
            if dist_r <= lim:
                pts = pts // 2 if tp1 else pts
                reasons.append({"code": "near_stop", "points": pts,
                                "label": f"{max(0.0, dist_r):.2f}R from the {'protected ' if tp1 else ''}stop"})
                break

    # give-back after TP1 from the best open profit
    peak = max(float(call.get("peak_r") or 0.0), max((side * ((r[2] if side > 0 else r[3]) - entry) / risk
                                                      for r in rows[-STRUCT_BARS:]), default=0.0) if risk else 0.0)
    facts["peak_r"] = _f(peak)
    if tp1 and peak >= GIVEBACK_MIN_PEAK_R:
        gb = (peak - r_now) / peak
        facts["giveback_pct"] = _f(gb * 100, 0)
        for lim, pts in GIVEBACK:
            if gb >= lim:
                reasons.append({"code": "giveback", "points": pts,
                                "label": f"Gave back {gb * 100:.0f}% of the {peak:.2f}R peak"})
                break

    # BTC shock against the trade
    if btc_rows and call["symbol"] not in NO_BTC_FACTOR:
        bp = btc_rows[-1][4]
        b1, b15 = _close_ago(btc_rows, 1), _close_ago(btc_rows, 15)
        m1 = (bp / b1 - 1) * 100 if b1 else None
        m15 = (bp / b15 - 1) * 100 if b15 else None
        facts["btc"] = {"move_1m_pct": _f(m1), "move_15m_pct": _f(m15)}
        hits = []
        if m15 is not None and -side * m15 >= BTC_15M_PCT:
            hits.append((BTC_15M_PTS, f"BTC {m15:+.2f}% in 15 min"))
        if m1 is not None and -side * m1 >= BTC_1M_PCT:
            hits.append((BTC_1M_PTS, f"BTC {m1:+.2f}% in 1 min"))
        if hits:
            pts, label = max(hits)
            reasons.append({"code": "btc", "points": pts, "label": label})

    # volatility spike while moving against us
    vr = realised_vol_ratio(rows)
    facts["vol_ratio"] = _f(vr)
    adv15 = (moves.get("15m") or {}).get("atr") or 0.0
    if vr is not None and adv15 > 0:
        for lim, pts in VOL_SPIKE:
            if vr >= lim:
                reasons.append({"code": "volatility", "points": pts, "label": f"Volatility {vr:.1f}x normal"})
                break

    # momentum on the call's own timeframe
    if memo:
        s_now = int(memo.get("side") if memo.get("side") is not None else side_of(memo.get("decision")))
        grade = (loads(call.get("payload"), {}) if isinstance(call.get("payload"), str) else (call.get("payload") or {})).get("grade")
        facts["analysis_now"] = {"decision": memo.get("decision"), "grade": memo.get("grade")}
        tf = str(call["timeframe"]).upper()
        if s_now == -side:
            reasons.append({"code": "flip", "points": FLIP_PTS,
                            "label": f"{tf} analysis flipped to {'SELL' if side > 0 else 'BUY'}"})
        elif s_now != side or (grade == "A" and memo.get("grade") not in ("A",)):
            reasons.append({"code": "grade_lost", "points": GRADE_LOST_PTS,
                            "label": f"{tf} {'grade ' + str(grade) if grade else 'call'} no longer confirmed"})

    # funding shock (optional, estimate)
    if funding_z is not None and side * funding_z >= FUNDING_Z:
        facts["funding_z"] = _f(funding_z)
        reasons.append({"code": "funding", "points": FUNDING_PTS, "estimate": True,
                        "label": f"Funding {abs(funding_z):.1f} sd against (estimate)"})

    reasons.sort(key=lambda r: -r["points"])
    sev = int(min(100, sum(r["points"] for r in reasons)))
    facts["severity"] = sev
    return {"severity": sev, "band": band_of(sev), "reasons": reasons, "facts": facts, "price": price,
            "r_now": r_now, "risk": risk}


def propose_stop(side: int, price: float, rows: list[tuple], atr: float, stop_if: float, risk: float) -> float | None:
    """A tighter stop from 1m structure / ATR, or None when none is valid (never looser, never at/through the price,
    at least PROPOSE_GAP_ATR from it and MIN_IMPROVE_R tighter than the stop in force)."""
    recent = rows[-STRUCT_BARS:]
    if not recent or atr <= 0:
        return None
    if side > 0:
        struct = min(r[3] for r in recent) - STRUCT_BUF_ATR * atr
        cand = min(max(struct, price - TIGHT_ATR_K * atr), price - PROPOSE_GAP_ATR * atr)
    else:
        struct = max(r[2] for r in recent) + STRUCT_BUF_ATR * atr
        cand = max(min(struct, price + TIGHT_ATR_K * atr), price + PROPOSE_GAP_ATR * atr)
    cand = _sig_round(cand)
    if side * (cand - stop_if) < MIN_IMPROVE_R * risk:
        return None
    return cand


def stop_problem(side: int, proposed: float | None, stop_if: float, price: float, atr: float) -> str | None:
    """Pure: why a proposed stop is not acceptable (None = fine)."""
    if proposed is None or not math.isfinite(proposed) or proposed <= 0:
        return "no valid tighter stop"
    if side * (proposed - stop_if) <= 0:
        return "the proposed stop is not tighter than the stop in force"
    if side * (price - proposed) <= 0:
        return "the proposed stop is on the wrong side of the current price"
    if side * (price - proposed) < MIN_GAP_ATR * atr:
        return f"the proposed stop is closer than {MIN_GAP_ATR} ATR to the price"
    return None


# ---- 2. Gemini: second opinion + explanation --------------------------------------------------------------------
AI_TASK = ("You are a risk assistant for the admin of a crypto signals app. The engine's rules flagged an open trade. "
           "Write 'explanation': 2 to 3 plain sentences in British English explaining, using ONLY the input numbers, why "
           "the rules flagged it. Then give 'verdict': 'agree' if the rules' action fits the facts, or 'downgrade' if the "
           "facts look weaker than the action (a downgrade moves CLOSE to TIGHTEN or TIGHTEN to no action). You can never "
           "make the action stronger. Do NOT predict prices, do NOT give advice, do NOT propose any price level and do "
           "NOT write any number that is not in the input. No emojis, no lists.")
AI_SCHEMA = {"type": "OBJECT", "properties": {"explanation": {"type": "STRING"},
                                              "verdict": {"type": "STRING", "enum": ["agree", "downgrade"]}},
             "required": ["explanation", "verdict"]}


def ai_inputs(facts: dict[str, Any], reasons: list[dict[str, Any]], level: str, proposed: float | None) -> dict[str, Any]:
    return {**facts, "reasons": [r["label"] for r in reasons], "rules_action": level,
            **({"proposed_stop": proposed} if proposed is not None and level == "TIGHTEN" else {})}


def ai_acceptable(out: Any, data: dict[str, Any]) -> tuple[str, str] | None:
    """(verdict, text) or None when the answer must be rejected (bad verdict, numbers not in the input, predictions,
    advice or contact text, not 2-3 sentences)."""
    from .briefing import PREDICT_RE, numbers_ok
    from .ai_advisor import clean_text
    if not isinstance(out, dict) or out.get("verdict") not in ("agree", "downgrade"):
        return None
    t = clean_text(out.get("explanation"), MAX_EXPLAIN)
    if not t or PREDICT_RE.search(t) or ADVICE_RE.search(t) or not numbers_ok(t, data):
        return None
    n = len(re.findall(r"[.!?](\s|$)", t))
    return (out["verdict"], t) if 2 <= n <= 3 else None


def template(level: str, sev: int, reasons: list[dict[str, Any]], proposed: float | None) -> str:
    why = "; ".join(r["label"] for r in reasons[:4]) or "no single strong reason"
    act = ("close the trade now" if level == "CLOSE" else
           f"tighten the stop to {fmt_price(proposed)}" if level == "TIGHTEN" and proposed is not None else "no action")
    return (f"Severity {sev} of 100 from the rules: {why}. The rules suggest to {act}. Nothing changes unless you apply it.")


def downgrade(level: str) -> str:
    return "TIGHTEN" if level == "CLOSE" else "NONE"


def second_opinion(adv: Any, facts: dict[str, Any], reasons: list[dict[str, Any]], level: str,
                   proposed: float | None, now: int) -> dict[str, Any]:
    """{level, path, text, model}. The level is the rules' level or one step lower; never higher."""
    from .briefing import ai_room
    rules_text = template(level, facts.get("severity", 0), reasons, proposed)
    if adv is None or not getattr(adv, "enabled", False) or not ai_room(adv, now):
        return {"level": level, "path": "rules_only", "text": rules_text, "model": None}
    data = ai_inputs(facts, reasons, level, proposed)
    try:
        out = adv.generate(AI_TASK, data, AI_SCHEMA, now)
    except Exception as exc:                                  # Gemini is optional
        log.warning("guardian AI failed: %s", type(exc).__name__)
        out = None
    if out is None:
        return {"level": level, "path": "rules_only", "text": rules_text, "model": None}
    ok = ai_acceptable(out, data)
    if ok is None:
        return {"level": level, "path": "ai_rejected", "text": rules_text, "model": getattr(adv, "model", None)}
    verdict, text = ok
    if verdict == "downgrade":
        return {"level": downgrade(level), "path": "ai_downgraded", "text": text, "model": getattr(adv, "model", None)}
    return {"level": level, "path": "ai_agreed", "text": text, "model": getattr(adv, "model", None)}


# ---- 6. dedupe ------------------------------------------------------------------------------------------------------
BLOCKING = ("live", "applied", "dismissed")      # these stop a new recommendation at the same level (escalation only)


def should_create(prev: list[dict[str, Any]], band: str | None, streak: int) -> tuple[bool, str | None]:
    """(create?, id of a live lower-level recommendation to supersede). `prev`: this call's recommendations."""
    if band is None:
        return False, None
    live = [p for p in prev if p["status"] == "live"]
    if live:
        top = max(live, key=lambda p: RANK[p["rules_level"]])
        if RANK[band] > RANK[top["rules_level"]]:
            return True, top["id"]                       # escalation: TIGHTEN -> CLOSE
        return False, None
    same = sorted((p for p in prev if p["rules_level"] == band), key=lambda p: p["created_at"])
    if not same:
        return True, None
    last = same[-1]
    if last["status"] in BLOCKING:
        return False, None
    return streak >= PERSIST_TICKS, None                 # expired / rejected / void / downgraded: conditions persisted


# ---- the engine step --------------------------------------------------------------------------------------------
class Guardian:
    def __init__(self, rt: Any, sink: Any = None, fetch: Callable[[str, int, int], list] | None = None,
                 advisor: Any = None, now: int | None = None):
        self.rt, self.db, self.sink = rt, rt.db, sink
        self.now = int(now or now_ms())
        self._fetch = fetch
        self._advisor = advisor
        self.ai_calls = 0

    # -- state ---------------------------------------------------------------------------------------------------
    def state(self) -> dict[str, Any]:
        st = self.db.get_setting(STATE, {}) or {}
        day = _day(self.now)
        if st.get("day") != day:
            st = {**st, "day": day, "today": {"checks": 0, "skipped_stale": 0, "skipped_price": 0, "errors": 0,
                                              "created": 0, "ai_calls": 0, "no_valid_stop": 0}}
        st.setdefault("memo", {})
        st.setdefault("calls", {})
        return st

    def save(self, st: dict[str, Any]) -> None:
        self.db.set_setting(STATE, st)

    # -- data ----------------------------------------------------------------------------------------------------
    def fetch(self, symbol: str, since: int, limit: int) -> list:
        if self._fetch is not None:
            return self._fetch(symbol, since, limit)
        prov = getattr(self.rt, "provider", None)
        if prov is None or not hasattr(prov, "fetch_ohlcv"):
            raise ConnectionError("no market data provider")
        return asyncio.run(prov.fetch_ohlcv(symbol, "1m", since=since, limit=limit))

    def m1(self, symbol: str) -> list[tuple]:
        """Newest M1_BARS 1-minute candles: cached in SQLite, only the missing tail is requested (one request)."""
        last = self.db.one("SELECT MAX(ts) AS t FROM guardian_m1 WHERE symbol = ?", (symbol,))
        t = (last or {}).get("t")
        since = max(int(t), self.now - M1_BARS * MIN) if t else self.now - M1_BARS * MIN
        rows = self.fetch(symbol, int(since), M1_BARS + 5) or []
        self.db.executemany("INSERT INTO guardian_m1 (symbol, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?) "
                            "ON CONFLICT (symbol, ts) DO UPDATE SET open = excluded.open, high = excluded.high, "
                            "low = excluded.low, close = excluded.close, volume = excluded.volume",
                            [(symbol, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                              float(r[5]) if len(r) > 5 else 0.0) for r in rows])
        got = self.db.query("SELECT ts, open, high, low, close FROM guardian_m1 WHERE symbol = ? AND ts <= ? "
                            "ORDER BY ts DESC LIMIT ?", (symbol, self.now, M1_BARS))
        return [(r["ts"], r["open"], r["high"], r["low"], r["close"]) for r in reversed(got)]

    def atr15(self, symbol: str) -> float | None:
        try:
            df = self.rt.candles(symbol, ATR_TF)
        except Exception:
            return None
        return atr_of(df.tail(ATR_N + 2) if df is not None and len(df) else None)

    def ref_price(self, symbol: str) -> float | None:
        try:
            px = self.rt.live_price(symbol)
        except Exception:
            px = None
        if px:
            return float(px)
        try:
            df = self.rt.candles(symbol, ATR_TF, include_forming=True)
        except TypeError:
            df = self.rt.candles(symbol, ATR_TF)
        except Exception:
            return None
        return float(df["close"].iloc[-1]) if df is not None and len(df) else None

    def funding_z(self, symbol: str) -> float | None:
        """Latest stored funding vs its last 30 days (z-score). Estimate; None without data."""
        try:
            rows = self.db.query("SELECT value FROM derivs WHERE symbol = ? AND kind = 'funding' AND ts >= ? ORDER BY ts",
                                 (symbol, self.now - 30 * 86_400_000))
        except Exception:
            return None
        vals = [float(r["value"]) for r in rows]
        if len(vals) < 30:
            return None
        hist, last = vals[:-1], vals[-1]
        m = sum(hist) / len(hist)
        sd = math.sqrt(sum((v - m) ** 2 for v in hist) / (len(hist) - 1))
        return (last - m) / sd if sd > 0 else None

    def advisor(self) -> Any:
        if self._advisor is None:
            from .ai_advisor import Advisor
            self._advisor = Advisor(self.db)
        return self._advisor

    # -- rows ------------------------------------------------------------------------------------------------------
    def recs(self, signal_id: str | None = None) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM guardian_recs", ()
        if signal_id:
            sql, args = sql + " WHERE signal_id = ?", (signal_id,)
        return self.db.query(sql + " ORDER BY created_at", args)

    def mark(self, rid: str, status: str, reason: str | None = None, extra: dict[str, Any] | None = None) -> None:
        if extra:
            r = self.db.one("SELECT payload FROM guardian_recs WHERE id = ?", (rid,))
            pay = {**(loads((r or {}).get("payload"), {}) or {}), **extra}
            self.db.execute("UPDATE guardian_recs SET status = ?, status_at = ?, status_reason = ?, payload = ? WHERE id = ?",
                            (status, self.now, reason, dumps(pay), rid))
        else:
            self.db.execute("UPDATE guardian_recs SET status = ?, status_at = ?, status_reason = ? WHERE id = ?",
                            (status, self.now, reason, rid))

    def restore_mirror(self) -> int:
        """Once, when the engine state was lost (no rows): re-insert the recommendations of the admin's document so
        dedupe holds across a lost cache. One Firestore read, only then."""
        if self.sink is None or self.db.get_setting(MIRROR_CHECKED, False):
            return 0
        n = 0
        if not self.db.one("SELECT 1 AS x FROM guardian_recs LIMIT 1"):
            try:
                doc = self.sink.get(f"views/{VIEW}") or {}
                v = loads(doc.get("json"), {}) if isinstance(doc.get("json"), str) else (doc or {})
            except Exception:
                v = {}
            for r in (v.get("live") or []) + (v.get("history") or []):
                try:
                    self.db.execute("INSERT INTO guardian_recs (id, signal_id, symbol, timeframe, side, level, rules_level, "
                                    "severity, created_at, expires_at, status, status_at, status_reason, shadow, payload) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (r["id"], r["signal_id"], r["symbol"], r["timeframe"], int(r["side"]), r["level"],
                                     r.get("rules_level") or r["level"], int(r["severity"]), int(r["created_at"]),
                                     int(r["expires_at"]), r["status"], r.get("status_at"), r.get("status_reason"),
                                     dumps(r["shadow"]) if r.get("shadow") else None,
                                     dumps({k: r.get(k) for k in PAYLOAD_KEYS if k in r} | {"restored": True})))
                    n += 1
                except Exception:
                    continue
        self.db.set_setting(MIRROR_CHECKED, True)
        return n

    # -- one tick ----------------------------------------------------------------------------------------------------
    def run(self, analyses: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
        """The engine step. Never raises: errors are counted and shown on the Guardian page."""
        if not ENABLED:
            return {"enabled": False}
        from . import tracking
        st = self.state()
        out: dict[str, Any] = {"calls": 0, "created": 0, "stale": 0, "errors": 0}
        new: list[dict[str, Any]] = []
        try:
            out["restored"] = self.restore_mirror()
            for (s, tf), a in (analyses or {}).items():
                if a.get("status") == "OK" and not a.get("stale"):     # stale candles never count as a fresh view
                    st["memo"][f"{s}|{tf}"] = {"at": int(a.get("generated_at") or self.now), "decision": a.get("decision"),
                                               "grade": a.get("grade"), "side": side_of(a.get("decision"))}
            self.housekeeping()
            calls = self.db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0 AND "
                                  "(fill_status IS NULL OR fill_status = 'FILLED') ORDER BY created_at")
            out["calls"] = len(calls)
            syms = sorted({c["symbol"] for c in calls})
            if any(c["symbol"] not in NO_BTC_FACTOR for c in calls):
                syms = sorted(set(syms) | {"BTC/USDT"})
            m1: dict[str, list[tuple] | None] = {}
            for s in syms:
                try:
                    m1[s] = self.m1(s)
                except Exception as exc:
                    m1[s] = None
                    st["today"]["errors"] += 1
                    st["last_error"] = {"at": self.now, "where": f"1m candles {coin(s)}", "text": _err(exc)}
            self.db.execute("DELETE FROM guardian_m1 WHERE ts < ?", (self.now - M1_KEEP_MS,))
            st["watched"] = {"coins": [coin(s) for s in syms], "calls": len(calls)}
            for c in calls:
                try:
                    res = self.check_call(c, m1, st)
                except Exception as exc:          # one call's problem never stops the others (or the tick)
                    st["today"]["errors"] += 1
                    out["errors"] += 1
                    st["last_error"] = {"at": self.now, "where": f"{coin(c['symbol'])} {c['timeframe']}", "text": _err(exc)}
                    continue
                if res == "stale":
                    out["stale"] += 1
                elif isinstance(res, dict):
                    new.append(res)
            live_ids = {c["id"] for c in calls}
            st["calls"] = {k: v for k, v in st["calls"].items() if k in live_ids}
            out["shadow"] = self.shadow_update()
        except Exception as exc:
            st["today"]["errors"] += 1
            out["errors"] += 1
            st["last_error"] = {"at": self.now, "where": "guardian", "text": _err(exc)}
            log.exception("guardian failed")
        st["last_check"] = self.now
        st["today"]["checks"] += 1
        st["today"]["ai_calls"] += self.ai_calls
        self.save(st)
        out["created"] = len(new)
        for r in new:
            try:
                self.notify(r)
            except Exception as exc:
                st["last_error"] = {"at": self.now, "where": "notify", "text": _err(exc)}
                self.save(st)
        if self.sink is not None:
            try:
                out["published"] = self.publish(force_close=any(r["level"] == "CLOSE" for r in new))
            except Exception as exc:
                st["last_error"] = {"at": self.now, "where": "publish", "text": _err(exc)}
                self.save(st)
        return out

    def housekeeping(self) -> None:
        """Live recommendations: expired after EXPIRES_MS, void when the call closed / was changed / is closing."""
        from . import tracking
        for r in self.db.query("SELECT * FROM guardian_recs WHERE status = 'live'"):
            sig = self.db.one("SELECT * FROM signals WHERE id = ?", (r["signal_id"],))
            if not sig or sig["status"] != "OPEN":
                self.mark(r["id"], "void", "the call closed before it was applied")
                continue
            adj = tracking.adjustments_of(self.db, r["signal_id"])
            if any(int(a["at"]) > int(r["created_at"]) for a in adj):
                self.mark(r["id"], "void", "the call was changed by the admin after this recommendation")
                continue
            if self.now > int(r["expires_at"]) + APPROVE_GRACE_MS:
                self.mark(r["id"], "expired", "not applied within 30 minutes")

    def check_call(self, c: dict[str, Any], m1: dict[str, list[tuple] | None], st: dict[str, Any]) -> Any:
        from . import adjust, tracking
        sid = c["id"]
        adj = tracking.adjustments_of(self.db, sid)
        if any(a["field"] == "close" for a in adj):
            return None                                  # already being closed by the admin
        rows = m1.get(c["symbol"]) or []
        memo = st["memo"].get(f"{c['symbol']}|{c['timeframe']}")
        btc = m1.get("BTC/USDT") if c["symbol"] not in NO_BTC_FACTOR else None
        atr = self.atr15(c["symbol"])
        max_age = ANALYSIS_MAX_AGE_MS.get(c["timeframe"], 75 * MIN)
        if (not fresh(rows, self.now) or atr is None or memo is None or self.now - int(memo["at"]) > max_age
                or (c["symbol"] not in NO_BTC_FACTOR and not fresh(btc or [], self.now))):
            st["today"]["skipped_stale"] += 1
            return "stale"                               # stale data never produces a recommendation
        price = rows[-1][4]
        ref = self.ref_price(c["symbol"])
        if not ref or abs(price / ref - 1) * 100 > PRICE_SANITY_PCT:
            st["today"]["skipped_price"] += 1
            return "price"
        stop_if = stop_in_force(c, adj)
        if int(c["side"]) * (price - stop_if) <= 0:
            return None                                  # at / through the stop: the record closes it on its own
        res = assess(c, rows, atr, stop_if, memo, btc, self.funding_z(c["symbol"]))
        band = res["band"]
        cs = st["calls"].setdefault(sid, {"streak": {"TIGHTEN": 0, "CLOSE": 0}})
        for lvl in LEVELS:
            cs["streak"][lvl] = cs["streak"][lvl] + 1 if band and RANK[band] >= RANK[lvl] else 0
        cs["severity"], cs["at"] = res["severity"], self.now
        ok, supersede = should_create(self.recs(sid), band, cs["streak"].get(band or "TIGHTEN", 0))
        if not ok:
            return None
        side = int(c["side"])
        proposed = propose_stop(side, price, rows, atr, stop_if, res["risk"])
        if proposed is not None and (stop_problem(side, proposed, stop_if, price, atr) or
                                     _adjust_refuses(c, adj, price, proposed)):
            proposed = None
        if band == "TIGHTEN" and proposed is None:
            st["today"]["no_valid_stop"] += 1
            return None
        ai = (second_opinion(self.advisor(), res["facts"], res["reasons"], band,
                             proposed if band == "TIGHTEN" else None, self.now)
              if self.ai_calls < MAX_AI_PER_TICK else
              {"level": band, "path": "rules_only", "text": template(band, res["severity"], res["reasons"], proposed),
               "model": None})
        if ai["path"] in ("ai_agreed", "ai_downgraded", "ai_rejected"):
            self.ai_calls += 1
        level = ai["level"]
        if level == "TIGHTEN" and proposed is None:
            level = "NONE"                               # downgraded from CLOSE, but no valid tighter stop exists
        if supersede:
            self.mark(supersede, "superseded", "a stronger recommendation replaced it")
        rid = new_id()
        status = "live" if level != "NONE" else "downgraded"
        pay = {"reasons": res["reasons"], "facts": res["facts"], "price": _sig_round(price), "entry": c["entry"],
               "stop_in_force": _sig_round(stop_if), "proposed_stop": proposed if level == "TIGHTEN" else None,
               "rules_proposed_stop": proposed, "atr": _sig_round(atr), "risk": res["risk"], "tp1_hit": bool(c.get("tp1_hit")),
               "ai": {"path": ai["path"], "text": ai["text"], "model": ai["model"]}}
        self.db.execute("INSERT INTO guardian_recs (id, signal_id, symbol, timeframe, side, level, rules_level, severity, "
                        "created_at, expires_at, status, status_at, status_reason, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (rid, sid, c["symbol"], c["timeframe"], side, level, band, res["severity"], self.now,
                         self.now + EXPIRES_MS, status, self.now if status != "live" else None,
                         "AI downgraded the rules' recommendation to no action" if status != "live" else None, dumps(pay)))
        # (no `decisions` row: that table feeds the member-readable views/decisions_recent; Guardian data is admin only)
        cs["streak"] = {"TIGHTEN": 0, "CLOSE": 0}
        st["today"]["created"] += 1
        return {"id": rid, "level": level, "status": status, "symbol": c["symbol"], "timeframe": c["timeframe"],
                "side": side, "severity": res["severity"], "proposed_stop": pay["proposed_stop"]}

    # -- notifications (admin only: never members, never the public channel) ----------------------------------
    def notify(self, r: dict[str, Any]) -> dict[str, Any]:
        if r["status"] != "live" or self.sink is None:
            return {"sent": 0}
        admins = [e for e in os.environ.get("ADMIN_EMAILS", "").replace(";", ",").split(",") if e.strip()]
        if not admins:            # without ADMIN_EMAILS a push without uid would reach every device: never send then
            return {"sent": 0, "reason": "ADMIN_EMAILS not set"}
        msg = push_message(r)
        res = self.sink.send_push([msg])
        chat = os.environ.get("GUARDIAN_TELEGRAM_CHAT", "").strip()
        if chat:
            res = {**res, "telegram": telegram_dm(self.sink, chat, f"{msg['title']}\n{msg['body']}")}
        return res

    # -- 7. shadow evidence --------------------------------------------------------------------------------------
    def shadow_update(self, limit: int = 40) -> int:
        from . import tracking
        done = 0
        for r in self.db.query("SELECT * FROM guardian_recs WHERE shadow IS NULL AND status != 'live' "
                               "ORDER BY created_at LIMIT ?", (limit,)):
            sig = self.db.one("SELECT * FROM signals WHERE id = ?", (r["signal_id"],))
            sh = None
            if not sig:
                sh = {"skipped": "call not found"}
            elif sig["status"] == "OPEN":
                continue
            elif sig["status"] in tracking.NO_RESULT_STATUSES:
                sh = {"skipped": f"call {sig['status'].lower()}"}
            else:
                try:
                    sh = shadow_outcome(self.rt, r, sig, self.now)
                except Exception as exc:
                    sh = None
                    log.warning("guardian shadow failed: %s", _err(exc))
                if sh is None and self.now - int(sig.get("closed_at") or self.now) > SHADOW_GIVE_UP_MS:
                    sh = {"skipped": "not enough candle data"}
            if sh is not None:
                self.db.execute("UPDATE guardian_recs SET shadow = ? WHERE id = ?", (dumps(sh), r["id"]))
                done += 1
        return done

    # -- 9. the admin's document (one, hash-dedup, admin only) ------------------------------------------------
    def view(self) -> dict[str, Any]:
        st = self.state()
        rows = self.db.query("SELECT * FROM guardian_recs ORDER BY created_at DESC LIMIT 400")
        live = [rec_view(r) for r in rows if r["status"] == "live"]
        hist = [rec_view(r) for r in rows if r["status"] != "live"][:HISTORY_IN_VIEW]
        return {"generated_at": self.now, "enabled": ENABLED,
                "status": {"last_check": st.get("last_check"), "watched": st.get("watched") or {"coins": [], "calls": 0},
                           "today": st.get("today") or {}, "day": st.get("day"), "last_error": st.get("last_error")},
                "live": live, "history": hist, "scoreboard": scoreboard(rows),
                "config": {"tighten_at": TIGHTEN_AT, "close_at": CLOSE_AT, "expires_min": EXPIRES_MS // MIN,
                           "min_gap_atr": MIN_GAP_ATR, "fresh_m1_min": FRESH_M1_MS // MIN, "persist_ticks": PERSIST_TICKS},
                "note": "Recommend-only: nothing changes unless the admin applies it. Shadow results are net R estimates "
                        "(same fees on both sides, funding ignored), from the record's own exit rules."}

    def publish(self, force_close: bool = False) -> bool:
        """Queue views/guardian: written only when it changed (hash), the status line at most every 30 min, a change of
        recommendations at once. In lean mode only a new CLOSE recommendation goes out."""
        if self.sink is None:
            return False
        if getattr(self.sink, "lean", False) and not force_close:
            st = self.state()
            st["today"]["lean_skipped"] = int(st["today"].get("lean_skipped", 0)) + 1
            self.save(st)
            return False
        v = self.view()
        self.sink.view(VIEW, v, volatile=("generated_at",), min_interval_s=1800, core=view_core(v))
        return True


PAYLOAD_KEYS = ("reasons", "facts", "price", "entry", "stop_in_force", "proposed_stop", "rules_proposed_stop", "atr",
                "risk", "tp1_hit", "ai", "applied")


def rec_view(r: dict[str, Any]) -> dict[str, Any]:
    p = loads(r.get("payload"), {}) or {}
    out = {k: r[k] for k in ("id", "signal_id", "symbol", "timeframe", "side", "level", "rules_level", "severity",
                             "created_at", "expires_at", "status", "status_at", "status_reason")}
    out.update({k: p[k] for k in PAYLOAD_KEYS if k in p and k != "risk"})
    if r.get("shadow"):
        out["shadow"] = loads(r["shadow"], None)
    return out


def view_core(v: dict[str, Any]) -> list[Any]:
    """What must reach the admin at once: the recommendations and their states, and the scoreboard counts."""
    return [[(r["id"], r["status"]) for r in v["live"] + v["history"]], (v.get("scoreboard") or {}).get("n")]


def scoreboard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cumulative shadow results (net R, with minus without): saved > 0 means the recommendation helped."""
    def agg(rs: list[dict[str, Any]]) -> dict[str, Any]:
        d = [float(x["delta_r"]) for x in rs]
        return {"n": len(d), "saved_r": round(sum(v for v in d if v > 0), 2), "cost_r": round(sum(v for v in d if v < 0), 2),
                "net_r": round(sum(d), 2), "helped": sum(1 for v in d if v > 1e-9), "hurt": sum(1 for v in d if v < -1e-9)}
    sh = [(r, loads(r["shadow"], None)) for r in rows if r.get("shadow")]
    good = [(r, s) for r, s in sh if isinstance(s, dict) and s.get("delta_r") is not None]
    return {**agg([s for _, s in good]),
            "applied": agg([s for r, s in good if r["status"] == "applied"]),
            "not_applied": agg([s for r, s in good if r["status"] != "applied"]),
            "by_level": {lvl: agg([s for r, s in good if s.get("action") == lvl]) for lvl in LEVELS},
            "pending": sum(1 for r in rows if not r.get("shadow")),
            "skipped": sum(1 for _, s in sh if isinstance(s, dict) and s.get("skipped"))}


def shadow_outcome(rt: Any, rec: dict[str, Any], sig: dict[str, Any], now: int) -> dict[str, Any] | None:
    """Net R of the closed call with vs without the recommendation (the record's exit rules, tracking.evaluate_signal).
    None when the candle data is not complete yet."""
    from . import tracking
    p = loads(rec.get("payload"), {}) or {}
    action = rec["level"] if rec["level"] != "NONE" else rec["rules_level"]
    adj = tracking.adjustments_of(rt.db, sig["id"])
    applied = rec["status"] == "applied"
    if applied:
        ap = p.get("applied") or {}
        base = [a for a in adj if not (int(a["at"]) == int(ap.get("at") or -1) and a["field"] == ap.get("field"))]
        with_ = adj
    else:
        if action == "TIGHTEN":
            stop = p.get("proposed_stop") or p.get("rules_proposed_stop")
            if stop is None:
                return {"skipped": "no level"}
            hyp = {"at": int(rec["created_at"]), "field": "stop", "old": None, "new": float(stop), "note": ""}
        else:
            hyp = {"at": int(rec["created_at"]), "field": "close", "old": float(p["price"]), "new": float(p["price"]), "note": ""}
        base, with_ = adj, sorted(adj + [hyp], key=lambda a: int(a["at"]))
    try:
        p15 = rt.candles(sig["symbol"], tracking.PATH_TF)
    except Exception:
        return None
    try:
        own = rt.candles(sig["symbol"], sig["timeframe"])
    except Exception:
        own = None
    end = max(now, int(sig.get("closed_at") or 0))
    a = tracking.evaluate_signal(sig, p15, own, end, adjust=with_)
    b = tracking.evaluate_signal(sig, p15, own, end, adjust=base)
    if a.get("status") in (None, "OPEN") or b.get("status") in (None, "OPEN") \
            or a.get("return_pct") is None or b.get("return_pct") is None:
        return None
    entry, stop0 = float(sig["entry"]), float(sig["stop"])
    risk_pct = abs(entry - stop0) / entry * 100
    if not risk_pct:
        return {"skipped": "no risk"}
    cost = tracking.cost_pct()
    with_r = (float(a["return_pct"]) - cost) / risk_pct
    without_r = (float(b["return_pct"]) - cost) / risk_pct
    return {"action": action, "applied": applied, "with_r": round(with_r, 3), "without_r": round(without_r, 3),
            "delta_r": round(with_r - without_r, 3), "status_with": a["status"], "status_without": b["status"],
            "record_status": sig["status"], "computed_at": now}


def push_message(r: dict[str, Any]) -> dict[str, str]:
    """Admin devices only: no uid and no broadcast (sinks: such a message goes to the ADMIN_EMAILS devices)."""
    act = "CLOSE NOW" if r["level"] == "CLOSE" else f"Tighten stop to {fmt_price(r['proposed_stop'])}"
    return {"title": f"Trade Guardian: {coin(r['symbol'])} {str(r['timeframe']).upper()} {'long' if r['side'] > 0 else 'short'}",
            "body": f"{act} · severity {r['severity']}/100. Review and approve on the Guardian page (expires in 30 min).",
            "url": "/guardian", "tag": f"guardian-{r['id']}"}


def telegram_dm(sink: Any, chat: str, text: str, session: Any = None) -> dict[str, Any]:
    """Optional private Telegram message to the admin (env GUARDIAN_TELEGRAM_CHAT). Never the public channel."""
    from . import telegram
    cfg = telegram.config(sink)
    if not cfg.get("token"):
        return {"ok": False, "reason": "no bot token"}
    if str(chat).strip() == str(cfg.get("channel") or "").strip():
        return {"ok": False, "reason": "refused: the admin chat equals the public channel"}
    return telegram.send({**cfg, "channel": chat}, text, session=session)


def _adjust_refuses(sig: dict[str, Any], adj: list[dict[str, Any]], price: float, stop: float) -> bool:
    """True when adjust.validate (what Apply runs) would refuse this stop now."""
    from . import adjust, tracking
    try:
        adjust.validate(sig, tracking.current_levels(sig, adj), price, stop, None, NOTE_TIGHTEN)
    except adjust.AdjustError:
        return True
    return False


def _err(exc: BaseException) -> str:
    from ..redact import error_text
    return error_text(exc, 200)


# ---- 4. approval through the existing adjustment path ----------------------------------------------------------
def request_problem(rec: dict[str, Any], params: dict[str, Any]) -> str | None:
    """Pure: the Apply request itself does not match the recommendation (the recommendation stays live)."""
    if rec["status"] != "live":
        return f"this recommendation is no longer live ({rec['status']})"
    if str(params.get("signal_id") or "") != rec["signal_id"]:
        return "the recommendation does not belong to this signal"
    p = loads(rec.get("payload"), {}) if isinstance(rec.get("payload"), str) else (rec.get("payload") or {})
    if rec["level"] == "CLOSE":
        return None if params.get("action") == "close" else "this recommendation is a close: use its Apply button"
    if rec["level"] != "TIGHTEN":
        return "this recommendation has no action"
    proposed = p.get("proposed_stop")
    try:
        sent = float(params.get("stop"))
    except (TypeError, ValueError):
        return "the stop must be the recommended level"
    if proposed is None or params.get("action") == "close" or abs(sent - float(proposed)) > 1e-9 * max(1.0, abs(float(proposed))):
        return "the stop must be the recommended level"
    return None


def revalidate(rec: dict[str, Any], sig: dict[str, Any] | None, adj: list[dict[str, Any]], price: float | None,
               params: dict[str, Any], job_created_at: int | None, now: int) -> str | None:
    """Pure: why an Apply must be refused now because the market / call changed (None = go ahead)."""
    if int(job_created_at or now) > int(rec["expires_at"]) or now > int(rec["expires_at"]) + APPROVE_GRACE_MS:
        return "this recommendation expired (30 minutes)"
    if not sig or sig.get("status") != "OPEN":
        return "the call is no longer open"
    if sig.get("fill_status") == "PENDING":
        return "the entry has not filled"
    if any(a["field"] == "close" for a in adj):
        return "the call is already being closed"
    if any(int(a["at"]) > int(rec["created_at"]) for a in adj):
        return "the call was changed after this recommendation was made"
    if price is None or price <= 0:
        return "the engine has no current price for this coin; try again in a few minutes"
    p = loads(rec.get("payload"), {}) if isinstance(rec.get("payload"), str) else (rec.get("payload") or {})
    side = int(sig["side"])
    if rec["level"] == "CLOSE":
        return None
    proposed = p.get("proposed_stop")
    why = stop_problem(side, float(proposed), stop_in_force(sig, adj), float(price), float(p.get("atr") or 0))
    return f"no longer valid at the price now ({fmt_price(price)}): {why}" if why else None


def approve(rt: Any, params: dict[str, Any], by: str, sink: Any = None, job_created_at: int | None = None,
            now: int | None = None) -> dict[str, Any]:
    """Apply a recommendation through adjust.apply / adjust.close (the caller has checked that `by` is an admin).
    Raises adjust.AdjustError with the reason; the recommendation is marked applied or rejected either way."""
    from . import adjust, tracking
    g = Guardian(rt, now=now)
    rid = str(params.get("guardian_id") or "").strip()
    rec = rt.db.one("SELECT * FROM guardian_recs WHERE id = ?", (rid,)) if rid else None
    if not rec:
        raise adjust.AdjustError("this Guardian recommendation was not found")
    sig = rt.db.one("SELECT * FROM signals WHERE id = ?", (rec["signal_id"],))
    bad = request_problem(rec, params)
    if bad:
        raise adjust.AdjustError(bad)
    adj = tracking.adjustments_of(rt.db, rec["signal_id"]) if sig else []
    price = adjust.latest_price(rt, sig["symbol"]) if sig else None
    why = revalidate(rec, sig, adj, price, params, job_created_at, g.now)
    if why:
        g.mark(rid, "expired" if "expired" in why else "rejected", why)
        raise adjust.AdjustError(why)
    p = loads(rec["payload"], {}) or {}
    note = " ".join(str(params.get("note") or (NOTE_CLOSE if rec["level"] == "CLOSE" else NOTE_TIGHTEN)).split())
    try:
        if rec["level"] == "CLOSE":
            out = adjust.close(rt, {"signal_id": rec["signal_id"], "action": "close", "note": note}, by, sink, now=g.now)
            applied = {"at": out["at"], "field": "close", "value": out.get("price"), "by": by}
        else:
            out = adjust.apply(rt, {"signal_id": rec["signal_id"], "stop": p["proposed_stop"], "note": note}, by, sink, now=g.now)
            applied = {"at": out["at"], "field": "stop", "value": p["proposed_stop"], "by": by}
    except adjust.AdjustError as exc:
        g.mark(rid, "rejected", str(exc))
        raise
    g.mark(rid, "applied", f"applied by the admin at {fmt_price(price)}", {"applied": applied})
    return {**out, "guardian": {"id": rid, "status": "applied"}}


def dismiss(rt: Any, params: dict[str, Any], by: str, now: int | None = None) -> dict[str, Any]:
    """The admin dismissed a live recommendation (the caller has checked that `by` is an admin)."""
    g = Guardian(rt, now=now)
    rid = str(params.get("guardian_id") or "").strip()
    rec = rt.db.one("SELECT * FROM guardian_recs WHERE id = ?", (rid,)) if rid else None
    if not rec:
        raise GuardianError("this Guardian recommendation was not found")
    if rec["status"] != "live":
        raise GuardianError(f"this recommendation is no longer live ({rec['status']})")
    g.mark(rid, "dismissed", f"dismissed by {by}")
    return {"ok": True, "guardian": {"id": rid, "status": "dismissed"}, "message": "Dismissed. Nothing was changed."}
