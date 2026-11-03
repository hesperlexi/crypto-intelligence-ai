"""v2.16 AI coin reports (advisory only: they never change a decision, a level or a risk limit).

One short report per watchlist coin, built from the engine's own analyses: trend (4H and 1D regimes), the nearest
support / resistance zones on 4H, what the AI expects on 4H and 12H (direction lean with the same directional
confidence the app shows on the coin page), the current public call if one is open, the main risk, and the level that
would invalidate the view. The text is deterministic; Gemini may add 1-2 sentences built only from the report's own
numbers, within the daily Gemini budget (coins with an open call first; a coin's sentence is renewed only when its
report changes, at most every COIN_AI_EVERY_MS).

Refreshed on the engine's hourly analyses (12H / 1D are analysed once an hour) and published as ONE compact document
views/coin_reports (hash-deduplicated, at most hourly), so a change costs one Firestore write for all coins. The report
holds no live price, so an unchanged market writes nothing.
"""
from __future__ import annotations

import logging
from typing import Any

from ..db import Database, dumps, now_ms

log = logging.getLogger(__name__)
HOUR = 3_600_000
REPORT_TFS = ("4h", "12h")
SETTING = "coin_reports"
COIN_AI_EVERY_MS = 4 * HOUR
COIN_AI_MAX_PER_DAY = 40          # Gemini sentences per day for all coins together
COIN_AI_PER_TICK = 3
AI_RESERVE = 30                   # calls left free for the record's notes and the market briefing
MAX_AI = 320
PUBLIC_TFS = ("15m", "1h", "4h", "12h", "1d", "3d")


def _sig(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return float(f"{f:.6g}") if f == f else None


def _coin(sym: str) -> str:
    b = sym.split("/")[0]
    return "GOLD" if b == "PAXG" else b


def _px(v: Any) -> str:
    from ..pricefmt import fmt_price
    return fmt_price(v)


def trend_label(g4: str | None, g1: str | None) -> str:
    gs = {g for g in (g4, g1) if g}
    if not gs:
        return "Not enough data"
    if "Unstable" in gs:
        return "Unsettled"
    if gs == {"Bull"}:
        return "Uptrend"
    if gs == {"Bear"}:
        return "Downtrend"
    if gs == {"Bull", "Bear"}:
        return "Mixed: 4H and 1D disagree"
    if "Bull" in gs:
        return "Sideways, leaning up"
    if "Bear" in gs:
        return "Sideways, leaning down"
    return "Sideways"


def _expect(a: dict[str, Any] | None, tf: str) -> dict[str, Any]:
    if not a or a.get("status") != "OK" or not (a.get("forecast") or {}).get("available"):
        return {"timeframe": tf, "lean": None, "note": "no trained model yet" if a else "not analysed yet"}
    dv = a.get("direction_view") or {}
    conf = a.get("confidence")
    return {"timeframe": tf, "lean": "up" if dv.get("side", 0) > 0 else "down",
            "confidence": round(float(conf), 2) if isinstance(conf, (int, float)) else None,
            "above_threshold": bool(dv.get("clears_policy")), "proven_edge": bool(dv.get("policy_edge"))}


def _zones(a: dict[str, Any] | None) -> dict[str, list[float]]:
    z = (((a or {}).get("levels") or {}).get("zones")) or {}
    return {"support": [_sig(x.get("mid")) for x in (z.get("support") or [])[:2] if x.get("mid") is not None],
            "resistance": [_sig(x.get("mid")) for x in (z.get("resistance") or [])[:2] if x.get("mid") is not None]}


def _open_call(db: Database, symbol: str) -> dict[str, Any] | None:
    from . import tracking
    r = db.one("SELECT timeframe FROM signals WHERE symbol = ? AND status = 'OPEN' AND side != 0 ORDER BY created_at DESC LIMIT 1",
               (symbol,))
    if not r:
        return None
    c = tracking.current_call(db, symbol, r["timeframe"])
    if not c or c.get("status") != "OPEN":
        return None
    stop = c.get("stop")
    if c.get("tp2_hit"):
        stop = c.get("tp1")                # the record's rule: stop at TP1 after TP2, at break-even after TP1
    elif c.get("tp1_hit"):
        stop = c.get("entry")
    return {"timeframe": r["timeframe"], "side": c["side"], "fill_status": c.get("fill_status"), "entry": _sig(c.get("entry")),
            "stop": _sig(stop), "tp1": _sig(c.get("tp1")), "tp2": _sig(c.get("tp2")), "tp3": _sig(c.get("tp3")),
            "tp1_hit": int(c.get("tp1_hit") or 0), "tp2_hit": int(c.get("tp2_hit") or 0), "created_at": c.get("created_at"),
            "id": c.get("id")}


def _risk(a4: dict[str, Any] | None, ex: list[dict[str, Any]], trend: str) -> str:
    a4 = a4 or {}
    nr = a4.get("news_risk")
    if nr:
        return f"High-impact US data ({nr.get('title')}) {nr.get('when')}: prices can jump both ways."
    vol = (a4.get("volatility") or {}).get("state")
    if vol in ("HIGH", "EXTREME"):
        return f"Volatility is {vol.lower()} on 4H, so stops are hit more easily."
    rsi = (a4.get("indicators") or {}).get("rsi")
    if isinstance(rsi, (int, float)) and (rsi >= 75 or rsi <= 25):
        return f"RSI {rsi:.0f} on 4H is {'overbought' if rsi >= 75 else 'oversold'}; sharp snap-backs are common there."
    leans = [e.get("lean") for e in ex if e.get("lean")]
    if len(leans) == 2 and leans[0] != leans[1]:
        return "The 4H and 12H AI leans point different ways."
    if trend.startswith("Mixed"):
        return "The 4H and 1D trends disagree."
    if ex and ex[0].get("lean") and not ex[0].get("above_threshold"):
        return "The 4H AI lean is weak (below its proven threshold)."
    return "No unusual risk flagged; any trade can still hit its stop."


def _invalidation(call: dict[str, Any] | None, lean: str | None, zones: dict[str, list[float]]) -> dict[str, Any] | None:
    if call and call.get("stop") is not None:
        word = "below" if call["side"] == "LONG" else "above"
        return {"price": call["stop"], "text": f"The {call['timeframe'].upper()} {call['side'].lower()} call ends if price trades "
                                               f"{word} {_px(call['stop'])} (its stop now)."}
    if lean == "up" and zones["support"]:
        return {"price": zones["support"][0], "text": f"A move below the 4H support near {_px(zones['support'][0])} would undo the up lean."}
    if lean == "down" and zones["resistance"]:
        return {"price": zones["resistance"][0],
                "text": f"A move above the 4H resistance near {_px(zones['resistance'][0])} would undo the down lean."}
    return None


def _lean_text(e: dict[str, Any]) -> str:
    if not e.get("lean"):
        return f"{e['timeframe'].upper()}: {e.get('note', 'no view')}"
    conf = f" ({e['confidence']:.0%} confidence)" if e.get("confidence") is not None else ""
    weak = "" if e.get("above_threshold") else ", weak"
    return f"{e['timeframe'].upper()} leans {e['lean']}{conf}{weak}"


def report(db: Database, symbol: str, analyses: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any] | None:
    a4, a12, a1d = analyses.get((symbol, "4h")), analyses.get((symbol, "12h")), analyses.get((symbol, "1d"))
    if not a4 or a4.get("status") != "OK":
        return None
    g4 = ((a4.get("regime") or {}).get("group"))
    g1 = ((a1d or {}).get("regime") or {}).get("group")
    trend = trend_label(g4, g1)
    ex = [_expect(a4, "4h"), _expect(a12, "12h")]
    zones = _zones(a4)
    call = _open_call(db, symbol)
    lean = ex[0].get("lean") or ex[1].get("lean")
    inval = _invalidation(call, lean, zones)
    risk = _risk(a4, ex, trend)
    s = [f"{_coin(symbol)}: {trend.lower()} (4H {((a4.get('regime') or {}).get('regime') or 'n/a').lower()}"
         + (f", 1D {((a1d or {}).get('regime') or {}).get('regime', 'n/a').lower()})." if a1d else ").")]
    s.append("AI view: " + "; ".join(_lean_text(e) for e in ex) + ".")
    if zones["support"] or zones["resistance"]:
        s.append("Key levels: " + ", ".join(p for p in (
            zones["support"] and f"support {_px(zones['support'][0])}",
            zones["resistance"] and f"resistance {_px(zones['resistance'][0])}") if p) + ".")
    if call:
        st = "waiting for entry" if call.get("fill_status") == "PENDING" else "running"
        s.append(f"Open {call['timeframe'].upper()} {call['side'].lower()} call ({st}), entry {_px(call['entry'])}, stop {_px(call['stop'])}.")
    return {"symbol": symbol, "coin": _coin(symbol), "trend": {"label": trend, "regime_4h": (a4.get("regime") or {}).get("regime"),
            "regime_1d": ((a1d or {}).get("regime") or {}).get("regime")},
            "levels": zones, "expects": ex, "call": call, "risk": risk, "invalidation": inval, "summary": " ".join(s),
            "bar_ts": a4.get("bar_ts")}


def core(r: dict[str, Any]) -> str:
    """What has to change before Gemini writes a coin's sentence again."""
    c = r.get("call") or {}
    return dumps([r["trend"]["label"], [(e.get("lean"), e.get("above_threshold")) for e in r["expects"]],
                  c.get("id"), c.get("fill_status"), c.get("tp1_hit"), c.get("tp2_hit"), r.get("risk")])


AI_TASK = ("Write 'text': 1 or 2 plain sentences for members that explain this coin report, using ONLY the input values "
           "(trend, AI lean and confidence per timeframe, key levels, open call, main risk, invalidation level). Describe; "
           "do NOT predict prices, do NOT mention profit or guarantees, do NOT advise to buy or sell, and do NOT write any "
           "number that is not in the input. No emojis.")


def _ai(adv: Any, r: dict[str, Any], now: int) -> str | None:
    from .briefing import PREDICT_RE, numbers_ok
    from .ai_advisor import clean_text
    data = {k: r[k] for k in ("coin", "trend", "levels", "expects", "call", "risk", "invalidation")}
    data["call"] = {k: v for k, v in (data["call"] or {}).items() if k not in ("id", "created_at")} or None
    out = adv.generate(AI_TASK, data, {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}, "required": ["text"]}, now)
    t = clean_text((out or {}).get("text"), MAX_AI)
    if not t or PREDICT_RE.search(t) or not numbers_ok(t, data):
        return None
    return t


def _ai_room(adv: Any, now: int, state: dict[str, Any]) -> bool:
    import time as _t
    if adv is None or not adv.enabled or not adv.available(now):
        return False
    day = _t.strftime("%Y-%m-%d", _t.gmtime(now / 1000))
    if state.get("ai_day") == day and int(state.get("ai_used") or 0) >= COIN_AI_MAX_PER_DAY:
        return False
    st = adv._state()
    used = int(st.get("count") or 0) if st.get("day") == day else 0
    return adv.daily_limit - used > AI_RESERVE


def run(db: Database, analyses: dict[tuple[str, str], dict[str, Any]], symbols: list[str], now: int | None = None,
        advisor: Any = None) -> dict[str, Any]:
    """Engine step (hourly analyses): rebuild every coin's report; Gemini sentences for changed reports within budget."""
    import time as _t
    now = now or now_ms()
    if not any(tf == "12h" for _, tf in analyses):
        return {"skipped": "waits for the hourly analyses (12H)"}
    state = db.get_setting(SETTING, None) or {}
    old = state.get("reports") or {}
    reports: dict[str, Any] = {}
    for s in symbols:
        try:
            r = report(db, s, analyses)
        except Exception as exc:                     # one coin never stops the others
            log.warning("coin report %s: %s", s, type(exc).__name__)
            r = None
        if r is None:
            if s in old:
                reports[s] = old[s]
            continue
        prev_ai = (old.get(s) or {}).get("ai")
        r["ai"] = prev_ai if prev_ai and prev_ai.get("core") == core(r) else None
        r["_stale_ai"] = prev_ai if r["ai"] is None else None
        reports[s] = r
    if advisor is None:
        from .ai_advisor import Advisor
        advisor = Advisor(db)
    day = _t.strftime("%Y-%m-%d", _t.gmtime(now / 1000))
    if state.get("ai_day") != day:
        state = {**state, "ai_day": day, "ai_used": 0}
    # coins with an open call first, then the rest; only reports whose content changed since their last sentence
    todo = sorted((s for s, r in reports.items() if r.get("ai") is None and (not r.get("_stale_ai")
                   or now - int(r["_stale_ai"].get("at") or 0) >= COIN_AI_EVERY_MS)),
                  key=lambda s: (reports[s].get("call") is None, s))
    made = 0
    for s in todo:
        if made >= COIN_AI_PER_TICK or not _ai_room(advisor, now, state):
            break
        try:
            t = _ai(advisor, reports[s], now)
        except Exception as exc:
            log.warning("coin report AI %s: %s", s, type(exc).__name__)
            t = None
        state["ai_used"] = int(state.get("ai_used") or 0) + 1
        made += 1
        if t:
            reports[s]["ai"] = {"text": t, "model": advisor.model, "at": now, "core": core(reports[s])}
    for r in reports.values():
        stale = r.pop("_stale_ai", None)
        if r.get("ai") is None and stale:
            r["ai"] = None                            # an old sentence never describes a changed report
    db.set_setting(SETTING, {**state, "reports": reports, "at": now})
    return {"coins": len(reports), "ai_written": made}


def view(db: Database, symbols: list[str]) -> dict[str, Any]:
    """The published document: one entry per watchlist coin (no live price inside)."""
    st = db.get_setting(SETTING, None) or {}
    reps = st.get("reports") or {}
    out = {}
    for s in symbols:
        r = reps.get(s)
        if not r:
            continue
        ai = r.get("ai")
        out[s] = {**{k: v for k, v in r.items() if k != "ai"}, "ai": {"text": ai["text"], "at": ai["at"]} if ai else None}
    return {"reports": out, "note": "Built from the engine's own analysis; AI lines are written only from these numbers. "
                                    "Context, not advice.", "generated_at": now_ms()}
