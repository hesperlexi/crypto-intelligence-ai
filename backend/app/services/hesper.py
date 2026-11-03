"""ROAD TO RICH - Hesper, the admin's all-in demo bot (owner decisions, 2 Nov 2026). Virtual money only: nothing here
ever talks to an exchange's trading API.

* A **run** starts with $100. Hesper takes only **public grade-A calls** from the record (`signals`, any public
  timeframe), one trade at a time: when flat, the best fresh call (published in the last `FRESH_MS`; highest
  confidence, tie -> newer) is entered like the futures bots enter (market, or a limit for BUY ON PULLBACK).
* **All-in**: margin = the whole balance (`ALL_IN` keeps a sliver for fees), isolated margin, leverage up to 25x but
  lowered per trade so the liquidation price sits 1.5x the stop distance beyond the entry (`futures.safe_leverage`,
  the futures bots' rule). Futures fees, slippage and 8-hourly funding exactly as the futures bots.
* Exits are the bots' own (`BotEngine._manage_decision`, shared rules in engine/manage.py): 50 / 25 / 25 at TP1-3,
  break-even after TP1, TP1 after TP2, runner when the call has one, the call's own time limit, admin stop / TP1
  changes and "Close now" on the call, reversal on a grade-A opposite call (never on 15m), followed on 15m candles.
* A run ends only by itself: FAIL on a liquidation ("liquidated") or when the balance is below `MIN_BALANCE`
  ("busted"); SUCCESS when the realised balance reaches `GOAL` ($1,000). The next run starts at once at $100.
  Never reset by hand. Every run and trade is kept (`hesper_runs`, `hesper_trades`); a finished run is never changed.

Isolation: Hesper has its own tables and its own state (setting `hesper_state`); it is not a row of `bots`, so the
bots report, the Results "Demo bots" list, the track record, auto-trade, Telegram, achievements, the weekly report,
training and wins_today never see it. It only reads `signals`. Admin-only view `views/hesper`.
"""
from __future__ import annotations

from typing import Any

from ..data.base import tf_ms
from ..db import dumps, loads, new_id, now_ms
from ..engine import futures as F
from . import analysis
from . import tracking
from .bots import BotEngine
from .runtime import Runtime

BOT_ID = "hesper"
NAME = "Hesper"
START_BALANCE = 100.0
GOAL = 1000.0
MIN_BALANCE = 1.0            # below this a run is "busted" (cannot open a meaningful trade)
MAX_LEVERAGE = 25
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


def _fresh_state(run: int, now: int) -> dict[str, Any]:
    return {"run": run, "started_at": now, "cash": START_BALANCE, "positions": [], "pending": [], "start_prices": {},
            "last_bar": {}, "last_entry_bar": {}, "fees_paid": 0.0, "funding_paid": 0.0, "liquidations": 0,
            "notes": [], "peak": START_BALANCE, "trades": 0, "wins": 0, "trade_cfg": None, "end": None,
            "taken": []}


def _trade_cfg(tf: str, horizon: int, lev: float) -> dict[str, Any]:
    """The bot config `_manage_decision` follows the current trade with (one trade at a time)."""
    return {"id": BOT_ID, "name": NAME, "mode": "decision", "timeframe": tf, "symbols": "all", "market": "futures",
            "safe_leverage": True, "leverage": float(lev), "max_hold_bars": int(horizon), "grades": "".join(GRADES),
            "pending_bars": PENDING_BARS, "allow_short": True, "starting_balance": START_BALANCE}


class Hesper(BotEngine):
    def __init__(self, rt: Runtime):
        super().__init__(rt)

    # ---- state -------------------------------------------------------------------------------------------
    def load(self) -> dict[str, Any] | None:
        st = self.db.get_setting(STATE_KEY, None)
        return st if isinstance(st, dict) else None

    def save(self, state: dict[str, Any]) -> None:
        self.db.set_setting(STATE_KEY, state)

    def start(self, now: int) -> dict[str, Any]:
        """One-time start (flag `hesper_v1`): run 1 at $100 from now. Never restarted afterwards."""
        state = self.load()
        if state is not None:
            return state
        if not self.db.get_setting(SINCE, None):
            self.db.set_setting(SINCE, now)
        last = self.db.one("SELECT MAX(run) AS n FROM hesper_runs")
        run = int((last or {}).get("n") or 0) + 1
        state = _fresh_state(run, now)
        self._insert_run(state)
        self.db.set_setting(FLAG, True)
        self.save(state)
        return state

    def _insert_run(self, state: dict[str, Any]) -> None:
        self.db.execute("INSERT INTO hesper_runs (run, started_at, result, start_balance, peak, trades, wins) "
                        "VALUES (?, ?, 'RUNNING', ?, ?, 0, 0) ON CONFLICT (run) DO NOTHING",
                        (state["run"], state["started_at"], START_BALANCE, START_BALANCE))

    def bots(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return []               # never part of the bots machinery's own list (report, adjustments of `bots` rows)

    # ---- one cycle -----------------------------------------------------------------------------------------
    def run(self, now: int | None = None) -> list[dict[str, Any]]:
        now = now_ms() if now is None else now
        state = self.start(now)
        events: list[dict[str, Any]] = []
        self._funding(state, now)
        cfg = state.get("trade_cfg")
        if cfg and (state["positions"] or state["pending"]):
            events += self._manage_decision(cfg, state, now)
        if not state["positions"] and not state["pending"]:
            state["trade_cfg"] = None
            ended = self._check_end(state, now)
            if ended:
                events.append(ended)
                state = self.load() or state
            events += self._enter(state, now)
        state["equity"] = self.equity(state)
        state["updated_at"] = now
        self.save(state)
        return events

    def _check_end(self, state: dict[str, Any], now: int) -> dict[str, Any] | None:
        """Flat: has the run ended? Liquidation or a balance below MIN_BALANCE -> FAIL; >= GOAL -> SUCCESS."""
        cash = float(state["cash"])
        if state.get("end") == "liquidated":
            result, reason = "FAIL", "liquidated"
        elif cash >= GOAL - 1e-9:
            result, reason = "SUCCESS", "goal"
        elif cash < MIN_BALANCE:
            result, reason = "FAIL", "busted"
        else:
            return None
        at = int(state.get("end_at") or now)
        self.db.execute("UPDATE hesper_runs SET ended_at = ?, result = ?, reason = ?, end_balance = ?, peak = ?, "
                        "trades = ?, wins = ? WHERE run = ? AND result = 'RUNNING'",
                        (at, result, reason, cash, max(float(state["peak"]), cash), state["trades"], state["wins"],
                         state["run"]))
        nxt = _fresh_state(int(state["run"]) + 1, now)
        nxt["taken"] = list(state.get("taken") or [])[-50:]       # a call is never taken twice, even across runs
        self._insert_run(nxt)
        self.save(nxt)
        return {"bot": BOT_ID, "type": "run_end", "run": state["run"], "result": result, "reason": reason,
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

    def _enter(self, state: dict[str, Any], now: int) -> list[dict[str, Any]]:
        if float(state["cash"]) < MIN_BALANCE:
            return []
        for r in self.candidates(now, state.get("taken")):
            ev = self._enter_call(state, r, now)
            if ev:
                return [ev]
        return []

    def _enter_call(self, state: dict[str, Any], r: dict[str, Any], now: int) -> dict[str, Any] | None:
        sym, side, tf = r["symbol"], int(r["side"]), r["timeframe"]
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
        lev = float(min(MAX_LEVERAGE, F.safe_leverage(entry, stop, MAX_LEVERAGE, symbol=r.get("symbol"))))
        fee_rate = F.FUTURES_FEE_RATE
        qty = float(state["cash"]) * ALL_IN / (entry * (1 / lev + fee_rate))
        if qty <= 0:
            return None
        p = r["payload"]
        horizon = int(p.get("horizon_bars") or tracking.horizon_for(tf))
        info = {"signal_id": r["id"], "signal": r.get("signal"), "decision": r["decision"], "grade": p.get("grade"),
                "confidence": r.get("confidence"), "bar_ts": r["bar_ts"], "timeframe": tf, "rr": r.get("rr"),
                "atr": r.get("atr"), "leverage": lev, "horizon_bars": horizon, "run": state["run"],
                "balance_before": float(state["cash"]), "published_at": r["created_at"]}
        run = p.get("runner") or {}
        if run.get("on") and run.get("target"):
            info["run_target"] = float(run["target"])
        cfg = _trade_cfg(tf, horizon, lev)
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
            return {"bot": BOT_ID, "type": "limit", "symbol": sym, "price": entry, "signal_id": r["id"]}
        pos = self._open(state, sym, side, px, qty, now, info, stop, targets, lev=lev, cfg=cfg)
        if not pos:
            return None
        state["trade_cfg"] = cfg
        return {"bot": BOT_ID, "type": "open", "symbol": sym, "side": side, "price": pos["entry"], "leverage": lev,
                "signal_id": r["id"]}

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
        self.db.execute(f"INSERT INTO hesper_trades ({', '.join(trade)}) VALUES ({', '.join('?' * len(trade))}) "
                        "ON CONFLICT (id) DO NOTHING", list(trade.values()))
        state["trades"] = int(state.get("trades", 0)) + 1
        state["wins"] = int(state.get("wins", 0)) + (1 if pnl > 0 else 0)
        state["peak"] = max(float(state.get("peak", START_BALANCE)), bal)
        best = self.db.one("SELECT id, symbol, timeframe, pnl, roi_pct FROM hesper_trades WHERE run = ? "
                           "ORDER BY pnl DESC LIMIT 1", (trade["run"],))
        self.db.execute("UPDATE hesper_runs SET trades = ?, wins = ?, peak = ?, best_trade = ? "
                        "WHERE run = ? AND result = 'RUNNING'",
                        (state["trades"], state["wins"], state["peak"], dumps(best) if best else None, trade["run"]))
        state["end_at"] = int(now)
        if reason == "liquidated":
            state["end"] = "liquidated"
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


def view(rt: Any) -> dict[str, Any]:
    db = rt.db
    st = db.get_setting(STATE_KEY, None)
    since = db.get_setting(SINCE, None)
    base = {"name": NAME, "since": since, "start": START_BALANCE, "goal": GOAL, "max_leverage": MAX_LEVERAGE,
            "min_balance": MIN_BALANCE, "started": bool(st), "generated_at": now_ms()}
    runs = db.query("SELECT * FROM hesper_runs ORDER BY run DESC")
    for r in runs:
        r["best_trade"] = loads(r.get("best_trade"), None)
    done = [r for r in runs if r["result"] != "RUNNING"]
    succ = [r for r in done if r["result"] == "SUCCESS"]
    fails = [r for r in done if r["result"] == "FAIL"]
    all_trades = db.query("SELECT * FROM hesper_trades ORDER BY closed_at DESC, id DESC")
    best_run = max(runs, key=lambda r: r["peak"]) if runs else None
    fastest = min(succ, key=lambda r: (r["ended_at"] - r["started_at"], r["trades"])) if succ else None
    fewest = min(succ, key=lambda r: (r["trades"], r["ended_at"] - r["started_at"])) if succ else None
    score = {"successes": len(succ), "failures": len(fails),
             "liquidations": sum(1 for r in fails if r["reason"] == "liquidated"),
             "busted": sum(1 for r in fails if r["reason"] == "busted"), "runs": len(runs), "finished": len(done),
             "best_peak": {"run": best_run["run"], "peak": best_run["peak"]} if best_run else None,
             "all_time_peak": max([r["peak"] for r in runs] or [START_BALANCE]),
             "avg_trades_per_run": (sum(r["trades"] for r in done) / len(done)) if done else None,
             "fastest_success": {"run": fastest["run"], "ms": fastest["ended_at"] - fastest["started_at"],
                                 "trades": fastest["trades"]} if fastest else None,
             "fewest_trades_success": {"run": fewest["run"], "trades": fewest["trades"]} if fewest else None,
             "trades": len(all_trades), "wins": sum(1 for t in all_trades if t["pnl"] > 0),
             "streak": _streak(all_trades)}
    current = None
    if st:
        pos = (st.get("positions") or [None])[0]
        pend = (st.get("pending") or [None])[0]
        current = {"run": st["run"], "started_at": st["started_at"], "cash": st["cash"],
                   "balance": st.get("equity", st["cash"]), "peak": st.get("peak"), "trades": st.get("trades", 0),
                   "wins": st.get("wins", 0), "updated_at": st.get("updated_at"), "open": None, "pending": None}
        if pos:
            i = pos.get("info") or {}
            current["open"] = {"id": pos["id"], "symbol": pos["symbol"], "timeframe": i.get("timeframe"), "side": pos["side"],
                               "entry": pos["entry"], "stop": pos["stop"], "stop0": pos.get("stop0"),
                               "targets": pos.get("targets"), "tp_hit": pos["tp_hit"], "leverage": pos.get("lev"),
                               "qty": pos["qty"], "qty_open": pos["qty_open"], "margin": pos.get("margin"),
                               "coll": pos.get("coll"), "liq": pos.get("liq"), "realized": pos.get("realized"),
                               "opened_at": pos["opened_at"], "signal_id": i.get("signal_id"),
                               "confidence": i.get("confidence"), "horizon_bars": i.get("horizon_bars"),
                               "run_target": i.get("run_target"), "balance_before": i.get("balance_before")}
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
        pts = [[r["started_at"], START_BALANCE]] + [[t["closed_at"], round(t["balance_after"], 4)]
                                                   for t in by_run.get(int(r["run"]), [])]
        if len(pts) > CURVE_POINTS:
            step = len(pts) / CURVE_POINTS
            pts = [pts[int(i * step)] for i in range(CURVE_POINTS - 1)] + [pts[-1]]
        curves[str(r["run"])] = pts
    return {**base, "current": current, "score": score,
            "runs": [{k: r.get(k) for k in ("run", "started_at", "ended_at", "result", "reason", "start_balance",
                                              "end_balance", "peak", "trades", "wins", "best_trade")}
                     for r in runs[:VIEW_RUNS]],
            "trades": [_trade_row(t) for t in all_trades[:VIEW_TRADES]], "curves": curves,
            "label": "Demo · virtual money · not financial advice"}


def core(v: dict[str, Any]) -> Any:
    """What goes out at once when it changes: a trade opened / filled / hit a target / closed, or a run ended."""
    c = v.get("current") or {}
    o = c.get("open") or {}
    p = c.get("pending") or {}
    return [c.get("run"), c.get("trades"), (v.get("score") or {}).get("trades"), o.get("id"), o.get("tp_hit"),
            o.get("stop"), p.get("id")]
