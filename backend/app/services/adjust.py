"""Admin adjustment of an open call's stop-loss / take-profit 1 (v2.7). Public and forward-only.

The admin queues a website job `adjust_signal` {signal_id, stop?, tp1?, note}. The engine checks that the job's creator
is an admin (the job's `by` email against ADMIN_EMAILS; never the params), validates the new levels against the latest
price it has, and then:
  * stores each change for good in `signal_adjustments` (+ a `decisions` row, rule 'admin_adjust');
  * the record follows the ORIGINAL levels for candles opened before the change and the new level from the first 15m
    candle opening at/after it (engine/manage.follow `adjust`); the signal row keeps its published levels;
  * the demo bots holding that call's position apply the same change forward-only (services/bots.py);
  * every member's device gets a notification; cards and rows show "Updated" with the history.
Members' practice accounts (auto-trade) are not changed: see `apply` (their positions are not linked to a call).
"""
from __future__ import annotations

import math
from typing import Any

from ..db import new_id, now_ms
from ..pricefmt import fmt_price
from . import tracking

FIELDS = ("stop", "tp1")
LABEL = {"stop": "stop-loss", "tp1": "take-profit 1"}
MAX_DIST = 0.5            # new levels within +-50% of the entry


class AdjustError(ValueError):
    """A plain-language reason the change was refused (the job fails with it)."""


def latest_price(rt: Any, symbol: str) -> float | None:
    """Live price, else the newest 15m close the engine has (also the forming candle)."""
    try:
        px = rt.live_price(symbol)
    except Exception:
        px = None
    if px:
        return float(px)
    for kw in ({"include_forming": True}, {}):
        try:
            df = rt.candles(symbol, tracking.PATH_TF, **kw)
        except TypeError:
            continue
        except Exception:
            return None
        if df is not None and len(df):
            return float(df["close"].iloc[-1])
    return None


def _num(v: Any, name: str) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise AdjustError(f"the new {LABEL[name]} is not a number")
    if not math.isfinite(x) or x <= 0:
        raise AdjustError(f"the new {LABEL[name]} must be a positive price")
    return x


def validate(sig: dict[str, Any] | None, cur: dict[str, float], price: float | None, stop: float | None,
             tp1: float | None, note: str) -> list[tuple[str, float, float]]:
    """Pure: the changes [(field, old, new)] or AdjustError with the reason. `cur` = levels now in force."""
    if not sig:
        raise AdjustError("this signal was not found")
    if sig.get("status") != "OPEN" or not sig.get("side"):
        raise AdjustError(f"only an open or pending signal can be changed (this one is {str(sig.get('status')).lower()})")
    if not (3 <= len(note) <= 200):
        raise AdjustError("a note of 3 to 200 characters is required (members see it)")
    if price is None or price <= 0:
        raise AdjustError("the engine has no current price for this coin; try again in a few minutes")
    side, entry = int(sig["side"]), float(sig["entry"])
    pending = sig.get("fill_status") == "PENDING"
    long = side > 0
    word = "long" if long else "short"
    ch: list[tuple[str, float, float]] = []
    if stop is not None and abs(stop - float(cur["stop"])) > 1e-12:
        ch.append(("stop", float(cur["stop"]), stop))
    if tp1 is not None and abs(tp1 - float(cur["tp1"])) > 1e-12:
        if sig.get("tp1_hit"):
            raise AdjustError("take-profit 1 was already hit, so it can no longer be changed")
        ch.append(("tp1", float(cur["tp1"]), tp1))
    if not ch:
        raise AdjustError("nothing to change: the new values equal the current ones")
    for f, _, v in ch:
        if abs(v / entry - 1) > MAX_DIST:
            raise AdjustError(f"the new {LABEL[f]} is more than 50% away from the entry ({fmt_price(entry)})")
    new_stop = next((v for f, _, v in ch if f == "stop"), float(cur["stop"]))
    new_tp1 = next((v for f, _, v in ch if f == "tp1"), float(cur["tp1"]))
    p = fmt_price(price)
    if any(f == "stop" for f, _, _ in ch):
        if long and new_stop >= price:
            raise AdjustError(f"for a long, the stop-loss must be below the current price ({p})")
        if not long and new_stop <= price:
            raise AdjustError(f"for a short, the stop-loss must be above the current price ({p})")
        if pending and side * (entry - new_stop) <= 0:
            raise AdjustError(f"the entry ({fmt_price(entry)}) has not filled yet: the stop-loss must stay on the "
                              f"{'lower' if long else 'upper'} side of it")
    if any(f == "tp1" for f, _, _ in ch):
        if long and new_tp1 <= price:
            raise AdjustError(f"for a long, take-profit 1 must be above the current price ({p})")
        if not long and new_tp1 >= price:
            raise AdjustError(f"for a short, take-profit 1 must be below the current price ({p})")
    if not sig.get("tp1_hit") and side * (new_tp1 - entry) <= 0:
        raise AdjustError(f"take-profit 1 must stay on the profit side of the entry ({fmt_price(entry)}) for a {word}")
    if side * (new_tp1 - new_stop) <= 0:
        raise AdjustError("the stop-loss must be on the other side of take-profit 1")
    return ch


def message(sig: dict[str, Any], ch: list[tuple[str, float, float]], note: str) -> dict[str, str]:
    """The broadcast notification (every member's devices)."""
    coin = str(sig["symbol"]).split("/")[0]
    coin = "GOLD" if coin == "PAXG" else coin
    head = f"{coin} {str(sig['timeframe']).upper()} {'long' if int(sig['side']) > 0 else 'short'} update"
    parts = [f"{LABEL[f][0].upper() + LABEL[f][1:]} moved {fmt_price(o)} → {fmt_price(n)}" for f, o, n in ch]
    return {"title": head, "body": f"{'; '.join(parts)}. Note: {note}"[:400],
            "url": f"/signals?symbol={sig['symbol']}&timeframe={sig['timeframe']}&market=futures",
            "tag": f"adjust-{sig['id']}", "broadcast": "1"}


def apply(rt: Any, params: dict[str, Any], by: str, sink: Any = None, now: int | None = None) -> dict[str, Any]:
    """Validate and store the change (the caller has checked that `by` is an admin). Raises AdjustError."""
    db = rt.db
    sid = str(params.get("signal_id") or "").strip()
    note = " ".join(str(params.get("note") or "").split())
    stop, tp1 = _num(params.get("stop"), "stop"), _num(params.get("tp1"), "tp1")
    sig = db.one("SELECT * FROM signals WHERE id = ?", (sid,)) if sid else None
    adj = tracking.adjustments_of(db, sid) if sig else []
    if any(a["field"] == "close" for a in adj):
        raise AdjustError("this signal is being closed by the admin, so its levels can no longer change")
    cur = tracking.current_levels(sig, adj) if sig else {}
    price = latest_price(rt, sig["symbol"]) if sig else None
    ch = validate(sig, cur, price, stop, tp1, note)
    at = int(now or now_ms())
    for f, old, new in ch:
        db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note, by, price_at_change) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id(), sid, at, f, old, new, note, by, price))
        tracking.log_decision(db, "admin_adjust", sig["symbol"], sig["timeframe"], sid,
                              {"field": f, "old": old, "new": new, "note": note, "by": by, "price_at_change": price,
                               "fill_status": sig.get("fill_status"), "tp1_hit": bool(sig.get("tp1_hit"))}, ts=at)
    bots = 0
    try:
        from .bots import BotEngine
        bots = BotEngine(rt).apply_adjustment(sig, [(f, n) for f, _, n in ch], at)
    except Exception as exc:                     # the record change stands; bots are best effort
        bots = f"not applied: {type(exc).__name__}"
    out: dict[str, Any] = {"ok": True, "signal_id": sid, "at": at, "price_at_change": price, "bots_updated": bots,
                           "changes": [{"field": f, "old": o, "new": n} for f, o, n in ch],
                           "message": "Saved. The change applies from the next 15-minute candle and members are notified."}
    if sink is not None:
        out["push"] = sink.send_push([message(sig, ch, note)])
    adjusted = getattr(rt, "adjusted_ids", None)
    if isinstance(adjusted, set):
        adjusted.add(sid)
    return out


# ---- v2.8 admin close: close an open call now, at the market price (public, the result is what the price gives) ----

def close_validate(sig: dict[str, Any] | None, price: float | None, note: str, already: bool,
                   still_open: bool) -> None:
    """Pure: AdjustError with the reason, else None."""
    if not sig:
        raise AdjustError("this signal was not found")
    if sig.get("status") != "OPEN" or not sig.get("side"):
        raise AdjustError(f"only an open signal can be closed (this one is {str(sig.get('status')).lower()})")
    if sig.get("fill_status") == "PENDING":
        raise AdjustError("the entry has not filled yet, so there is no trade to close")
    if already:
        raise AdjustError("this signal is already being closed")
    if not (3 <= len(note) <= 200):
        raise AdjustError("a note of 3 to 200 characters is required (members see it)")
    if price is None or price <= 0:
        raise AdjustError("the engine has no current price for this coin; try again in a few minutes")
    if not still_open:
        raise AdjustError("the price already reached a stop or target in the last minutes; the record closes it on "
                          "its own at the next update")


def close_result(sig: dict[str, Any], adj: list[dict[str, Any]], p15: Any, price: float, at: int) -> dict[str, Any]:
    """What the record will show: the same follow as tracking, with the close at `price` (forming candle included)."""
    res = tracking.evaluate_signal(sig, p15, None, at, adjust=list(adj) + [{"at": at, "field": "close", "old": price,
                                                                          "new": price, "note": ""}])
    if res.get("status") == "OPEN" and p15 is not None and len(p15):
        # the path ends inside the current candle: the close is final once that candle's data is in
        res = {**res, "status": "CLOSING"}
    return res


def close_message(sig: dict[str, Any], price: float, ret: float | None, roi: float | None, note: str) -> dict[str, str]:
    coin = str(sig["symbol"]).split("/")[0]
    coin = "GOLD" if coin == "PAXG" else coin
    head = f"{coin} {str(sig['timeframe']).upper()} {'long' if int(sig['side']) > 0 else 'short'} closed"
    if ret is None:
        res = ""
    else:
        res = f" Result {'+' if ret > 0 else ''}{ret:.2f}%" + (f" ({'+' if roi > 0 else ''}{roi:.2f}% ROI)" if roi is not None else "") + "."
    return {"title": head, "body": f"Closed by the admin at {fmt_price(price)}.{res} Note: {note}"[:400],
            "url": f"/signals?symbol={sig['symbol']}&timeframe={sig['timeframe']}&market=futures",
            "tag": f"close-{sig['id']}", "broadcast": "1"}


def close(rt: Any, params: dict[str, Any], by: str, sink: Any = None, now: int | None = None) -> dict[str, Any]:
    """Close an open call at the engine's current market price (the caller has checked that `by` is an admin).
    The record follows every candle that closed before now with the normal rules, then closes the rest at this
    price; win or loss is what that price gives. Members are notified; the bots holding the call close too."""
    from ..engine import futures as F
    db = rt.db
    sid = str(params.get("signal_id") or "").strip()
    note = " ".join(str(params.get("note") or "").split())
    sig = db.one("SELECT * FROM signals WHERE id = ?", (sid,)) if sid else None
    adj = tracking.adjustments_of(db, sid) if sig else []
    price = latest_price(rt, sig["symbol"]) if sig else None
    at = int(now or now_ms())
    p15 = None
    still_open = True
    if sig and price:
        try:
            p15 = rt.candles(sig["symbol"], tracking.PATH_TF, include_forming=True)
        except TypeError:
            p15 = rt.candles(sig["symbol"], tracking.PATH_TF)
        except Exception:
            p15 = None
        # the forming candle counts here: a level it already touched before the click wins over the close
        chk = tracking.evaluate_signal(sig, p15, None, at, adjust=adj)
        still_open = chk.get("status", "OPEN") == "OPEN"
    close_validate(sig, price, note, any(a["field"] == "close" for a in adj), still_open)
    res = close_result(sig, adj, p15, price, at)
    ret = res.get("return_pct")
    lev = F.signal_leverage(sig.get("entry"), sig.get("stop"))
    roi = F.roi_on_margin(ret, lev)
    db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note, by, price_at_change) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id(), sid, at, "close", price, price, note, by, price))
    tracking.log_decision(db, "admin_close", sig["symbol"], sig["timeframe"], sid,
                          {"price": price, "note": note, "by": by, "return_pct": ret, "tp1_hit": bool(sig.get("tp1_hit"))}, ts=at)
    bots = 0
    try:
        from .bots import BotEngine
        bots = BotEngine(rt).apply_close(sig, price, at)
    except Exception as exc:                     # the record close stands; bots are best effort
        bots = f"not applied: {type(exc).__name__}"
    word = "" if ret is None else (" as a win" if ret > 0 else " as a loss")
    out: dict[str, Any] = {"ok": True, "signal_id": sid, "at": at, "price": price, "return_pct": ret, "roi_pct": roi,
                           "bots_closed": bots,
                           "message": f"Closed at {fmt_price(price)}{word}. The record shows it within a few minutes and members are notified."}
    if sink is not None:
        out["push"] = sink.send_push([close_message(sig, price, ret, roi, note)])
    adjusted = getattr(rt, "adjusted_ids", None)
    if isinstance(adjusted, set):
        adjusted.add(sid)
    return out
