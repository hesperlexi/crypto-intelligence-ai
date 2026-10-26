"""DEMO TRADING BOTS. Virtual money only - this module never talks to an exchange's trading API.

Two kinds of bot, both run by the engine on every cycle, on either market:

* market = spot     - 1x, the full position value is set aside (shorts are simulated the same way)
* market = futures  - USDT-margined perpetual, isolated margin: only margin = notional / leverage is set aside,
                      futures fees, funding paid / received every 8 hours, and liquidation when price reaches
                      the liquidation price (the remaining margin is lost). With `safe_leverage` the bot lowers
                      leverage so the liquidation price always sits well beyond the stop.


* decision   - trades only the engine's final decisions (BUY / BUY ON PULLBACK / SELL) with the trade plan's
               entry, stop and three targets, risk-based sizing, a third of the position closed at each
               target, the stop moved to break-even after TP1 and trailed to TP1 after TP2. Measures what following the signals earns.
* prediction - trades every ensemble call (UP -> long, DOWN -> short) for exactly one bar of its timeframe,
               with no other filter. Measures the raw accuracy and payoff of the model's predictions.

Honesty rules:
* entries fill at the price available when the engine runs (never at an earlier close), plus spread and
  slippage, and pay the trading fee
* stops and targets are checked against every closed 15-minute candle since the previous check; when one
  candle touches both, the stop is assumed to fill first
* nothing is back-filled: statistics only contain trades the bot actually took after it started
"""
from __future__ import annotations

import copy
from typing import Any

import numpy as np

from ..config import settings
from ..data.base import tf_ms
from ..db import Database, dumps, loads, new_id, now_ms
from ..engine import futures as F
from . import analysis
from .runtime import Runtime

PATH_TF = "15m"
CONF_BUCKETS = (0.0, 0.45, 0.5, 0.55, 0.6, 1.0001)
MAX_EQUITY_POINTS = 3000

_FUT = {"market": "futures", "safe_leverage": True}
DEFAULT_BOTS: list[dict[str, Any]] = [
    {"id": "signal-4h", "name": "Signal bot 4H", "enabled": True, "mode": "decision", "timeframe": "4h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 25.0,
     "max_open_positions": 5, "allow_short": True, "pending_bars": 6, "max_hold_bars": 42, "reset_token": "1", "market": "spot", "leverage": 1.0},
    {"id": "signal-1h", "name": "Signal bot 1H", "enabled": True, "mode": "decision", "timeframe": "1h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 25.0,
     "max_open_positions": 5, "allow_short": True, "pending_bars": 6, "max_hold_bars": 48, "reset_token": "1", "market": "spot", "leverage": 1.0},
    {"id": "predict-4h", "name": "Prediction tracker 4H", "enabled": True, "mode": "prediction", "timeframe": "4h",
     "symbols": "all", "starting_balance": 10_000.0, "position_pct": 10.0, "min_probability": 0.40,
     "allow_short": True, "reset_token": "1", "market": "spot", "leverage": 1.0},
    {"id": "predict-1h", "name": "Prediction tracker 1H", "enabled": True, "mode": "prediction", "timeframe": "1h",
     "symbols": "all", "starting_balance": 10_000.0, "position_pct": 10.0, "min_probability": 0.40,
     "allow_short": True, "reset_token": "1", "market": "spot", "leverage": 1.0},
    {"id": "predict-confident-4h", "name": "Confident-call tracker 4H", "enabled": True, "mode": "prediction",
     "timeframe": "4h", "symbols": "all", "starting_balance": 10_000.0, "position_pct": 10.0, "min_probability": 0.40,
     "allow_short": True, "reset_token": "1", "market": "spot", "leverage": 1.0, "confident_only": True},
    {"id": "futures-signal-4h", "name": "Futures signal bot 4H", "enabled": True, "mode": "decision", "timeframe": "4h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 20.0,
     "max_open_positions": 5, "allow_short": True, "pending_bars": 6, "max_hold_bars": 42, "reset_token": "1",
     "leverage": 5.0, **_FUT},
    {"id": "futures-signal-1h", "name": "Futures signal bot 1H", "enabled": True, "mode": "decision", "timeframe": "1h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 20.0,
     "max_open_positions": 5, "allow_short": True, "pending_bars": 6, "max_hold_bars": 48, "reset_token": "1",
     "leverage": 5.0, **_FUT},
    {"id": "signal-ab-4h", "name": "Signal bot 4H · grades A+B", "enabled": True, "mode": "decision", "timeframe": "4h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 25.0,
     "max_open_positions": 6, "allow_short": True, "pending_bars": 6, "max_hold_bars": 42, "reset_token": "1", "market": "spot",
     "leverage": 1.0, "grades": "AB"},
    {"id": "signal-ab-1h", "name": "Signal bot 1H · grades A+B", "enabled": True, "mode": "decision", "timeframe": "1h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 25.0,
     "max_open_positions": 6, "allow_short": True, "pending_bars": 6, "max_hold_bars": 48, "reset_token": "1", "market": "spot",
     "leverage": 1.0, "grades": "AB"},
    {"id": "futures-signal-ab-4h", "name": "Futures signal bot 4H · grades A+B", "enabled": True, "mode": "decision", "timeframe": "4h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 20.0,
     "max_open_positions": 6, "allow_short": True, "pending_bars": 6, "max_hold_bars": 42, "reset_token": "1",
     "leverage": 5.0, "grades": "AB", **_FUT},
    {"id": "futures-signal-ab-1h", "name": "Futures signal bot 1H · grades A+B", "enabled": True, "mode": "decision", "timeframe": "1h",
     "symbols": "all", "starting_balance": 10_000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 20.0,
     "max_open_positions": 6, "allow_short": True, "pending_bars": 6, "max_hold_bars": 48, "reset_token": "1",
     "leverage": 5.0, "grades": "AB", **_FUT},
    {"id": "futures-predict-1h", "name": "Futures prediction tracker 1H", "enabled": True, "mode": "prediction",
     "timeframe": "1h", "symbols": "all", "starting_balance": 10_000.0, "position_pct": 5.0, "min_probability": 0.40,
     "allow_short": True, "reset_token": "1", "leverage": 3.0, **_FUT},
]
def size_multiplier(grade: str | None, filter_score: float | None = None, filter_threshold: float | None = None) -> float:
    """Bigger on stronger calls, smaller on weaker ones (0.5x - 1.5x of the normal risk): grade A 1.2x, grade B 0.8x,
    plus up to +30 % when the trade filter scores the setup well above its bar."""
    m = 1.2 if grade == "A" else 0.8 if grade == "B" else 1.0
    if filter_score is not None and filter_threshold:
        m *= float(np.clip(1 + (filter_score - filter_threshold) * 2, 1.0, 1.3))
    return float(np.clip(m, 0.5, 1.5))


# the bots that take exactly the calls members see on the Signals page (futures, grades A+B, every coin):
# the app's own scorecard, shown first on the public track record
SCORECARD_IDS = ("futures-signal-ab-1h", "futures-signal-ab-4h")
FIELDS = {"name": str, "enabled": bool, "mode": str, "timeframe": str, "symbols": (str, list),
          "starting_balance": float, "risk_per_trade_pct": float, "max_position_pct": float,
          "max_open_positions": int, "allow_short": bool, "pending_bars": int, "max_hold_bars": int,
          "position_pct": float, "min_probability": float, "reset_token": str, "market": str, "leverage": float,
          "safe_leverage": bool, "confident_only": bool, "grades": str, "edge_sizing": bool, "max_same_side": int}


def clean_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a bot config coming from the website. Unknown or malformed fields are dropped."""
    market = "futures" if raw.get("market") == "futures" else "spot"
    base = next((copy.deepcopy(b) for b in DEFAULT_BOTS if b["mode"] == raw.get("mode") and b.get("market", "spot") == market),
                copy.deepcopy(DEFAULT_BOTS[0]))
    out = {**base, "id": str(raw.get("id") or new_id()[:8])}
    for k, typ in FIELDS.items():
        if k not in raw or raw[k] is None:
            continue
        v = raw[k]
        try:
            if typ is float:
                v = float(v)
            elif typ is int:
                v = int(v)
            elif typ is bool:
                v = bool(v)
            elif typ is str:
                v = str(v)
            elif not isinstance(v, (str, list)):
                continue
        except (TypeError, ValueError):
            continue
        out[k] = v
    if out["mode"] not in ("decision", "prediction"):
        out["mode"] = "decision"
    if out["timeframe"] not in ("1h", "4h", "12h", "1d"):
        out["timeframe"] = "4h"
    out["starting_balance"] = max(100.0, out["starting_balance"])
    out["risk_per_trade_pct"] = float(np.clip(out.get("risk_per_trade_pct", 1.0), 0.05, 10))
    out["max_position_pct"] = float(np.clip(out.get("max_position_pct", 25.0), 1, 100))
    out["position_pct"] = float(np.clip(out.get("position_pct", 10.0), 1, 100))
    out["min_probability"] = float(np.clip(out.get("min_probability", 0.4), 0.34, 0.95))
    out["max_open_positions"] = int(np.clip(out.get("max_open_positions", 5), 1, 50))
    out["market"] = "futures" if out.get("market") == "futures" else "spot"
    out["leverage"] = float(np.clip(out.get("leverage", 1.0), 1, F.MAX_LEVERAGE)) if out["market"] == "futures" else 1.0
    out["safe_leverage"] = bool(out.get("safe_leverage", True))
    out["confident_only"] = bool(out.get("confident_only", False))
    return out


class BotEngine:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.db: Database = rt.db
        self.adverse = (settings.slippage_bps + settings.spread_bps / 2) / 1e4
        self.fee = settings.fee_rate
        self.funding: dict[str, dict[str, Any]] = getattr(rt, "funding_rates", None) or {}

    # ---- configuration ----------------------------------------------------------------------------------
    def sync_configs(self, configs: list[dict[str, Any]]) -> None:
        """Mirror the website's bot list. A changed reset_token (or starting balance) restarts that bot."""
        wanted = {c["id"]: c for c in (clean_config(c) for c in configs)}
        have = {r["id"]: r for r in self.db.query("SELECT * FROM bots")}
        for bid in set(have) - set(wanted):
            self._wipe(bid)
            self.db.execute("DELETE FROM bots WHERE id = ?", (bid,))
        for bid, cfg in wanted.items():
            row = have.get(bid)
            old = loads(row["config"], {}) if row else None
            if row is None or row["reset_token"] != cfg["reset_token"] or old.get("starting_balance") != cfg["starting_balance"] \
                    or old.get("mode") != cfg["mode"] or old.get("timeframe") != cfg["timeframe"] \
                    or old.get("market", "spot") != cfg["market"]:
                self._wipe(bid)
                self.db.execute("DELETE FROM bots WHERE id = ?", (bid,))
                self.db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES (?, ?, ?, ?, ?)",
                                (bid, dumps(cfg), dumps(self._fresh_state(cfg)), cfg["reset_token"], now_ms()))
            else:
                self.db.execute("UPDATE bots SET config = ? WHERE id = ?", (dumps(cfg), bid))

    def _wipe(self, bid: str) -> None:
        self.db.execute("DELETE FROM bot_trades WHERE bot_id = ?", (bid,))
        self.db.execute("DELETE FROM bot_equity WHERE bot_id = ?", (bid,))

    def _fresh_state(self, cfg: dict[str, Any]) -> dict[str, Any]:
        return {"cash": cfg["starting_balance"], "positions": [], "pending": [], "started_at": now_ms(),
                "start_prices": {}, "last_bar": {}, "last_entry_bar": {}, "fees_paid": 0.0, "notes": [],
                "funding_paid": 0.0, "liquidations": 0}

    def bots(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return [(loads(r["config"], {}), loads(r["state"], {})) for r in self.db.query("SELECT * FROM bots ORDER BY created_at")]

    # ---- market access ------------------------------------------------------------------------------------
    def _price(self, symbol: str) -> float | None:
        px = self.rt.live_price(symbol)
        if px is None:
            df = self.rt.candles(symbol, PATH_TF)
            px = float(df["close"].iloc[-1]) if not df.empty else None
        return px

    def _path(self, symbol: str, after_ts: int) -> list[tuple[int, float, float, float, float]]:
        """Closed 15m candles opened after `after_ts`: (open_ts, open, high, low, close)."""
        df = self.rt.candles(symbol, PATH_TF)
        df = df[df["ts"] > after_ts]
        return list(zip(df["ts"].astype(int), df["open"], df["high"], df["low"], df["close"]))

    # ---- one cycle --------------------------------------------------------------------------------------
    def run(self, now: int | None = None) -> list[dict[str, Any]]:
        now = now_ms() if now is None else now
        events: list[dict[str, Any]] = []
        for cfg, state in self.bots():
            if not cfg.get("enabled", True):
                self._mark(cfg, state, now)
                continue
            syms = self.rt.symbols() if cfg["symbols"] == "all" else [s for s in cfg["symbols"] if s in self.rt.symbols()]
            for s in syms:
                if s not in state["start_prices"]:
                    px = self._price(s)
                    if px:
                        state["start_prices"][s] = px
            self._funding(state, now)
            if cfg["mode"] == "decision":
                events += self._manage_decision(cfg, state, now)
                events += self._enter_decision(cfg, state, syms, now)
            else:
                events += self._run_prediction(cfg, state, syms, now)
            self._mark(cfg, state, now)
        return events

    def _mark(self, cfg: dict[str, Any], state: dict[str, Any], now: int) -> None:
        eq = self.equity(state)
        bench = self._benchmark(cfg, state)
        self.db.execute("INSERT INTO bot_equity (bot_id, ts, equity, benchmark) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT (bot_id, ts) DO UPDATE SET equity = excluded.equity, benchmark = excluded.benchmark",
                        (cfg["id"], now, eq, bench))
        n = self.db.one("SELECT COUNT(*) AS n FROM bot_equity WHERE bot_id = ?", (cfg["id"],))["n"]
        if n > MAX_EQUITY_POINTS:   # thin the oldest half to every other point
            rows = self.db.query("SELECT ts FROM bot_equity WHERE bot_id = ? ORDER BY ts LIMIT ?", (cfg["id"], n // 2))
            self.db.executemany("DELETE FROM bot_equity WHERE bot_id = ? AND ts = ?",
                                [(cfg["id"], r["ts"]) for r in rows[1::2]])
        state["equity"], state["benchmark"], state["updated_at"] = eq, bench, now
        self.db.execute("UPDATE bots SET state = ? WHERE id = ?", (dumps(state), cfg["id"]))

    def equity(self, state: dict[str, Any]) -> float:
        eq = state["cash"]
        for p in state["positions"]:
            px = self._price(p["symbol"]) or p["entry"]
            value = p["qty_open"] * _coll(p) + p["side"] * p["qty_open"] * (px - p["entry"])
            eq += max(0.0, value) if p.get("lev", 1) > 1 else value     # isolated margin cannot go below zero
        for o in state["pending"]:
            eq += o.get("reserved", 0.0)
        return float(eq)

    def _benchmark(self, cfg: dict[str, Any], state: dict[str, Any]) -> float | None:
        rel = [self._price(s) / p0 for s, p0 in state["start_prices"].items() if p0 and self._price(s)]
        return float(cfg["starting_balance"] * np.mean(rel)) if rel else None

    # ---- fills ------------------------------------------------------------------------------------------
    def _open(self, state: dict[str, Any], symbol: str, side: int, raw_px: float, qty: float, now: int,
              info: dict[str, Any], stop: float | None = None, targets: list[float] | None = None,
              exit_at: int | None = None, fill_raw: bool = False, lev: float = 1.0,
              cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
        fut = (cfg or {}).get("market") == "futures"
        fee_rate = F.FUTURES_FEE_RATE if fut else self.fee
        lev = max(1.0, float(lev)) if fut else 1.0
        fill = raw_px if fill_raw else raw_px * (1 + side * self.adverse)
        fee = qty * fill * fee_rate
        cost = qty * fill / lev + fee
        if qty <= 0 or cost > state["cash"] + 1e-9:
            return None
        state["cash"] -= cost
        state["fees_paid"] = state.get("fees_paid", 0.0) + fee
        pos = {"id": new_id()[:12], "symbol": symbol, "side": side, "entry": fill, "qty": qty, "qty_open": qty,
               "stop": stop, "stop0": stop, "targets": targets or [], "tp_hit": 0, "opened_at": now,
               "last_check": _first_full_candle(now), "exit_at": exit_at, "realized": -fee, "fees": fee,
               "exit_value": 0.0, "info": info, "lev": lev, "coll": fill / lev, "fee_rate": fee_rate,
               "market": "futures" if fut else "spot", "funding": 0.0, "funded_until": now,
               "liq": F.liquidation_price(fill, side, lev) if fut else None, "margin": qty * fill / lev}
        state["positions"].append(pos)
        return pos

    def _reduce(self, state: dict[str, Any], pos: dict[str, Any], qty: float, raw_px: float, at_stop_or_target: bool) -> None:
        # stop and target fills already include the adverse move of hitting a level; only slippage is added
        px = raw_px * (1 - pos["side"] * (settings.slippage_bps / 1e4 if at_stop_or_target else self.adverse))
        fee = qty * px * pos.get("fee_rate", self.fee)
        pnl = pos["side"] * qty * (px - pos["entry"]) - fee
        state["cash"] += qty * _coll(pos) + pos["side"] * qty * (px - pos["entry"]) - fee
        state["fees_paid"] = state.get("fees_paid", 0.0) + fee
        pos["qty_open"] -= qty
        pos["realized"] += pnl
        pos["fees"] += fee
        pos["exit_value"] += qty * px

    def _liquidate(self, state: dict[str, Any], pos: dict[str, Any]) -> None:
        """Isolated margin: the margin still in the position is lost; nothing comes back to the cash balance."""
        lost = pos["qty_open"] * _coll(pos)
        pos["realized"] -= lost
        pos["exit_value"] += pos["qty_open"] * pos["liq"]
        pos["qty_open"] = 0.0
        state["liquidations"] = state.get("liquidations", 0) + 1

    def _liq_hit(self, pos: dict[str, Any], op: float, hi: float, lo: float) -> bool:
        liq = pos.get("liq")
        if liq is None:
            return False
        side = pos["side"]
        if not ((lo <= liq) if side > 0 else (hi >= liq)):
            return False
        stop = pos.get("stop")
        # a stop between the price and the liquidation level fills first, unless the candle opened beyond it
        protected = stop is not None and side * (stop - liq) > 0 and side * (op - liq) > 0 and side * (op - stop) > 0
        return not protected

    def _funding(self, state: dict[str, Any], now: int) -> None:
        """Futures funding every 8 hours on the open notional (longs pay a positive rate, shorts receive it)."""
        for pos in state["positions"]:
            if pos.get("market") != "futures":
                continue
            times = F.funding_times(pos.get("funded_until", pos["opened_at"]), now)
            if not times:
                continue
            rate = (self.funding.get(pos["symbol"]) or {}).get("rate")
            rate = F.DEFAULT_FUNDING_RATE if rate is None else rate
            px = self._price(pos["symbol"]) or pos["entry"]
            amount = len(times) * pos["side"] * pos["qty_open"] * px * rate
            state["cash"] -= amount
            pos["funding"] = pos.get("funding", 0.0) + amount
            pos["realized"] -= amount
            state["funding_paid"] = state.get("funding_paid", 0.0) + amount
            pos["funded_until"] = times[-1]

    def _close_trade(self, bot_id: str, state: dict[str, Any], pos: dict[str, Any], now: int, reason: str,
                     correct: bool | None = None) -> dict[str, Any]:
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
        avg_exit = pos["exit_value"] / pos["qty"] if pos["qty"] else pos["entry"]
        risk = abs(pos["entry"] - pos["stop0"]) * pos["qty"] if pos.get("stop0") else None
        notional = pos["qty"] * pos["entry"]
        if correct is None:
            correct = pos["side"] * (avg_exit - pos["entry"]) > 0
        trade = {"id": pos["id"], "bot_id": bot_id, "symbol": pos["symbol"], "side": pos["side"],
                 "opened_at": pos["opened_at"], "closed_at": now, "entry": pos["entry"], "exit": avg_exit,
                 "qty": pos["qty"], "pnl": pos["realized"], "fees": pos["fees"],
                 "return_pct": pos["realized"] / notional * 100 if notional else 0.0,
                 "r_multiple": pos["realized"] / risk if risk else None, "exit_reason": reason,
                 "correct": int(bool(correct)),
                 "info": dumps({**pos["info"], "tp_hit": pos["tp_hit"], "market": pos.get("market", "spot"),
                                "leverage": pos.get("lev", 1.0), "margin": pos.get("margin"),
                                "funding": pos.get("funding", 0.0), "liquidation_price": pos.get("liq"),
                                "roe_pct": pos["realized"] / pos["margin"] * 100 if pos.get("margin") else None})}
        self.db.execute("INSERT INTO bot_trades (id, bot_id, symbol, side, opened_at, closed_at, entry, exit, qty, pnl, fees, "
                        "return_pct, r_multiple, exit_reason, correct, info) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (id) DO NOTHING", list(trade.values()))
        return trade

    # ---- decision bots ----------------------------------------------------------------------------------
    def _manage_decision(self, cfg: dict[str, Any], state: dict[str, Any], now: int) -> list[dict[str, Any]]:
        events = []
        tf = tf_ms(cfg["timeframe"])
        step = tf_ms(PATH_TF)
        # pending limit orders (BUY ON PULLBACK): fill when a candle trades through the limit
        for o in list(state["pending"]):
            filled = False
            for ts, op, hi, lo, cl in self._path(o["symbol"], o["last_check"]):
                o["last_check"] = ts
                if ts + step > o["expires_at"]:
                    break
                touched = lo <= o["limit"] if o["side"] > 0 else hi >= o["limit"]
                if touched:
                    px = min(op, o["limit"]) if o["side"] > 0 else max(op, o["limit"])
                    state["cash"] += o["reserved"]
                    state["pending"].remove(o)
                    pos = self._open(state, o["symbol"], o["side"], px, o["qty"], ts, o["info"], o["stop"], o["targets"],
                                     fill_raw=True, lev=o.get("lev", 1.0), cfg=cfg)
                    if pos:
                        pos["last_check"] = ts - step         # re-check this same candle for the stop
                        events.append({"bot": cfg["id"], "type": "fill", "symbol": o["symbol"], "price": px})
                    filled = True
                    break
            if not filled and o in state["pending"] and (now >= o["expires_at"]):
                state["cash"] += o["reserved"]
                state["pending"].remove(o)
                events.append({"bot": cfg["id"], "type": "expired", "symbol": o["symbol"]})
        # open positions: walk every closed 15m candle since the last check
        for pos in list(state["positions"]):
            side = pos["side"]
            done = None
            for ts, op, hi, lo, cl in self._path(pos["symbol"], pos["last_check"]):
                pos["last_check"] = ts
                if self._liq_hit(pos, op, hi, lo):
                    self._liquidate(state, pos)
                    done = ("liquidated", ts + step)
                    break
                stop_hit = (lo <= pos["stop"]) if side > 0 else (hi >= pos["stop"])
                if stop_hit:
                    px = min(op, pos["stop"]) if side > 0 else max(op, pos["stop"])
                    self._reduce(state, pos, pos["qty_open"], px, True)
                    done = ("trailing stop" if pos["tp_hit"] >= 2 else "breakeven stop" if pos["tp_hit"] else "stop", ts + step)
                    break
                while pos["tp_hit"] < len(pos["targets"]):
                    tp = pos["targets"][pos["tp_hit"]]
                    if not ((hi >= tp) if side > 0 else (lo <= tp)):
                        break
                    px = max(op, tp) if side > 0 else min(op, tp)
                    leg = pos["qty_open"] if pos["tp_hit"] == len(pos["targets"]) - 1 else pos["qty"] / len(pos["targets"])
                    self._reduce(state, pos, min(leg, pos["qty_open"]), px, True)
                    pos["tp_hit"] += 1
                    if pos["tp_hit"] == 1:
                        pos["stop"] = pos["entry"]            # protect the rest at break-even
                    elif pos["tp_hit"] == 2 and pos["targets"]:
                        pos["stop"] = pos["targets"][0]       # trail: after TP2 the last third is locked in at TP1
                if pos["qty_open"] <= pos["qty"] * 1e-9:
                    done = (f"TP{pos['tp_hit']}", ts + step)
                    break
                if ts + step >= pos["opened_at"] + cfg.get("max_hold_bars", 42) * tf:
                    self._reduce(state, pos, pos["qty_open"], cl, False)
                    done = ("time exit", ts + step)
                    break
            if done:
                t = self._close_trade(cfg["id"], state, pos, done[1], done[0])
                events.append({"bot": cfg["id"], "type": "close", "symbol": pos["symbol"], "reason": done[0], "pnl": t["pnl"]})
        events += self._reversals(cfg, state, now)
        return events

    def _signal_side(self, cfg: dict[str, Any], symbol: str) -> int:
        """+1 / -1 when the bot's timeframe currently has a tradable call it would take, else 0."""
        a = analysis.analyze(self.rt, symbol, cfg["timeframe"], detail=False)
        if a.get("status") != "OK" or a.get("decision") not in analysis.TRADE_DECISIONS:
            return 0
        if a.get("grade") and a["grade"] not in str(cfg.get("grades") or "A"):
            return 0
        if not (a.get("setup") or {}).get("valid"):
            return 0
        return 1 if a["decision"] in ("BUY", "BUY ON PULLBACK") else -1

    def _reversals(self, cfg: dict[str, Any], state: dict[str, Any], now: int) -> list[dict[str, Any]]:
        """The call flipped (long -> short or back): close the open trade at market, profit or loss, and drop any
        pending entry the other way. The new direction is then entered like any fresh signal (no hedging: one
        position per coin)."""
        events = []
        for pos in list(state["positions"]):
            side = self._signal_side(cfg, pos["symbol"])
            if side == 0 or side == pos["side"]:
                continue
            px = self._price(pos["symbol"])
            if not px:
                continue
            in_profit = pos["side"] * (px - pos["entry"]) > 0
            self._reduce(state, pos, pos["qty_open"], px, False)
            reason = "signal reversed (profit taken)" if in_profit else "signal reversed (loss cut)"
            t = self._close_trade(cfg["id"], state, pos, now, reason)
            events.append({"bot": cfg["id"], "type": "close", "symbol": pos["symbol"], "reason": reason, "pnl": t["pnl"]})
        for o in list(state["pending"]):
            side = self._signal_side(cfg, o["symbol"])
            if side and side != o["side"]:
                state["cash"] += o["reserved"]
                state["pending"].remove(o)
                events.append({"bot": cfg["id"], "type": "expired", "symbol": o["symbol"], "reason": "signal reversed"})
        return events

    def _enter_decision(self, cfg: dict[str, Any], state: dict[str, Any], syms: list[str], now: int) -> list[dict[str, Any]]:
        events = []
        busy = {p["symbol"] for p in state["positions"]} | {o["symbol"] for o in state["pending"]}
        max_same = int(cfg.get("max_same_side") or 3)
        for s in syms:
            if s in busy or len(state["positions"]) + len(state["pending"]) >= cfg["max_open_positions"]:
                continue
            a = analysis.analyze(self.rt, s, cfg["timeframe"], detail=False)
            if a.get("status") != "OK" or a.get("decision") not in analysis.TRADE_DECISIONS:
                continue
            if a.get("grade") and a["grade"] not in str(cfg.get("grades") or "A"):
                continue
            setup = a.get("setup") or {}
            if not setup.get("valid") or state["last_entry_bar"].get(s) == a["bar_ts"]:
                continue
            side = int(setup["side_int"])
            if side < 0 and not cfg.get("allow_short", True):
                continue
            # many coins signalling the same way at once is really one bet on the market: cap it
            same = sum(1 for p in state["positions"] if p["side"] == side) + sum(1 for o in state["pending"] if o["side"] == side)
            if same >= max_same:
                continue
            px = self._price(s)
            if px is None:
                continue
            stop, targets = float(setup["stop"]), [float(t["price"]) for t in setup["targets"]]
            # the plan must still make sense at the price the bot can actually get
            if side * (px - stop) <= 0 or side * (targets[0] - px) <= 0:
                continue
            fc = a.get("forecast") or {}
            info = {"signal": a["signal"]["signal"], "decision": a["decision"], "confidence": a.get("confidence"),
                    "p_up": (fc.get("probabilities") or {}).get("up"), "p_down": (fc.get("probabilities") or {}).get("down"),
                    "predicted": fc.get("predicted"), "model_version": fc.get("model_version"),
                    "edge_confirmed": fc.get("edge_confirmed"), "rr": setup.get("risk_reward"),
                    "bar_ts": a["bar_ts"], "timeframe": cfg["timeframe"]}
            eq = self.equity(state)
            entry = float(setup["ideal_entry"]) if a["decision"] == "BUY ON PULLBACK" else px
            risk_per_unit = abs(entry - stop)
            fut = cfg.get("market") == "futures"
            lev = 1.0
            if fut:
                lev = cfg.get("leverage", 1.0)
                if cfg.get("safe_leverage", True):
                    lev = float(min(lev, F.safe_leverage(entry, stop, lev)))
            fee_rate = F.FUTURES_FEE_RATE if fut else self.fee
            # risk-based size (the stop decides the loss, not the leverage); the margin per position is capped
            mult = size_multiplier(a.get("grade"), a.get("filter_score"), a.get("filter_threshold")) if cfg.get("edge_sizing", True) else 1.0
            info["size_mult"] = mult
            qty = eq * cfg["risk_per_trade_pct"] * mult / 100 / risk_per_unit
            qty = min(qty, eq * cfg["max_position_pct"] / 100 * lev / entry,
                      state["cash"] * 0.995 / (entry * (1 / lev + fee_rate)))
            info["leverage"] = lev
            if qty <= 0:
                continue
            state["last_entry_bar"][s] = a["bar_ts"]
            if a["decision"] == "BUY ON PULLBACK" and side * (px - entry) > 0:
                reserved = qty * entry * (1 / lev + fee_rate)
                state["cash"] -= reserved
                state["pending"].append({"symbol": s, "side": side, "limit": entry, "qty": qty, "reserved": reserved, "lev": lev,
                                         "stop": stop, "targets": targets, "placed_at": now, "info": info,
                                         "last_check": _first_full_candle(now),
                                         "expires_at": now + cfg.get("pending_bars", 6) * tf_ms(cfg["timeframe"])})
                events.append({"bot": cfg["id"], "type": "limit", "symbol": s, "price": entry})
            else:
                if self._open(state, s, side, px, qty, now, info, stop, targets, lev=lev, cfg=cfg):
                    events.append({"bot": cfg["id"], "type": "open", "symbol": s, "side": side, "price": px})
        return events

    # ---- prediction trackers ----------------------------------------------------------------------------
    def _run_prediction(self, cfg: dict[str, Any], state: dict[str, Any], syms: list[str], now: int) -> list[dict[str, Any]]:
        events = []
        tf = cfg["timeframe"]
        step = tf_ms(PATH_TF)
        # 0) futures: liquidation can happen before the bar ends
        for pos in list(state["positions"]):
            if pos.get("liq") is None:
                continue
            for ts, op, hi, lo, cl in self._path(pos["symbol"], pos["last_check"]):
                if ts + step > pos["exit_at"]:
                    break
                pos["last_check"] = ts
                if self._liq_hit(pos, op, hi, lo):
                    self._liquidate(state, pos)
                    t = self._close_trade(cfg["id"], state, pos, ts + step, "liquidated", correct=False)
                    events.append({"bot": cfg["id"], "type": "liquidated", "symbol": pos["symbol"], "pnl": t["pnl"]})
                    break
        # 1) close every position whose bar has finished, at the close of the candle ending at exit_at
        for pos in list(state["positions"]):
            if now < pos["exit_at"]:
                continue
            path = [c for c in self._path(pos["symbol"], pos["opened_at"] - step) if c[0] + step <= pos["exit_at"]]
            px = path[-1][4] if path and path[-1][0] + step == pos["exit_at"] else self._price(pos["symbol"])
            if px is None:
                continue
            self._reduce(state, pos, pos["qty_open"], px, False)
            t = self._close_trade(cfg["id"], state, pos, max(now, pos["exit_at"]), "bar closed",
                                  correct=pos["side"] * (px - pos["info"]["entry_ref"]) > 0)
            events.append({"bot": cfg["id"], "type": "close", "symbol": pos["symbol"], "pnl": t["pnl"]})
        # 2) act on new predictions (one per symbol per bar)
        busy = {p["symbol"] for p in state["positions"]}
        for s in syms:
            if s in busy:
                continue
            fc = analysis.model_forecast(self.rt, s, tf)
            if not fc.get("available") or state["last_bar"].get(s) == fc["bar_ts"]:
                continue
            bar_close = fc["bar_ts"] + tf_ms(tf)
            if now - bar_close > tf_ms(tf) * 0.75:
                state["last_bar"][s] = fc["bar_ts"]          # too late to act on this bar honestly
                continue
            state["last_bar"][s] = fc["bar_ts"]
            cls = fc["predicted_class"]
            side = 1 if cls == 2 else -1 if cls == 0 else 0
            if side == 0 or fc["p_max"] < cfg["min_probability"] or (side < 0 and not cfg.get("allow_short", True)):
                continue
            if cfg.get("confident_only") and not (fc.get("confident_call") or {}).get("is_confident"):
                continue    # only calls above the model's out-of-sample confident-call threshold
            px = self._price(s)
            if px is None:
                continue
            eq = self.equity(state)
            fut = cfg.get("market") == "futures"
            lev = float(cfg.get("leverage", 1.0)) if fut else 1.0
            fee_rate = F.FUTURES_FEE_RATE if fut else self.fee
            margin = min(eq * cfg["position_pct"] / 100, state["cash"] * 0.995 / (1 + fee_rate * lev))
            qty = margin * lev / px
            info = {"predicted": fc["predicted"], "p_max": fc["p_max"], "p_up": fc["probabilities"]["up"],
                    "p_down": fc["probabilities"]["down"], "confidence": (fc.get("confidence") or {}).get("confidence"),
                    "model_version": fc["model_version"], "edge_confirmed": fc["edge_confirmed"],
                    "bar_ts": fc["bar_ts"], "entry_ref": px, "entry_delay_min": round((now - bar_close) / 60000, 1),
                    "expected_return": fc.get("expected_return"), "timeframe": tf}
            info["leverage"] = lev
            if self._open(state, s, side, px, qty, now, info, exit_at=bar_close + tf_ms(tf), lev=lev, cfg=cfg):
                events.append({"bot": cfg["id"], "type": "open", "symbol": s, "side": side, "price": px})
        return events

    # ---- reporting --------------------------------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        out = []
        for cfg, state in self.bots():
            trades = self.db.query("SELECT * FROM bot_trades WHERE bot_id = ? ORDER BY closed_at DESC", (cfg["id"],))
            for t in trades:
                t["info"] = loads(t["info"], {})
            eq = self.db.query("SELECT ts, equity, benchmark FROM bot_equity WHERE bot_id = ? ORDER BY ts", (cfg["id"],))
            step = max(1, len(eq) // 600)
            curve = eq[::step] + ([eq[-1]] if eq and (len(eq) - 1) % step else [])
            out.append({"config": cfg, "state": {k: state.get(k) for k in ("cash", "equity", "benchmark", "started_at",
                                                                          "updated_at", "fees_paid", "funding_paid",
                                                                          "liquidations")},
                        "positions": state["positions"], "pending": state["pending"],
                        "stats": trade_stats(trades, cfg, state, eq), "trades": trades[:300], "equity_curve": curve})
        return {"bots": out, "defaults": DEFAULT_BOTS, "path_timeframe": PATH_TF,
                "costs": {"fee_rate": self.fee, "futures_fee_rate": F.FUTURES_FEE_RATE, "slippage_bps": settings.slippage_bps,
                          "spread_bps": settings.spread_bps, "maintenance_margin": F.MAINTENANCE_MARGIN,
                          "default_funding_rate": F.DEFAULT_FUNDING_RATE},
                "funding": self.funding,
                "generated_at": now_ms()}


def _first_full_candle(now: int) -> int:
    """`last_check` value so the path starts with the first 15m candle that opened at or after `now`
    (a candle already in progress at entry time is skipped: part of it happened before the entry)."""
    step = tf_ms(PATH_TF)
    return now - step if now % step == 0 else now - now % step


def _bucket_stats(trades: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    rows = []
    for lo, hi in zip(CONF_BUCKETS[:-1], CONF_BUCKETS[1:]):
        sel = [t for t in trades if t["info"].get(key) is not None and lo <= t["info"][key] < hi]
        if sel:
            rows.append({"lo": lo, "hi": min(hi, 1.0), "n": len(sel),
                         "mean": float(np.mean([t["info"][key] for t in sel])),
                         "hit_rate": float(np.mean([t["correct"] for t in sel])),
                         "win_rate": float(np.mean([t["pnl"] > 0 for t in sel])),
                         "avg_return_pct": float(np.mean([t["return_pct"] for t in sel]))})
    return rows


def trade_stats(trades: list[dict[str, Any]], cfg: dict[str, Any], state: dict[str, Any],
                equity: list[dict[str, Any]]) -> dict[str, Any]:
    start = cfg["starting_balance"]
    eq_now = state.get("equity", start)
    bench = state.get("benchmark")
    curve = np.array([e["equity"] for e in equity]) if equity else np.array([start])
    peak = np.maximum.accumulate(curve)
    n = len(trades)
    base = {"trades": n, "return_pct": (eq_now / start - 1) * 100, "equity": eq_now,
            "benchmark_return_pct": (bench / start - 1) * 100 if bench else None,
            "max_drawdown_pct": float((curve / peak - 1).min() * 100), "open_positions": len(state["positions"]),
            "fees_paid": state.get("fees_paid", 0.0), "funding_paid": state.get("funding_paid", 0.0),
            "liquidations": state.get("liquidations", 0)}
    if not n:
        return {**base, "note": "No closed trades yet. Statistics appear after the first trade closes."}
    pnl = np.array([t["pnl"] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    rs = [t["r_multiple"] for t in trades if t["r_multiple"] is not None]
    k = int(sum(t["correct"] for t in trades))
    from ..ml.metrics import wilson

    lo, hi = wilson(k, n)
    key = "p_max" if cfg["mode"] == "prediction" else "confidence"
    by_symbol = {}
    for t in trades:
        d = by_symbol.setdefault(t["symbol"], {"n": 0, "pnl": 0.0, "correct": 0})
        d["n"] += 1
        d["pnl"] += t["pnl"]
        d["correct"] += t["correct"]
    return {
        **base, "win_rate": float(len(wins) / n), "direction_accuracy": k / n, "direction_ci95": [lo, hi],
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        "avg_return_pct": float(np.mean([t["return_pct"] for t in trades])),
        "avg_r": float(np.mean(rs)) if rs else None, "total_pnl": float(pnl.sum()),
        "best_pct": float(max(t["return_pct"] for t in trades)), "worst_pct": float(min(t["return_pct"] for t in trades)),
        "longs": sum(t["side"] > 0 for t in trades), "shorts": sum(t["side"] < 0 for t in trades),
        "long_accuracy": _mean([t["correct"] for t in trades if t["side"] > 0]),
        "short_accuracy": _mean([t["correct"] for t in trades if t["side"] < 0]),
        "by_confidence": _bucket_stats(trades, key), "confidence_key": key,
        "by_exit": {r: sum(t["exit_reason"] == r for t in trades) for r in sorted({t["exit_reason"] for t in trades})},
        "by_symbol": [{"symbol": s, **d, "accuracy": d["correct"] / d["n"]} for s, d in sorted(by_symbol.items())],
        "avg_hold_h": float(np.mean([(t["closed_at"] - t["opened_at"]) / 3.6e6 for t in trades])),
        "avg_leverage": _mean([t["info"].get("leverage") or 1.0 for t in trades]),
        "avg_roe_pct": _mean([t["info"]["roe_pct"] for t in trades if t["info"].get("roe_pct") is not None]),
        "long_pnl": float(sum(t["pnl"] for t in trades if t["side"] > 0)),
        "short_pnl": float(sum(t["pnl"] for t in trades if t["side"] < 0)),
    }


def _mean(v: list[float]) -> float | None:
    return float(np.mean(v)) if v else None


def _coll(pos: dict[str, Any]) -> float:
    """Cash set aside per unit: the entry price for spot (1x), entry / leverage for futures."""
    return pos.get("coll", pos["entry"])
