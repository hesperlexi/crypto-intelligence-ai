"""Lost-state guard (v2.13): refuse to run the engine on an empty state.

If the Actions cache is gone and the encrypted backup could not be restored, the engine would start on an empty SQLite
file and republish empty records over the real ones. This check fails the job instead, unless FRESH_INSTALL=1 (a
repository variable, for a genuinely new installation).

Usage (from the repository root): python3 scripts/state_guard.py [path/to/crypto_ai.db]
"""
from __future__ import annotations

import os
import sqlite3
import sys


def state_ok(path: str) -> tuple[bool, str]:
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return False, f"no engine database at {path}"
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            settings = con.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0]
            candles = con.execute("SELECT COUNT(*) FROM (SELECT 1 FROM market_data LIMIT 1)").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error as exc:
        return False, f"engine database unreadable ({type(exc).__name__})"
    if not settings or not candles:
        return False, f"engine database looks empty (settings {settings}, candles {candles})"
    return True, f"engine state present ({settings} settings)"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "backend/data/crypto_ai.db"
    ok, why = state_ok(path)
    if ok:
        print(why)
        return 0
    if os.environ.get("FRESH_INSTALL") == "1":
        print(f"::warning::{why}; FRESH_INSTALL=1, so the engine starts on a new state")
        return 0
    print(f"::error::{why}. The cache is gone and the backup could not be restored, so the engine is NOT started "
          "(it would overwrite the real records). Restore the state, or set the repository variable FRESH_INSTALL=1 "
          "only for a brand-new installation.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
