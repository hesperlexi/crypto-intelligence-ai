"""PAPER TRADING. Virtual orders against live prices - this application never sends a real order."""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..db import new_id, now_ms
from .runtime import USER, Runtime

MODE = "PAPER"


class PaperError(ValueError):
    pass


def account(rt: Runtime) -> dict[str, Any]:
    acc = rt.db.one("SELECT * FROM paper_accounts WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (USER,))
    return acc or reset(rt, 10_000.0)


def reset(rt: Runtime, starting_balance: float = 10_000.0, benchmark: str = "BTC/USDT") -> dict[str, Any]:
    if starting_balance <= 0:
        raise PaperError("starting balance must be positive")
    acc = {"id": new_id(), "user_id": USER, "starting_balance": float(starting_balance), "cash": float(starting_balance),
           "created_at": now_ms(), "benchmark_symbol": benchmark, "benchmark_price": _price(rt, benchmark, required=False)}
    rt.db.execute("INSERT INTO paper_accounts (id, user_id, starting_balance, cash, created_at, benchmark_symbol, "
                  "benchmark_price) VALUES (?, ?, ?, ?, ?, ?, ?)", list(acc.values()))
    return acc


def _price(rt: Runtime, symbol: str, required: bool = True) -> float | None:
    """Live price, or the last stored close if the feed has not delivered a tick yet."""
    px = rt.live_price(symbol)
    if px is None:
        for tf in ("1m", "5m", "15m", "1h"):
            df = rt.candles(symbol, tf, include_forming=True)
            if not df.empty:
                px = float(df["close"].iloc[-1])
                break
    if px is None and required:
        raise PaperError(f"no market price available for {symbol}")
    return px


def order(rt: Runtime, symbol: str, side: str, qty: float | None = None, notional: float | None = None,
          note: str | None = None) -> dict[str, Any]:
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise PaperError("side must be BUY or SELL")
    acc = account(rt)
    mark = _price(rt, symbol)
    adverse = (settings.slippage_bps + settings.spread_bps / 2) / 1e4
    fill = mark * (1 + adverse) if side == "BUY" else mark * (1 - adverse)
    pos = rt.db.one("SELECT * FROM paper_positions WHERE account_id = ? AND symbol = ?", (acc["id"], symbol))
    held = pos["qty"] if pos else 0.0
    if qty is None:
        if notional is None:
            raise PaperError("give qty or notional")
        qty = notional / fill
    if side == "SELL" and qty > held * (1 + 1e-9):   # spot paper account: no short selling
        raise PaperError(f"cannot sell {qty:g}; position is {held:g}")
    if side == "SELL":
        qty = min(qty, held)
    if qty <= 0:
        raise PaperError("quantity must be positive")
    fee = qty * fill * settings.fee_rate
    slip = qty * abs(fill - mark)
    realized = 0.0
    if side == "BUY":
        cost = qty * fill + fee
        if cost > acc["cash"] + 1e-9:
            raise PaperError(f"insufficient virtual cash: need {cost:,.2f}, have {acc['cash']:,.2f}")
        new_qty = held + qty
        avg = ((pos["avg_price"] * held if pos else 0.0) + qty * fill) / new_qty
        cash = acc["cash"] - cost
    else:
        realized = qty * (fill - pos["avg_price"]) - fee
        new_qty, avg = held - qty, pos["avg_price"]
        cash = acc["cash"] + qty * fill - fee
    if new_qty <= 1e-12:
        rt.db.execute("DELETE FROM paper_positions WHERE account_id = ? AND symbol = ?", (acc["id"], symbol))
    else:
        rt.db.execute("INSERT INTO paper_positions (account_id, symbol, qty, avg_price) VALUES (?, ?, ?, ?) "
                      "ON CONFLICT (account_id, symbol) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price",
                      (acc["id"], symbol, new_qty, avg))
    rt.db.execute("UPDATE paper_accounts SET cash = ? WHERE id = ?", (cash, acc["id"]))
    trade = {"id": new_id(), "account_id": acc["id"], "created_at": now_ms(), "mode": MODE, "symbol": symbol,
             "side": side, "qty": float(qty), "price": float(fill), "mark_price": float(mark), "fee": float(fee),
             "slippage_cost": float(slip), "realized_pnl": float(realized), "note": note}
    rt.db.execute("INSERT INTO trades (id, account_id, created_at, mode, symbol, side, qty, price, mark_price, fee, "
                  "slippage_cost, realized_pnl, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", list(trade.values()))
    return trade


def state(rt: Runtime) -> dict[str, Any]:
    acc = account(rt)
    positions, market_value, unrealized = [], 0.0, 0.0
    for p in rt.db.query("SELECT * FROM paper_positions WHERE account_id = ?", (acc["id"],)):
        mark = _price(rt, p["symbol"], required=False)
        mv = p["qty"] * mark if mark else None
        upnl = p["qty"] * (mark - p["avg_price"]) if mark else None
        market_value += mv or 0.0
        unrealized += upnl or 0.0
        positions.append({**p, "mark": mark, "market_value": mv, "unrealized_pnl": upnl,
                          "unrealized_pct": (mark / p["avg_price"] - 1) * 100 if mark else None})
    trades = rt.db.query("SELECT * FROM trades WHERE account_id = ? ORDER BY created_at DESC LIMIT 200", (acc["id"],))
    tot = rt.db.one("SELECT COALESCE(SUM(realized_pnl), 0) AS r, COALESCE(SUM(fee), 0) AS f, "
                    "COALESCE(SUM(slippage_cost), 0) AS s, COUNT(*) AS n FROM trades WHERE account_id = ?", (acc["id"],))
    equity = acc["cash"] + market_value
    bench_now = _price(rt, acc["benchmark_symbol"], required=False) if acc["benchmark_symbol"] else None
    bench_ret = (bench_now / acc["benchmark_price"] - 1) if bench_now and acc["benchmark_price"] else None
    ret = equity / acc["starting_balance"] - 1
    return {
        "mode": "PAPER TRADING", "account": acc, "cash": acc["cash"], "market_value": market_value, "equity": equity,
        "return_pct": ret * 100, "realized_pnl": tot["r"], "unrealized_pnl": unrealized, "fees": tot["f"],
        "slippage": tot["s"], "trade_count": tot["n"], "positions": positions, "trades": trades,
        "benchmark": {"label": f"Buy & hold {acc['benchmark_symbol']} since account start",
                      "return_pct": None if bench_ret is None else bench_ret * 100,
                      "excess_pct": None if bench_ret is None else (ret - bench_ret) * 100},
        "day_realized_pnl": rt.db.one("SELECT COALESCE(SUM(realized_pnl), 0) AS r FROM trades WHERE account_id = ? "
                                      "AND created_at >= ?", (acc["id"], now_ms() - 86_400_000))["r"],
    }
