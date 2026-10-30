"""One-time v2.1.0 fresh start (planned as v1.0.0): every trade and performance record is removed (wins and losses alike) and the record
starts again from the launch moment. Owner decision, 30 Oct 2026: no backup.

Runs inside the engine (worker.sync_config) only when APPROVED is True and the settings flag `reset_v1_done` is
unset, so it happens exactly once and never races the engine's own state. `python -m app.reset_v1 dry-run` counts
what would be removed without changing anything.

Kept: Auth accounts, users (memberships, payments), config/* (coins, bots, limits, membership), alerts (rules),
auto_paper (settings), user_coins, user_state, push_tokens, presence, owner/*, security rules, trained models,
candle history, model forecasts and their accuracy telemetry.
"""
from __future__ import annotations

import sys
from typing import Any

# Set to True only after the owner typed the approval phrase.
APPROVED = True             # owner typed "APPROVE RESET v2.1.0" on 30 Oct 2026, 22:46 Dubai
APPROVAL_PHRASE = "APPROVE RESET v2.1.0"
VERSION = "2.1.0"

SQL_TABLES = ("signals", "shadow_signals", "trades", "bots", "bot_trades", "bot_equity", "paper_accounts",
              "paper_positions", "backtests", "alert_events", "decisions", "published")
FS_COLLECTIONS = ("paper", "paper_trades", "paper_futures_trades", "auto_paper_state", "jobs")
SETTING_PREFIXES = ("safety:", "tg_")
SETTING_KEYS = ("weekly_report_notified", "job_counts", "record_since_tf")
# view documents that only describe old trades; they are deleted (bots' books) or republished empty (the rest)
VIEW_PREFIXES = ("bot_", "signals", "track_record", "weekly_report", "achievements", "wins_today", "scorecard",
                 "decisions_recent", "alerts_u_", "alerts", "paper")


def _count(db, table: str) -> int:
    try:
        return int((db.one(f"SELECT COUNT(*) AS n FROM {table}") or {}).get("n") or 0)
    except Exception:
        return 0


def plan(rt: Any, sink: Any) -> dict[str, Any]:
    """What a reset would remove. Reads only."""
    db = rt.db
    views = [i for i, _ in sink.list("views")]
    return {
        "sqlite_rows": {t: _count(db, t) for t in SQL_TABLES},
        "firestore_docs": {c: len(sink.list(c)) for c in FS_COLLECTIONS},
        "views_reset": sorted(v for v in views if v.startswith(VIEW_PREFIXES)),
        "settings": sorted(k for k in _setting_keys(db)
                           if k.startswith(SETTING_PREFIXES) or k in SETTING_KEYS),
    }


def _setting_keys(db) -> list[str]:
    try:
        return [r["key"] for r in db.query("SELECT key FROM app_settings")]
    except Exception:
        return []


def run(rt: Any, sink: Any, now: int) -> dict[str, Any]:
    """Remove every trade and performance record and restart the record at `now`."""
    db = rt.db
    out = plan(rt, sink)
    for t in SQL_TABLES:
        try:
            db.execute(f"DELETE FROM {t}")
        except Exception as exc:                       # a table an older database never had
            out.setdefault("skipped_tables", []).append(f"{t}: {type(exc).__name__}")
    for k in out["settings"]:
        db.execute("DELETE FROM app_settings WHERE key = ?", (k,))
    for c in FS_COLLECTIONS:
        for did, _ in sink.list(c):
            sink.delete(f"{c}/{did}")
    for v in out["views_reset"]:
        if v.startswith("bot_"):                       # republished from the fresh books; old ids must not linger
            sink.delete(f"views/{v}")
    doc = sink.get("config/bots") or {}
    if isinstance(doc.get("bots"), list):
        sink.set("config/bots", {**doc, "bots": [{**b, "reset_token": "v1"} for b in doc["bots"]], "updated_at": now})
    db.set_setting("record_since", now)
    db.set_setting("record_since_tf", {})
    db.set_setting("testing_since", now)
    db.set_setting("release", {"version": VERSION, "launched_at": now})
    sink.set("config/release", {"version": VERSION, "launched_at": now, "updated_at": now})
    db.set_setting("reset_v1_done", now)
    return out


def maybe_run(rt: Any, sink: Any, now: int) -> dict[str, Any] | None:
    if not APPROVED or rt.db.get_setting("reset_v1_done", 0):
        return None
    return run(rt, sink, now)


if __name__ == "__main__":                              # python -m app.reset_v1 dry-run
    import json

    from .config import settings
    from .db import get_db
    from .services.runtime import Runtime
    from .sinks import FirestoreSink
    from .worker import settings_project

    if sys.argv[1:2] != ["dry-run"]:
        sys.exit("usage: python -m app.reset_v1 dry-run")
    settings.ensure_dirs()
    db = get_db()
    rt = Runtime(db, None)                             # no market data needed to count
    sink = FirestoreSink(db, settings_project())       # reads only: plan() never writes
    print(json.dumps({"approved": APPROVED, "done": db.get_setting("reset_v1_done", 0), **plan(rt, sink)},
                     indent=1, default=str))
