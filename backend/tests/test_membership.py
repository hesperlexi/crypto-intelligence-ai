"""Memberships: who is active, alerts of lapsed members pause, admins hear about proofs, members get reminders."""
from app.services import membership as M

DAY = M.DAY_MS
NOW = 1_800_000_000_000


def test_is_active():
    assert M.is_active(None, NOW)                                            # admins have no record
    assert M.is_active({"status": "approved"}, NOW)                          # approved before memberships existed
    assert M.is_active({"status": "approved", "expires_at": NOW + DAY}, NOW)
    assert not M.is_active({"status": "approved", "expires_at": NOW - 1}, NOW)
    assert not M.is_active({"status": "pending"}, NOW)
    assert not M.is_active({"status": "blocked", "expires_at": NOW + DAY}, NOW)


def test_proof_and_reminder_notifications_are_sent_once():
    users = {
        "a": {"status": "pending", "email": "a@x.com", "payment": {"status": "submitted", "submitted_at": NOW - 5, "months": 3, "amount": 30, "currency": "USDT"}},
        "b": {"status": "approved", "email": "b@x.com", "expires_at": NOW + 2.5 * DAY},
        "c": {"status": "approved", "email": "c@x.com", "expires_at": NOW + 20 * DAY},
    }
    msgs, seen = M.notifications(users, {}, NOW)
    assert [m["title"] for m in msgs] == ["Payment proof received", "Membership ending soon"]
    assert "uid" not in msgs[0] and msgs[1]["uid"] == "b"                    # proofs -> admins, reminder -> member
    assert "30 USDT for 3 months" in msgs[0]["body"]
    again, seen = M.notifications(users, seen, NOW + 60_000)
    assert again == []
    last_day, _ = M.notifications(users, seen, NOW + 2 * DAY)                # the last-day reminder comes separately
    assert [m["uid"] for m in last_day] == ["b"]


def test_worker_pauses_alerts_of_lapsed_members(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = LocalSink(tmp_path)
    now = worker.now_ms()
    sink.set("users/old", {"status": "approved", "email": "o@x.com", "expires_at": now - DAY})
    sink.set("users/ok", {"status": "approved", "email": "k@x.com", "expires_at": now + 30 * DAY})
    for aid, owner in (("a1", "old"), ("a2", "ok"), ("a3", "admin-uid")):
        sink.set(f"alerts/{aid}", {"type": "TRADE_SETUP", "symbol": "BTC/USDT", "timeframe": "4h", "owner_uid": owner, "enabled": True})
    notes = worker.sync_config(rt, sink)
    enabled = {r["id"]: r["enabled"] for r in rt.db.query("SELECT id, enabled FROM alerts")}
    assert enabled == {"a1": 0, "a2": 1, "a3": 1}
    assert notes["inactive_members"] == 1


def test_active_members_coins_are_tracked_and_lapsed_ones_dropped(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.db.set_setting("watchlist_majors_v2", True)      # the one-time major-coin expansion is tested separately
    rt.db.set_setting("gold_paxg_v21", True)            # and so is the one-time gold addition
    sink = LocalSink(tmp_path)
    now = worker.now_ms()
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    sink.set("users/ok", {"status": "approved", "expires_at": now + 30 * DAY})
    sink.set("users/old", {"status": "approved", "expires_at": now - DAY})
    sink.set("user_coins/ok", {"symbols": ["PEPE/USDT", "BTC/USDT", "sol"]})
    sink.set("user_coins/old", {"symbols": ["DOGE/USDT"]})
    notes = worker.sync_config(rt, sink)
    assert set(rt.symbols()) == {"BTC/USDT", "PEPE/USDT", "SOL/USDT"}
    assert notes["member_coins"] == ["PEPE/USDT", "SOL/USDT"]
    sink.set("user_coins/ok", {"symbols": []})
    worker.sync_config(rt, sink)
    assert rt.symbols() == ["BTC/USDT"]


def test_admin_can_change_member_coin_limits(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = LocalSink(tmp_path)
    now = worker.now_ms()
    sink.set("config/watchlist", {"symbols": ["BTC/USDT"]})
    sink.set("config/limits", {"member_coin_limit": 2, "member_coins_max": 3})
    for u in ("a", "b"):
        sink.set(f"users/{u}", {"status": "approved", "expires_at": now + 30 * DAY})
    sink.set("user_coins/a", {"symbols": ["AAA", "BBB", "CCC"]})
    sink.set("user_coins/b", {"symbols": ["DDD", "EEE"]})
    notes = worker.sync_config(rt, sink)
    assert notes["member_coins"] == ["AAA/USDT", "BBB/USDT", "DDD/USDT"]   # 2 each, 3 in total


def test_major_coins_are_added_once_and_removals_stick(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [] if q == "HBAR" else [f"{q}/USDT"]         # an unlisted coin is never added

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    worker.sync_config(rt, sink)
    syms = set(rt.symbols())
    assert {"ETH/USDT", "DOGE/USDT", "AAVE/USDT"} <= syms and "HBAR/USDT" not in syms
    doc = sink.get("config/watchlist")
    sink.set("config/watchlist", {**doc, "symbols": [x for x in doc["symbols"] if x["symbol"] != "DOGE/USDT"]})
    worker.sync_config(rt, sink)
    assert "DOGE/USDT" not in rt.symbols()                    # the admin removed it: not re-added


def test_renamed_coin_moves_to_its_new_pair(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [] if q == "TON" else [f"{q}/USDT"]          # TON no longer trades

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.db.set_setting("watchlist_majors_v2", True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "TON/USDT", "pinned": True}]})
    notes = worker.sync_config(rt, sink)
    assert notes["renamed"] == {"TON/USDT": "GRAM/USDT"}
    assert "GRAM/USDT" in rt.symbols() and "TON/USDT" not in rt.symbols()
    assert {"symbol": "GRAM/USDT", "pinned": True} in sink.get("config/watchlist")["symbols"]
    assert "renamed" not in worker.sync_config(rt, sink)          # done once


def test_gold_is_added_once_and_can_be_removed(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    rt.db.set_setting("watchlist_majors_v2", True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    assert worker.sync_config(rt, sink)["gold_added"] == "PAXG/USDT" and "PAXG/USDT" in rt.symbols()
    doc = sink.get("config/watchlist")
    sink.set("config/watchlist", {**doc, "symbols": [x for x in doc["symbols"] if x["symbol"] != "PAXG/USDT"]})
    worker.sync_config(rt, sink)
    assert "PAXG/USDT" not in rt.symbols()                    # removed by the admin: stays removed


def test_testing_mode_v24_keeps_ten_coins_futures_bots_and_restarts_practice(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("watchlist_majors_v2", "gold_paxg_v21", "fresh_start_v23"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": s, "pinned": False} for s in ("BTC/USDT", "PEPE/USDT", "ENA/USDT")]})
    sink.set("paper/u1_futures", {"wallet": 5})
    sink.set("paper_futures_trades/t1", {"uid": "u1"})
    notes = worker.sync_config(rt, sink)
    assert sorted(rt.symbols()) == sorted(worker.TEST_COINS)
    assert all(b["market"] == "futures" for b in sink.get("config/bots")["bots"]) and len(sink.get("config/bots")["bots"]) == 4      # v2.6: the 15m bot is removed (15m paused)
    assert sink.get("paper/u1_futures") is None and sink.get("paper_futures_trades/t1") is None
    assert notes["testing_v24"]["coins"] == worker.TEST_COINS
    assert "testing_v24" not in worker.sync_config(rt, sink)       # done once
    assert len(sink.get("config/bots")["bots"]) == 4                # spot bots (and the paused 15m bot) are not added back


def test_testing_gold_swaps_xaut_for_paxg_once(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"

        async def search_markets(self, q, limit=50):
            return [f"{q}/USDT"]

    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("watchlist_majors_v2", "gold_paxg_v21", "fresh_start_v23", "testing_v24"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "XAUT/USDT", "pinned": True}]})
    worker.sync_config(rt, sink)
    assert set(rt.symbols()) == {"BTC/USDT", "PAXG/USDT"}
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})   # a later removal sticks
    worker.sync_config(rt, sink)
    assert set(rt.symbols()) == {"BTC/USDT"}


def test_15m_resumes_grade_a_only_with_one_bot(tmp_path):
    from app.db import Database
    from app.services.runtime import Runtime
    from app.sinks import LocalSink
    from app import worker

    class _P:
        name = "test"
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    for f in ("watchlist_majors_v2", "gold_paxg_v21", "fresh_start_v23", "testing_v24", "testing_v24b", "pause_15m_v26"):
        rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    sink.set("config/bots", {"bots": [{"id": "b", "timeframe": "1h", "market": "futures"}],
                             "defaults_added": ["b"] + [d["id"] for d in worker.DEFAULT_BOTS]})
    notes = worker.sync_config(rt, sink)
    assert notes.get("resume_15m_bot") == "futures-signal-a-15m"
    bots = sink.get("config/bots")["bots"]
    assert [b["id"] for b in bots] == ["b", "futures-signal-a-15m"] and bots[1]["grades"] == "A"
    worker.sync_config(rt, sink)                          # once only (a later removal sticks)
    assert len(sink.get("config/bots")["bots"]) == 2
