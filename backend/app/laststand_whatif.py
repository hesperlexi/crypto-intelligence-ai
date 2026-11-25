"""What-if (read-only): the Hesper Challenge's real trades replayed with Last Stand's leverage from a small start.

Each Hesper trade (same call, same entry, same exits) is re-sized with `LastStand._leverage` (up to 50x, liquidation 1.15x
the stop distance away). Net result per trade = Hesper's net P/L as a share of its notional x Last Stand's notional.
Liquidation: any 15m candle during the trade that reaches Last Stand's liquidation price while the stop does not protect
it (the bots' rule), or a trade Hesper itself lost to liquidation. After a liquidation a new run starts at `start` with the
next trade. Usage: python -m app.laststand_whatif --start 15 --out x.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3

from .engine import futures as F
from .services.hesper import LastStand, ALL_IN

STEP = 900_000


def _candles(c, symbol, a, b):
    ex = c.execute("SELECT exchange, COUNT(*) n FROM market_data WHERE symbol=? AND timeframe='15m' GROUP BY exchange "
                   "ORDER BY n DESC LIMIT 1", (symbol,)).fetchone()
    if not ex:
        return []
    return c.execute("SELECT ts, open, high, low, close FROM market_data WHERE exchange=? AND symbol=? AND timeframe='15m' "
                     "AND ts >= ? AND ts < ? ORDER BY ts", (ex[0], symbol, a, b)).fetchall()


def run(db_path: str, start: float) -> dict:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    trades = [dict(r) for r in c.execute("SELECT * FROM hesper_trades ORDER BY opened_at, id")]
    ls = LastStand.__new__(LastStand)
    bal, peak, run_no, runs, rows = start, start, 1, [], []
    hz = start                                      # the same trades at Hesper's own leverage, from the same start
    cur = {"run": 1, "start": start, "trades": 0, "wins": 0, "peak": start, "first": None}
    for t in trades:
        info = json.loads(t.get("info") or "{}") or {}
        entry, side, sym = float(t["entry"]), int(t["side"]), t["symbol"]
        stop = info.get("stop0")
        notional_h = float(t["qty"]) * entry
        q = float(t["pnl"]) / notional_h if notional_h else 0.0          # net share of notional (fees, funding included)
        hz = max(0.0, hz * (1 + ALL_IN * float(t["leverage"]) * q)) if t["exit_reason"] != "liquidated" else 0.0
        if stop is None:
            continue
        lev = ls._leverage(entry, float(stop), {"symbol": sym}, t["timeframe"]) or float(t["leverage"])
        liq = F.liquidation_price(entry, side, lev, symbol=sym)
        dead = t["exit_reason"] == "liquidated"
        if not dead:
            for ts, op, hi, lo, cl in _candles(c, sym, int(t["opened_at"]) - STEP + 1, int(t["closed_at"])):
                hit = lo <= liq if side > 0 else hi >= liq
                protected = side * (float(stop) - liq) > 0 and side * (op - liq) > 0 and side * (op - float(stop)) > 0
                if hit and not protected:
                    dead = True
                    break
        before = bal
        cur["first"] = cur["first"] or int(t["opened_at"])
        if dead:
            bal = 0.0
        else:
            bal = max(0.0, bal * (1 + ALL_IN * lev * q))
        cur["trades"] += 1
        cur["wins"] += 1 if bal > before else 0
        cur["peak"] = max(cur["peak"], bal)
        rows.append({"run": run_no, "symbol": sym, "tf": t["timeframe"], "side": side, "opened_at": t["opened_at"],
                     "hesper_lev": t["leverage"], "ls_lev": lev, "move_pct": round(q * 100, 3), "exit": t["exit_reason"],
                     "liquidated": dead, "before": round(before, 2), "after": round(bal, 2)})
        if dead or bal < 1.0:
            runs.append({**cur, "end": round(bal, 2), "result": "liquidated" if dead else "busted", "ended_at": int(t["closed_at"])})
            run_no += 1
            bal = start
            cur = {"run": run_no, "start": start, "trades": 0, "wins": 0, "peak": start, "first": None}
    if cur["trades"]:
        runs.append({**cur, "end": round(bal, 2), "result": "running", "ended_at": None})
    best = max(runs, key=lambda r: r["peak"]) if runs else None
    return {"ok": True, "start": start, "hesper_trades": len(trades), "replayed": len(rows),
            "first_trade": trades[0]["opened_at"] if trades else None, "last_trade": trades[-1]["closed_at"] if trades else None,
            "runs": runs, "liquidations": sum(1 for r in runs if r["result"] == "liquidated"),
            "best_peak": best["peak"] if best else None, "now": round(bal, 2),
            "same_trades_hesper_leverage_from_start": round(hz, 2), "rows": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/crypto_ai.db")
    ap.add_argument("--start", type=float, default=15.0)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    from .research_verdict import frozen_copy               # V3.2: private copy without the forward-holdout period
    db_path = a.db if a.db.startswith("sqlite:///") else f"sqlite:///{a.db}"
    out = json.dumps(run(frozen_copy(db_path).replace("sqlite:///", ""), a.start), indent=1, default=str)
    if a.out == "-":
        print(out)
    else:
        open(a.out, "w").write(out)
