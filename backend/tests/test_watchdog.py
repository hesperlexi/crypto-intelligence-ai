from app import watchdog


class Fake:
    def __init__(self, updated):
        self.docs = {"views/meta": {"updated_at": updated}}
        self.sent = []

    def get(self, p):
        return self.docs.get(p)

    def set(self, p, d, merge=False):
        self.docs[p] = d

    def send_push(self, msgs):
        self.sent += msgs
        return {"sent": len(msgs)}


def test_notifies_once_when_down_and_again_when_back():
    now = 10_000_000_000
    s = Fake(now - 120 * 60_000)
    assert watchdog.check(s, 75, now)["down"] and s.sent[-1]["title"] == "Engine stopped"
    watchdog.check(s, 75, now + 30 * 60_000)
    assert len(s.sent) == 1                      # no repeat within 12 hours
    s.docs["views/meta"]["updated_at"] = now + 40 * 60_000
    r = watchdog.check(s, 75, now + 45 * 60_000)
    assert not r["down"] and s.sent[-1]["title"] == "Engine running again" and len(s.sent) == 2
    watchdog.check(s, 75, now + 60 * 60_000)
    assert len(s.sent) == 2
