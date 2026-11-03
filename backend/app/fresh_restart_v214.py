"""v2.14 fresh restart (owner decision, 3 Nov 2026: "delete permanently", wins and losses alike).

One-time migration, flag `fresh_restart_v214` (listed in `worker.MIGRATION_FLAGS`, so the v2.13 lost-state guard marks it
done - never run - on a fresh / empty engine database, and Firestore `admin/migrations` remembers it). Runs inside
`worker.sync_config`. The old history is DELETED, not hidden: nothing can bring it back except an older engine backup.

Deleted (engine SQLite): every signal / call of the record and its side tables (`HISTORY_TABLES`), every bot book
(`BOT_TABLES`; the line-up in Firestore `config/bots` is kept and every bot restarts with a fresh balance through a new
`reset_token`), Hesper's runs and trades and its state (next cycle starts Run #1 at $100), the safety switch state, the
v2.13 restart note, and the publish cache (so every view is re-published from the empty record at once).
Deleted (Firestore): Telegram drafts about old calls (`owner/telegram_drafts` items), view documents that only hold old
history and are no longer re-published (`views/scalping`, legacy `views/bot_*`).
Kept: candles, models, training data, forecasts (`predictions`), news, users, memberships, payments, alerts, settings
unrelated to the record, the Telegram bot token and options, and members' own practice accounts, manual practice trades
and auto-trade logs (`paper*`, `auto_paper*`; owner decision).

`python -m app.fresh_restart_v214 dry-run` counts what would be deleted without changing anything.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from typing import Any

FLAG = "fresh_restart_v214"
RESET_TOKEN = "v214"
# the record and everything derived from single calls
HISTORY_TABLES = ("signals", "shadow_signals", "scalp_signals", "signal_proofs", "signal_adjustments", "decisions")
# the demo bots' books (bots rows are re-created from config/bots with a fresh balance) and Hesper
BOT_TABLES = ("bot_trades", "bot_equity", "bots")
HESPER_TABLES = ("hesper_runs", "hesper_trades")
CACHE_TABLES = ("published",)              # view hashes: every view goes out again, built from the empty record
SQL_TABLES = HISTORY_TABLES + BOT_TABLES + HESPER_TABLES + CACHE_TABLES
SETTING_PREFIXES = ("safety:",)            # safety switch state per coin / timeframe
SETTING_KEYS = ("hesper_state", "hesper_since", "hesper_v1", "honest_record_since", "honest_record_prev",
                "record_restart", "scalp_backfill_state")
# views that only describe old history and are not re-published by the engine any more
VIEW_DELETE_PREFIXES = ("bot_", "scalping")
TELEGRAM_DRAFTS = "owner/telegram_drafts"
NOTE = "real entry prices, after fees."
DUBAI = timezone(timedelta(hours=4))


def note_text(now: int) -> str:
    d = datetime.fromtimestamp(now / 1000, DUBAI)
    return f"Fresh start {d.day} {d.strftime('%b %Y')}: {NOTE}"


def _count(db, table: str) -> int:
    try:
        return int((db.one(f"SELECT COUNT(*) AS n FROM {table}") or {}).get("n") or 0)
    except Exception:
        return 0


def _setting_keys(db) -> list[str]:
    try:
        return [r["key"] for r in db.query("SELECT key FROM app_settings")]
    except Exception:
        return []


def has_history(db) -> bool:
    """Anything to restart? (an empty / brand-new database has no calls, no bot trades and no Hesper runs)."""
    return any(_count(db, t) for t in HISTORY_TABLES + ("bot_trades", "bot_equity") + HESPER_TABLES)


def plan(rt: Any, sink: Any) -> dict[str, Any]:
    """What the restart deletes. Reads only."""
    db = rt.db
    try:
        views = [i for i, _ in sink.list("views")]
    except Exception:
        views = []
    try:
        drafts = len((sink.get(TELEGRAM_DRAFTS) or {}).get("items") or [])
    except Exception:
        drafts = 0
    return {
        "sqlite_rows": {t: _count(db, t) for t in SQL_TABLES},
        "settings": sorted(k for k in _setting_keys(db) if k.startswith(SETTING_PREFIXES) or k in SETTING_KEYS),
        "views_deleted": sorted(v for v in views if v.startswith(VIEW_DELETE_PREFIXES)),
        "telegram_drafts": drafts,
    }


def run(rt: Any, sink: Any, now: int) -> dict[str, Any]:
    """Delete the old history (see the module doc) and restart the record, the bots and Hesper at `now`."""
    db = rt.db
    out = plan(rt, sink)
    for t in SQL_TABLES:
        try:
            db.execute(f"DELETE FROM {t}")
        except Exception as exc:                       # a table an older database never had
            out.setdefault("skipped_tables", []).append(f"{t}: {type(exc).__name__}")
    for k in out["settings"]:
        db.execute("DELETE FROM app_settings WHERE key = ?", (k,))
    for v in out["views_deleted"]:
        try:
            sink.delete(f"views/{v}")
        except Exception:
            pass
    if out["telegram_drafts"]:
        try:
            sink.set(TELEGRAM_DRAFTS, {"items": [], "updated_at": now}, merge=True)
        except Exception:
            pass
    # Telegram: nothing closed before now is ever announced (the calls are gone anyway)
    db.set_setting("tg_win_last", now)
    # bots: same line-up, every book restarts with its starting balance; futures bots use the engine's leverage (10-50x)
    doc = sink.get("config/bots") or {}
    if isinstance(doc.get("bots"), list):
        bots = [{**b, "reset_token": RESET_TOKEN, **({"leverage": 50.0, "safe_leverage": True}
                                                     if b.get("market") == "futures" else {})} for b in doc["bots"]]
        sink.set("config/bots", {**doc, "bots": bots, "updated_at": now})
        out["bots_reset"] = [b.get("id") for b in bots]
    # the counted record starts now for every timeframe; one restart line on Results
    out["previous"] = {"record_since": db.get_setting("record_since", None),
                       "record_since_tf": db.get_setting("record_since_tf", None)}
    db.set_setting("record_since", now)
    db.set_setting("record_since_tf", {})
    db.set_setting("record_restart", {"at": now, "text": note_text(now), "version": "2.14"})
    db.set_setting("honest_record_v213", True)       # v2.13's restart is merged into this one (never a second restart)
    db.set_setting(FLAG, now)
    return out


def maybe_run(rt: Any, sink: Any, now: int) -> dict[str, Any] | None:
    """Runs once. On a database without any history only the flag is set (nothing to restart, never runs later)."""
    db = rt.db
    if db.get_setting(FLAG, None):
        return None
    if not has_history(db):
        db.set_setting(FLAG, now)
        db.set_setting("honest_record_v213", True)
        return {"skipped": "empty database"}
    return run(rt, sink, now)


if __name__ == "__main__":                              # python -m app.fresh_restart_v214 dry-run
    import json

    from .config import settings
    from .db import get_db
    from .services.runtime import Runtime
    from .sinks import FirestoreSink
    from .worker import settings_project

    if sys.argv[1:2] != ["dry-run"]:
        sys.exit("usage: python -m app.fresh_restart_v214 dry-run")
    settings.ensure_dirs()
    db = get_db()
    rt = Runtime(db, None)
    sink = FirestoreSink(db, settings_project())       # reads only: plan() never writes
    print(json.dumps({"done": db.get_setting(FLAG, None), **plan(rt, sink)}, indent=1, default=str))
