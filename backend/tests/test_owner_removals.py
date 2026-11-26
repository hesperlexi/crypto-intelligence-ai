import json

from app.db import Database
from app.services import owner_removals as R


class RT:
    def __init__(self):
        self.db = Database("sqlite:///:memory:")


def test_the_two_anthropic_calls_leave_record_bots_and_challenge_with_balances_set_back():
    rt = RT(); db = rt.db
    c15, c1h = R.FROM_MS + 18 * 3_600_000, R.FROM_MS + 5 * 3_600_000
    for sid, tf, ts, side in (("a15", "15m", c15, -1), ("a1h", "1h", c1h, 1), ("other", "15m", c15, 1)):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status) "
                   "VALUES (?, ?, ?, ?, 1, 'X', 'X', 1, ?, 'STOPPED')", (sid, ts, "BTC/USDT" if sid == "other" else R.SYMBOL, tf, side))
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('b15', ?, ?, 'v', 1)",
               (json.dumps({"id": "b15", "timeframe": "15m"}), json.dumps({"cash": 1000.0, "positions": [], "pending": []})))
    db.execute("INSERT INTO bot_trades (id, bot_id, symbol, side, opened_at, closed_at, entry, exit, qty, pnl, fees, return_pct, r_multiple, "
               "exit_reason, correct, info) VALUES ('t1', 'b15', ?, -1, ?, ?, 1, 1, 1, -390.0, 0, 0, 0, 'stop', 0, '{}')", (R.SYMBOL, c15 - 60_000, c15 + 1_200_000))
    db.execute("INSERT INTO bot_equity (bot_id, ts, equity, benchmark) VALUES ('b15', ?, 610.0, 0)", (c15 + 2_000_000,))
    from app.services.hesper import Hesper
    Hesper.ensure_tables(db) if hasattr(Hesper, "ensure_tables") else None
    out = R.remove_anthropic_25nov(rt)
    assert {c["tf"] for c in out["calls"]} == {"15m", "1h"}
    assert [r["id"] for r in db.query("SELECT id FROM signals")] == ["other"]
    assert db.one("SELECT COUNT(*) AS n FROM bot_trades")["n"] == 0
    assert json.loads(db.one("SELECT state FROM bots")["state"])["cash"] == 1390.0
    assert db.one("SELECT equity FROM bot_equity")["equity"] == 1000.0
    assert db.one("SELECT COUNT(*) AS n FROM removed_record")["n"] == 2


def test_waiting_calls_and_the_ena_challenge_trade_are_removed_26nov():
    rt = RT(); db = rt.db
    t = R.UPDATES_FROM_MS + 3_600_000
    for i, (sid, fs, ts) in enumerate((("w1", "PENDING", t), ("filled", "FILLED", t), ("oldwait", "PENDING", R.UPDATES_FROM_MS - 1))):
        db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, status, fill_status) "
                   "VALUES (?, ?, 'SOL/USDT', '4h', ?, 'X', 'X', 1, 1, 'OPEN', ?)", (sid, ts, i, fs))
    order = {"symbol": "SOL/USDT", "side": 1, "reserved": 50.0, "placed_at": t, "info": {"signal_id": "w1", "timeframe": "4h"}}
    db.execute("INSERT INTO bots (id, config, state, reset_token, created_at) VALUES ('b4', ?, ?, 'v', 1)",
               (json.dumps({"id": "b4", "timeframe": "4h"}), json.dumps({"cash": 100.0, "positions": [], "pending": [order]})))
    from app.services.hesper import Hesper
    db.set_setting(Hesper.STATE_KEY, {"run": 3, "cash": 40.0, "trades": 2, "wins": 1, "pending": [], "positions": [
        {"id": "p1", "symbol": "ENA/USDT", "opened_at": t, "qty": 10, "qty_open": 10, "margin": 50.0, "realized": -0.5}]})
    out = R.remove_waiting_and_ena_26nov(rt, now=t + 3_600_000)
    assert sorted(r["id"] for r in db.query("SELECT id FROM signals")) == ["filled", "oldwait"]
    assert json.loads(db.one("SELECT state FROM bots")["state"]) == {"cash": 150.0, "positions": [], "pending": []}
    st = db.get_setting(Hesper.STATE_KEY)
    assert st["positions"] == [] and st["cash"] == 90.5
    assert len(out["waiting"]) == 1 and out["ena"] == [{"who": Hesper.BOT_ID, "open": True}]
    assert R.REASON.startswith("owner removal 25 Nov")
