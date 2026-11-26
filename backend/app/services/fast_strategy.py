"""V3.4 Stage 3D: Fast Opportunity paper strategy - ISOLATED, paper only, never promoted automatically.

What it is: a separate virtual book that takes long-only entries from the Fast Opportunity Radar's clean candidates.
What it is not: a signal. Nothing in the record, the bots, Hesper / Last Stand, members' auto-trade, alerts, Telegram or
the public views reads it (a test checks); it reads the radar only through the compact setting `radar_fast_snapshot`
(never the radar module) and asks the central portfolio controller (services/portfolio_risk.book_check) before every entry.

Own configuration (setting `fast_strategy_config`, defaults below), own state (`fast_strategy_state`), own trades (table
`fast_trades`, never deleted), own statistics (`stats`) and own promotion check (`promotion`, report only).

Rules (fixed in `DEFAULTS`; a change of any rule restarts the count used for promotion: `config_hash`):
  entry      radar candidate flagged in the top 3 of its category, score > min_score, NO warnings, liquidity ok,
             above the 1h EMA20 and EMA50, radar snapshot <= 2 h old; long only
  regime     no new entry when the market regime is a downtrend / breakdown / unstable / uncertain or the market risk
             state is HIGH / SEVERE
  size       risk_pct (0.25 %) of equity between entry and stop; notional <= max_notional_pct of equity and <= cash
  stop       entry - stop_atr x ATR(24, 1h); break-even (entry + costs) once a closed bar is >= +1R
  exits      stop first, then target (target_r x R); trend exit when the coin closes below its 1h EMA50; time exit
             after max_hold_h; all on CLOSED 1h bars, a stop gapped through fills at that bar's close
  costs      spot taker fee per side + slippage (meme / alt) + half the spread, both ways, in every result
  duplicates one open position per coin; the same radar bar is never taken twice; cooldown_h per coin after a close;
             2 losses in a row -> pause_h; strategy drawdown >= halt_dd_r -> no new entries until the owner resets it
  outages    no new bars -> nothing is assumed: stop / target stay in force and are checked on the bars when they come
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

H = 3_600_000
DEFAULTS: dict[str, Any] = {
    "enabled": True, "start_balance": 10_000.0, "risk_pct": 0.25, "max_open": 3, "max_notional_pct": 20.0,
    "top_n": 3, "min_score": 0.25, "stop_atr": 2.0, "target_r": 2.0, "max_hold_h": 72, "cooldown_h": 24, "pause_h": 12,
    "halt_dd_r": 8.0, "fee_pct": 0.10, "slippage_bps": {"meme": 15.0, "alt": 8.0}, "max_snapshot_age_h": 2.0,
}
BLOCK_REGIMES = ("strong_bear", "weak_bear", "breakdown", "unstable", "uncertain")
BLOCK_RISK = ("HIGH", "SEVERE")
PROMOTION = {"min_closed": 300, "min_pf": 1.1, "max_dd_r": 15.0, "min_category_n": 50, "min_regime_n": 30,
             "min_assets": 5, "min_asset_n": 20}


def config(db: Any) -> dict[str, Any]:
    c = dict(DEFAULTS)
    v = db.get_setting("fast_strategy_config", None)
    if isinstance(v, dict):
        c.update({k: v[k] for k in v if k in DEFAULTS})
    c["risk_pct"] = min(float(c["risk_pct"]), DEFAULTS["risk_pct"])      # never above 0.25 % without a code change
    return c


def config_hash(c: dict[str, Any]) -> str:
    rules = {k: c[k] for k in sorted(c) if k not in ("enabled",)}
    return hashlib.sha1(json.dumps(rules, sort_keys=True).encode()).hexdigest()[:12]


def ensure(db: Any) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS fast_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT NOT NULL, symbol TEXT, category TEXT, source TEXT,
        signal_bar INTEGER, opened_at INTEGER, entry REAL, stop0 REAL, stop REAL, target REAL, qty REAL, risk_usd REAL,
        cost_pct REAL, fees REAL, status TEXT DEFAULT 'OPEN', exit REAL, exit_reason TEXT, closed_at INTEGER, pnl REAL,
        r REAL, last_bar INTEGER, regime TEXT, score REAL, config_hash TEXT, notes TEXT)""")
    db.execute("CREATE INDEX IF NOT EXISTS fast_trades_coin ON fast_trades (coin, status)")


def _state(db: Any, c: dict[str, Any]) -> dict[str, Any]:
    s = db.get_setting("fast_strategy_state", None)
    if not isinstance(s, dict):
        s = {"cash": float(c["start_balance"]), "start_balance": float(c["start_balance"]), "cooldown": {},
             "taken_bars": {}, "loss_streak": 0, "pause_until": 0, "halted": False, "peak_r": 0.0, "cum_r": 0.0,
             "started_at": int(time.time() * 1000), "errors": []}
    return s


def costs(c: dict[str, Any], category: str | None, spread_bps: float | None) -> float:
    """One-way cost as a fraction of price."""
    slip = float((c["slippage_bps"] or {}).get(category or "alt", 10.0))
    return float(c["fee_pct"]) / 100 + (slip + (spread_bps or 10.0) / 2) / 1e4


def open_trades(db: Any) -> list[dict[str, Any]]:
    ensure(db)
    return db.query("SELECT * FROM fast_trades WHERE status = 'OPEN' ORDER BY opened_at")


def book(db: Any) -> dict[str, Any]:
    """This book in the shape the central portfolio controller reads (services/portfolio_risk.book_positions)."""
    return {"positions": [{"symbol": t["symbol"], "side": 1, "entry": t["entry"], "stop": t["stop"], "stop0": t["stop0"],
                           "qty": t["qty"], "qty_open": t["qty"]} for t in open_trades(db)], "pending": []}


def _close(db: Any, t: dict[str, Any], price: float, reason: str, at: int, one_way: float) -> dict[str, Any]:
    exit_px = price * (1 - one_way)
    fees = float(t["fees"] or 0) + exit_px * t["qty"] * one_way
    pnl = (exit_px - t["entry"]) * t["qty"]
    r = pnl / t["risk_usd"] if t["risk_usd"] else None
    db.execute("UPDATE fast_trades SET status = 'CLOSED', exit = ?, exit_reason = ?, closed_at = ?, pnl = ?, r = ?, fees = ? "
               "WHERE id = ?", (exit_px, reason, at, pnl, r, fees, t["id"]))
    return {"id": t["id"], "coin": t["coin"], "reason": reason, "pnl": round(pnl, 2), "r": round(r, 3) if r is not None else None}


def manage(db: Any, snap: dict[str, Any], c: dict[str, Any], st: dict[str, Any], now: int) -> list[dict[str, Any]]:
    """Follow every open trade on the closed bars it has not seen yet. Returns the closes."""
    coins = {x["coin"]: x for x in snap.get("coins") or []}
    closed = []
    for t in open_trades(db):
        x = coins.get(t["coin"])
        if not x:
            continue                                   # no data this hour: nothing assumed, stop stays in force
        one_way = float(t["cost_pct"] or 0)
        risk = t["entry"] - t["stop0"]
        stop = float(t["stop"])
        done = None
        last = int(t["last_bar"] or t["signal_bar"] or 0)
        for ts, hi, lo, cl in sorted(x.get("recent_bars") or []):
            if ts <= last:
                continue
            last = ts
            if lo <= stop:
                done = (min(stop, cl) if hi < stop else stop, "stop" if stop < t["entry"] else "break-even", ts + H)
                break
            if hi >= t["target"]:
                done = (t["target"], "target", ts + H)
                break
            if cl >= t["entry"] + risk and stop < t["entry"]:
                stop = t["entry"] * (1 + 2 * one_way)  # break-even after costs
            if ts + H - int(t["opened_at"]) >= int(c["max_hold_h"]) * H:
                done = (cl, "time", ts + H)
                break
        if done is None and x.get("above_ema50") is False and last > int(t["signal_bar"] or 0):
            bars = sorted(x.get("recent_bars") or [])
            if bars and bars[-1][0] == last:
                done = (bars[-1][3], "trend exit (below 1h EMA50)", last + H)
        db.execute("UPDATE fast_trades SET stop = ?, last_bar = ? WHERE id = ?", (stop, last, t["id"]))
        if done:
            res = _close(db, {**t, "stop": stop}, done[0], done[1], done[2], one_way)
            closed.append(res)
            st["cash"] = float(st["cash"]) + done[0] * (1 - one_way) * t["qty"]
            st["cooldown"][t["coin"]] = done[2]
            st["loss_streak"] = st.get("loss_streak", 0) + 1 if (res["pnl"] or 0) < 0 else 0
            if st["loss_streak"] >= 2:
                st["pause_until"] = now + int(c["pause_h"]) * H
            st["cum_r"] = float(st.get("cum_r", 0)) + (res["r"] or 0)
            st["peak_r"] = max(float(st.get("peak_r", 0)), st["cum_r"])
            if st["peak_r"] - st["cum_r"] >= float(c["halt_dd_r"]):
                st["halted"] = True
    return closed


def equity(db: Any, st: dict[str, Any], snap: dict[str, Any]) -> float:
    px = {x["coin"]: x.get("price") for x in snap.get("coins") or []}
    return float(st["cash"]) + sum(float(px.get(t["coin"]) or t["entry"]) * t["qty"] for t in open_trades(db))


def candidates(snap: dict[str, Any], c: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for x in snap.get("coins") or []:
        if not x.get("flagged") or (x.get("category_rank") or 99) > int(c["top_n"]):
            continue
        if (x.get("score") or 0) <= float(c["min_score"]) or x.get("warnings"):
            continue
        if not x.get("liquidity_ok") or not x.get("above_ema20") or not x.get("above_ema50"):
            continue
        if not x.get("atr_24") or not x.get("price") or not x.get("recent_bars"):
            continue
        out.append(x)
    return sorted(out, key=lambda x: -(x.get("score") or 0))


def run(rt: Any, now: int | None = None) -> dict[str, Any]:
    """Hourly, after the radar scan. Manages open trades, then considers entries. Never raises."""
    db = rt.db
    now = int(time.time() * 1000) if now is None else int(now)
    c = config(db)
    if not c["enabled"]:
        return {"enabled": False}
    ensure(db)
    st = _state(db, c)
    out: dict[str, Any] = {"opened": [], "closed": [], "skipped": []}
    snap = db.get_setting("radar_fast_snapshot", None) or {}
    try:
        out["closed"] = manage(db, snap, c, st, now)
        fresh = snap and now - int(snap.get("at") or 0) <= float(c["max_snapshot_age_h"]) * H
        reg, risk = snap.get("market_regime"), snap.get("regime")
        why_not = ("radar snapshot missing or old" if not fresh else "strategy halted (drawdown)" if st.get("halted")
                   else "paused after 2 losses" if now < int(st.get("pause_until") or 0)
                   else f"market regime {reg}" if (reg in BLOCK_REGIMES or reg is None)
                   else f"market risk {risk}" if risk in BLOCK_RISK else None)
        if why_not:
            out["skipped"].append(why_not)
        else:
            eq = equity(db, st, snap)
            for x in candidates(snap, c):
                opens = open_trades(db)
                if len(opens) >= int(c["max_open"]):
                    out["skipped"].append("max open reached")
                    break
                coin, bar = x["coin"], int(x["recent_bars"][-1][0])
                if any(t["coin"] == coin for t in opens):
                    continue
                if (st["taken_bars"].get(coin) or 0) >= bar:
                    continue                                   # the same radar bar is never taken twice
                if now - int(st["cooldown"].get(coin) or 0) < int(c["cooldown_h"]) * H:
                    out["skipped"].append(f"{coin}: cooldown")
                    continue
                gate = _portfolio(rt, db, x["symbol"])
                if not gate.get("allowed", False):
                    out["skipped"].append(f"{coin}: {gate.get('reason') or 'portfolio limit'}")
                    continue
                one_way = costs(c, x.get("category"), x.get("spread_bps"))
                entry = float(x["price"]) * (1 + one_way)
                stop = float(x["price"]) - float(c["stop_atr"]) * float(x["atr_24"])
                risk_ps = entry - stop
                if stop <= 0 or risk_ps <= 0:
                    continue
                risk_usd = eq * float(c["risk_pct"]) / 100
                qty = risk_usd / risk_ps
                cap = min(eq * float(c["max_notional_pct"]) / 100, float(st["cash"]))
                if qty * entry > cap:
                    qty = cap / entry
                    risk_usd = qty * risk_ps
                if qty <= 0 or qty * entry < 10:
                    out["skipped"].append(f"{coin}: too small")
                    continue
                fee = entry * qty * one_way
                db.execute("INSERT INTO fast_trades (coin, symbol, category, source, signal_bar, opened_at, entry, stop0, stop, "
                           "target, qty, risk_usd, cost_pct, fees, last_bar, regime, score, config_hash, notes) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (coin, x["symbol"], x.get("category"), x.get("source"), bar, bar + H, entry, stop, stop,
                            entry + float(c["target_r"]) * risk_ps, qty, risk_usd, one_way, fee, bar, reg, x.get("score"),
                            config_hash(c), "entry = last closed 1h close + fee + slippage + half spread"))
                st["cash"] = float(st["cash"]) - entry * qty
                st["taken_bars"][coin] = bar
                out["opened"].append({"coin": coin, "entry": round(entry, 8), "stop": round(stop, 8), "risk_usd": round(risk_usd, 2)})
    except Exception as exc:
        st["errors"] = ((st.get("errors") or []) + [{"at": now, "error": f"{type(exc).__name__}: {exc}"[:160]}])[-20:]
        out["error"] = type(exc).__name__
    db.set_setting("fast_strategy_state", st)
    return out


def _portfolio(rt: Any, db: Any, symbol: str) -> dict[str, Any]:
    try:
        from . import portfolio_risk as PR
        return PR.book_check(rt, book(db), symbol, 1)
    except Exception as exc:
        return {"allowed": False, "reason": f"portfolio check unavailable ({type(exc).__name__})"}


# ---- statistics and promotion (report only) ---------------------------------------------------------------------------

def _agg(rs: list[float]) -> dict[str, Any]:
    n = len(rs)
    if not n:
        return {"n": 0}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    gains, losses = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
    cum = peak = dd = 0.0
    for x in rs:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"n": n, "win_rate": round(sum(x > 0 for x in rs) / n, 3), "avg_r": round(m, 4), "total_r": round(sum(rs), 3),
            "ci95": [round(m - 1.96 * sd / math.sqrt(n), 4), round(m + 1.96 * sd / math.sqrt(n), 4)] if n > 1 else None,
            "profit_factor": round(gains / losses, 3) if losses > 0 else None, "max_dd_r": round(dd, 3)}


def stats(db: Any, config_hash_only: str | None = None) -> dict[str, Any]:
    ensure(db)
    rows = db.query("SELECT * FROM fast_trades WHERE status = 'CLOSED'" + (" AND config_hash = ?" if config_hash_only else "")
                    + " ORDER BY closed_at", (config_hash_only,) if config_hash_only else ())
    rs = [float(r["r"]) for r in rows if r["r"] is not None]
    by = lambda key: {k: _agg([float(r["r"]) for r in rows if r.get(key) == k and r["r"] is not None])  # noqa: E731
                      for k in sorted({str(r.get(key)) for r in rows}) if k != "None"}
    return {"overall": _agg(rs), "net_pnl": round(sum(float(r["pnl"] or 0) for r in rows), 2),
            "fees": round(sum(float(r["fees"] or 0) for r in rows), 2),
            "by_category": by("category"), "by_regime": by("regime"), "by_coin": by("coin"),
            "exits": {e: sum(1 for r in rows if r["exit_reason"] == e) for e in sorted({r["exit_reason"] for r in rows})},
            "open": len(open_trades(db)), "basis": "paper only; net of fee, slippage and half spread; R = P/L / planned risk"}


def promotion(db: Any) -> dict[str, Any]:
    """Whether the strategy meets EVERY promotion requirement (it is never promoted automatically). Only trades made
    under the current rules count (a rule change restarts the count: forward evidence only)."""
    c = config(db)
    h = config_hash(c)
    s = stats(db, h)
    o = s["overall"]
    failed: list[str] = []
    P = PROMOTION
    if o.get("n", 0) < P["min_closed"]:
        failed.append(f"{o.get('n', 0)} of {P['min_closed']} closed paper trades under the current rules")
    if not o.get("ci95") or o["ci95"][0] <= 0:
        failed.append("net expectancy not shown above zero (95 % interval)")
    if (o.get("profit_factor") or 0) < P["min_pf"]:
        failed.append(f"profit factor below {P['min_pf']}")
    if (o.get("max_dd_r") or 0) > P["max_dd_r"]:
        failed.append(f"drawdown above {P['max_dd_r']}R")
    for k, v in s["by_category"].items():
        if v["n"] >= P["min_category_n"] and v["avg_r"] <= 0:
            failed.append(f"{k}: negative after costs")
    for k, v in s["by_regime"].items():
        if v["n"] >= P["min_regime_n"] and v["avg_r"] < 0:
            failed.append(f"market regime {k}: negative")
    if len({k for k, v in s["by_category"].items() if v["n"] >= P["min_category_n"]}) < 1:
        failed.append("no category with enough trades")
    if sum(1 for v in s["by_coin"].values() if v["n"] >= P["min_asset_n"]) < P["min_assets"]:
        failed.append(f"fewer than {P['min_assets']} coins with {P['min_asset_n']}+ trades")
    st = db.get_setting("fast_strategy_state", {}) or {}
    recent_err = [e for e in st.get("errors") or [] if int(time.time() * 1000) - int(e.get("at", 0)) <= 7 * 24 * H]
    if recent_err:
        failed.append(f"{len(recent_err)} unresolved errors in the last 7 days")
    if st.get("halted"):
        failed.append("halted by its drawdown limit")
    failed.append("protected forward holdout verdict not yet run (owner step: research_verdict.read_holdout_once)") \
        if not db.get_setting("fast_strategy_holdout_verdict", None) else None
    failed = [f for f in failed if f]
    return {"eligible": not failed, "promoted": False, "failed": failed, "config_hash": h, "requirements": P,
            "note": "a trade count alone proves nothing; promotion is a manual owner decision even when eligible"}


def report(db: Any) -> dict[str, Any]:
    c = config(db)
    st = db.get_setting("fast_strategy_state", {}) or {}
    return {"config": c, "config_hash": config_hash(c), "stats": stats(db), "promotion": promotion(db),
            "state": {k: st.get(k) for k in ("cash", "start_balance", "halted", "pause_until", "loss_streak", "started_at")},
            "open_trades": [{k: t[k] for k in ("coin", "category", "opened_at", "entry", "stop", "target", "risk_usd")}
                            for t in open_trades(db)],
            "authority": "isolated paper strategy: never a signal, never in the record, bots or members' accounts"}
