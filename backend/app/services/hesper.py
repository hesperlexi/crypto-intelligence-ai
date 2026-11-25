"""ROAD TO RICH - Hesper, the admin's all-in demo bot (owner decisions, 2 Nov 2026). Virtual money only: nothing here
ever talks to an exchange's trading API.

* A **run** starts with $100. Hesper takes only **public grade-A calls** from the record (`signals`, any public
  timeframe), one trade at a time: when flat, the best fresh call (published in the last `FRESH_MS`; highest
  confidence, tie -> newer) is entered like the futures bots enter (market, or a limit for BUY ON PULLBACK).
* **All-in**: margin = the whole balance (`ALL_IN` keeps a sliver for fees), isolated margin, leverage up to 25x but
  lowered per trade so the liquidation price sits 1.5x the stop distance beyond the entry (`futures.safe_leverage`,
  the futures bots' rule). v2.14: 15m calls use the engine's 10-50x (`futures.engine_leverage`; too wide -> skipped). Futures fees, slippage and 8-hourly funding exactly as the futures bots.
* Exits are the bots' own (`BotEngine._manage_decision`, shared rules in engine/manage.py): 50 / 25 / 25 at TP1-3,
  break-even after TP1, TP1 after TP2, runner when the call has one, the call's own time limit, admin stop / TP1
  changes and "Close now" on the call, reversal on a grade-A opposite call (never on 15m), followed on 15m candles.
* v2.22 (owner, 14 Nov 2026): a run is OPEN-ENDED. It ends by itself only as a FAIL - a liquidation ("liquidated") or a
  balance below `MIN_BALANCE` ("busted") - or when the admin presses "End run & start new" (job `hesper_new_run`,
  `stop_run`): any open position closes at the engine's price, a pending order is cancelled, the run is STOPPED
  ("stopped") with its final balance, and the next run starts at once at $100. `GOAL` ($1,000) is only a milestone:
  the first time the balance reaches it, `goal_reached_at` is stored on the run and it keeps trading. Runs that ended
  SUCCESS / "goal" before v2.22 keep that result. Every run and trade is kept (`hesper_runs`, `hesper_trades`); a
  finished run is never changed.

Isolation: Hesper has its own tables and its own state (setting `hesper_state`); it is not a row of `bots`, so the
bots report, the Results "Demo bots" list, the track record, auto-trade, Telegram, achievements, the weekly report,
training and wins_today never see it. It only reads `signals`. Admin-only view `views/hesper`.
"""
from __future__ import annotations

import math
import os
from typing import Any

from ..data.base import tf_ms
from ..db import dumps, loads, new_id, now_ms
from ..engine import futures as F
from ..pricefmt import fmt_price
from . import analysis
from . import tracking
from .bots import BotEngine
from .runtime import Runtime

BOT_ID = "hesper"
NAME = "Hesper"
START_BALANCE = 100.0
GOAL = 1000.0
MIN_BALANCE = 1.0            # below this a run is "busted" (cannot open a meaningful trade)
MAX_LEVERAGE = 25                        # v2.13 ceiling (all timeframes except 15m)
MIN_LEVERAGE = F.MIN_LEVERAGE            # v2.14, 15m only: 10-50x chosen by the engine
ALL_IN = 0.995               # share of the balance used for margin + entry fee (the bots' own cash buffer)
FRESH_MS = 30 * 60_000       # a call counts as "fresh" for this long after publication
PENDING_BARS = 6             # a pullback limit waits this many candles of its timeframe (as the bots)
GRADES = ("A",)
STATE_KEY = "hesper_state"
FLAG = "hesper_v1"
SINCE = "hesper_since"
VIEW_TRADES = 100
VIEW_RUNS = 500
VIEW_CURVES = 20
CURVE_POINTS = 300


MIN_START, MAX_START = 10.0, 1_000_000.0      # v2.23: the admin chooses each run's starting amount (USDT)


def goal_of(start: float) -> float:
    """v2.23: the milestone is 10x the run's start ($100 -> $1,000)."""
    return float(start) * 10


def _fresh_state(run: int, now: int, start: float = START_BALANCE) -> dict[str, Any]:
    start = float(start)
    return {"run": run, "started_at": now, "cash": start, "start_balance": start, "goal": goal_of(start),
            "positions": [], "pending": [], "start_prices": {},
            "last_bar": {}, "last_entry_bar": {}, "fees_paid": 0.0, "funding_paid": 0.0, "liquidations": 0,
            "notes": [], "peak": start, "trades": 0, "wins": 0, "trade_cfg": None, "end": None,
            "taken": []}


def _start_of(state: dict[str, Any] | None) -> float:
    return float((state or {}).get("start_balance") or START_BALANCE)


def _trade_cfg(tf: str, horizon: int, lev: float, bot_id: str = BOT_ID, name: str = NAME) -> dict[str, Any]:
    """The bot config `_manage_decision` follows the current trade with (one trade at a time)."""
    return {"id": bot_id, "name": name, "mode": "decision", "timeframe": tf, "symbols": "all", "market": "futures",
            "safe_leverage": True, "leverage": float(lev), "max_hold_bars": int(horizon), "grades": "".join(GRADES),
            "pending_bars": PENDING_BARS, "allow_short": True, "starting_balance": START_BALANCE}


class Hesper(BotEngine):
    # v2.63: one class per challenge (Hesper Challenge, Last Stand); each has its own state, flag and tables
    BOT_ID, NAME, TITLE = BOT_ID, NAME, "Hesper Challenge"
    STATE_KEY, FLAG, SINCE = STATE_KEY, FLAG, SINCE
    RUNS, TRADES = "hesper_runs", "hesper_trades"
    AUTO_START = True            # run 1 starts by itself (one time)
    AUTO_RESTART = True          # after a liquidation / bust the next run starts at once with the same amount
    MIN_START, MAX_START = 10.0, 1_000_000.0
    # v3.2 (owner, 25 Nov 2026: "the challenge is missing important grade-A entries ... I want quick money"): up to SLOTS
    # trades at once; each is sized so its stop costs RISK_PCT of the balance (equity) - margin capped by the free cash
    # and the leverage cap; after PAUSE_AFTER losses in a row no new trade for PAUSE_MS (open trades keep running)
    SLOTS = int(os.environ.get("CHALLENGE_SLOTS", "5"))
    RISK_PCT = float(os.environ.get("HESPER_RISK_PCT", "10"))
    PAUSE_AFTER = 2
    PAUSE_MS = 4 * 3_600_000

    def __init__(self, rt: Runtime):
        super().__init__(rt)

    # ---- state -------------------------------------------------------------------------------------------
    def load(self) -> dict[str, Any] | None:
        st = self.db.get_setting(self.STATE_KEY, None)
        return st if isinstance(st, dict) else None

    def save(self, state: dict[str, Any]) -> None:
        self.db.set_setting(self.STATE_KEY, state)

    def start(self, now: int) -> dict[str, Any] | None:
        """One-time start (flag `hesper_v1`): run 1 at $100 from now. Never restarted afterwards. Last Stand
        (AUTO_START False) waits for the admin's first "Start run" instead (None until then)."""
        state = self.load()
        if state is not None or not self.AUTO_START:
            return state
        if not self.db.get_setting(self.SINCE, None):
            self.db.set_setting(self.SINCE, now)
        last = self.db.one(f"SELECT MAX(run) AS n FROM {self.RUNS}")
        run = int((last or {}).get("n") or 0) + 1
        state = _fresh_state(run, now)
        self._insert_run(state)
        self.db.set_setting(self.FLAG, True)
        self.save(state)
        return state

    def _insert_run(self, state: dict[str, Any]) -> None:
        st = _start_of(state)
        self.db.execute(f"INSERT INTO {self.RUNS} (run, started_at, result, start_balance, peak, trades, wins) "
                        "VALUES (?, ?, 'RUNNING', ?, ?, 0, 0) ON CONFLICT (run) DO NOTHING",
                        (state["run"], state["started_at"], st, st))

    def bots(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return []               # never part of the bots machinery's own list (report, adjustments of `bots` rows)

    # ---- one cycle -----------------------------------------------------------------------------------------
    def run(self, now: int | None = None) -> list[dict[str, Any]]:
        now = now_ms() if now is None else now
        state = self.start(now)
        if not state or state.get("idle"):                  # v2.23: stopped by the admin, waiting for "Start new run"
            return []
        events: list[dict[str, Any]] = []
        self._funding(state, now)
        if state["positions"] or state["pending"]:
            before = {q["id"]: int(q.get("tp_hit") or 0) for q in state["positions"]}
            evs = self._manage_all(state, now)
            for e in evs:                      # v2.30: the run and the cash after a close, for the notification
                e.setdefault("run", state["run"])
                if e.get("type") in ("close", "liquidated"):
                    e.setdefault("balance", float(state["cash"]))
            events += evs
            # v2.30: a target reached on a trade that is still open (a close reports its own targets)
            for q in state["positions"]:
                for n in range(before.get(q["id"], 0) + 1, int(q.get("tp_hit") or 0) + 1):
                    if q["id"] in before:
                        events.append({"bot": self.BOT_ID, "type": "tp", "symbol": q["symbol"], "tp": n,
                                       "side": q.get("side"), "run": state["run"]})
        if not state["positions"] and not state["pending"]:
            state["trade_cfg"] = None
            ended = self._check_end(state, now)
            if ended:
                events.append(ended)
                state = self.load() or state
                if state.get("idle"):          # v2.63 Last Stand: waits for the admin's next "Start run"
                    return events
        if not state.get("idle"):
            events += self._enter(state, now)
        for e in events:
            e.setdefault("run", state["run"])
        state["equity"] = self.equity(state)
        hit = self._milestone(state, now)
        if hit:
            events.append(hit)
        state["updated_at"] = now
        self.save(state)
        return events

    def _milestone(self, state: dict[str, Any], now: int) -> dict[str, Any] | None:
        """v2.22: the first time the run's balance (equity at the engine's price) reaches GOAL, note it once."""
        goal = float(state.get("goal") or goal_of(_start_of(state)))
        if state.get("goal_reached_at") or float(state.get("equity", state["cash"])) < goal - 1e-9:
            return None
        state["goal_reached_at"] = int(now)
        self.db.execute(f"UPDATE {self.RUNS} SET goal_reached_at = ? WHERE run = ? AND result = 'RUNNING' "
                        "AND goal_reached_at IS NULL", (int(now), state["run"]))
        return {"bot": self.BOT_ID, "type": "goal_reached", "run": state["run"], "balance": float(state["equity"])}

    def _finish(self, state: dict[str, Any], now: int, result: str, reason: str, at: int, start_next: bool = True) -> None:
        """Close the run's row (result / reason / balance). An automatic end (liquidated / busted) starts the next run
        at once with the same starting amount; an admin stop (v2.23) leaves the challenge idle until "Start new run"."""
        cash = float(state["cash"])
        self.db.execute(f"UPDATE {self.RUNS} SET ended_at = ?, result = ?, reason = ?, end_balance = ?, peak = ?, "
                        "trades = ?, wins = ? WHERE run = ? AND result = 'RUNNING'",
                        (at, result, reason, cash, max(float(state["peak"]), cash), state["trades"], state["wins"],
                         state["run"]))
        taken = list(state.get("taken") or [])[-50:]       # a call is never taken twice, even across runs
        if not start_next:
            self.save({"idle": True, "run": int(state["run"]), "stopped_at": int(at), "taken": taken,
                       "start_balance": _start_of(state), "last_end_balance": cash})
            return
        nxt = _fresh_state(int(state["run"]) + 1, now, _start_of(state))
        nxt["taken"] = taken
        self._insert_run(nxt)
        self.save(nxt)

    def start_new(self, amount: float, now: int | None = None, by: str = "") -> dict[str, Any]:
        """v2.23 admin "Start new run" after a stop, with the starting amount the admin chose."""
        now = now_ms() if now is None else now
        amount = float(amount)
        if not (self.MIN_START <= amount <= self.MAX_START):
            raise ValueError(f"the starting amount must be between {self.MIN_START:,.0f} and {self.MAX_START:,.0f} USDT")
        state = self.load()
        if state is not None and not state.get("idle"):
            raise ValueError(f"run #{state['run']} is still running; stop it first")
        last = self.db.one(f"SELECT MAX(run) AS n FROM {self.RUNS}")
        run = int((last or {}).get("n") or 0) + 1
        nxt = _fresh_state(run, now, amount)
        nxt["taken"] = list((state or {}).get("taken") or [])
        if not self.db.get_setting(self.SINCE, None):
            self.db.set_setting(self.SINCE, now)
        self.db.set_setting(self.FLAG, True)
        self._insert_run(nxt)
        self.save(nxt)
        return {"run": run, "start_balance": amount, "goal": goal_of(amount), "by": by}

    def stop_run(self, now: int | None = None, by: str = "", start_next: bool = False) -> dict[str, Any]:
        """Admin "Stop run": close any open position at the engine's price, cancel a pending order and end the run as
        STOPPED ("stopped") with its final balance. v2.23: the challenge then waits for "Start new run" (the admin
        chooses the amount); `start_next=True` keeps the v2.22 behaviour (next run at the same amount at once)."""
        now = now_ms() if now is None else now
        state = self.load()
        if state is None:
            raise ValueError(f"the {self.TITLE} has not started yet")
        if state.get("idle"):
            raise ValueError(f"run #{state['run']} has already ended")
        closed = []
        for pos in list(state.get("positions") or []):
            px = self._price(pos["symbol"]) or pos["entry"]
            if pos["qty_open"] > 0:
                self._reduce(state, pos, pos["qty_open"], float(px), False)
            closed.append(self._close_trade(self.BOT_ID, state, pos, now, "stopped by admin"))
        for o in list(state.get("pending") or []):
            state["cash"] = state.get("cash", 0.0) + o.get("reserved", 0.0)
        state["pending"] = []
        state["trade_cfg"] = None
        run, cash = int(state["run"]), float(state["cash"])
        start = _start_of(state)
        self._finish(state, now, "STOPPED", "stopped", int(now), start_next=start_next)
        return {"stopped_run": run, "final_balance": round(cash, 2), "multiple": round(cash / start, 3),
                "closed_trades": len(closed), "next_run": run + 1 if start_next else None, "by": by}

    def _check_end(self, state: dict[str, Any], now: int) -> dict[str, Any] | None:
        """Flat: has the run ended by itself? Liquidation or a balance below MIN_BALANCE -> FAIL. (v2.22: reaching
        GOAL no longer ends a run - see `_milestone`; the admin ends a run with `stop_run`.)"""
        cash = float(state["cash"])
        if state.get("end") == "liquidated":               # older runs (one trade at a time)
            result, reason = "FAIL", "liquidated"
        elif cash < MIN_BALANCE:
            result, reason = "FAIL", "liquidated" if state.get("last_end_reason") == "liquidated" else "busted"
        else:
            return None
        self._finish(state, now, result, reason, int(state.get("end_at") or now), start_next=self.AUTO_RESTART)
        return {"bot": self.BOT_ID, "type": "run_end", "restart": self.AUTO_RESTART, "run": state["run"], "result": result, "reason": reason,
                "balance": cash}

    # ---- entries ---------------------------------------------------------------------------------------------
    def candidates(self, now: int, taken: list[str] | None = None) -> list[dict[str, Any]]:
        """Fresh public grade-A calls of the record, best first (confidence, then newer)."""
        from ..config import MODEL_TIMEFRAMES
        rows = self.db.query("SELECT * FROM signals WHERE created_at >= ? AND created_at <= ? AND status = 'OPEN' "
                             "AND side != 0 AND decision IN ('BUY', 'BUY ON PULLBACK', 'SELL')", (now - FRESH_MS, now))
        skip = set(taken or [])
        out = []
        for r in rows:
            p = loads(r.get("payload"), {}) or {}
            if r["id"] in skip or p.get("grade") not in GRADES or p.get("shadow") or p.get("scalp"):
                continue
            tf = r["timeframe"]
            if tf not in MODEL_TIMEFRAMES or tf in analysis.DEMO_ONLY_TFS or tf in analysis.PAUSED_TFS:
                continue
            if r.get("fill_status") not in (None, "PENDING", "FILLED") or r.get("stop") is None or r.get("tp1") is None:
                continue
            out.append({**r, "payload": p})
        out.sort(key=lambda r: (-(r.get("confidence") or 0.0), -int(r["created_at"])))
        return out

    def _manage_all(self, state: dict[str, Any], now: int) -> list[dict[str, Any]]:
        """v3.2: each trade is followed with its own config (timeframe, time limit, leverage) - several can be open."""
        def key(x: dict[str, Any]) -> str:
            return dumps((x.get("info") or {}).get("cfg") or state.get("trade_cfg") or {})
        groups: dict[str, dict[str, Any]] = {}
        for x in state["positions"]:
            groups.setdefault(key(x), {"pos": [], "pend": []})["pos"].append(x)
        for x in state["pending"]:
            groups.setdefault(key(x), {"pos": [], "pend": []})["pend"].append(x)
        all_pos, all_pend = list(state["positions"]), list(state["pending"])
        events: list[dict[str, Any]] = []
        kept_pos: list[dict[str, Any]] = []
        kept_pend: list[dict[str, Any]] = []
        for k, g in groups.items():
            cfg = loads(k, {}) or None
            if not cfg:
                kept_pos += g["pos"]
                kept_pend += g["pend"]
                continue
            state["positions"], state["pending"] = list(g["pos"]), list(g["pend"])
            events += self._manage_decision(cfg, state, now)
            kept_pos += state["positions"]
            kept_pend += state["pending"]
        state["positions"], state["pending"] = kept_pos, kept_pend
        del all_pos, all_pend
        return events

    def open_count(self, state: dict[str, Any]) -> int:
        return len(state.get("positions") or []) + len(state.get("pending") or [])

    def _enter(self, state: dict[str, Any], now: int) -> list[dict[str, Any]]:
        if float(state["cash"]) < MIN_BALANCE:
            return []
        if int(state.get("pause_until") or 0) > now:
            return []                          # v3.2: resting after PAUSE_AFTER losses in a row
        busy = {x["symbol"] for x in (state.get("positions") or []) + (state.get("pending") or [])}
        out = []
        for r in self.candidates(now, state.get("taken")):
            if self.open_count(state) >= self.SLOTS or float(state["cash"]) < MIN_BALANCE:
                break
            if r["symbol"] in busy:
                continue                       # one trade per coin
            ev = self._enter_call(state, r, now)
            if ev:
                out.append(ev)
                busy.add(r["symbol"])
        return out

    def _enter_call(self, state: dict[str, Any], r: dict[str, Any], now: int) -> dict[str, Any] | None:
        sym, side, tf = r["symbol"], int(r["side"]), r["timeframe"]
        # V3.2 (audit R-14): with a price feed in place (the engine installs a ticker snapshot every tick, empty when the
        # fetch failed), enter only at that coin's live ticker - never at the 15m close fallback of _price(). The call
        # stays a candidate and is retried next tick; exits and pending fills keep using _price / candles as before.
        # Without any feed (offline replays, tests) the candle price is used as before.
        if getattr(self.rt, "feed", None) is not None:
            px = self.rt.live_price(sym)
            if px is None or not math.isfinite(px) or px <= 0:
                return None
        else:
            px = self._price(sym)
        if px is None:
            return None
        stop = float(r["stop"])
        targets = [float(t) for t in (r.get("tp1"), r.get("tp2"), r.get("tp3")) if t is not None]
        # the plan must still make sense at the price Hesper can get (the bots' rule)
        if side * (px - stop) <= 0 or side * (targets[0] - px) <= 0:
            return None
        pullback = r["decision"] == "BUY ON PULLBACK" and r.get("entry") is not None and side * (px - float(r["entry"])) > 0
        entry = float(r["entry"]) if pullback else px
        if side * (entry - stop) <= 0:
            return None
        lev = self._leverage(entry, stop, r, tf)
        if lev is None:
            return None
        fee_rate = F.FUTURES_FEE_RATE
        # v3.2: the stop costs RISK_PCT of the balance (equity incl. open trades); never more margin than the free cash
        eq = float(self.equity(state))
        risk_amt = eq * self.RISK_PCT / 100
        qty_risk = risk_amt / (abs(entry - stop) + 2 * entry * fee_rate)
        qty_cash = float(state["cash"]) * ALL_IN / (entry * (1 / lev + fee_rate))
        qty = min(qty_risk, qty_cash) if self.RISK_PCT > 0 else qty_cash     # RISK_PCT 0 = the old all-in sizing
        if qty <= 0 or qty * entry / lev < MIN_BALANCE * 0.5:
            return None
        p = r["payload"]
        horizon = int(p.get("horizon_bars") or tracking.horizon_for(tf))
        info = {"signal_id": r["id"], "signal": r.get("signal"), "decision": r["decision"], "grade": p.get("grade"),
                "confidence": r.get("confidence"), "bar_ts": r["bar_ts"], "timeframe": tf, "rr": r.get("rr"),
                "atr": r.get("atr"), "leverage": lev, "horizon_bars": horizon, "run": state["run"],
                "balance_before": float(self.equity(state)), "published_at": r["created_at"],
                "risk_pct": self.RISK_PCT}
        run = p.get("runner") or {}
        if run.get("on") and run.get("target"):
            info["run_target"] = float(run["target"])
        cfg = _trade_cfg(tf, horizon, lev, self.BOT_ID, self.NAME)
        info["cfg"] = cfg                      # v3.2: each trade keeps its own follow-up config
        state["taken"] = (list(state.get("taken") or []) + [r["id"]])[-50:]
        state["last_entry_bar"][sym] = r["bar_ts"]
        if pullback:
            reserved = qty * entry * (1 / lev + fee_rate)
            state["cash"] -= reserved
            state["pending"].append({"id": new_id()[:12], "symbol": sym, "side": side, "limit": entry, "qty": qty,
                                     "reserved": reserved, "lev": lev, "stop": stop, "targets": targets, "placed_at": now,
                                     "info": info, "last_check": _first_full(now),
                                     "expires_at": now + PENDING_BARS * tf_ms(tf)})
            state["trade_cfg"] = cfg
            return {"bot": self.BOT_ID, "type": "limit", "symbol": sym, "price": entry, "signal_id": r["id"]}
        pos = self._open(state, sym, side, px, qty, now, info, stop, targets, lev=lev, cfg=cfg)
        if not pos:
            return None
        state["trade_cfg"] = cfg
        return {"bot": self.BOT_ID, "type": "open", "symbol": sym, "side": side, "price": pos["entry"], "leverage": lev,
                "signal_id": r["id"]}

    def _leverage(self, entry: float, stop: float, r: dict[str, Any], tf: str) -> float | None:
        # v2.14: the engine's leverage (10-50x from stop distance, coin tier, grade); too wide for 10x -> not taken
        if F.in_policy(tf):          # v2.14 (15m): the engine's 10-50x; too wide for 10x -> not taken
            el = F.engine_leverage(entry, stop, r.get("symbol"), (r.get("payload") or {}).get("grade") or "A", tf)
            return None if el is None else float(el)
        # v2.13: up to 25x, lowered so liquidation sits 1.5x the stop distance away
        return float(min(MAX_LEVERAGE, F.safe_leverage(entry, stop, MAX_LEVERAGE, symbol=r.get("symbol"))))

    # ---- closes -----------------------------------------------------------------------------------------------
    def _close_trade(self, bot_id: str, state: dict[str, Any], pos: dict[str, Any], now: int, reason: str,
                     correct: bool | None = None) -> dict[str, Any]:
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
        info = pos.get("info") or {}
        avg_exit = pos["exit_value"] / pos["qty"] if pos["qty"] else pos["entry"]
        margin = float(pos.get("margin") or 0.0)
        pnl = float(pos["realized"])
        bal = float(state["cash"])
        trade = {"id": pos["id"], "run": int(info.get("run") or state["run"]), "signal_id": info.get("signal_id"),
                 "symbol": pos["symbol"], "timeframe": info.get("timeframe") or "", "side": int(pos["side"]),
                 "leverage": float(pos.get("lev", 1.0)), "opened_at": int(pos["opened_at"]), "closed_at": int(now),
                 "entry": float(pos["entry"]), "exit": float(avg_exit), "qty": float(pos["qty"]), "margin": margin,
                 "pnl": pnl, "fees": float(pos.get("fees", 0.0)), "funding": float(pos.get("funding", 0.0)),
                 "roi_pct": pnl / margin * 100 if margin else None, "exit_reason": reason, "tp_hit": int(pos["tp_hit"]),
                 "balance_before": float(info.get("balance_before") or bal - pnl), "balance_after": bal,
                 "info": dumps({"confidence": info.get("confidence"), "grade": info.get("grade"),
                                "decision": info.get("decision"), "liquidation_price": pos.get("liq"),
                                "stop0": pos.get("stop0"), "targets": pos.get("targets"),
                                "run_target": info.get("run_target"), "horizon_bars": info.get("horizon_bars")})}
        self.db.execute(f"INSERT INTO {self.TRADES} ({', '.join(trade)}) VALUES ({', '.join('?' * len(trade))}) "
                        "ON CONFLICT (id) DO NOTHING", list(trade.values()))
        state["trades"] = int(state.get("trades", 0)) + 1
        state["wins"] = int(state.get("wins", 0)) + (1 if pnl > 0 else 0)
        state["peak"] = max(float(state.get("peak", _start_of(state))), bal)
        best = self.db.one(f"SELECT id, symbol, timeframe, pnl, roi_pct FROM {self.TRADES} WHERE run = ? "
                           "ORDER BY pnl DESC LIMIT 1", (trade["run"],))
        self.db.execute(f"UPDATE {self.RUNS} SET trades = ?, wins = ?, peak = ?, best_trade = ? "
                        "WHERE run = ? AND result = 'RUNNING'",
                        (state["trades"], state["wins"], state["peak"], dumps(best) if best else None, trade["run"]))
        state["end_at"] = int(now)
        if reason == "liquidated":
            state["liquidations"] = int(state.get("liquidations", 0)) + 1
            state["last_end_reason"] = "liquidated"
            if self.SLOTS <= 1:
                state["end"] = "liquidated"            # one trade at a time (old rule): a liquidation ends the run
        else:
            state["last_end_reason"] = None
        # v3.2: PAUSE_AFTER losses in a row -> no new trade for PAUSE_MS
        if pnl > 0:
            state["loss_streak"] = 0
        else:
            state["loss_streak"] = int(state.get("loss_streak", 0)) + 1
            if state["loss_streak"] >= self.PAUSE_AFTER:
                state["pause_until"] = int(now) + self.PAUSE_MS
                state["loss_streak"] = 0
        return trade

    # ---- admin changes on the call Hesper holds (adjust.py) ----------------------------------------------------
    def _mine(self, sig: dict[str, Any]):
        return lambda x: (x.get("info") or {}).get("signal_id") == sig.get("id")

    def apply_adjustment(self, sig: dict[str, Any], changes: list[tuple[str, float]], at: int) -> int:
        state = self.load()
        if not state or not changes:
            return 0
        n = 0
        for x in list(state.get("positions") or []) + list(state.get("pending") or []):
            if self._mine(sig)(x):
                x["adj"] = list(x.get("adj") or []) + [{"at": int(at), "field": f, "new": float(v)} for f, v in changes]
                n += 1
        if n:
            self.save(state)
        return n

    def apply_close(self, sig: dict[str, Any], price: float, at: int) -> int:
        state = self.load()
        if not state:
            return 0
        n = 0
        for x in state.get("positions") or []:
            if self._mine(sig)(x) and not x.get("admin_close"):
                x["admin_close"] = {"at": int(at), "price": float(price)}
                n += 1
        for o in list(state.get("pending") or []):
            if self._mine(sig)(o):
                state["cash"] = state.get("cash", 0.0) + o.get("reserved", 0.0)
                state["pending"].remove(o)
                n += 1
        if n:
            self.save(state)
        return n

    # ---- v2.63 admin "Close all" / "Close 50%" on the challenge's own trade (never the call, never the other run) ----
    def admin_close(self, fraction: float, now: int | None = None, by: str = "", px: float | None = None,
                    pos_id: str | None = None) -> dict[str, Any]:
        """Close the open trade now at the engine's price: all of it (fraction 1) or half of what is still open
        (0.5). The run goes on. A half close scales the remaining target legs so TP1-3 still take 50 / 25 / 25 of what
        is left. "Close all" also cancels a waiting entry order."""
        now = now_ms() if now is None else now
        fraction = float(fraction)
        if fraction not in (0.5, 1.0):
            raise ValueError("choose Close all or Close 50%")
        state = self.load()
        if not state or state.get("idle"):
            raise ValueError("no run in progress")
        if pos_id is None and fraction == 1.0 and len(state.get("positions") or []) > 1:
            # v3.2 "Close all trades": every open trade closes at the engine's price, waiting orders are cancelled
            total, evs = 0.0, []
            for q in list(state["positions"]):
                price = float(self._price(q["symbol"]) or q["entry"])
                self._reduce(state, q, float(q["qty_open"]), price, False)
                t = self._close_trade(self.BOT_ID, state, q, now, "closed by admin")
                total += float(t["pnl"])
            for o in list(state.get("pending") or []):
                state["cash"] = state.get("cash", 0.0) + o.get("reserved", 0.0)
            state["pending"], state["trade_cfg"] = [], None
            state["equity"] = self.equity(state)
            self.save(state)
            return {"closed": "all trades", "pnl": round(total, 4), "balance": round(float(state["cash"]), 2), "by": by,
                    "event": {"bot": self.BOT_ID, "type": "close", "symbol": "all", "reason": "closed by admin",
                              "pnl": total, "run": state["run"], "balance": float(state["cash"])}}
        cand = [q for q in state.get("positions") or [] if pos_id is None or q["id"] == pos_id]
        if pos_id is not None and not cand:
            pend = [o for o in state.get("pending") or [] if o.get("id") == pos_id]
            if pend:
                state["cash"] = state.get("cash", 0.0) + pend[0].get("reserved", 0.0)
                state["pending"] = [o for o in state["pending"] if o.get("id") != pos_id]
                self.save(state)
                return {"cancelled_order": True, "balance": round(float(state["cash"]), 2), "by": by}
            raise ValueError("that trade is no longer open")
        pos = cand[0] if cand else None
        if pos is None:
            pend = list(state.get("pending") or [])
            if pend and fraction == 1.0:
                for o in pend:
                    state["cash"] = state.get("cash", 0.0) + o.get("reserved", 0.0)
                state["pending"], state["trade_cfg"] = [], None
                self.save(state)
                return {"cancelled_order": True, "balance": round(float(state["cash"]), 2), "by": by}
            raise ValueError("no open trade to close" + (" (an entry order is waiting: use Close all to cancel it)" if pend else ""))
        price = float(px if px is not None else (self._price(pos["symbol"]) or pos["entry"]))
        left = float(pos["qty_open"])
        if fraction == 1.0 or left * 0.5 * price < 1.0:          # half of a dust position: close it all
            self._reduce(state, pos, left, price, False)
            t = self._close_trade(self.BOT_ID, state, pos, now, "closed by admin")
            state["trade_cfg"] = None
            state["equity"] = self.equity(state)
            self.save(state)
            return {"closed": "all", "symbol": pos["symbol"], "price": price, "pnl": round(t["pnl"], 4),
                    "balance": round(float(state["cash"]), 2), "by": by,
                    "event": {"bot": self.BOT_ID, "type": "close", "symbol": pos["symbol"], "reason": "closed by admin",
                              "pnl": t["pnl"], "run": state["run"], "balance": float(state["cash"])}}
        before = float(pos["realized"])
        self._reduce(state, pos, left * 0.5, price, False)
        pos["leg_scale"] = float(pos.get("leg_scale") or 1.0) * 0.5
        pos["admin_partials"] = list(pos.get("admin_partials") or []) + [{"at": int(now), "price": price, "share": 0.5}]
        state["equity"] = self.equity(state)
        self.save(state)
        part = float(pos["realized"]) - before
        return {"closed": "half", "symbol": pos["symbol"], "price": price, "pnl": round(part, 4),
                "balance": round(float(state["equity"]), 2), "by": by,
                "event": {"bot": self.BOT_ID, "type": "partial", "symbol": pos["symbol"], "pnl": part,
                          "run": state["run"], "side": pos.get("side")}}


class LastStand(Hesper):
    """v2.63 (owner, 21 Nov 2026): a second all-in run inside the Hesper Challenge page. Same calls and rules as the
    Hesper Challenge (fresh public grade-A calls, all-in, one trade at a time), its own account and record. The admin
    starts each run with any amount, can close its trade (all / 50%), and the run goes on until it is liquidated (or too
    small to trade). Nothing starts by itself: after a liquidation it waits for the admin's next "Start run"."""
    BOT_ID, NAME, TITLE = "laststand", "Last Stand", "Last Stand"
    RISK_PCT = float(os.environ.get("LASTSTAND_RISK_PCT", "15"))
    STATE_KEY, FLAG, SINCE = "laststand_state", "laststand_v1", "laststand_since"
    RUNS, TRADES = "laststand_runs", "laststand_trades"
    AUTO_START = False
    AUTO_RESTART = False
    MIN_START, MAX_START = 5.0, 1_000_000.0
    # v2.63b (owner: "a bit aggressive, we use a very little amount"): up to 50x on every timeframe, liquidation only
    # LIQ_BUFFER x the stop distance beyond the entry (Hesper: 1.5x, max 25x). The stop still comes before liquidation.
    MAX_LEVERAGE = 50
    LIQ_BUFFER = 1.15

    def _leverage(self, entry: float, stop: float, r: dict[str, Any], tf: str) -> float | None:
        dist = abs(entry - stop) / entry if entry else 0.0
        if dist <= 0:
            return None
        m = F.maintenance_rate(r.get("symbol"))
        fee = F.FUTURES_FEE_RATE
        lev = math.floor(1 / (self.LIQ_BUFFER * dist * (1 + m + fee) + m + fee))
        return float(max(1, min(self.MAX_LEVERAGE, lev)))


CHALLENGES = (Hesper, LastStand)
BY_ID = {c.BOT_ID: c for c in CHALLENGES}


def _first_full(now: int) -> int:
    from .bots import _first_full_candle
    return _first_full_candle(now)


# ---- admin view (views/hesper) -----------------------------------------------------------------------------------

def _streak(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Current streak over all trades, newest first: {kind: win | loss | None, n}."""
    kind, n = None, 0
    for t in trades:
        k = "win" if t["pnl"] > 0 else "loss"
        if kind is None:
            kind = k
        if k != kind:
            break
        n += 1
    return {"kind": kind, "n": n}


def _trade_row(t: dict[str, Any]) -> dict[str, Any]:
    return {k: t.get(k) for k in ("id", "run", "symbol", "timeframe", "side", "leverage", "opened_at", "closed_at", "entry",
                                  "exit", "margin", "pnl", "roi_pct", "exit_reason", "tp_hit", "balance_before",
                                  "balance_after", "fees", "funding")}


def view(rt: Any, cls: type[Hesper] = Hesper) -> dict[str, Any]:
    db = rt.db
    st = db.get_setting(cls.STATE_KEY, None)
    since = db.get_setting(cls.SINCE, None)
    start = _start_of(st if isinstance(st, dict) else None)
    base = {"id": cls.BOT_ID, "name": cls.NAME, "title": cls.TITLE, "auto_restart": cls.AUTO_RESTART,
            "min_start": cls.MIN_START, "since": since, "start": start, "goal": float((st or {}).get("goal") or goal_of(start)) if isinstance(st, dict) else goal_of(start),
            "max_leverage": MAX_LEVERAGE, "idle": bool(isinstance(st, dict) and st.get("idle")),
            "policy": {"timeframes": list(F.POLICY_TFS), "min": F.MIN_LEVERAGE, "max": F.POLICY_MAX_LEVERAGE},
            "min_balance": MIN_BALANCE, "started": bool(st), "generated_at": now_ms()}
    runs = db.query(f"SELECT * FROM {cls.RUNS} ORDER BY run DESC")
    for r in runs:
        r["best_trade"] = loads(r.get("best_trade"), None)
    done = [r for r in runs if r["result"] != "RUNNING"]
    succ = [r for r in done if r["result"] == "SUCCESS"]
    fails = [r for r in done if r["result"] == "FAIL"]
    stopped = [r for r in done if r["result"] == "STOPPED"]
    # v2.22: a run "made it" when it reached the $1,000 milestone (old SUCCESS runs, or goal_reached_at on newer ones)
    reached = [r for r in runs if r["result"] == "SUCCESS" or r.get("goal_reached_at")]
    all_trades = db.query(f"SELECT * FROM {cls.TRADES} ORDER BY closed_at DESC, id DESC")
    best_run = max(runs, key=lambda r: r["peak"]) if runs else None
    fastest = min(succ, key=lambda r: (r["ended_at"] - r["started_at"], r["trades"])) if succ else None
    fewest = min(succ, key=lambda r: (r["trades"], r["ended_at"] - r["started_at"])) if succ else None
    score = {"successes": len(succ), "failures": len(fails), "stopped": len(stopped), "milestones": len(reached),
             "best_end": max([float(r["end_balance"] or 0) for r in stopped + succ] or [0.0]) or None,
             "liquidations": sum(1 for r in fails if r["reason"] == "liquidated"),
             "busted": sum(1 for r in fails if r["reason"] == "busted"), "runs": len(runs), "finished": len(done),
             "best_peak": {"run": best_run["run"], "peak": best_run["peak"]} if best_run else None,
             "all_time_peak": max([r["peak"] for r in runs] or [start]),
             "avg_trades_per_run": (sum(r["trades"] for r in done) / len(done)) if done else None,
             "fastest_success": {"run": fastest["run"], "ms": fastest["ended_at"] - fastest["started_at"],
                                 "trades": fastest["trades"]} if fastest else None,
             "fewest_trades_success": {"run": fewest["run"], "trades": fewest["trades"]} if fewest else None,
             "trades": len(all_trades), "wins": sum(1 for t in all_trades if t["pnl"] > 0),
             "streak": _streak(all_trades)}
    current = None
    if st and not st.get("idle"):
        pos = (st.get("positions") or [None])[0]
        pend = (st.get("pending") or [None])[0]
        current = {"run": st["run"], "started_at": st["started_at"], "cash": st["cash"],
                   "balance": st.get("equity", st["cash"]), "peak": st.get("peak"), "trades": st.get("trades", 0),
                   "wins": st.get("wins", 0), "updated_at": st.get("updated_at"), "open": None, "pending": None,
                   "goal_reached_at": st.get("goal_reached_at"), "start_balance": _start_of(st),
                   "goal": float(st.get("goal") or goal_of(_start_of(st)))}
        current.update({"slots": cls.SLOTS, "risk_pct": cls.RISK_PCT, "pause_until": st.get("pause_until"),
                        "loss_streak": st.get("loss_streak", 0), "opens": [], "pendings": []})
        for q in st.get("positions") or []:
            i = q.get("info") or {}
            current["opens"].append({"id": q["id"], "symbol": q["symbol"], "timeframe": i.get("timeframe"), "side": q["side"],
                                     "entry": q["entry"], "stop": q["stop"], "stop0": q.get("stop0"),
                                     "targets": q.get("targets"), "tp_hit": q["tp_hit"], "leverage": q.get("lev"),
                                     "qty": q["qty"], "qty_open": q["qty_open"], "margin": q.get("margin"),
                                     "coll": q.get("coll"), "liq": q.get("liq"), "realized": q.get("realized"),
                                     "opened_at": q["opened_at"], "signal_id": i.get("signal_id"),
                                     "horizon_bars": i.get("horizon_bars"), "run_target": i.get("run_target"),
                                     "risk_pct": i.get("risk_pct"), "admin_partials": len(q.get("admin_partials") or [])})
        for o in st.get("pending") or []:
            i = o.get("info") or {}
            current["pendings"].append({"id": o.get("id"), "symbol": o["symbol"], "timeframe": i.get("timeframe"),
                                        "side": o["side"], "limit": o["limit"], "stop": o["stop"], "leverage": o.get("lev"),
                                        "reserved": o.get("reserved"), "placed_at": o.get("placed_at"),
                                        "expires_at": o.get("expires_at")})
        if pos:
            i = pos.get("info") or {}
            current["open"] = {"id": pos["id"], "symbol": pos["symbol"], "timeframe": i.get("timeframe"), "side": pos["side"],
                               "entry": pos["entry"], "stop": pos["stop"], "stop0": pos.get("stop0"),
                               "targets": pos.get("targets"), "tp_hit": pos["tp_hit"], "leverage": pos.get("lev"),
                               "qty": pos["qty"], "qty_open": pos["qty_open"], "margin": pos.get("margin"),
                               "coll": pos.get("coll"), "liq": pos.get("liq"), "realized": pos.get("realized"),
                               "opened_at": pos["opened_at"], "signal_id": i.get("signal_id"),
                               "confidence": i.get("confidence"), "horizon_bars": i.get("horizon_bars"),
                               "run_target": i.get("run_target"), "balance_before": i.get("balance_before"),
                               "admin_partials": len(pos.get("admin_partials") or [])}
        elif pend:
            i = pend.get("info") or {}
            current["pending"] = {"id": pend.get("id"), "symbol": pend["symbol"], "timeframe": i.get("timeframe"),
                                  "side": pend["side"], "limit": pend["limit"], "stop": pend["stop"],
                                  "targets": pend.get("targets"), "leverage": pend.get("lev"),
                                  "reserved": pend.get("reserved"), "placed_at": pend.get("placed_at"),
                                  "expires_at": pend.get("expires_at"), "signal_id": i.get("signal_id")}
    curves: dict[str, list[list[float]]] = {}
    by_run: dict[int, list[dict[str, Any]]] = {}
    for t in reversed(all_trades):
        by_run.setdefault(int(t["run"]), []).append(t)
    for r in runs[:VIEW_CURVES]:
        pts = [[r["started_at"], float(r.get("start_balance") or START_BALANCE)]] + [[t["closed_at"], round(t["balance_after"], 4)]
                                                   for t in by_run.get(int(r["run"]), [])]
        if len(pts) > CURVE_POINTS:
            step = len(pts) / CURVE_POINTS
            pts = [pts[int(i * step)] for i in range(CURVE_POINTS - 1)] + [pts[-1]]
        curves[str(r["run"])] = pts
    return {**base, "current": current, "score": score,
            "open_ended": True,
            "runs": [{k: r.get(k) for k in ("run", "started_at", "ended_at", "result", "reason", "start_balance",
                                              "end_balance", "peak", "trades", "wins", "best_trade", "goal_reached_at")}
                     for r in runs[:VIEW_RUNS]],
            "trades": [_trade_row(t) for t in all_trades[:VIEW_TRADES]], "curves": curves,
            "label": "Demo · virtual money · not financial advice"}


def core(v: dict[str, Any]) -> Any:
    """What goes out at once when it changes: a trade opened / filled / hit a target / closed, or a run ended."""
    c = v.get("current") or {}
    o = c.get("open") or {}
    p = c.get("pending") or {}
    return [c.get("run"), c.get("trades"), (v.get("score") or {}).get("trades"), o.get("id"), o.get("tp_hit"),
            o.get("stop"), p.get("id"), c.get("goal_reached_at"), v.get("idle")]


# ---- v2.30 notifications (owner, 14 Nov 2026: "also for hesper challenge - very important") --------------------
# Every challenge event becomes a push: trade opened / limit placed / limit filled / limit expired / TP hit / trade
# closed (with P/L and balance) / liquidated / run ended / goal reached. Sent to the admin's devices; also to each active
# member when the admin shows the challenge to members (config/hesper.visibility == 'members', read only when there is
# something to send). Notification text only: nothing here changes a trade.
PUSH_URL, MEMBER_URL = "/rich", "/results?tab=challenge"      # admin page / members' Results tab
REASONS = {"stop": "stop loss", "breakeven stop": "break-even stop", "trailing stop": "stop at TP1, profit kept",
           "time exit": "time limit", "time stop": "time limit", "runner target": "runner target"}


def _coin(sym: Any) -> str:
    s = str(sym or "")
    return "GOLD" if s.startswith("PAXG") else s.split("/")[0]


def _usd(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "-"


def push_text(ev: dict[str, Any]) -> tuple[str, str] | None:
    """(title, body) of one challenge event, or None for an event that is not worth a notification."""
    t, coin, run = ev.get("type"), _coin(ev.get("symbol")), ev.get("run")
    title = (BY_ID.get(str(ev.get("bot") or "")) or Hesper).TITLE
    head = f"{title} · run #{run}" if run else title
    side = "LONG" if (ev.get("side") or 0) > 0 else "SHORT"
    if t == "open":
        lev = f", {float(ev['leverage']):g}x" if ev.get("leverage") else ""
        return head, f"{coin} {side} opened at {fmt_price(ev.get('price'))}{lev}."
    if t == "limit":
        return head, f"{coin}: entry order placed at {fmt_price(ev.get('price'))}, waiting for the price."
    if t == "fill":
        return head, f"{coin}: entry filled at {fmt_price(ev.get('price'))}, the trade is live."
    if t == "expired":
        return head, f"{coin}: entry order cancelled" + (f" ({ev['reason']})." if ev.get("reason") else ", price never reached it.")
    if t == "tp":
        extra = " Stop moved to break-even." if ev.get("tp") == 1 else (" Stop moved to TP1." if ev.get("tp") == 2 else "")
        return head, f"{coin} {side}: TP{ev.get('tp')} hit, part of the trade closed in profit.{extra}"
    if t in ("close", "liquidated"):
        pnl = float(ev.get("pnl") or 0)
        why = "liquidated" if t == "liquidated" else REASONS.get(str(ev.get("reason") or ""), str(ev.get("reason") or ""))
        bal = f" Balance {_usd(ev['balance'])}." if ev.get("balance") is not None else ""
        return head, f"{coin} closed {'+' if pnl >= 0 else '-'}{_usd(abs(pnl))}" + (f" ({why})." if why else ".") + bal
    if t == "run_end":
        why = {"liquidated": "liquidated", "busted": "balance too low to trade"}.get(ev.get("reason"), ev.get("reason") or "ended")
        nxt = "The next run starts now." if ev.get("restart", True) else "Start the next run when you're ready."
        return head, f"Run ended: {why}. Final balance {_usd(ev.get('balance'))}. {nxt}"
    if t == "goal_reached":
        return head, f"10x reached! Balance {_usd(ev.get('balance'))}. The run keeps going."
    if t == "partial":
        pnl = float(ev.get("pnl") or 0)
        return head, f"{coin}: half of the trade closed by the admin, {'+' if pnl >= 0 else '-'}{_usd(abs(pnl))}. The rest stays open."
    return None


def push_messages(events: list[dict[str, Any]], member_uids: list[str] | tuple[str, ...] = ()) -> list[dict[str, str]]:
    """Push messages for the admin (no uid) and, when given, each member (uid)."""
    out: list[dict[str, str]] = []
    for ev in events or []:
        tb = push_text(ev)
        if not tb:
            continue
        bot = str(ev.get("bot") or BOT_ID)
        base = {"title": tb[0], "body": tb[1], "url": PUSH_URL if bot == BOT_ID else f"{PUSH_URL}?c={bot}",
                "tag": f"{'hesper' if bot == BOT_ID else bot}-{ev.get('run')}-{ev.get('type')}-{_coin(ev.get('symbol'))}-{ev.get('tp') or ''}"}
        out.append(dict(base))
        murl = MEMBER_URL if bot == BOT_ID else f"{MEMBER_URL}&c={bot}"
        out += [{**base, "uid": uid, "url": murl} for uid in member_uids]
    return out
