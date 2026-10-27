"""Where the batch engine reads user configuration from and publishes results to.

FirestoreSink : production (Firebase). Credentials from FIREBASE_SERVICE_ACCOUNT (the JSON key, as text)
                or GOOGLE_APPLICATION_CREDENTIALS (a path).
LocalSink     : same interface on a folder of JSON files - used by tests and for dry runs.

Published views are stored as {"json": "<payload>", "updated_at": ms}. Keeping the payload as a JSON string
sidesteps Firestore's restrictions (no nested arrays, no NaN, special characters in map keys) and lets the
website receive exactly the same objects the local API returns.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .db import Database, dumps

MAX_DOC_BYTES = 1_000_000


def _now() -> int:
    return int(time.time() * 1000)


class BaseSink:
    def __init__(self, db: Database | None = None):
        self.db = db
        self.pending: dict[str, dict[str, Any]] = {}
        self.writes = 0
        self.skipped = 0

    # -- views (hash-deduplicated so unchanged documents cost no Firestore writes) ----------------------
    def view(self, name: str, payload: Any, volatile: tuple[str, ...] = ("generated_at",)) -> None:
        text = dumps(payload)
        if len(text.encode()) > MAX_DOC_BYTES:
            text = dumps({"error": "payload too large for one document", "bytes": len(text)})
        stable = payload
        if isinstance(payload, dict) and volatile:
            stable = {k: v for k, v in payload.items() if k not in volatile}
        digest = hashlib.sha1(dumps(stable).encode()).hexdigest()
        if self.db is not None:
            row = self.db.one("SELECT hash FROM published WHERE doc_id = ?", (name,))
            if row and row["hash"] == digest:
                self.skipped += 1
                return
        self.pending[f"views/{name}"] = {"json": text, "updated_at": _now(), "_hash": digest}

    def flush(self) -> int:
        docs = {k: {kk: vv for kk, vv in v.items() if kk != "_hash"} for k, v in self.pending.items()}
        if docs:
            self._write_many(docs)
        if self.db is not None:
            rows = [(k.split("/", 1)[1], v["_hash"], _now()) for k, v in self.pending.items() if "_hash" in v]
            self.db.executemany("INSERT INTO published (doc_id, hash, ts) VALUES (?, ?, ?) "
                                "ON CONFLICT (doc_id) DO UPDATE SET hash = excluded.hash, ts = excluded.ts", rows)
        n = len(docs)
        self.writes += n
        self.pending.clear()
        return n

    # -- interface implemented by subclasses ---------------------------------------------------------------
    def _write_many(self, docs: dict[str, dict[str, Any]]) -> None:
        raise NotImplementedError

    def get(self, path: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        raise NotImplementedError

    def list(self, collection: str) -> list[tuple[str, dict[str, Any]]]:
        raise NotImplementedError

    def queued_jobs(self) -> list[tuple[str, dict[str, Any]]]:
        jobs = [(i, d) for i, d in self.list("jobs") if d.get("status") == "queued"]
        return sorted(jobs, key=lambda j: j[1].get("created_at") or 0)

    def delete(self, path: str) -> None:
        raise NotImplementedError

    def transact(self, path: str, fn) -> Any:
        """Read-modify-write one document: fn(current or None) -> (new data or None to leave it, result)."""
        new, result = fn(self.get(path))
        if new is not None:
            self.set(path, new)
        return result

    def add(self, collection: str, data: dict[str, Any]) -> str:
        from .db import new_id
        doc_id = new_id()
        self.set(f"{collection}/{doc_id}", data)
        return doc_id

    # -- phone notifications (web push through Firebase Cloud Messaging) -----------------------------------
    def send_push(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Send each {title, body, url, tag} to every registered device. Returns counts; never raises."""
        return {"sent": 0, "devices": 0, "reason": "not supported by this sink"}


def chunks(docs: dict[str, dict[str, Any]], max_docs: int = 400, max_bytes: int = 7_000_000):
    """Split documents into commit-sized groups by count and by (approximate) size."""
    cur: list[tuple[str, dict[str, Any]]] = []
    size = 0
    for path, data in docs.items():
        n = len(path) + sum(len(str(k)) + len(v) if isinstance(v, str) else len(str(k)) + 16 for k, v in data.items())
        if cur and (len(cur) >= max_docs or size + n > max_bytes):
            yield cur
            cur, size = [], 0
        cur.append((path, data))
        size += n
    if cur:
        yield cur


class LocalSink(BaseSink):
    def __init__(self, root: str | Path, db: Database | None = None):
        super().__init__(db)
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str) -> Path:
        return self.root / (path + ".json")

    def _write_many(self, docs: dict[str, dict[str, Any]]) -> None:
        for path, data in docs.items():
            self.set(path, data)

    def get(self, path: str) -> dict[str, Any] | None:
        p = self._path(path)
        return json.loads(p.read_text()) if p.exists() else None

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if merge and p.exists():
            data = {**json.loads(p.read_text()), **data}
        p.write_text(dumps(data))

    def list(self, collection: str) -> list[tuple[str, dict[str, Any]]]:
        d = self.root / collection
        if not d.is_dir():
            return []
        return [(p.stem, json.loads(p.read_text())) for p in sorted(d.glob("*.json"))]

    def delete(self, path: str) -> None:
        self._path(path).unlink(missing_ok=True)

    def send_push(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        tokens = self.list("push_tokens")
        log = self.root / "push_log.jsonl"
        sent = 0
        with log.open("a") as f:
            for m in messages:
                to = [t for t, d in tokens if (d.get("uid") == m["uid"] if m.get("uid") else True)]
                sent += len(to)
                f.write(dumps({**m, "devices": len(to)}) + "\n")
        return {"sent": sent, "devices": len(tokens)}


class FirestoreSink(BaseSink):
    def __init__(self, db: Database | None = None, project_id: str | None = None):
        super().__init__(db)
        import firebase_admin
        from firebase_admin import credentials, firestore

        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.Certificate(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
        else:
            raise RuntimeError("set FIREBASE_SERVICE_ACCOUNT (service-account JSON) to publish to Firestore")
        opts = {"projectId": project_id} if project_id else None
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, opts)
        self.fs = firestore.client()

    def _write_many(self, docs: dict[str, dict[str, Any]]) -> None:
        # A Firestore commit holds at most 500 writes AND at most 10 MiB; analysis documents can be several hundred
        # KB each, so batches are cut by size as well (v2.3: after a nightly training every analysis changes at once
        # and one 400-document batch went over 10 MiB, so nothing at all was published).
        for chunk in chunks(docs, max_docs=400, max_bytes=7_000_000):
            batch = self.fs.batch()
            for path, data in chunk:
                batch.set(self.fs.document(path), data)
            batch.commit()

    def get(self, path: str) -> dict[str, Any] | None:
        snap = self.fs.document(path).get()
        return snap.to_dict() if snap.exists else None

    def set(self, path: str, data: dict[str, Any], merge: bool = False) -> None:
        self.fs.document(path).set(json.loads(dumps(data)), merge=merge)
        self.writes += 1

    def list(self, collection: str) -> list[tuple[str, dict[str, Any]]]:
        return [(s.id, s.to_dict() or {}) for s in self.fs.collection(collection).stream()]

    def queued_jobs(self) -> list[tuple[str, dict[str, Any]]]:
        try:
            from google.cloud.firestore_v1.base_query import FieldFilter

            q = self.fs.collection("jobs").where(filter=FieldFilter("status", "==", "queued"))
        except ImportError:
            q = self.fs.collection("jobs").where("status", "==", "queued")
        jobs = [(s.id, s.to_dict() or {}) for s in q.stream()]
        return sorted(jobs, key=lambda j: j[1].get("created_at") or 0)

    def delete(self, path: str) -> None:
        self.fs.document(path).delete()

    def transact(self, path: str, fn) -> Any:
        from google.cloud import firestore as gfs

        ref = self.fs.document(path)

        @gfs.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            new, result = fn(snap.to_dict() if snap.exists else None)
            if new is not None:
                tx.set(ref, json.loads(dumps(new)))
            return result

        return run(self.fs.transaction())

    def add(self, collection: str, data: dict[str, Any]) -> str:
        _, ref = self.fs.collection(collection).add(json.loads(dumps(data)))
        self.writes += 1
        return ref.id

    def send_push(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if not messages:
            return {"sent": 0, "devices": 0}
        try:
            from firebase_admin import messaging

            devices = [(d.get("token") or i, d.get("uid"), (d.get("email") or "").lower()) for i, d in self.list("push_tokens")]
        except Exception as exc:
            return {"sent": 0, "devices": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
        if not devices:
            return {"sent": 0, "devices": 0, "reason": "no device has turned notifications on"}
        admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
        sent, dead, errors = 0, set(), []
        for m in messages:                     # no cap on messages or members; FCM takes up to 500 devices per call
            to = m.get("uid")
            # a member's alert goes to that member's devices only; an admin alert to the admins' devices;
            # a broadcast (market-wide news) to every device that turned notifications on
            if m.get("broadcast"):
                tokens = [t for t, _, _ in devices]
            else:
                tokens = [t for t, uid, email in devices if (uid == to if to else (not admins or email in admins or uid is None))]
            if not tokens:
                continue
            data = {k: str(v)[:900] for k, v in m.items() if v is not None and k not in ("uid", "broadcast")}
            for i in range(0, len(tokens), 500):
                chunk = tokens[i:i + 500]
                msg = messaging.MulticastMessage(
                    tokens=chunk, data=data,
                    webpush=messaging.WebpushConfig(headers={"Urgency": "high", "TTL": "86400"}))
                try:
                    res = messaging.send_each_for_multicast(msg)
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}"[:200])
                    continue
                sent += res.success_count
                for tok, r in zip(chunk, res.responses):
                    if not r.success and type(r.exception).__name__ in ("UnregisteredError", "SenderIdMismatchError"):
                        dead.add(tok)
                    elif not r.success:
                        errors.append(f"{type(r.exception).__name__}: {r.exception}"[:200])
        for tok in dead:                       # devices that uninstalled / revoked permission
            try:
                self.fs.document(f"push_tokens/{tok}").delete()
            except Exception:
                pass
        return {"sent": sent, "devices": len(devices), "removed": len(dead), "errors": errors[:3]}
