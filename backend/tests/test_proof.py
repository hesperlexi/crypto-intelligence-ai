"""v2.9 sealed-signal proof: fingerprint at publication, text revealed only after close, Telegram seal/reveal once."""
import hashlib

import pandas as pd

from app.data.base import tf_ms
from app.db import Database
from app.services import proof, telegram as TG, tracking as T

H1 = tf_ms("1h")
BAR = 1_700_000_000_000 - (1_700_000_000_000 % tf_ms("4h"))


def _a():
    return {"symbol": "BTC/USDT", "timeframe": "4h", "bar_ts": BAR, "price": 100.0, "decision": "BUY", "grade": "A",
            "confidence": 0.6, "regime": {"regime": "BULL"}, "volatility": {"state": "NORMAL"},
            "signal": {"signal": "BUY", "score": 70, "reasons": [], "warnings": []},
            "setup": {"valid": True, "side_int": 1, "ideal_entry": 100.0, "stop": 98.0, "risk_reward": 1.6, "atr": 1.0,
                      "targets": [{"price": t, "rr": 1.0} for t in (102.0, 103.0, 104.0)]}, "flags": []}


def test_seal_matches_published_levels_and_text_hashes_to_fingerprint():
    db = Database("sqlite:///:memory:")
    T.log_signal(db, _a(), now=BAR + H1)
    s = db.one("SELECT * FROM signals")
    p = db.one("SELECT * FROM signal_proofs")
    assert p["signal_id"] == s["id"] and hashlib.sha256(p["text"].encode()).hexdigest() == p["hash"]
    assert "|BTC/USDT|4H|LONG|entry=100|stop=98|tp1=102|tp2=103|tp3=104|" in p["text"] and "salt=" in p["text"]
    # text hidden while open, shown once closed
    assert "text" not in proof.for_ids(db, [s["id"]], set())[s["id"]]
    assert proof.for_ids(db, [s["id"]], {s["id"]})[s["id"]]["text"] == p["text"]


class _Sess:
    def __init__(self):
        self.sent = []

    def post(self, url, timeout=None, json=None, **kw):
        self.sent.append(json["text"])

        class R:
            def json(self_):
                return {"ok": True}
        return R()


class RT:
    def __init__(self, db):
        self.db = db


def test_telegram_seals_fresh_calls_once_skips_stale_and_reveals_after_close():
    db = Database("sqlite:///:memory:")
    created = BAR + H1
    T.log_signal(db, _a(), now=created)
    cfg = {"token": "x", "channel": "@c"}
    sess = _Sess()
    assert TG.proofs(RT(db), cfg, created + 5 * 60_000, sess) == ["seal x1"]
    h = db.one("SELECT hash FROM signal_proofs")["hash"]
    assert h in sess.sent[0] and "BTC" not in sess.sent[0]
    assert TG.proofs(RT(db), cfg, created + 10 * 60_000, sess) == []            # once only, nothing to reveal yet
    db.execute("UPDATE signals SET status = 'STOPPED', return_pct = -2.0, closed_at = ?", (created + 3 * H1,))
    assert TG.proofs(RT(db), cfg, created + 4 * H1, sess) == ["reveal"]
    assert "Stopped out" in sess.sent[-1] and h in sess.sent[-1] and "salt=" in sess.sent[-1]
    assert TG.proofs(RT(db), cfg, created + 5 * H1, sess) == []
    # a call first seen too late is never sealed (no back-dating)
    a2 = {**_a(), "symbol": "ETH/USDT"}
    T.log_signal(db, a2, now=created)
    assert TG.proofs(RT(db), cfg, created + 2 * H1, sess) == []
    assert db.one("SELECT sealed_post_at FROM signal_proofs WHERE text LIKE '%ETH%'")["sealed_post_at"] == -1
