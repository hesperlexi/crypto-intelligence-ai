"""Thin DB-API layer. SQLite by default; PostgreSQL/TimescaleDB when DATABASE_URL starts with postgres.

The SQL in this project is written in the portable subset both engines accept
(`?` placeholders are translated to `%s` for PostgreSQL).
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
# v2.5 columns added to existing tables (safe on both engines: added only when missing)
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    table: [("fill_status", "TEXT"), ("filled_at", "BIGINT"), ("peak_r", "DOUBLE PRECISION"),
            ("peak_pct", "DOUBLE PRECISION"), ("exit_reason", "TEXT"), ("managed", "INTEGER"), ("atr", "DOUBLE PRECISION"),
            ("app_version", "TEXT"), ("engine_version", "TEXT")]
    for table in ("signals", "shadow_signals")
}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


def to_jsonable(o: Any) -> Any:
    """Plain-JSON copy: numpy scalars/arrays -> python, NaN / inf -> null (browsers reject NaN in JSON)."""
    import numpy as np

    if o is None or isinstance(o, (str, bool, int)):
        return o
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): to_jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [to_jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.ndarray):
        return to_jsonable(o.tolist())
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def dumps(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), allow_nan=False, separators=(",", ":"))


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


class Database:
    def __init__(self, url: str | None = None):
        self.url = url or settings.database_url
        self._lock = threading.RLock()
        self.is_postgres = self.url.startswith("postgres")
        if self.is_postgres:
            import psycopg2  # noqa: WPS433 - optional dependency

            self._conn = psycopg2.connect(self.url)
            self._conn.autocommit = True
        else:
            path = self.url.replace("sqlite:///", "")
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self.init_schema()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.is_postgres else sql

    def init_schema(self) -> None:
        script = SCHEMA_PATH.read_text()
        with self._lock:
            if self.is_postgres:
                cur = self._conn.cursor()
                cur.execute(script)
                cur.close()
            else:
                self._conn.executescript(script)
        self.migrate()

    def columns(self, table: str) -> set[str]:
        if self.is_postgres:
            rows = self.query("SELECT column_name AS name FROM information_schema.columns WHERE table_name = ?", (table,))
        else:
            rows = self.query(f"PRAGMA table_info({table})")
        return {r["name"] for r in rows}

    def migrate(self) -> None:
        """ALTER TABLE ... ADD COLUMN for columns newer than the stored database (idempotent, SQLite and PostgreSQL)."""
        for table, cols in MIGRATIONS.items():
            have = self.columns(table)
            for name, typ in cols:
                if name in have:
                    continue
                try:
                    self.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                except Exception:          # added concurrently by another process: fine
                    if name not in self.columns(table):
                        raise

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._sql(sql), tuple(params))
            n = cur.rowcount
            cur.close()
            return n

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with self._lock:
            cur = self._conn.cursor()
            if not self.is_postgres:
                cur.execute("BEGIN")
            try:
                cur.executemany(self._sql(sql), rows)
                if not self.is_postgres:
                    cur.execute("COMMIT")
            except Exception:
                if not self.is_postgres:
                    cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(self._sql(sql), tuple(params))
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
            return rows

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def ping(self) -> bool:
        try:
            self.query("SELECT 1 AS ok")
            return True
        except Exception:
            return False

    # -- small key/value helper used for user-editable settings ---------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM app_settings WHERE key = ?", (key,))
        return loads(row["value"], default) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, dumps(value)),
        )


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        settings.ensure_dirs()
        _db = Database()
    return _db


def set_db(db: Database) -> None:
    """Used by tests to inject an in-memory database."""
    global _db
    _db = db
