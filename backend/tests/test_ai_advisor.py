"""Gemini advisor with a mocked HTTP client: off without a key, budget, breaker, clamping, filters, parse failures."""
import json

from app.db import Database, dumps
from app.services import ai_advisor as AI
from app.services import tracking as T

NOW = 1_700_000_000_000


class Resp:
    def __init__(self, code, payload=None, text=None):
        self.status_code = code
        self._p = payload if payload is not None else {"candidates": [{"content": {"parts": [{"text": text or "{}"}]}}]}

    def json(self):
        return self._p


class Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json, "headers": headers})
        r = self.responses.pop(0) if self.responses else Resp(500)
        if isinstance(r, Exception):
            raise r
        return r


def ok(obj):
    return Resp(200, text=json.dumps(obj))


GOOD = {"rationale": "The engine rates this BTC 1h long grade A with 58% directional confidence. Trend and momentum "
                     "point up; the stop is 1R away and targets sit at 1R, 1.5R and 2.5R.", "regime": "Bull trend"}


def _sig(db):
    a = {"symbol": "BTC/USDT", "timeframe": "1h", "bar_ts": NOW, "price": 101.0, "decision": "BUY", "grade": "A",
         "confidence": 0.58, "regime": {"regime": "BULL"}, "signal": {"signal": "BUY", "score": 70, "reasons": [], "warnings": []},
         "setup": {"valid": True, "side_int": 1, "ideal_entry": 100.0, "stop": 98.0, "risk_reward": 1.6, "atr": 1.0,
                   "targets": [{"price": 102.0, "rr": 1}, {"price": 103.0, "rr": 1.5}, {"price": 105.0, "rr": 2.5}]}, "flags": []}
    assert T.log_signal(db, a, now=NOW)
    return db.one("SELECT * FROM signals")


def test_disabled_without_key():
    db = Database("sqlite:///:memory:")
    adv = AI.Advisor(db, api_key="", client=Client(ok(GOOD)))
    assert not adv.enabled and adv.generate("x", {}, {}) is None
    assert AI.run(db, adv, now=NOW) == {"enabled": False, "rationales": 0, "reviews": 0, "params_applied": 0}


def test_rationale_is_stored_in_the_payload_and_logged_and_no_user_data_is_sent():
    db = Database("sqlite:///:memory:")
    _sig(db)
    cl = Client(ok({**GOOD, "params": {"giveback_arm_r": 5.0, "giveback_frac": 0.1, "trail_atr_k": 2.5}}))
    adv = AI.Advisor(db, api_key="k", client=cl)
    out = AI.run(db, adv, now=NOW + 1000)
    assert out["rationales"] == 1 and out["params_applied"] == 0           # AI_PARAMS off: suggestion only
    s = db.one("SELECT payload FROM signals")
    ai = json.loads(s["payload"])["ai"]
    assert ai["rationale"].startswith("The engine") and ai["regime"] == "Bull trend" and ai["model"] and ai["at"]
    assert db.get_setting("ai_manage_params", None) is None
    sug = db.get_setting("ai_manage_suggestion")
    assert sug["giveback_arm_r"] == 1.0 and sug["giveback_frac"] == 0.3 and sug["trail_atr_k"] == 2.5   # clamped
    sent = dumps(cl.calls[0]["body"])
    assert "@" not in sent.replace("support@cryptointelai.com", "") and "uid" not in sent
    assert cl.calls[0]["headers"]["x-goog-api-key"] == "k" and "gemini-flash-lite-latest" in cl.calls[0]["url"]
    body = cl.calls[0]["body"]
    assert body["generationConfig"]["responseMimeType"] == "application/json" and body["generationConfig"]["temperature"] == 0.2
    rules = [d["rule"] for d in T.recent_decisions(db)["decisions"]]
    assert "ai_rationale" in rules and "ai_params_suggested" in rules
    # cached: a second run makes no call for the same signal
    assert AI.run(db, AI.Advisor(db, api_key="k", client=Client()), now=NOW + 2000)["rationales"] == 0
    assert T.latest_ai(db, "BTC/USDT", "1h")["rationale"].startswith("The engine")


def test_params_applied_only_with_ai_params(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ai_params", True)
    db = Database("sqlite:///:memory:")
    _sig(db)
    AI.run(db, AI.Advisor(db, api_key="k", client=Client(ok({**GOOD, "params": {"trail_atr_k": 9}}))), now=NOW + 1)
    assert db.get_setting("ai_manage_params") == {"trail_atr_k": 4.0}
    assert T.manage_params(db)["trail_atr_k"] == 4.0


def test_daily_budget():
    db = Database("sqlite:///:memory:")
    adv = AI.Advisor(db, api_key="k", client=Client(*[ok(GOOD)] * 5), daily_limit=2)
    assert adv.generate("t", {}, {}, NOW) and adv.generate("t", {}, {}, NOW)
    assert adv.generate("t", {}, {}, NOW) is None and len(adv._client.calls) == 2
    assert adv.generate("t", {}, {}, NOW + 86_400_000) is not None        # next UTC day


def test_circuit_breaker_and_429():
    db = Database("sqlite:///:memory:")
    adv = AI.Advisor(db, api_key="k", client=Client(Resp(500), TimeoutError("x"), Resp(503), ok(GOOD), ok(GOOD)))
    for _ in range(3):
        assert adv.generate("t", {}, {}, NOW) is None
    assert not adv.available(NOW + 60_000)                                 # paused after 3 failures
    assert adv.available(NOW + AI.PAUSE_MS + 1)
    db2 = Database("sqlite:///:memory:")
    adv2 = AI.Advisor(db2, api_key="k", client=Client(Resp(429), ok(GOOD)))
    assert adv2.generate("t", {}, {}, NOW) is None and not adv2.available(NOW + 1000)


def test_404_tries_the_fallback_model_once():
    db = Database("sqlite:///:memory:")
    cl = Client(Resp(404), ok(GOOD))
    adv = AI.Advisor(db, api_key="k", client=cl)
    assert adv.generate("t", {}, {}, NOW) == GOOD
    assert "gemini-flash-latest" in cl.calls[1]["url"] and adv.model == "gemini-flash-latest"
    cl = Client(Resp(404), Resp(404), Resp(404), ok(GOOD))
    adv = AI.Advisor(Database("sqlite:///:memory:"), api_key="k", client=cl)
    assert adv.generate("t", {}, {}, NOW) is None and len(cl.calls) == 3


def test_json_parse_failure_returns_none():
    db = Database("sqlite:///:memory:")
    adv = AI.Advisor(db, api_key="k", client=Client(Resp(200, text="not json"), Resp(200, payload={"oops": 1})))
    assert adv.generate("t", {}, {}, NOW) is None and adv.generate("t", {}, {}, NOW) is None


def test_banned_phrases_links_and_contacts_are_dropped():
    for bad in ("This is a guaranteed winner.", "A risk-free entry here.", "Sure profit on this one.",
                "See https://example.com for more.", "Email me at trader@gmail.com.", "Join our telegram @pumpgroup.",
                "Visit binance.com now.", "Call +1 555 123 4567."):
        assert AI.clean_text(bad, 400) is None, bad
    assert AI.clean_text("Questions: support@cryptointelai.com or www.cryptointelai.com.", 400)
    long = "Word " * 300
    assert len(AI.clean_text(long, 100)) <= 101
    db = Database("sqlite:///:memory:")
    _sig(db)
    AI.run(db, AI.Advisor(db, api_key="k", client=Client(ok({"rationale": "Guaranteed 100% profit!", "regime": "x"}))), now=NOW + 5)
    ai = json.loads(db.one("SELECT payload FROM signals")["payload"])["ai"]
    assert "rationale" not in ai and ai["failed_rationale"]


def test_review_when_a_call_closes():
    db = Database("sqlite:///:memory:")
    _sig(db)
    adv = AI.Advisor(db, api_key="k", client=Client(ok(GOOD), ok({"review": "The call reached target 1 and closed at break-even."})))
    AI.run(db, adv, now=NOW + 1)
    db.execute("UPDATE signals SET status = 'TP1', return_pct = 1.0, closed_at = ?, exit_reason = 'break_even'", (NOW + 5000,))
    out = AI.run(db, adv, now=NOW + 6000)
    assert out["reviews"] == 1
    assert json.loads(db.one("SELECT payload FROM signals")["payload"])["ai"]["review"].startswith("The call")
