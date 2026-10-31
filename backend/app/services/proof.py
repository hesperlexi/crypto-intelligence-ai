"""v2.9 sealed-signal proof: makes the public record independently checkable without giving signals away.

When a call is published, `seal` stores a fixed text of its published levels plus a random secret (salt) and the
SHA-256 fingerprint of that text. The Telegram autopilot posts the fingerprint at once (time-stamped by Telegram,
coin and levels hidden) and, when the call closes, the full text: anyone can hash it (any SHA-256 tool, or the
Verify box on the Results page) and see it equals the fingerprint posted before the result was known. The salt
stops anyone guessing the levels from the fingerprint. Nothing here changes a decision or a result.
"""
from __future__ import annotations

import hashlib
import secrets
from typing import Any

from ..db import Database

VERSION = "CIA-SEAL-1"


def _n(v: Any) -> str:
    return "-" if v is None else f"{float(v):.10g}"


def text_of(sig: dict[str, Any], salt: str) -> str:
    """The sealed text (one line, fixed field order)."""
    side = "LONG" if int(sig["side"]) > 0 else "SHORT"
    return "|".join([VERSION, str(sig["id"]), str(sig["symbol"]), str(sig["timeframe"]).upper(), side,
                     f"entry={_n(sig.get('entry'))}", f"stop={_n(sig.get('stop'))}", f"tp1={_n(sig.get('tp1'))}",
                     f"tp2={_n(sig.get('tp2'))}", f"tp3={_n(sig.get('tp3'))}", f"published={int(sig['created_at'])}",
                     f"salt={salt}"])


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seal(db: Database, sig: dict[str, Any]) -> dict[str, Any] | None:
    """Store the proof of one just-published call (once; the published levels are the row's columns)."""
    if not sig or not sig.get("side"):
        return None
    t = text_of(sig, secrets.token_hex(8))
    h = digest(t)
    db.execute("INSERT INTO signal_proofs (signal_id, created_at, text, hash) VALUES (?, ?, ?, ?) "
               "ON CONFLICT (signal_id) DO NOTHING", (sig["id"], int(sig["created_at"]), t, h))
    return {"hash": h}


def for_ids(db: Database, ids: list[str], closed: set[str]) -> dict[str, dict[str, Any]]:
    """{signal_id: {hash, text?, sealed_at?}}: the text only for closed calls (an open call's salt stays secret)."""
    out: dict[str, dict[str, Any]] = {}
    ids = [i for i in ids if i]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in db.query(f"SELECT * FROM signal_proofs WHERE signal_id IN ({','.join('?' * len(part))})", tuple(part)):
            out[r["signal_id"]] = {"hash": r["hash"], "sealed_at": r["sealed_post_at"],
                                   **({"text": r["text"]} if r["signal_id"] in closed else {})}
    return out
