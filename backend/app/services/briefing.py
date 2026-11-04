"""v2.16 AI market briefing (advisory only: it never changes a decision, a level or a risk limit).

Every 4 hours - and at most hourly when the market mood or BTC / ETH's 4H regime changes - the engine collects its own
real numbers (4H regimes across the watchlist, breadth, BTC / ETH trend and AI lean, Fear & Greed, dominance, top
movers, upcoming high-impact US releases, open calls by side) and writes a 3-5 sentence plain-English briefing plus a
few bullet facts. Gemini writes the text when it is available and within its daily budget (it may only use the given
numbers: any number in its answer that is not in the input, any prediction or promise sends the briefing back to the
template); otherwise the same numbers fill a fixed template. The bullets are always the engine's own facts.

Stored in the engine's settings (`briefing`) and published as the `briefing` field of the existing views/market_context
document (no new Firestore document; the Home page reads it), and posted to Telegram 1-2x a day (services/telegram.py).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..db import Database, now_ms

log = logging.getLogger(__name__)
HOUR = 3_600_000
EVERY_MS = 4 * HOUR              # regular refresh
MIN_GAP_MS = 1 * HOUR            # a regime change refreshes it sooner, but never more than hourly
AI_RESERVE = 25                  # Gemini calls kept free for the record's notes (rationales / reviews) each day
MAX_TEXT = 700
SETTING = "briefing"
MAJORS = ("BTC/USDT", "ETH/USDT")

PREDICT_RE = re.compile(
    r"\b(will|going to|is set to|are set to|likely to|poised to|expected to|bound to)\s+(\w+\s+)?"
    r"(rise|rally|climb|surge|soar|pump|moon|fall|drop|crash|dump|plunge|reach|hit|break|bounce|recover|continue|explode)\b"
    r"|\bprice target\b|\b(buy|sell|short|long) now\b|\bprofit|\bgains? (of|up to)\b|\bupside of\b", re.I)
NUM_RE = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
# numbers that appear in plain wording (4H, 24 hours, 7 days, 50-period, top 3) and are always allowed
WORD_NUMBERS = {1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 12.0, 15.0, 24.0, 30.0, 50.0, 60.0, 100.0}


def _r(v: Any, dp: int = 1) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, dp) if f == f else None


def _coin(sym: str) -> str:
    b = sym.split("/")[0]
    return "GOLD" if b == "PAXG" else b


def _regime(a: dict[str, Any] | None) -> tuple[str | None, str | None]:
    reg = (a or {}).get("regime") or {}
    return reg.get("regime"), reg.get("group")


def _lean(a: dict[str, Any] | None) -> dict[str, Any] | None:
    """The AI's direction on this timeframe and whether it clears the model's threshold (None without a model).
    v2.17 (owner, 4 Nov 2026): no confidence % (the next-candle hit rate overstates), so Gemini never sees one."""
    dv = (a or {}).get("direction_view") or None
    if not dv or not ((a or {}).get("forecast") or {}).get("available"):
        return None
    return {"lean": "up" if dv.get("side", 0) > 0 else "down",
            "above_threshold": bool(dv.get("clears_policy"))}


def facts(db: Database, analyses: dict[tuple[str, str], dict[str, Any]], ctx: dict[str, Any] | None,
          now: int | None = None) -> dict[str, Any] | None:
    """The briefing's inputs: only numbers the engine has (rounded, so unchanged markets give the same facts)."""
    from .alerts import mood_of
    from .news import events
    now = now or now_ms()
    four = {s: a for (s, tf), a in analyses.items() if tf == "4h" and a.get("status") == "OK"}
    if not four:
        return None
    mood = mood_of(analyses, "4h")
    above = sum(1 for a in four.values() if (a.get("indicators") or {}).get("ema_50") and a.get("last_close")
                and float(a["last_close"]) > float(a["indicators"]["ema_50"]))
    ch = {s: a.get("change_24h_pct") for s, a in four.items() if isinstance(a.get("change_24h_pct"), (int, float))}
    up = sorted(ch.items(), key=lambda kv: -kv[1])
    out: dict[str, Any] = {
        "coins": len(four), "mood": mood,
        "breadth": {"above_ema50_4h": above, "of": len(four), "up_24h": sum(1 for v in ch.values() if v > 0)},
        "movers": {"up": [{"coin": _coin(s), "change_24h_pct": _r(v)} for s, v in up[:3] if v > 0],
                   "down": [{"coin": _coin(s), "change_24h_pct": _r(v)} for s, v in up[::-1][:3] if v < 0]},
    }
    for sym in MAJORS:
        a4, a1 = analyses.get((sym, "4h")), analyses.get((sym, "1d"))
        if not a4 or a4.get("status") != "OK":
            continue
        r4, g4 = _regime(a4)
        r1, _ = _regime(a1)
        out[_coin(sym).lower()] = {"price": _r(a4.get("price"), 2), "change_24h_pct": _r(a4.get("change_24h_pct")),
                                   "regime_4h": r4, "group_4h": g4, "regime_1d": r1, "ai_4h": _lean(a4)}
    s = (ctx or {}).get("sentiment") or {}
    if isinstance(s.get("value"), (int, float)):
        out["fear_greed"] = {"value": int(s["value"]), "label": s.get("label"),
                             "change_7d": int(s["change_7d"]) if isinstance(s.get("change_7d"), (int, float)) else None}
    m = (ctx or {}).get("market") or {}
    if isinstance(m.get("btc_dominance"), (int, float)):
        out["btc_dominance_pct"] = _r(m["btc_dominance"])
    if isinstance(m.get("market_cap_change_24h_pct"), (int, float)):
        out["market_cap_change_24h_pct"] = _r(m["market_cap_change_24h_pct"])
    try:
        evs = [e for e in events(db, now, now + 24 * HOUR) if e.get("impact") == "High" and e.get("country") == "USD"]
    except Exception:
        evs = []
    out["news"] = [{"title": e["title"], "in_hours": _r((e["ts"] - now) / HOUR), "ts": int(e["ts"])} for e in evs[:3]]
    rows = db.query("SELECT side, fill_status, COUNT(*) AS n FROM signals WHERE status = 'OPEN' AND side != 0 "
                    "GROUP BY side, fill_status")
    out["open_calls"] = {"long": sum(r["n"] for r in rows if r["side"] > 0 and r["fill_status"] != "PENDING"),
                         "short": sum(r["n"] for r in rows if r["side"] < 0 and r["fill_status"] != "PENDING"),
                         "waiting_entry": sum(r["n"] for r in rows if r["fill_status"] == "PENDING")}
    return out


def core(f: dict[str, Any]) -> list[Any]:
    """What counts as a 'big regime change': the mood, BTC's and ETH's 4H regime group."""
    return [(f.get("mood") or {}).get("status"), (f.get("btc") or {}).get("group_4h"), (f.get("eth") or {}).get("group_4h")]


# ---- deterministic template ------------------------------------------------------------------------------------
MOOD_WORD = {"BULL": "leaning bullish", "BEAR": "leaning bearish", "NEUTRAL": "mixed"}


def _pct(v: Any) -> str:
    return "n/a" if v is None else f"{float(v):+.1f}%"


def _major(name: str, x: dict[str, Any] | None) -> str | None:
    if not x:
        return None
    reg = (x.get("regime_4h") or "no clear regime").lower()
    return f"{name} is in a {reg} 4H regime ({_pct(x.get('change_24h_pct'))} in 24 hours)"


def template(f: dict[str, Any]) -> str:
    m = f.get("mood") or {}
    s = [f"The market is {MOOD_WORD.get(m.get('status'), 'mixed')}: {m.get('bull', 0)} of {m.get('assets', 0)} coins are in "
         f"a bullish 4H regime and {m.get('bear', 0)} in a bearish one."]
    maj = [t for t in (_major("Bitcoin", f.get("btc")), _major("Ether", f.get("eth"))) if t]
    if maj:
        s.append("; ".join(maj) + ".")
    b = f.get("breadth") or {}
    s.append(f"{b.get('above_ema50_4h', 0)} of {b.get('of', 0)} coins trade above their 4H 50-period average and "
             f"{b.get('up_24h', 0)} are up on the day.")
    fg = f.get("fear_greed")
    if fg:
        t = f"Fear & Greed reads {fg['value']} ({fg.get('label') or 'n/a'})"
        if f.get("btc_dominance_pct") is not None:
            t += f" and Bitcoin's dominance is {f['btc_dominance_pct']:.1f}%"
        s.append(t + ".")
    news = f.get("news") or []
    if news:
        n0 = news[0]
        s.append(f"Next high-impact US release: {n0['title']} in about {n0['in_hours']:.1f} hours; new entries pause around it.")
    else:
        s.append("No high-impact US release is due in the next 24 hours.")
    return " ".join(s[:5])


def bullets(f: dict[str, Any]) -> list[str]:
    out = []
    m = f.get("mood") or {}
    if m:
        out.append(f"Mood (4H): {m.get('bull', 0)} bullish · {m.get('neutral', 0)} neutral · {m.get('bear', 0)} bearish")
    bt, et = f.get("btc"), f.get("eth")
    if bt or et:
        out.append(" · ".join(t for t in (bt and f"BTC {_pct(bt.get('change_24h_pct'))} 24h", et and f"ETH {_pct(et.get('change_24h_pct'))} 24h") if t))
    oc = f.get("open_calls") or {}
    out.append(f"Open calls: {oc.get('long', 0)} long · {oc.get('short', 0)} short"
               + (f" · {oc['waiting_entry']} waiting for entry" if oc.get("waiting_entry") else ""))
    mv = f.get("movers") or {}
    if mv.get("up") or mv.get("down"):
        parts = []
        if mv.get("up"):
            parts.append(f"strongest {mv['up'][0]['coin']} {_pct(mv['up'][0]['change_24h_pct'])}")
        if mv.get("down"):
            parts.append(f"weakest {mv['down'][0]['coin']} {_pct(mv['down'][0]['change_24h_pct'])}")
        out.append("24h: " + " · ".join(parts))
    if f.get("news"):
        n0 = f["news"][0]
        out.append(f"{n0['title']} in {n0['in_hours']:.1f} h (entries pause)")
    elif f.get("fear_greed"):
        out.append(f"Fear & Greed {f['fear_greed']['value']}" + (f" · BTC dominance {f['btc_dominance_pct']:.1f}%"
                                                                 if f.get("btc_dominance_pct") is not None else ""))
    return out[:5]


# ---- Gemini text, checked against the facts -----------------------------------------------------------------------
def _numbers(obj: Any) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        v = float(obj)
        for x in (v, abs(v), v * 100, abs(v) * 100):
            out |= {x, round(x), round(x, 1), round(x, 2)}
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "ts":
                out |= _numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= _numbers(v)
    elif isinstance(obj, str):
        for t in NUM_RE.findall(obj):
            try:
                out.add(float(t.replace(",", "")))
            except ValueError:
                pass
    return out


def numbers_ok(text: str, f: dict[str, Any]) -> bool:
    """Every number in the text is one of the input numbers (or a plain wording number such as 4H / 24 hours)."""
    allowed = _numbers(f) | WORD_NUMBERS
    for t in NUM_RE.findall(text):
        try:
            x = abs(float(t.replace(",", "")))
        except ValueError:
            return False
        if not any(abs(x - v) <= max(0.051, 0.002 * abs(v)) for v in allowed):
            return False
    return True


def acceptable(text: Any, f: dict[str, Any]) -> str | None:
    from .ai_advisor import clean_text
    t = clean_text(text, MAX_TEXT)
    if not t or PREDICT_RE.search(t) or not numbers_ok(t, f):
        return None
    n = len(re.findall(r"[.!?](\s|$)", t))
    return t if 2 <= n <= 6 else None


def ai_room(adv: Any, now: int) -> bool:
    """Gemini usable and more than AI_RESERVE calls left today (the record's notes keep priority)."""
    import time as _t
    if adv is None or not adv.available(now):
        return False
    st = adv._state()
    used = int(st.get("count") or 0) if st.get("day") == _t.strftime("%Y-%m-%d", _t.gmtime(now / 1000)) else 0
    return adv.daily_limit - used > AI_RESERVE


TASK = ("Write 'text': a market briefing for members of a crypto analysis app, 3 to 5 plain sentences in British "
        "English, using ONLY the input values (market mood and breadth, Bitcoin and Ether regime and 24h change, Fear & "
        "Greed, dominance, top movers, upcoming US releases, open calls). Describe the current state only. Do NOT "
        "predict prices or direction, do NOT mention profit, returns, targets or guarantees, do NOT give advice to buy "
        "or sell, and do NOT write any number that is not in the input. No emojis, no lists.")


def ai_text(adv: Any, f: dict[str, Any], now: int) -> str | None:
    if not ai_room(adv, now):
        return None
    data = {k: v for k, v in f.items() if k != "news"} | {"news": [{k: v for k, v in n.items() if k != "ts"} for n in f.get("news") or []]}
    out = adv.generate(TASK, data, {"type": "OBJECT", "properties": {"text": {"type": "STRING"}}, "required": ["text"]}, now)
    return acceptable((out or {}).get("text"), f)


# ---- the engine step ----------------------------------------------------------------------------------------------
def current(db: Database) -> dict[str, Any] | None:
    b = db.get_setting(SETTING, None)
    return {k: v for k, v in b.items() if k not in ("core",)} if isinstance(b, dict) and b.get("text") else None


def due(prev: dict[str, Any] | None, f: dict[str, Any], now: int) -> str | None:
    if not prev or not prev.get("at"):
        return "first"
    age = now - int(prev["at"])
    if age >= EVERY_MS:
        return "every 4 h"
    if age >= MIN_GAP_MS and prev.get("core") != core(f):
        return "regime change"
    return None


def run(db: Database, analyses: dict[tuple[str, str], dict[str, Any]], ctx: dict[str, Any] | None,
        now: int | None = None, advisor: Any = None) -> dict[str, Any]:
    """Engine step: refresh the briefing when due. Never raises into the cycle (the caller wraps it)."""
    now = now or now_ms()
    if not any(tf == "1d" for _, tf in analyses):
        return {"skipped": "waits for the hourly analyses (1D regime)"}
    f = facts(db, analyses, ctx, now)
    if not f:
        return {"skipped": "no 4H analyses"}
    prev = db.get_setting(SETTING, None)
    why = due(prev if isinstance(prev, dict) else None, f, now)
    if not why:
        return {"skipped": "not due"}
    if advisor is None:
        from .ai_advisor import Advisor
        advisor = Advisor(db)
    text, source = None, "template"
    try:
        text = ai_text(advisor, f, now) if advisor.enabled else None
    except Exception as exc:                          # Gemini is optional: the template always works
        log.warning("briefing AI failed: %s", type(exc).__name__)
    if text:
        source = "ai"
    else:
        text = template(f)
    b = {"text": text, "bullets": bullets(f), "source": source, "model": advisor.model if source == "ai" else None,
         "at": now, "reason": why, "core": core(f), "mood": (f.get("mood") or {}).get("status"),
         "facts": {k: f.get(k) for k in ("mood", "breadth", "open_calls", "fear_greed", "btc_dominance_pct")},
         "note": ("Written by AI from the engine's own numbers" if source == "ai" else "Built from the engine's own numbers")
                 + ". Context, not advice; it never changes a signal."}
    db.set_setting(SETTING, b)
    return {"refreshed": why, "source": source, "chars": len(text)}

