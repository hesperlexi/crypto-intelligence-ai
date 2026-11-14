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
    users = {"m1": {"status": "active"}, "m2": {"status": "expired"}}
    monkeypatch.setattr(worker, "load_users", lambda rt, sink: (users, False))
    monkeypatch.setattr(worker.membership, "is_active", lambda u, now: u.get("status") == "active")
    assert worker.hesper_members(None, _Sink("admin")) == []
    assert worker.hesper_members(None, _Sink(None)) == []
    assert worker.hesper_members(None, _Sink("members")) == ["m1"]
