"""Auto-trade signals into members' paper (practice) futures accounts.

A member switches it on in the trading screen (Firestore auto_paper/{uid}: margin per trade, leverage, timeframes,
grades, take-profit level, max open positions, coins). Each engine run, every NEW futures trade signal that matches
is placed in their account, also while the app is closed:
  * price inside the signal's entry zone -> market order now (live price + spread/slippage, 0.05% fee);
  * otherwise -> limit order at the signal's ideal entry (margin reserved; it fills when the price gets there).
Stop-loss and take-profit come from the signal; the app's normal paper engine then handles them, also while closed.
Virtual money only: nothing is ever sent to an exchange. The engine's own log is in auto_paper_state/{uid}.

The account document layout is identical to the one the website writes (frontend/src/lib/paperFutures.ts).
"""
from __future__ import annotations

import logging
import random
import string
from typing import Any

from ..data.base import tf_ms
from ..db import now_ms
from ..engine import futures as F
from . import membership

log = logging.getLogger(__name__)
FEE = 0.0005
MAKER = 0.0002
MMR = 0.005
ADVERSE = (2 + 0.5) / 1e4
MAX_LEV = 50
TAKES = {"tp1": 0, "tp2": 1, "tp3": 2}
# v2.4 testing mode: each member's auto-trade holds at most 3 trades at a time and opens at most 6 new ones a day
MAX_OPEN_CAP = 3
MAX_NEW_PER_DAY = 6
DEFAULTS = {"enabled": False, "margin": 100.0, "leverage": "signal", "timeframes": ["1h", "4h"], "grades": "AB",
            "take": "tp2", "max_open": 3, "coins": "all", "notify": True, "scale": True, "max_same_side": 3}


def _rid(n: int = 10) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def liq_price(entry: float, side: int, lev: float) -> float:
    return max(0.0, entry * (1 - 1 / max(1, lev) + MMR)) if side > 0 else entry * (1 + 1 / max(1, lev) - MMR)


def new_account(now: int, balance: float = 10_000.0) -> dict[str, Any]:
    return {"id": _rid(), "starting_balance": balance, "wallet": balance, "created_at": now, "positions": {},
            "position_mode": "oneway", "totals": {"realized": 0, "fees": 0, "funding": 0, "count": 0, "wins": 0, "liquidations": 0}}


def settings_of(raw: dict[str, Any] | None) -> dict[str, Any]:
    s = {**DEFAULTS, **{k: v for k, v in (raw or {}).items() if k in DEFAULTS}}
    try:
        s["margin"] = max(1.0, min(1_000_000.0, float(s["margin"])))
    except (TypeError, ValueError):
        s["margin"] = DEFAULTS["margin"]
    if s["leverage"] != "signal":
        try:
            s["leverage"] = int(max(1, min(MAX_LEV, float(s["leverage"]))))
        except (TypeError, ValueError):
            s["leverage"] = "signal"
    s["timeframes"] = [t for t in (s["timeframes"] or []) if t in ("15m", "1h", "4h", "12h", "1d", "3d")] or ["1h", "4h"]
    s["grades"] = "A" if str(s["grades"]).upper() == "A" else "AB"
    s["take"] = s["take"] if s["take"] in TAKES else "tp2"
    s["max_open"] = int(max(1, min(MAX_OPEN_CAP, int(s.get("max_open") or MAX_OPEN_CAP))))
    s["max_same_side"] = int(max(1, min(50, int(s.get("max_same_side") or 3))))
    s["scale"] = bool(s.get("scale", True))
    return s


def candidates(rows_by_tf: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Valid futures trade calls from this run's futures rows."""
    out = []
    for tf, rows in rows_by_tf.items():
        for r in rows:
            p = r.get("plan") or {}
            if r.get("side") in (1, -1) and p.get("valid") and p.get("stop") and p.get("targets") and r.get("price"):
                out.append({**r, "timeframe": tf})
    return out


def origin_of(sig: dict[str, Any]) -> dict[str, Any]:
    """Which call an auto-trade came from (shown in the position's details on the Trade page)."""
    call = sig.get("call") or {}
    return {"id": call.get("id"), "symbol": sig["symbol"], "timeframe": sig["timeframe"], "grade": sig.get("grade"),
            "side": "LONG" if int(sig["side"]) > 0 else "SHORT", "at": call.get("created_at")}


def place(acc: dict[str, Any] | None, sig: dict[str, Any], s: dict[str, Any], now: int) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Pure function: the new account document (or None to leave it) and a result record."""
    acc = acc or new_account(now)
    sym, side, p = sig["symbol"], int(sig["side"]), sig["plan"]
    res = {"ts": now, "symbol": sym, "timeframe": sig["timeframe"], "side": "LONG" if side > 0 else "SHORT", "grade": sig.get("grade")}
    positions, orders = dict(acc.get("positions") or {}), dict(acc.get("orders") or {})
    reversed_ = None
    # the call flipped on a coin the auto-trader holds: close that auto trade at market (profit or loss), drop an
    # auto order the other way, then take the new direction. Manual trades are never touched; no hedging.
    for key, pos in list(positions.items()):
        if pos.get("symbol") == sym and pos.get("auto") and int(pos["side"]) != side:
            price_now = float(sig["price"])
            fill = price_now * (1 - pos["side"] * ADVERSE)
            fee = pos["qty"] * fill * FEE
            gross = pos["side"] * pos["qty"] * (fill - pos["entry"])
            back = max(0.0, pos["margin"] + gross) - fee
            pnl = back - pos["margin"] - (pos.get("fees") or 0)
            del positions[key]
            t = acc.get("totals") or {}
            acc = {**acc, "wallet": acc["wallet"] + back, "positions": positions,
                   "totals": {**t, "realized": (t.get("realized") or 0) + pnl, "fees": (t.get("fees") or 0) + fee,
                              "count": (t.get("count") or 0) + 1, "wins": (t.get("wins") or 0) + (1 if pnl > 0 else 0)}}
            reversed_ = {"type": "CLOSE", "reason": "signal reversed", "symbol": sym, "side": pos["side"], "qty": pos["qty"],
                         "price": fill, "entry": pos["entry"], "leverage": pos["leverage"], "margin": pos["margin"], "fee": fee,
                         "realized_pnl": pnl, "roe_pct": pnl / pos["margin"] * 100 if pos["margin"] else None,
                         "funding": pos.get("funding") or 0, "opened_at": pos.get("opened_at"), "auto": True}
    for oid, od in list(orders.items()):
        if od.get("symbol") == sym and od.get("auto") and int(od["side"]) != side:
            del orders[oid]
            acc = {**acc, "wallet": acc["wallet"] + od.get("reserve", 0), "orders": orders}
    if reversed_:
        res["reversed"] = reversed_
    if any(x.get("symbol") == sym for x in list(positions.values()) + list(orders.values())):
        return (acc if reversed_ else None), {**res, "action": "skipped", "reason": "a position or order on this coin is already open"}
    same = sum(1 for x in list(positions.values()) + list(orders.values()) if int(x.get("side", 0)) == side)
    if same >= s["max_same_side"]:
        return (acc if reversed_ else None), {**res, "action": "skipped",
                                               "reason": f"already {same} {'long' if side > 0 else 'short'} trades open (same-direction limit)"}
    if len(positions) + len(orders) >= s["max_open"]:
        return (acc if reversed_ else None), {**res, "action": "skipped", "reason": f"the limit of {s['max_open']} open trades is reached"}
    stop = float(p["stop"])
    targets = p["targets"]
    take = float(targets[min(TAKES[s["take"]], len(targets) - 1)]["price"])
    price, ideal = float(sig["price"]), float(p.get("entry") or sig["price"])
    zone = p.get("entry_zone") or [ideal, ideal]
    lo, hi = min(zone), max(zone)
    market = lo <= price <= hi
    entry = price * (1 + side * ADVERSE) if market else ideal
    if side * (entry - stop) <= 0 or side * (take - entry) <= 0:
        return (acc if reversed_ else None), {**res, "action": "skipped", "reason": "price already moved past the stop or target"}
    safe = F.safe_leverage(entry, stop, MAX_LEV, MMR, buffer=1.1)
    lev = int(p.get("suggested_leverage") or safe) if s["leverage"] == "signal" else int(s["leverage"])
    lev = max(1, min(lev, safe, MAX_LEV))           # never so high that liquidation comes before the stop
    from .bots import size_multiplier
    mult = size_multiplier(sig.get("grade"), sig.get("filter_score"), sig.get("filter_threshold")) if s["scale"] else 1.0
    margin = round(float(s["margin"]) * mult, 2)
    if market:
        qty = margin * lev / entry
        fee = qty * entry * FEE
        if margin + fee > acc["wallet"] + 1e-9:
            return (acc if reversed_ else None), {**res, "action": "skipped", "reason": f"not enough virtual balance (${acc['wallet']:.2f})"}
        key = sym.replace("/", "")
        positions[key] = {"key": key, "symbol": sym, "side": side, "qty": qty, "entry": entry, "margin": margin, "leverage": lev,
                          "liq": liq_price(entry, side, lev), "stop": stop, "take": take, "opened_at": now, "checked_at": now,
                          "funded_until": now, "funding": 0, "fees": fee, "auto": True, "signal": origin_of(sig)}
        t = acc.get("totals") or {}
        new = {**acc, "wallet": acc["wallet"] - margin - fee, "positions": positions, "totals": {**t, "fees": (t.get("fees") or 0) + fee}}
        return new, {**res, "action": "opened", "price": entry, "qty": qty, "margin": margin, "leverage": lev, "fee": fee,
                     "stop": stop, "take": take, "liq": positions[key]["liq"], "account_id": acc["id"]}
    reserve = margin * (1 + lev * MAKER)
    if reserve > acc["wallet"] + 1e-9:
        return (acc if reversed_ else None), {**res, "action": "skipped", "reason": f"not enough virtual balance (${acc['wallet']:.2f})"}
    oid = _rid(8)
    orders[oid] = {"id": oid, "symbol": sym, "side": side, "price": entry, "margin": margin, "leverage": lev, "stop": stop,
                   "take": take, "reserve": reserve, "created_at": now, "checked_at": now, "auto": True, "signal": origin_of(sig),
                   "expires_at": now + 6 * tf_ms(sig["timeframe"])}
    return {**acc, "wallet": acc["wallet"] - reserve, "orders": orders}, {
        **res, "action": "limit order", "price": entry, "margin": margin, "leverage": lev, "stop": stop, "take": take}


def run(sink, rows_by_tf: dict[str, list[dict[str, Any]]], now: int | None = None) -> dict[str, Any]:
    now = now or now_ms()
    sigs = candidates(rows_by_tf)
    users = dict(sink.list("users"))
    out = {"members": 0, "opened": 0, "orders": 0, "skipped": 0, "push": []}
    for uid, raw in sink.list("auto_paper"):
        s = settings_of(raw)
        if not s["enabled"] or not membership.is_active(users.get(uid), now):
            continue
        out["members"] += 1
        state = sink.get(f"auto_paper_state/{uid}") or {}
        done: dict[str, int] = dict(state.get("done") or {})
        mine = set((sink.get(f"user_coins/{uid}") or {}).get("symbols") or []) if s["coins"] == "mine" else None
        entries = []
        for sig in sigs:
            if sig["timeframe"] not in s["timeframes"] or (s["grades"] == "A" and sig.get("grade") != "A"):
                continue
            if mine is not None and sig["symbol"] not in mine:
                continue
            key = f"{sig['symbol']}|{sig['timeframe']}|{sig['side']}"
            if sum(1 for v in done.values() if now - int(v) < 86_400_000) >= MAX_NEW_PER_DAY:
                break                                   # daily limit of new auto-trades reached
            # one entry per signal: the same call is not re-entered on later candles for 6 bars
            if now - int(done.get(key, 0)) < 6 * tf_ms(sig["timeframe"]):
                continue
            result = sink.transact(f"paper/{uid}_futures", lambda acc, sig=sig: place(acc, sig, s, now))
            done[key] = now
            if result.get("reversed"):
                acc_id = (sink.get(f"paper/{uid}_futures") or {}).get("id")
                sink.add("paper_futures_trades", {**result["reversed"], "account_id": acc_id, "uid": uid, "created_at": now,
                                                  "mode": "PAPER FUTURES"})
                out["reversed"] = out.get("reversed", 0) + 1
            entries.append(result)
            if result["action"] == "opened":
                out["opened"] += 1
                sink.add("paper_futures_trades", {"account_id": result["account_id"], "type": "OPEN", "symbol": sig["symbol"],
                                                  "side": sig["side"], "qty": result["qty"], "price": result["price"],
                                                  "mark_price": sig["price"], "leverage": result["leverage"], "margin": result["margin"],
                                                  "fee": result["fee"], "liquidation_price": result["liq"], "stop": result["stop"],
                                                  "take": result["take"], "hedge": False, "auto": True, "uid": uid,
                                                  "created_at": now, "mode": "PAPER FUTURES"})
            elif result["action"] == "limit order":
                out["orders"] += 1
            else:
                out["skipped"] += 1
            if s["notify"] and result["action"] != "skipped":
                out["push"].append({"uid": uid, "title": f"Auto-trade · {sig['symbol']} {result['side']}",
                                    "body": (f"{'Opened' if result['action'] == 'opened' else 'Limit order at'} "
                                             f"{result['price']:.6g} · margin ${result['margin']:.0f} at {result['leverage']}x · "
                                             f"stop {result['stop']:.6g} · target {result['take']:.6g} (practice account)"),
                                    "url": "/paper?market=futures", "tag": f"auto-{uid}-{sig['symbol']}"})
        if entries or not state:
            done = {k: v for k, v in done.items() if now - v < 14 * 86_400_000}
            sink.set(f"auto_paper_state/{uid}", {"done": done, "updated_at": now,
                                                  "log": (entries + list(state.get("log") or []))[:60]})
    return out
