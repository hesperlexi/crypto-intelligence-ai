"""V3.0 testing-results reset (owner, 24 Nov 2026, typed "RESET TESTING RESULTS"). ARCHIVE, not delete.

Every testing-result table is first COPIED into `archive_v3_<table>` (same columns + `archived_at`), the copy's row count
is checked against the original, and only then is the original emptied - all in one SQLite transaction, so either all of
it happens or none. The archive tables stay in the engine database (and its backups): research such as the turn-watch
re-test keeps its data, and the old history can be restored with one INSERT ... SELECT. Nothing reads them for Results.

Kept untouched: members' practice accounts, trades and auto-trade logs (owner), users, memberships, alerts, candles,
futures / order-flow data, models, predictions, news, settings, the leaderboard.
Restarted: the record (`record_since` = now, per-timeframe starts and exclusions cleared, one restart line on Results),
demo bot books (same line-up, fresh balance, reset token v3), Hesper (Run #1 at $100) and Last Stand (waits for the
admin), Trade Guardian history, safety-switch state. Audit: setting `reset_v3_audit`; old setting values in
`archive_v3_settings`. Runs once (flag `fresh_restart_v3`, in worker.MIGRATION_FLAGS)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

FLAG = "fresh_restart_v3"
TOKEN = "v3"
ARCHIVE_TABLES = ("signals", "shadow_signals", "scalp_signals", "signal_proofs", "signal_adjustments", "decisions",
                  "rejected_signals", "held_signals", "bot_trades", "bot_equity", "hesper_runs", "hesper_trades",
                  "laststand_runs", "laststand_trades", "guardian_recs")
CLEAR_TABLES = ("bots", "published", "edge_published")        # rebuilt by the engine
SETTING_KEYS = ("hesper_state", "hesper_since", "hesper_v1", "laststand_state", "record_restart", "record_excludes",
                "honest_record_since", "honest_record_prev", "scalp_backfill_state")
SETTING_PREFIXES = ("safety:",)
TELEGRAM_DRAFTS = "owner/telegram_drafts"
DUBAI = timezone(timedelta(hours=4))


def _tables(db) -> set[str]:
    return {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _n(db, t: str) -> int:
    return int((db.one(f'SELECT COUNT(*) AS n FROM "{t}"') or {}).get("n") or 0)


def note_text(now: int) -> str:
    d = datetime.fromtimestamp(now / 1000, DUBAI)
    return f"V3.0 fresh start {d.day} {d.strftime('%b %Y')}: earlier testing results are archived. Real entry prices, after fees."


def plan(db) -> dict[str, Any]:
    have = _tables(db)
    keys = [r["key"] for r in db.query("SELECT key FROM app_settings")]
    return {"archive": {t: _n(db, t) for t in ARCHIVE_TABLES if t in have},
            "clear": {t: _n(db, t) for t in CLEAR_TABLES if t in have},
            "settings": sorted(k for k in keys if k in SETTING_KEYS or k.startswith(SETTING_PREFIXES))}


def run(rt: Any, sink: Any, now: int) -> dict[str, Any]:
    db = rt.db
    p = plan(db)
    old_settings = {k: db.get_setting(k, None) for k in p["settings"]}
    done: dict[str, int] = {}
    raw = _raw_connection(db)
    lock = getattr(db, "_lock", None)
    if lock is not None:
        lock.acquire()
    try:
        raw.execute("BEGIN IMMEDIATE")
        for t, n in p["archive"].items():
            a = f"archive_v3_{t}"
            exists = raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (a,)).fetchone()
            if exists:
                raw.execute(f'INSERT INTO "{a}" SELECT *, ? FROM "{t}"', (now,))
            else:
                raw.execute(f'CREATE TABLE "{a}" AS SELECT *, ? AS archived_at FROM "{t}"', (now,))
            got = raw.execute(f'SELECT COUNT(*) FROM "{a}" WHERE archived_at = ?', (now,)).fetchone()[0]
            if got != n:
                raise RuntimeError(f"archive check failed for {t}: {got} copied, {n} expected")
            raw.execute(f'DELETE FROM "{t}"')
            done[t] = n
        for t in p["clear"]:
            raw.execute(f'DELETE FROM "{t}"')
        raw.execute("COMMIT")
    except Exception:
        raw.execute("ROLLBACK")
        raise
    finally:
        if lock is not None:
            lock.release()
    db.set_setting("archive_v3_settings", {"at": now, "values": old_settings})
    for k in p["settings"]:
        db.execute("DELETE FROM app_settings WHERE key = ?", (k,))
    # Telegram: nothing closed before now is announced; pending drafts are about archived calls
    db.set_setting("tg_win_last", now)
    try:
        if (sink.get(TELEGRAM_DRAFTS) or {}).get("items"):
            sink.set(TELEGRAM_DRAFTS, {"items": [], "updated_at": now}, merge=True)
    except Exception:
        pass
    # demo bots: same line-up and settings, fresh books
    bots_reset = []
    try:
        doc = sink.get("config/bots") or {}
        if isinstance(doc.get("bots"), list):
            bots = [{**b, "reset_token": TOKEN} for b in doc["bots"]]
            sink.set("config/bots", {**doc, "bots": bots, "updated_at": now})
            bots_reset = [b.get("id") for b in bots]
    except Exception:
        pass
    prev = {"record_since": db.get_setting("record_since", None), "record_since_tf": db.get_setting("record_since_tf", None)}
    db.set_setting("record_since", now)
    db.set_setting("record_since_tf", {})
    db.set_setting("record_restart", {"at": now, "text": note_text(now), "version": "3.0"})
    db.set_setting("honest_record_v213", True)
    audit = {"at": now, "by": "owner (RESET TESTING RESULTS, 24 Nov 2026)", "archived": done, "cleared": p["clear"],
             "settings_reset": p["settings"], "bots_reset": bots_reset, "previous": prev,
             "kept": "members' practice accounts / trades / auto-trade logs, users, candles, models, research data"}
    db.set_setting("reset_v3_audit", audit)
    db.set_setting(FLAG, now)
    return audit


def _raw_connection(db):
    """The sqlite3 connection behind app.db.Database (one transaction for copy + check + delete)."""
    for attr in ("conn", "_conn", "connection", "_connection"):
        c = getattr(db, attr, None)
        if c is not None and hasattr(c, "execute"):
            return c
    if hasattr(db, "engine"):
        return db.engine.raw_connection()
    raise RuntimeError("no sqlite connection")


def verify(db) -> dict[str, Any]:
    """After the reset: originals empty, archives hold the rows, integrity ok."""
    have = _tables(db)
    out = {"integrity": db.one("PRAGMA quick_check")}
    out["empty"] = {t: _n(db, t) for t in ARCHIVE_TABLES if t in have}
    out["archived"] = {t: _n(db, f"archive_v3_{t}") for t in ARCHIVE_TABLES if f"archive_v3_{t}" in have}
    return out


def maybe_run(rt: Any, sink: Any, now: int) -> dict[str, Any] | None:
    db = rt.db
    if db.get_setting(FLAG, None):
        return None
    if not any(_n(db, t) for t in ("signals", "bot_trades", "hesper_trades") if t in _tables(db)):
        db.set_setting(FLAG, now)
        return {"skipped": "empty database"}
    out = run(rt, sink, now)
    out["verify"] = verify(db)
    db.set_setting("reset_v3_audit", out)
    return out
