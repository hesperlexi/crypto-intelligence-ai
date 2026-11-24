"""Undo the V3.0 reset for the Hesper Challenge (owner, 24 Nov 2026: "restore the trades of Hesper Challenge main and
Last Stand"). The reset (app/fresh_restart_v3.py) had archived `hesper_runs`, `hesper_trades`, `laststand_runs`,
`laststand_trades` into `archive_v3_<table>` and saved the old settings in `archive_v3_settings`.

In one transaction: whatever the challenge tables hold now (the run that started after the reset) is moved to
`archive_v3b_<table>` (kept, never deleted), the archived history is copied back, and the old state settings
(`hesper_state`, `hesper_since`, `hesper_v1`, `laststand_state`) are restored - the open trades come back and are
followed again from their last check over every 15m candle since (bots._manage_decision). The post-reset values of
those settings are kept in `restore_hesper_prev`. Runs once (flag `restore_hesper_v3`)."""
from __future__ import annotations

from typing import Any

FLAG = "restore_hesper_v3"
TABLES = ("hesper_runs", "hesper_trades", "laststand_runs", "laststand_trades")
KEYS = ("hesper_state", "hesper_since", "hesper_v1", "laststand_state")


def _cols(raw, t: str) -> list[str]:
    return [r[1] for r in raw.execute(f'PRAGMA table_info("{t}")').fetchall()]


def run(rt: Any, now: int) -> dict[str, Any]:
    db = rt.db
    saved = (db.get_setting("archive_v3_settings", None) or {}).get("values") or {}
    raw = db._conn
    out: dict[str, Any] = {"restored": {}, "moved_aside": {}}
    lock = getattr(db, "_lock", None)
    if lock is not None:
        lock.acquire()
    try:
        raw.execute("BEGIN IMMEDIATE")
        have = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for t in TABLES:
            a = f"archive_v3_{t}"
            if t not in have or a not in have:
                continue
            cols = _cols(raw, t)
            n_now = raw.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            if n_now:
                b = f"archive_v3b_{t}"
                if b in have:
                    raw.execute(f'INSERT INTO "{b}" SELECT *, ? FROM "{t}"', (now,))
                else:
                    raw.execute(f'CREATE TABLE "{b}" AS SELECT *, ? AS archived_at FROM "{t}"', (now,))
                raw.execute(f'DELETE FROM "{t}"')
                out["moved_aside"][t] = n_now
            cl = ", ".join(f'"{c}"' for c in cols)
            raw.execute(f'INSERT INTO "{t}" ({cl}) SELECT {cl} FROM "{a}"')
            got = raw.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            want = raw.execute(f'SELECT COUNT(*) FROM "{a}"').fetchone()[0]
            if got != want:
                raise RuntimeError(f"restore check failed for {t}: {got} vs {want}")
            out["restored"][t] = got
        raw.execute("COMMIT")
    except Exception:
        raw.execute("ROLLBACK")
        raise
    finally:
        if lock is not None:
            lock.release()
    db.set_setting("restore_hesper_prev", {"at": now, "values": {k: db.get_setting(k, None) for k in KEYS}})
    for k in KEYS:
        if k in saved and saved[k] is not None:
            db.set_setting(k, saved[k])
            out.setdefault("settings", []).append(k)
    db.set_setting(FLAG, now)
    return out


def maybe_run(rt: Any, now: int) -> dict[str, Any] | None:
    db = rt.db
    if db.get_setting(FLAG, None):
        return None
    if not db.get_setting("fresh_restart_v3", None) or not db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='archive_v3_hesper_runs'"):
        db.set_setting(FLAG, now)                       # nothing was archived (fresh database): nothing to restore
        return {"skipped": "no archive"}
    return run(rt, now)
