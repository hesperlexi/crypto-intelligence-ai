"""v2.30 Hesper Challenge notifications: every event becomes a clear push, admin always, members only when shown."""
from app.services import hesper
from app import worker


def _ev():
    return [{"type": "open", "symbol": "SOL/USDT", "side": 1, "price": 187.2, "leverage": 22, "run": 8},
            {"type": "tp", "symbol": "SOL/USDT", "tp": 1, "side": 1, "run": 8},
            {"type": "close", "symbol": "SOL/USDT", "reason": "stop", "pnl": -20.5, "balance": 79.5, "run": 8},
            {"type": "run_end", "run": 8, "reason": "liquidated", "balance": 3.2},
            {"type": "unknown"}]


def test_texts():
    msgs = hesper.push_messages(_ev())
    assert len(msgs) == 4 and all("uid" not in m and m["url"] == "/rich" for m in msgs)
    assert "SOL LONG opened at 187.20, 22x" in msgs[0]["body"]
    assert "TP1 hit" in msgs[1]["body"] and "break-even" in msgs[1]["body"]
    assert msgs[2]["body"].startswith("SOL closed -$20.50 (stop loss)") and "$79.50" in msgs[2]["body"]
    assert "liquidated" in msgs[3]["body"] and msgs[3]["title"] == "Hesper Challenge · run #8"
    assert len({m["tag"] for m in msgs}) == 4


def test_members_get_their_own_copy():
    msgs = hesper.push_messages(_ev()[:1], ["a", "b"])
    assert [m.get("uid") for m in msgs] == [None, "a", "b"]
    assert msgs[1]["url"] == "/results?tab=challenge"


class _Sink:
    def __init__(self, vis):
        self.vis = vis

    def get(self, path):
        return {"visibility": self.vis} if self.vis else None


def test_members_only_when_shown(monkeypatch):
    from app.db import Database
    from app.services.runtime import Runtime

    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    users = {"m1": {"status": "active"}, "m2": {"status": "expired"}}
    monkeypatch.setattr(worker, "load_users", lambda rt, sink: (users, False))
    monkeypatch.setattr(worker.membership, "is_active", lambda u, now: u.get("status") == "active")
    assert worker.hesper_members(rt, _Sink("admin"), force=True) == []
    assert worker.hesper_members(rt, _Sink(None), force=True) == []
    assert worker.hesper_members(rt, _Sink("members"), force=True) == ["m1"]
    assert rt.db.get_setting("hesper_push_members") == ["m1"]
    assert worker.hesper_members(rt, _Sink("admin")) == ["m1"]      # cached for 30 min (no read)


def test_v238_published_bot_report_is_slim():
    from app.services.bots import BotEngine
    rep = {"bots": [{"trades": list(range(300)), "equity_curve": [{"ts": i} for i in range(1000)], "stats": {"trades": 300}}], "x": 1}
    s = BotEngine.slim(rep)
    b = s["bots"][0]
    assert len(b["trades"]) == 60 and b["trades"][0] == 0 and len(b["equity_curve"]) <= 301
    assert b["equity_curve"][-1] == {"ts": 999} and b["stats"] == {"trades": 300} and s["x"] == 1
    assert len(rep["bots"][0]["trades"]) == 300            # the engine's own report is untouched


def test_v238_draft_keeps_card_recipe_and_redraws(monkeypatch):
    from app.services import telegram as T
    store = {}

    class S:
        def transact(self, path, fn):
            doc, ret = fn(store.get(path))
            store[path] = doc
            return ret

        def get(self, path):
            return store.get(path)

        def set(self, path, doc, merge=False):
            store[path] = doc
    sink = S()
    did = T.add_draft(sink, "win", "caption", b"OLD", 1, ("result_card", {"symbol": "SOL/USDT"}))
    assert store[T.DRAFTS]["items"][0]["card"] == ["result_card", {"symbol": "SOL/USDT"}]
    sent = {}
    monkeypatch.setattr(T, "config", lambda s: {"token": "t", "channel": "c"})
    monkeypatch.setattr(T, "_card", lambda name, *a: b"NEW")
    monkeypatch.setattr(T, "send_photo", lambda cfg, png, cap, session=None: sent.update(png=png))
    assert T.post_draft(sink, did)["sent"] and sent["png"] == b"NEW"
