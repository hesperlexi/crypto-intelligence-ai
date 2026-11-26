"""V3.4 Stage 3A: market regime engine (context only).

One classification of the WHOLE market, kept apart from the coin signals. Built only from data the engine already has,
read as of `now` (closed candles; records only once known; never a value from the future):

  BTC trend + structure     engine regime of BTC 4h and 1d (services/market_intel.btc_regime), 4h close vs its previous
                            30-candle range (breakout / breakdown), 4h volume expansion
  ETH relative strength     ETH vs BTC over 7 days (1h closed candles)
  breadth                   watchlist coins above their 4h EMA50 (market_intel.breadth)
  altcoin strength          median 7-day return vs BTC of the watchlist altcoins
  volatility                BTC 4h ATR14 / ATR100 (market_intel.btc_volatility)
  BTC dominance             CoinGecko /global hourly snapshots (market_snapshots, fetched_at <= now), change over 7 days
  funding, open interest,   BTC funding per 8 h, OKX open interest change 24 h, Coinalyze liquidations 24 h
  liquidations
  spot activity             BTC spot quote volume of the last closed day vs the 30 days before

Labels (`primary`): strong_bull, weak_bull, strong_bear, weak_bear, sideways, breakout, breakdown, unstable, uncertain;
`volatility`: high | low | normal (overlay, also listed in `labels`). Every input is listed in `evidence` with its reading,
what it supports and its data status. `agreement` = share of directional evidence that agrees with the trend (a count,
NOT a probability); `confidence` high / medium / low from agreement and data quality. A new label becomes the confirmed
regime only after it held for `PERSIST_RUNS` runs and `PERSIST_MIN` minutes (`transition` shows the pending one).

AUTHORITY: none. Nothing here blocks, approves, grades or sizes a trade. Stored in setting `market_regime` (log
`market_regime_log`), published as `views/market_regime` (members) and stored with each live call (`risk_shadow.regime`).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from . import market_intel as MI

H = MI.H
DAY = MI.DAY
PERSIST_RUNS = 3
PERSIST_MIN = 30
LOG_MAX = 200
NON_ALT = {"BTC/USDT", "ETH/USDT", "PAXG/USDT", "XAG/USDT", "MSTR/USDT", "ANTHROPIC/USDT"}
LABELS = ("strong_bull", "weak_bull", "strong_bear", "weak_bear", "sideways", "breakout", "breakdown", "unstable",
          "uncertain")
WORDS = {"strong_bull": "Strong uptrend", "weak_bull": "Weak uptrend", "strong_bear": "Strong downtrend",
         "weak_bear": "Weak downtrend", "sideways": "Sideways", "breakout": "Breakout", "breakdown": "Breakdown",
         "unstable": "Unstable", "uncertain": "Uncertain"}


def _ev(name: str, reading: str, supports: str, f: dict[str, Any] | None, **num: Any) -> dict[str, Any]:
    """One evidence row. supports: bull | bear | neutral | risk | none."""
    f = f or {}
    return {"input": name, "reading": reading, "supports": supports, "status": f.get("status", "unavailable"),
            "as_of": f.get("as_of"), "source": f.get("source"), **{k: v for k, v in num.items() if v is not None}}


# ---- inputs ------------------------------------------------------------------------------------------------------------

def structure(rt: Any, now: int, lookback: int = 30, recent: int = 3) -> dict[str, Any]:
    """BTC 4h close beyond its previous `lookback`-candle range within the last `recent` closed candles, plus volume."""
    src = "BTC 4h closed candles: range and volume"
    try:
        df = MI._closed(rt, "BTC/USDT", "4h", now)
    except Exception as exc:
        return MI._na(src, type(exc).__name__, now)
    if df is None or len(df) < lookback + recent + 60:
        return MI._na(src, "not enough closed 4h candles", now)
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    label = "inside range"
    for i in range(len(c) - recent, len(c)):
        hi, lo = h[i - lookback:i].max(), l[i - lookback:i].min()
        if c[i] > hi:
            label = "breakout"
        elif c[i] < lo:
            label = "breakdown"
    hi, lo = h[-lookback - 1:-1].max(), l[-lookback - 1:-1].min()
    vol_x = float(np.median(v[-6:]) / max(np.median(v[-66:-6]), 1e-12))
    st = "confirmed" if MI._fresh_candles(df, "4h", now) else "delayed"
    return MI.field(label, st, int(df["ts"].iloc[-1]) + 4 * H, src, now, range_high=round(float(hi), 2),
                    range_low=round(float(lo), 2), close=round(float(c[-1]), 2), volume_x=round(vol_x, 2))


def alt_strength(rt: Any, now: int) -> dict[str, Any]:
    src = "median 7-day return vs BTC of the watchlist altcoins"
    syms = [s for s in (rt.symbols() if hasattr(rt, "symbols") else []) if s not in NON_ALT]
    vals, stale = [], 0
    for s in syms:
        f = MI.relative_strength(rt, s, now)
        if f["status"] == "unavailable":
            continue
        stale += f["status"] != "confirmed"
        vals.append(float(f["value"]))
    if len(vals) < max(3, 0.5 * len(syms)):
        return MI._na(src, f"only {len(vals)} of {len(syms)} altcoins measurable", now)
    med = float(np.median(vals))
    st = "confirmed" if stale <= 0.2 * len(vals) else "delayed"
    return MI.field(round(med, 2), st, now - now % H, src, now, coins=len(vals),
                    beating_btc=int(sum(x > 0 for x in vals)))


def dominance(db: Any, now: int) -> dict[str, Any]:
    src = "BTC dominance (CoinGecko /global, hourly snapshots)"
    try:
        rows = db.query("SELECT ts, btc_dom, fetched_at FROM market_snapshots WHERE fetched_at <= ? AND ts >= ? ORDER BY ts",
                        (now, now - 8 * DAY))
    except Exception as exc:
        return MI._na(src, type(exc).__name__, now)
    rows = [r for r in rows if r.get("btc_dom") is not None]
    if not rows:
        return MI._na(src, "no snapshots", now)
    last = rows[-1]
    old = [r for r in rows if int(r["ts"]) <= int(last["ts"]) - 7 * DAY + 6 * H]
    ch = float(last["btc_dom"]) - float(old[0]["btc_dom"]) if old else None
    age_h = (now - int(last["fetched_at"])) / H
    st = "confirmed" if age_h <= 3 else "delayed" if age_h <= 24 else "unavailable"
    return MI.field(round(float(last["btc_dom"]), 2), st, int(last["fetched_at"]), src, now,
                    change_7d_pts=round(ch, 2) if ch is not None else None)


def spot_activity(rt: Any, now: int) -> dict[str, Any]:
    src = "BTC spot quote volume: last closed day vs the 30 days before"
    try:
        df = MI._closed(rt, "BTC/USDT", "1d", now)
    except Exception as exc:
        return MI._na(src, type(exc).__name__, now)
    if df is None or len(df) < 31:
        return MI._na(src, "fewer than 31 closed days", now)
    q = (df["volume"].to_numpy(float) * df["close"].to_numpy(float))
    ratio = float(q[-1] / max(np.median(q[-31:-1]), 1e-9))
    st = "confirmed" if MI._fresh_candles(df, "1d", now, 1.5) else "delayed"
    return MI.field(round(ratio, 2), st, int(df["ts"].iloc[-1]) + DAY, src, now)


def gather(rt: Any, now: int) -> dict[str, dict[str, Any]]:
    """Every input as a market_intel field (never raises)."""
    out: dict[str, dict[str, Any]] = {}
    calls = (("regime_4h", lambda: MI.btc_regime(rt, "4h", now)), ("regime_1d", lambda: MI.btc_regime(rt, "1d", now)),
             ("structure", lambda: structure(rt, now)), ("volatility", lambda: MI.btc_volatility(rt, now)),
             ("breadth", lambda: MI.breadth(rt, rt.symbols() if hasattr(rt, "symbols") else [], now)),
             ("eth_rs", lambda: MI.relative_strength(rt, "ETH/USDT", now)), ("alt_rs", lambda: alt_strength(rt, now)),
             ("dominance", lambda: dominance(rt.db, now)), ("funding", lambda: MI.funding(rt, "BTC/USDT", now)),
             ("open_interest", lambda: MI.open_interest(rt, "BTC/USDT", now)),
             ("liquidations", lambda: MI.liquidations(rt, "BTC/USDT", now)), ("spot", lambda: spot_activity(rt, now)))
    for name, fn in calls:
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = MI._na(name, type(exc).__name__, now)
    return out


# ---- classification (pure: inputs -> label) -----------------------------------------------------------------------------

def _dir(regime: str | None) -> int:
    r = (regime or "").upper()
    if "UNSTABLE" in r or not r:
        return 0
    return 1 if "BULL" in r else -1 if "BEAR" in r else 0


def classify(x: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ok = lambda k: x.get(k, {}).get("status") in ("confirmed", "delayed")
    val = lambda k: x.get(k, {}).get("value")
    ev: list[dict[str, Any]] = []
    core = ("regime_4h", "breadth", "volatility")
    core_ok = [k for k in core if ok(k)]
    confirmed = sum(1 for f in x.values() if f.get("status") == "confirmed")
    unavailable = sum(1 for f in x.values() if f.get("status") == "unavailable")
    quality = ("good" if len(core_ok) == 3 and all(x[k]["status"] == "confirmed" for k in core) and unavailable <= 4
               else "partial" if len(core_ok) >= 2 else "poor")

    r4, r1 = (val("regime_4h") if ok("regime_4h") else None), (val("regime_1d") if ok("regime_1d") else None)
    d4, d1 = _dir(r4), _dir(r1)
    ev.append(_ev("BTC regime 4h", r4 or "unavailable", {1: "bull", -1: "bear"}.get(d4, "neutral" if r4 else "none"),
                  x.get("regime_4h"), score=x.get("regime_4h", {}).get("score")))
    ev.append(_ev("BTC regime 1d", r1 or "unavailable", {1: "bull", -1: "bear"}.get(d1, "neutral" if r1 else "none"),
                  x.get("regime_1d")))
    st = val("structure") if ok("structure") else None
    vol_x = x.get("structure", {}).get("volume_x")
    ev.append(_ev("BTC 4h structure", st or "unavailable",
                  {"breakout": "bull", "breakdown": "bear"}.get(st or "", "neutral" if st else "none"), x.get("structure"),
                  volume_x=vol_x))
    vol = val("volatility") if ok("volatility") else None
    ev.append(_ev("BTC volatility", vol or "unavailable", "risk" if vol in ("high", "extreme") else "neutral" if vol else "none",
                  x.get("volatility"), atr_ratio=x.get("volatility", {}).get("atr_ratio")))
    b = val("breadth") if ok("breadth") else None
    ev.append(_ev("Breadth (above 4h EMA50)", f"{b:.0%}" if b is not None else "unavailable",
                  "bull" if b is not None and b >= 0.6 else "bear" if b is not None and b <= 0.4 else "neutral" if b is not None else "none",
                  x.get("breadth"), share=b))
    e = val("eth_rs") if ok("eth_rs") else None
    ev.append(_ev("ETH vs BTC, 7 d", f"{e:+.1f}%" if e is not None else "unavailable",
                  "bull" if e is not None and e >= 2 else "bear" if e is not None and e <= -4 else "neutral" if e is not None else "none",
                  x.get("eth_rs"), pct=e))
    a = val("alt_rs") if ok("alt_rs") else None
    ev.append(_ev("Altcoins vs BTC, 7 d (median)", f"{a:+.1f}%" if a is not None else "unavailable",
                  "bull" if a is not None and a >= 2 else "bear" if a is not None and a <= -4 else "neutral" if a is not None else "none",
                  x.get("alt_rs"), pct=a))
    dch = x.get("dominance", {}).get("change_7d_pts") if ok("dominance") else None
    ev.append(_ev("BTC dominance, 7 d", f"{dch:+.2f} pts" if dch is not None else "unavailable",
                  "bear" if dch is not None and dch >= 1.0 else "bull" if dch is not None and dch <= -1.0 else "neutral" if dch is not None else "none",
                  x.get("dominance"), change_pts=dch))
    fu = val("funding") if ok("funding") else None
    ev.append(_ev("BTC funding per 8 h", f"{fu:+.3f}%" if fu is not None else "unavailable",
                  "risk" if fu is not None and abs(fu) >= 0.03 else "neutral" if fu is not None else "none", x.get("funding"), pct=fu))
    oi = x.get("open_interest", {}).get("change_24h_pct") if ok("open_interest") else None
    ev.append(_ev("BTC open interest, 24 h", f"{oi:+.1f}%" if oi is not None else "unavailable",
                  "risk" if oi is not None and abs(oi) >= 8 else "neutral" if oi is not None else "none",
                  x.get("open_interest"), pct=oi))
    lq = x.get("liquidations", {}) if ok("liquidations") else {}
    lr = None
    if lq.get("longs_24h") is not None and (lq.get("longs_24h", 0) + lq.get("shorts_24h", 0)) > 0:
        lr = lq["longs_24h"] / (lq["longs_24h"] + lq["shorts_24h"])
    ev.append(_ev("BTC liquidations, 24 h", f"{lr:.0%} longs" if lr is not None else "unavailable",
                  "bear" if lr is not None and lr >= 0.75 else "bull" if lr is not None and lr <= 0.25 else "neutral" if lr is not None else "none",
                  x.get("liquidations"), long_share=round(lr, 3) if lr is not None else None))
    sp = val("spot") if ok("spot") else None
    ev.append(_ev("BTC spot volume vs 30 d", f"{sp:.2f}x" if sp is not None else "unavailable",
                  "risk" if sp is not None and sp >= 1.8 else "neutral" if sp is not None else "none", x.get("spot"), ratio=sp))

    # volatility overlay
    vol_label = "high" if vol in ("high", "extreme") else "low" if vol == "low" else "normal" if vol else None
    # trend
    bull = sum(1 for r in ev if r["supports"] == "bull")
    bear = sum(1 for r in ev if r["supports"] == "bear")
    directional = bull + bear
    reasons: list[str] = []
    if quality == "poor" or r4 is None:
        primary = "uncertain"
        reasons.append("core inputs missing (BTC 4h regime, breadth or volatility)")
    elif "UNSTABLE" in (r4 or "").upper() or vol == "extreme":
        primary = "unstable"
        reasons.append("BTC 4h regime unstable" if "UNSTABLE" in (r4 or "").upper() else "BTC volatility extreme")
    elif st == "breakout" and (vol_x or 0) >= 1.3 and d4 >= 0:
        primary = "breakout"
        reasons.append(f"BTC closed above its 30-candle 4h range on {vol_x:.1f}x volume")
    elif st == "breakdown" and (vol_x or 0) >= 1.3 and d4 <= 0:
        primary = "breakdown"
        reasons.append(f"BTC closed below its 30-candle 4h range on {vol_x:.1f}x volume")
    elif d4 == 0:
        primary = "sideways"
        reasons.append(f"BTC 4h regime {r4}")
    else:
        side = "bull" if d4 > 0 else "bear"
        strong_regime = "STRONG" in (r4 or "").upper() or (d1 == d4 and (r4 or "").upper() in ("BULL", "BEAR"))
        breadth_ok = b is not None and ((b >= 0.6) if d4 > 0 else (b <= 0.4))
        strong = strong_regime and d1 == d4 and breadth_ok
        primary = f"{'strong' if strong else 'weak'}_{side}"
        reasons.append(f"BTC 4h {r4}" + (f", 1d {r1}" if r1 else "") + (f", breadth {b:.0%}" if b is not None else ""))
    against = (bear if primary.endswith("bull") or primary == "breakout" else
               bull if primary.endswith("bear") or primary == "breakdown" else 0)
    agree = (bull if primary.endswith("bull") or primary == "breakout" else
             bear if primary.endswith("bear") or primary == "breakdown" else 0)
    if primary in ("strong_bull", "weak_bull", "strong_bear", "weak_bear") and directional >= 4 and against > agree:
        reasons.append(f"more evidence against ({against}) than for ({agree})")
        primary = "uncertain"
    agreement = round(agree / directional, 3) if directional and primary not in ("sideways", "unstable", "uncertain") else None
    risk_flags = [r["input"] for r in ev if r["supports"] == "risk"]
    confidence = ("low" if primary in ("uncertain",) or quality == "poor" or agreement is None and primary != "sideways"
                  else "high" if quality == "good" and (agreement or 0) >= 0.75 and len(risk_flags) <= 1
                  else "medium")
    if primary == "sideways":
        confidence = "medium" if quality == "good" else "low"
    labels = [primary] + ([f"{vol_label}_volatility"] if vol_label in ("high", "low") else [])
    return {"primary": primary, "word": WORDS[primary], "labels": labels, "volatility": vol_label,
            "confidence": confidence, "agreement": agreement,
            "agreement_basis": "share of directional inputs agreeing with the label (a count, not a probability)",
            "data_quality": quality, "inputs": {"confirmed": confirmed, "unavailable": unavailable, "total": len(x)},
            "evidence": ev, "reasons": reasons, "risk_flags": risk_flags, "for": bull, "against_count": bear}


# ---- transitions -------------------------------------------------------------------------------------------------------

def advance(prev: dict[str, Any] | None, cls: dict[str, Any], now: int) -> dict[str, Any]:
    """Confirmed regime with persistence; returns the new state (pure)."""
    prev = prev or {}
    cur = prev.get("confirmed")
    new = cls["primary"]
    pend = prev.get("pending")
    state: dict[str, Any] = {"confirmed": cur, "since": prev.get("since"), "previous": prev.get("previous"),
                             "pending": None, "changed": False}
    if cur is None:                                  # first reading becomes the regime at once (nothing to compare with)
        state.update(confirmed=new, since=now)
        return state
    if new == cur:
        return state
    if pend and pend.get("label") == new:
        pend = {**pend, "runs": int(pend.get("runs", 1)) + 1}
    else:
        pend = {"label": new, "first_seen": now, "runs": 1}
    if pend["runs"] >= PERSIST_RUNS and now - int(pend["first_seen"]) >= PERSIST_MIN * 60_000:
        state.update(confirmed=new, since=now, previous=cur, changed=True)
    else:
        state["pending"] = pend
    return state


# ---- worker step ---------------------------------------------------------------------------------------------------------

def build(rt: Any, now: int | None = None, prev: dict[str, Any] | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else int(now)
    x = gather(rt, now)
    cls = classify(x)
    tr = advance(prev.get("transition") if prev else None, cls, now)
    return {"at": now, **cls, "regime": tr["confirmed"], "regime_word": WORDS.get(tr["confirmed"] or "", None),
            "transition": tr, "authority": "context only - never blocks, approves or sizes a trade"}


def run(rt: Any, sink: Any = None, now: int | None = None) -> dict[str, Any]:
    prev = rt.db.get_setting("market_regime", None)
    v = build(rt, now, prev)
    rt.db.set_setting("market_regime", v)
    if v["transition"].get("changed"):
        log = (rt.db.get_setting("market_regime_log", []) or [])[-(LOG_MAX - 1):]
        log.append({"at": v["at"], "from": v["transition"].get("previous"), "to": v["regime"],
                    "confidence": v["confidence"], "data_quality": v["data_quality"]})
        rt.db.set_setting("market_regime_log", log)
    if sink is not None:
        pub = {**v, "log": (rt.db.get_setting("market_regime_log", []) or [])[-30:], "generated_at": v["at"]}
        pub.pop("at", None)
        sink.view("market_regime", pub, volatile=("generated_at",), min_interval_s=1800,
                  core={"regime": v["regime"], "primary": v["primary"], "pending": (v["transition"].get("pending") or {}).get("label")})
    return {"regime": v["regime"], "primary": v["primary"], "confidence": v["confidence"], "data_quality": v["data_quality"]}


def current(db: Any, now: int | None = None, max_age_ms: int = 30 * 60_000) -> dict[str, Any] | None:
    now = int(time.time() * 1000) if now is None else now
    v = db.get_setting("market_regime", None)
    return v if v and now - int(v.get("at") or 0) <= max_age_ms else None


def compact(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """What a call stores (risk_shadow.regime)."""
    if not v:
        return None
    return {"regime": v.get("regime"), "primary": v.get("primary"), "volatility": v.get("volatility"),
            "confidence": v.get("confidence"), "data_quality": v.get("data_quality"), "at": v.get("at")}
