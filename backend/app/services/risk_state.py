"""V3.0 market risk state (owner brief 24 Nov 2026, Stage 2). ONE deterministic state for the whole market:
NORMAL / CAUTION / HIGH RISK / SEVERE / RECOVERY, from inputs the engine already records.

Every factor gives points (0 ok, 1 warn, 2 high). Missing CRITICAL data (BTC candles) counts as risk, never as zero.
Score 0-1 NORMAL, 2-3 CAUTION, 4-5 HIGH, >= 6 SEVERE. After HIGH / SEVERE the state is RECOVERY until the score has
stayed below HIGH for `RECOVERY_MS` (6 h). Gemini / the AI never changes it.

Effect (honest rule, same as every engine rule): on PUBLISHED CALLS the state is shadow only - stored on each call
(`risk_shadow.state`) so a replay can prove later which states lose; it blocks calls only after `research_verdict`
passes. On members' PRACTICE auto-trade (no effect on the record) `practice_policy` applies at once: HIGH = half size,
SEVERE = no new auto-trades (members can switch "follow market risk" off).

Stored: setting `risk_state` (current), `risk_state_log` (last 300 changes), `risk_state_series` (hourly, 7 days).
Published: `views/risk_state` (member-readable; core = state + factor levels, else at most every 30 min).
Thresholds reuse proven values where they exist (volatility 1.5x, loss stop 3R / 6R, sweep 6 h); the rest are
conservative first values, logged with every change so they can be judged."""
from __future__ import annotations

import time
from typing import Any

import numpy as np

H = 3_600_000
DAY = 86_400_000
STATES = ("NORMAL", "CAUTION", "HIGH", "SEVERE", "RECOVERY")
LABEL = {"NORMAL": "Normal", "CAUTION": "Caution", "HIGH": "High risk", "SEVERE": "Severe risk", "RECOVERY": "Recovery"}
POLICY = {
    "NORMAL": "Normal conditions. Every check still applies to each signal.",
    "CAUTION": "Be selective: prefer grade A calls and smaller size.",
    "HIGH": "Conditions are unsafe for many setups: practice auto-trade uses half size.",
    "SEVERE": "Stand aside: practice auto-trade opens nothing new until risk falls.",
    "RECOVERY": "Risk is falling after a rough spell: stay selective until it settles.",
}
RECOVERY_MS = 6 * H
PUBLISH_EVERY_S = 1800
BTC = "BTC/USDT"


def _f(key: str, label: str, pts: int, status: str, value: Any = None, detail: str = "", critical: bool = False,
       source: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "points": int(pts), "status": status, "value": value, "detail": detail,
            "critical": critical, "source": source}


def _atr_ratio(df) -> float | None:
    if df is None or len(df) < 110:
        return None
    h, l, c = df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float)
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    a100 = float(tr[-100:].mean())
    return float(tr[-14:].mean()) / a100 if a100 > 0 else None


def _closed(df, step: int, now: int):
    if df is None or len(df) == 0:
        return df
    return df[df["ts"].astype("int64") + step <= now]


def f_btc_vol(rt, now) -> dict[str, Any]:
    try:
        r = _atr_ratio(_closed(rt.candles(BTC, "4h"), 4 * H, now))
    except Exception:
        r = None
    if r is None:
        return _f("btc_vol", "BTC volatility", 1, "unknown", None, "BTC 4h candles unavailable", True, "Binance")
    pts = 2 if r >= 1.5 else 1 if r >= 1.25 else 0
    return _f("btc_vol", "BTC volatility", pts, ("high", "warn", "ok")[2 - pts], round(r, 2),
              f"recent 4h range is {r:.2f}x its 100-candle normal", True, "Binance 4h")


def f_btc_move(rt, now) -> dict[str, Any]:
    try:
        df = _closed(rt.candles(BTC, "1h"), H, now)
        c = df["close"].to_numpy(float)[-5:]
    except Exception:
        c = None
    if c is None or len(c) < 5:
        return _f("btc_move", "Sudden BTC move", 1, "unknown", None, "BTC 1h candles unavailable", True, "Binance")
    m1, m4 = (c[-1] / c[-2] - 1) * 100, (c[-1] / c[0] - 1) * 100
    big = max(abs(m1) / 2.0, abs(m4) / 4.0)
    pts = 2 if big >= 1 else 1 if max(abs(m1) / 1.2, abs(m4) / 2.5) >= 1 else 0
    return _f("btc_move", "Sudden BTC move", pts, ("high", "warn", "ok")[2 - pts], {"h1": round(m1, 2), "h4": round(m4, 2)},
              f"BTC {m1:+.1f}% last hour, {m4:+.1f}% last 4 hours", True, "Binance 1h")


def f_data(rt, now) -> dict[str, Any]:
    try:
        df = rt.candles(BTC, "15m")
        age = (now - (int(df["ts"].iloc[-1]) + 15 * 60_000)) / 60_000 if df is not None and len(df) else None
    except Exception:
        age = None
    if age is None:
        return _f("data", "Data freshness", 2, "high", None, "no recent BTC candles: the engine is blind", True, "engine")
    pts = 2 if age > 45 else 1 if age > 25 else 0
    return _f("data", "Data freshness", pts, ("high", "warn", "ok")[2 - pts], round(age), f"newest closed 15m candle {age:.0f} min old",
              True, "engine")


def f_breadth_vol(rt, now, symbols) -> dict[str, Any]:
    n = hot = 0
    for s in symbols:
        try:
            r = _atr_ratio(_closed(rt.candles(s, "4h"), 4 * H, now))
        except Exception:
            r = None
        if r is None:
            continue
        n += 1
        hot += r >= 1.5
    if n < 5:
        return _f("breadth_vol", "Market-wide volatility", 0, "unknown", None, "too few coins with data")
    share = hot / n
    pts = 2 if share >= 0.5 else 1 if share >= 0.3 else 0
    return _f("breadth_vol", "Market-wide volatility", pts, ("high", "warn", "ok")[2 - pts], {"hot": hot, "of": n},
              f"{hot} of {n} coins far above their normal volatility", source="Binance 4h")


def f_turn(rt, now) -> dict[str, Any]:
    m = rt.db.get_setting("market_turn_last", None) or {}
    if not m or now - int(m.get("at") or 0) > 3 * H:
        return _f("turn", "Trend turning", 0, "unknown", None, "market-turn reading older than 3 h")
    st = str(m.get("state") or "")
    pts = 1 if st.startswith("turning") else 0
    return _f("turn", "Trend turning", pts, "warn" if pts else "ok", st, f"market trend {m.get('trend')}: {st}",
              source="OKX + Binance")


def f_sweep(rt, now) -> dict[str, Any]:
    try:
        from . import sweep_guard
        s = sweep_guard.recent_sweep(rt.candles(BTC, "1h"), now)
    except Exception:
        return _f("sweep", "Stop run on BTC", 0, "unknown", None, "BTC 1h candles unavailable")
    if not s:
        return _f("sweep", "Stop run on BTC", 0, "ok", None, "no stop run in the last 6 hours", source="Binance 1h")
    side = "lows (bullish)" if s["side"] > 0 else "highs (bearish)"
    return _f("sweep", "Stop run on BTC", 1, "warn", s["side"], f"BTC swept its 2-day {side} and snapped back", source="Binance 1h")


def f_liq(rt, now) -> dict[str, Any]:
    try:
        rows = rt.db.query("SELECT kind, ts, value FROM derivs WHERE symbol = ? AND kind IN ('liq_long_4hour','liq_short_4hour') "
                           "AND ts >= ? ORDER BY ts", (BTC, now - 40 * 4 * H))
    except Exception:
        rows = []
    by: dict[int, float] = {}
    for r in rows:
        if int(r["ts"]) + 4 * H <= now:
            by[int(r["ts"])] = by.get(int(r["ts"]), 0.0) + float(r["value"] or 0)
    ts = sorted(by)
    if len(ts) < 12 or now - ts[-1] > 12 * H:
        return _f("liq", "Liquidation wave", 0, "unknown", None, "liquidation data not available yet", source="Coinalyze")
    last, med = by[ts[-1]], float(np.median([by[t] for t in ts[-31:-1]]))
    x = last / med if med > 0 else 0.0
    pts = 1 if x >= 5 and last >= 25e6 else 0
    return _f("liq", "Liquidation wave", pts, "warn" if pts else "ok", round(x, 1),
              f"BTC forced closes last 4h: ${last / 1e6:,.0f}M ({x:.1f}x normal)", source="Coinalyze")


def f_funding(rt, now) -> dict[str, Any]:
    try:
        rows = rt.db.query("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = 'funding_1h' AND ts >= ? ORDER BY ts",
                           (BTC, now - 30 * DAY))
    except Exception:
        rows = []
    v = np.array([float(r["value"]) for r in rows if r["value"] is not None], float)
    if len(v) < 24 * 10 or now - int(rows[-1]["ts"]) > 6 * H:
        return _f("funding", "Funding extreme", 0, "unknown", None, "funding history too short or stale")
    last = float(v[-24:].mean())
    sd = float(v.std())
    z = (last - float(v.mean())) / sd if sd > 0 else 0.0
    pts = 1 if abs(z) >= 3 else 0
    side = "longs" if last > 0 else "shorts"
    return _f("funding", "Funding extreme", pts, "warn" if pts else "ok", round(z, 1),
              f"{side} paying {'unusually much' if pts else 'a normal amount'} (z {z:+.1f})", source="Hyperliquid / OKX")


def f_news(rt, now) -> dict[str, Any]:
    try:
        from . import news
        e = news.event_risk(rt.db, now)
    except Exception:
        return _f("news", "Major US data", 0, "unknown", None, "calendar unavailable")
    if not e:
        return _f("news", "Major US data", 0, "ok", None, "no high-impact release within the pause window", source="economic calendar")
    return _f("news", "Major US data", 1, "warn", e["title"], f"{e['title']} {e['when']}", source="economic calendar")


def f_record(rt, now) -> dict[str, Any]:
    try:
        from . import risk_shadow
        day, week = risk_shadow.loss_sums(rt, now)
    except Exception:
        return _f("record", "Signal losses", 0, "unknown", None, "record unavailable")
    pts = 2 if (day <= -3 or week <= -6) else 1 if (day <= -1.5 or week <= -3) else 0
    return _f("record", "Signal losses", pts, ("high", "warn", "ok")[2 - pts], {"day": day, "week": week},
              f"closed signals {day:+.1f}R today, {week:+.1f}R this week (after fees)", source="track record")


def f_streak(rt, now) -> dict[str, Any]:
    try:
        from . import tracking
        closed = tuple(tracking.CLOSED_STATUSES)
        rows = rt.db.query(f"SELECT * FROM signals WHERE status IN ({','.join('?' * len(closed))}) AND closed_at >= ? "
                           "ORDER BY closed_at DESC LIMIT 12", (*closed, now - 14 * DAY))
        n = 0
        for r in rows:
            if r.get("fill_status") == "NOT_FILLED":
                continue
            net = tracking.net_pct(r)
            if net is None:
                continue
            if net < 0:
                n += 1
            else:
                break
    except Exception:
        return _f("streak", "Losing streak", 0, "unknown", None, "record unavailable")
    pts = 1 if n >= 5 else 0
    return _f("streak", "Losing streak", pts, "warn" if pts else "ok", n, f"{n} losing signals in a row", source="track record")


def f_exposure(rt, now) -> dict[str, Any]:
    try:
        rows = rt.db.query("SELECT side FROM signals WHERE status = 'OPEN' AND COALESCE(fill_status, 'FILLED') = 'FILLED'")
    except Exception:
        return _f("exposure", "One-sided exposure", 0, "unknown", None, "record unavailable")
    longs = sum(1 for r in rows if int(r.get("side") or 0) > 0)
    shorts = sum(1 for r in rows if int(r.get("side") or 0) < 0)
    big = max(longs, shorts)
    pts = 1 if big >= 10 else 0
    return _f("exposure", "One-sided exposure", pts, "warn" if pts else "ok", {"long": longs, "short": shorts},
              f"{longs} long and {shorts} short signals running", source="track record")


def assess(rt, now: int | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    syms = symbols if symbols is not None else (rt.symbols() if hasattr(rt, "symbols") else [])
    fs = []
    for fn in (f_data, f_btc_vol, f_btc_move, lambda r, n: f_breadth_vol(r, n, syms), f_turn, f_sweep, f_liq,
               f_funding, f_news, f_record, f_streak, f_exposure):
        try:
            fs.append(fn(rt, now))
        except Exception as e:  # noqa: BLE001 - one broken input must not hide the others
            fs.append(_f(getattr(fn, "__name__", "input"), "Input", 1, "unknown", None, f"check failed ({type(e).__name__})"))
    score = sum(f["points"] for f in fs)
    raw = "SEVERE" if score >= 6 else "HIGH" if score >= 4 else "CAUTION" if score >= 2 else "NORMAL"
    if any(f["key"] == "data" and f["status"] == "high" for f in fs) and raw in ("NORMAL", "CAUTION"):
        raw = "HIGH"                                   # blind engine: never "safe"
    return {"at": now, "score": score, "raw": raw, "factors": fs,
            "unavailable": [f["label"] for f in fs if f["status"] == "unknown"]}


def step_state(prev: dict[str, Any] | None, a: dict[str, Any]) -> dict[str, Any]:
    """Apply RECOVERY: after HIGH / SEVERE, stay RECOVERY until the raw state stayed below HIGH for RECOVERY_MS."""
    now, raw = a["at"], a["raw"]
    p = prev or {}
    pstate = p.get("state")
    calm_since = p.get("calm_since")
    if raw in ("HIGH", "SEVERE"):
        state, calm_since = raw, None
    elif pstate in ("HIGH", "SEVERE", "RECOVERY"):
        calm_since = calm_since or now
        state = "RECOVERY" if now - calm_since < RECOVERY_MS else raw
        if state != "RECOVERY":
            calm_since = None
    else:
        state, calm_since = raw, None
    since = p.get("since") if pstate == state else now
    top = sorted((f for f in a["factors"] if f["points"] > 0), key=lambda f: -f["points"])
    why = "; ".join(f["detail"] for f in top[:3]) or "no risk factor is raised"
    return {"state": state, "label": LABEL[state], "policy": POLICY[state], "score": a["score"], "raw": raw,
            "since": since, "calm_since": calm_since, "at": now, "why": why, "factors": a["factors"],
            "unavailable": a["unavailable"],
            "recovery_until": (calm_since + RECOVERY_MS) if state == "RECOVERY" and calm_since else None}


def practice_policy(state: str | None) -> dict[str, Any]:
    """What members' practice auto-trade does under a state (only when the member follows market risk)."""
    if state == "SEVERE":
        return {"open_new": False, "size": 0.0}
    if state == "HIGH":
        return {"open_new": True, "size": 0.5}
    return {"open_new": True, "size": 1.0}


def current(db) -> dict[str, Any] | None:
    s = db.get_setting("risk_state", None)
    if not s or int(time.time() * 1000) - int(s.get("at") or 0) > 2 * H:
        return None                                    # stale state = unknown, callers decide (never "safe")
    return s


def run(rt, sink=None, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    a = assess(rt, now)
    prev = rt.db.get_setting("risk_state", None)
    st = step_state(prev, a)
    rt.db.set_setting("risk_state", st)
    if not prev or prev.get("state") != st["state"]:
        log = rt.db.get_setting("risk_state_log", []) or []
        log.append({"at": now, "from": (prev or {}).get("state"), "to": st["state"], "score": st["score"], "why": st["why"]})
        rt.db.set_setting("risk_state_log", log[-300:])
    ser = rt.db.get_setting("risk_state_series", []) or []
    if not ser or now - int(ser[-1][0]) >= H - 120_000:
        ser.append([now, st["score"], st["state"]])
        ser = [x for x in ser if now - int(x[0]) <= 7 * DAY]
        rt.db.set_setting("risk_state_series", ser)
    if sink is not None:
        publish(rt, sink, st)
    return {"state": st["state"], "score": st["score"]}


def view(rt, st: dict[str, Any]) -> dict[str, Any]:
    return {"generated_at": st["at"], "state": st["state"], "label": st["label"], "policy": st["policy"],
            "score": st["score"], "since": st["since"], "why": st["why"], "recovery_until": st.get("recovery_until"),
            "factors": [{k: f[k] for k in ("key", "label", "points", "status", "value", "detail", "critical", "source")}
                        for f in st["factors"]],
            "unavailable": st["unavailable"],
            "log": (rt.db.get_setting("risk_state_log", []) or [])[-30:],
            "series": rt.db.get_setting("risk_state_series", []) or [],
            "levels": [{"state": s, "label": LABEL[s], "policy": POLICY[s]} for s in STATES],
            "method": "Points per factor (0 ok, 1 raised, 2 high). 0-1 Normal, 2-3 Caution, 4-5 High risk, 6+ Severe; "
                      "after High or Severe, Recovery until 6 calm hours. Missing BTC data counts as risk. "
                      "Signals: shown only, not blocking yet (needs a passed replay test). Practice auto-trade: "
                      "High = half size, Severe = no new trades."}


def publish(rt, sink, st: dict[str, Any]) -> None:
    if getattr(sink, "lean", False) and st["state"] not in ("HIGH", "SEVERE"):
        return
    v = view(rt, st)
    core = [v["state"], [(f["key"], f["status"]) for f in v["factors"]]]
    sink.view("risk_state", v, volatile=("generated_at",), min_interval_s=PUBLISH_EVERY_S, core=core)
