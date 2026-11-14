"""v2.22 admin "Hold" (owner, 14 Nov 2026): the admin may withdraw a freshly published call within HOLD_WINDOW_MIN.

The call leaves the public record (moved from `signals` to `held_signals`, never deleted), the demo bots / Hesper close
or cancel what they took from it at the engine's price, members are told it was withdrawn, and the same coin /
timeframe gets no new call while the held one would still be running. `held_signals` is followed with the record's own
rules, so `scoreboard()` shows what the withdrawn calls would have made - the evidence of whether holding helps.
The public record shows how many calls were withdrawn (`withdrawn_count`), so nothing disappears silently."""
from __future__ import annotations

import os
from typing import Any

from ..db import dumps, loads, now_ms
from ..pricefmt import fmt_price
from . import tracking

HOLD_WINDOW_MIN = int(os.environ.get("HOLD_WINDOW_MIN", "15"))
COLS = ("id", "created_at", "symbol", "timeframe", "bar_ts", "signal", "decision", "score", "confidence", "regime", "price",
        "side", "entry", "stop", "tp1", "tp2", "tp3", "rr", "status", "tp1_hit", "tp2_hit", "tp3_hit", "stop_hit",
        "closed_at", "return_pct", "model_version_id", "payload", "fill_status", "filled_at", "peak_r", "peak_pct",
        "exit_reason", "managed", "atr", "app_version", "engine_version", "return_net_pct", "cost_pct", "funding_pct")


class HoldError(ValueError):
    pass


def hold_validate(sig: dict[str, Any] | None, now: int, note: str) -> None:
    if not sig:
        raise HoldError("this signal was not found (it may already be held)")
    if sig.get("status") != "OPEN" or not sig.get("side"):
        raise HoldError(f"only a running call can be held (this one is {str(sig.get('status')).lower()})")
    age = (now - int(sig["created_at"])) / 60_000
    if age > HOLD_WINDOW_MIN:
        raise HoldError(f"a call can be held only within {HOLD_WINDOW_MIN} minutes of publication (this one is "
                        f"{age:.0f} minutes old); use Close now instead")
    if not (3 <= len(note) <= 200):
        raise HoldError("a note of 3 to 200 characters is required (members see it)")


def held_open(db: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    try:
        return db.one("SELECT id, held_at FROM held_signals WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' "
                      "ORDER BY created_at DESC LIMIT 1", (symbol, timeframe))
    except Exception:
        return None


def hold(rt: Any, params: dict[str, Any], by: str, sink: Any = None, now: int | None = None) -> dict[str, Any]:
    db = rt.db
    at = int(now or now_ms())
    sid = str(params.get("signal_id") or "").strip()
    note = " ".join(str(params.get("note") or "").split())
    sig = db.one("SELECT * FROM signals WHERE id = ?", (sid,)) if sid else None
    hold_validate(sig, at, note)
    cols = [c for c in COLS if c in sig]
    db.execute(f"INSERT INTO held_signals ({', '.join(cols)}, held_at, held_by, hold_note) "
               f"VALUES ({', '.join('?' * len(cols))}, ?, ?, ?)", (*[sig[c] for c in cols], at, by, note))
    db.execute("DELETE FROM signal_adjustments WHERE signal_id = ?", (sid,))
    db.execute("DELETE FROM signals WHERE id = ?", (sid,))
    tracking.log_decision(db, "admin_hold", sig["symbol"], sig["timeframe"], sid, {"note": note, "by": by}, ts=at)
    from .adjust import latest_price, _hesper
    price = latest_price(rt, sig["symbol"])
    bots = 0
    if price:
        try:
            from .bots import BotEngine
            bots = BotEngine(rt).apply_close(sig, price, at)
        except Exception as exc:
            bots = f"not applied: {type(exc).__name__}"
        _hesper(rt, "apply_close", sig, price, at)
    out: dict[str, Any] = {"ok": True, "signal_id": sid, "held_at": at, "bots_changed": bots,
                           "message": "Held: the call is withdrawn from the record and members are told. It is still "
                                      "followed privately for your hold scoreboard."}
    if sink is not None:
        coin = "GOLD" if sig["symbol"].startswith("PAXG") else sig["symbol"].split("/")[0]
        out["push"] = sink.send_push([{
            "title": f"{coin} {str(sig['timeframe']).upper()} {'long' if int(sig['side']) > 0 else 'short'} withdrawn",
            "body": f"The admin withdrew this call{f' (price {fmt_price(price)})' if price else ''}: it is not counted. Note: {note}"[:400],
            "url": f"/signals?symbol={sig['symbol']}&timeframe={sig['timeframe']}&market=futures", "tag": f"hold-{sid}",
            "broadcast": "1"}])
    adjusted = getattr(rt, "adjusted_ids", None)
    if isinstance(adjusted, set):
        adjusted.add(sid)
    return out


def scoreboard(db: Any, limit: int = 30) -> dict[str, Any]:
    """What the held calls did / would have done (net, in R of their original risk)."""
    try:
        rows = db.query("SELECT * FROM held_signals ORDER BY held_at DESC")
    except Exception:
        return {"n": 0, "items": []}
    items, rs = [], []
    for r in rows:
        risk = abs(float(r["entry"]) - float(r["stop"])) / float(r["entry"]) * 100 if r.get("entry") and r.get("stop") else None
        net = tracking.net_pct(r) if r.get("status") in tracking.CLOSED_STATUSES and r.get("return_pct") is not None else None
        nr = net / risk if net is not None and risk else None
        if nr is not None:
            rs.append(nr)
        if len(items) < limit:
            items.append({"id": r["id"], "symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
                          "held_at": r.get("held_at"), "note": r.get("hold_note"), "status": r["status"],
                          "tp1_hit": r.get("tp1_hit"), "net_pct": net, "net_r": nr, "entry": r.get("entry"), "stop": r.get("stop")})
    n = len(rs)
    return {"n": len(rows), "closed": n, "open": sum(1 for r in rows if r["status"] == "OPEN"),
            "would_have_won": sum(1 for x in rs if x > 0), "would_have_lost": sum(1 for x in rs if x <= 0),
            "total_r": round(sum(rs), 2) if n else 0.0, "avg_r": round(sum(rs) / n, 3) if n else None,
            # positive total = the held calls would have made money: holding them cost that much
            "verdict": None if n < 5 else ("holding saved money" if sum(rs) < 0 else "holding cost money"),
            "window_min": HOLD_WINDOW_MIN, "items": items}


def withdrawn_count(db: Any, since: int) -> int:
    try:
        return int((db.one("SELECT COUNT(*) AS n FROM held_signals WHERE created_at >= ?", (int(since),)) or {}).get("n") or 0)
    except Exception:
        return 0
