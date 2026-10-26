"""Safety switch per coin and timeframe (v2.2).

When the live record of one coin on one timeframe turns bad, its new signals pause instead of dragging the whole
record down:
  * pause  - of its last 25 closed signals (at least 20), the average result is below zero AND fewer than 40 %
             reached take-profit 1;
  * while paused, the trades it would have taken are tracked as hidden practice trades (shadow_signals);
  * resume - automatically, once at least 8 of those practice trades have closed with a positive average and
             at least half reaching take-profit 1. After a resume only signals issued after it are judged.
Everything is per (symbol, timeframe); the state lives in the engine's settings.
"""
from __future__ import annotations

from typing import Any

from ..db import Database, now_ms

WINDOW = 25
MIN_N = 20
BAD_HIT = 0.40
RECOVER_N = 8
RECOVER_HIT = 0.50
CLOSED = ("TP1", "TP2", "TP3", "STOPPED", "EXPIRED")


def _key(symbol: str, timeframe: str) -> str:
    return f"safety:{symbol}:{timeframe}"


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if not n:
        return {"n": 0, "avg_return_pct": None, "tp1_rate": None}
    return {"n": n, "avg_return_pct": sum(float(r["return_pct"]) for r in rows) / n,
            "tp1_rate": sum(1 for r in rows if r["status"] in ("TP1", "TP2", "TP3")) / n}


def _closed(db: Database, table: str, symbol: str, timeframe: str, since: int) -> list[dict[str, Any]]:
    marks = ",".join("?" * len(CLOSED))
    return db.query(f"SELECT status, return_pct FROM {table} WHERE symbol = ? AND timeframe = ? AND side != 0 "
                    f"AND status IN ({marks}) AND return_pct IS NOT NULL AND created_at >= ? "
                    f"ORDER BY created_at DESC LIMIT ?", (symbol, timeframe, *CLOSED, since, WINDOW))


def check(db: Database, symbol: str, timeframe: str, since: int = 0, now: int | None = None) -> dict[str, Any]:
    """{'paused': bool, ...}. Moves the switch when its rules say so."""
    now = now or now_ms()
    st = db.get_setting(_key(symbol, timeframe), {}) or {}
    if st.get("paused_at"):
        s = _stats(_closed(db, "shadow_signals", symbol, timeframe, int(st["paused_at"])))
        if s["n"] >= RECOVER_N and s["avg_return_pct"] > 0 and s["tp1_rate"] >= RECOVER_HIT:
            st = {"resumed_at": now, "last_pause": st.get("paused_at"), "recovered_with": s}
            db.set_setting(_key(symbol, timeframe), st)
            return {"paused": False, "resumed_at": now, "practice": s}
        return {"paused": True, "paused_at": st["paused_at"], "trigger": st.get("trigger"), "practice": s,
                "reason": (f"paused by the safety switch: its last {st.get('trigger', {}).get('n', WINDOW)} signals "
                           f"lost on average; it resumes by itself when its practice trades recover "
                           f"({s['n']}/{RECOVER_N} closed so far)")}
    start = max(int(since or 0), int(st.get("resumed_at") or 0))
    s = _stats(_closed(db, "signals", symbol, timeframe, start))
    if s["n"] >= MIN_N and s["avg_return_pct"] < 0 and s["tp1_rate"] < BAD_HIT:
        db.set_setting(_key(symbol, timeframe), {"paused_at": now, "trigger": s, "resumed_at": st.get("resumed_at")})
        return {"paused": True, "paused_at": now, "trigger": s,
                "reason": f"paused by the safety switch: its last {s['n']} signals lost on average "
                          f"({s['tp1_rate']:.0%} reached take-profit 1)"}
    return {"paused": False, "record": s}


def overview(db: Database) -> list[dict[str, Any]]:
    """Every coin/timeframe the switch has paused right now (for the website)."""
    rows = db.query("SELECT key, value FROM app_settings WHERE key LIKE 'safety:%'")
    out = []
    from ..db import loads

    for r in rows:
        v = loads(r["value"], {}) or {}
        if v.get("paused_at"):
            _, sym, tf = r["key"].split(":", 2)
            out.append({"symbol": sym, "timeframe": tf, "paused_at": v["paused_at"], "trigger": v.get("trigger")})
    return sorted(out, key=lambda x: -x["paused_at"])
