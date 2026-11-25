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
