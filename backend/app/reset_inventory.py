"""V3.0 Phase 1 reset inventory (READ-ONLY, owner brief 24 Nov 2026).

Lists every SQLite table of the engine state (main DB + flow.db) with its row count, its foreign keys and a purpose
class, plus the Firestore collections with document counts. Nothing is changed or deleted.

    python -m app.reset_inventory --out x.json [--firestore]

Classes:
  test_result  - testing performance only; a V3.0 reset would clear it (after the owner types RESET TESTING RESULTS)
  keep         - configuration, market history, research data, models, logs; never cleared
  unsure       - not classified; kept and reported (rule: when in doubt, keep)
Output holds counts only (no coins, sides, levels, user ids or e-mails).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from typing import Any

# testing results: the record, every side table built from single calls, bot books, challenges, Guardian history
TEST_RESULT = {
    "signals": "public signal record (wins and losses)",
    "shadow_signals": "calls held by the safety switch, followed privately",
    "scalp_signals": "old 15m scalping log (switched off 2 Nov)",
    "signal_proofs": "sealed fingerprints of calls (feature removed)",
    "signal_adjustments": "admin stop / target / close changes on calls",
    "decisions": "engine decision log of calls",
    "rejected_signals": "calls blocked by filters, followed privately (filter check)",
    "held_signals": "calls withdrawn by the admin (Hold)",
    "bot_trades": "demo bot trades",
    "bot_equity": "demo bot equity curves",
    "bots": "demo bot books (re-created from config/bots with a fresh balance)",
    "hesper_runs": "Hesper Challenge runs",
    "hesper_trades": "Hesper Challenge trades",
    "laststand_runs": "Last Stand runs",
    "laststand_trades": "Last Stand trades",
    "guardian_recs": "Trade Guardian recommendations + shadow outcomes",
    "published": "view hash cache (rebuilt from the empty record)",
    "edge_published": "edge view hash cache (rebuilt)",
}
# never cleared
KEEP_PREFIX = ("candles", "candle", "prediction", "model", "training", "train", "feature", "news", "derivs", "mkt_",
               "flow_", "book_", "liq_", "market_", "altseason", "radar", "funding", "guardian_m1", "news_sentiment",
               "alert", "app_settings", "settings", "leaderboard", "users", "watchlist", "coin", "backtest",
               "evaluation", "drift", "calibration", "regime", "sentiment", "push", "error", "log", "audit")
# owner choice needed (they mix testing figures with member data)
ASK = {
    "leaderboard_entries": "members' monthly practice ranking readings (depends on practice accounts)",
    "leaderboard_winners": "past monthly winners (prizes were given)",
    "alert_marks": "which alert was already sent per call (cleared calls make these orphans; harmless)",
}
SETTING_KEYS_TEST = ("hesper_state", "hesper_since", "hesper_v1", "laststand_state", "record_restart", "record_since",
                     "record_since_tf", "record_excludes", "tg_win_last", "challenger_log", "turn_shadow_log",
                     "gate_failures", "filter_off_revoked")
SETTING_PREFIX_TEST = ("safety:", "filter_off_revoked|")


def classify(table: str) -> tuple[str, str]:
    if table in TEST_RESULT:
        return "test_result", TEST_RESULT[table]
    if table in ASK:
        return "ask_owner", ASK[table]
    if table.startswith("sqlite_"):
        return "keep", "SQLite internal"
    if table.startswith(KEEP_PREFIX):
        return "keep", "configuration / market history / research / models / logs"
    return "unsure", "not classified - kept"


def sqlite_inventory(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"path": os.path.basename(path), "exists": False}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        tables = [r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = []
        for t in tables:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            fks = [dict(table=r["table"], col=r["from"], to=r["to"]) for r in con.execute(f'PRAGMA foreign_key_list("{t}")')]
            cls, why = classify(t)
            out.append({"table": t, "rows": n, "class": cls, "why": why, "foreign_keys": fks})
        settings = {"test_result": [], "keep_count": 0}
        if "app_settings" in tables:
            keys = [r[0] for r in con.execute("SELECT key FROM app_settings")]
            for k in keys:
                if k in SETTING_KEYS_TEST or k.startswith(SETTING_PREFIX_TEST):
                    settings["test_result"].append(k.split("|")[0].split(":")[0] + (":*" if k.startswith(("safety:",)) else ""))
                else:
                    settings["keep_count"] += 1
            settings["test_result"] = sorted(set(settings["test_result"]))
        integrity = con.execute("PRAGMA quick_check").fetchone()[0]
        return {"path": os.path.basename(path), "exists": True, "bytes": os.path.getsize(path), "integrity": integrity,
                "tables": out, "settings": settings}
    finally:
        con.close()


FS_TEST = {"paper": "members' practice accounts (owner kept them in earlier restarts)",
           "auto_paper_state": "auto-trade logs", "owner": "owner docs incl. Telegram drafts"}


def firestore_inventory() -> dict[str, Any]:
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw:
        return {"ok": False, "reason": "no service account in this job"}
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
    fs = firestore.client()
    cols = []
    for c in fs.collections():
        try:
            n = c.count().get()[0][0].value
        except Exception as e:  # noqa: BLE001
            n = f"count failed: {type(e).__name__}"
        cols.append({"collection": c.id, "docs": n, "note": FS_TEST.get(c.id, "")})
    # practice accounts: how many have trade sub-collections (names only, first 20 docs)
    sub = {}
    try:
        for d in fs.collection("paper").limit(20).stream():
            for s in d.reference.collections():
                sub[s.id] = sub.get(s.id, 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "collections": cols, "paper_subcollections_seen_in_20": sub}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--data", default="data")
    ap.add_argument("--firestore", action="store_true")
    a = ap.parse_args()
    out: dict[str, Any] = {"ok": True, "read_only": True, "at": int(time.time() * 1000)}
    out["engine_db"] = sqlite_inventory(os.path.join(a.data, "crypto_ai.db"))
    out["flow_db"] = sqlite_inventory(os.path.join(a.data, "flow.db"))
    tabs = out["engine_db"].get("tables") or []
    out["summary"] = {cls: {"tables": sum(1 for t in tabs if t["class"] == cls), "rows": sum(t["rows"] for t in tabs if t["class"] == cls)}
                      for cls in ("test_result", "ask_owner", "unsure", "keep")}
    if a.firestore:
        try:
            out["firestore"] = firestore_inventory()
        except Exception as e:  # noqa: BLE001
            out["firestore"] = {"ok": False, "reason": f"{type(e).__name__}"}
    with open(a.out, "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
