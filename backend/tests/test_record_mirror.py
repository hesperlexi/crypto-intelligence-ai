"""v3.1 (owner, 25 Nov 2026): bots trade the record's own call, and trades are followed minute by minute after the last
closed 15-minute candle (services/m1tail.py) so hits / closes show at the next engine cycle."""
import json

import pandas as pd

from app.db import Database
from app.services import bots as B
from app.services import m1tail, tracking

Q, MIN = 900_000, 60_000
T0 = 1_800_000_000_000 - 1_800_000_000_000 % Q


class RT:
    def __init__(self, m1):
        self.db = Database("sqlite:///:memory:")
        self._m1 = m1

        class P:
            async def fetch_ohlcv(_s, symbol, tf, since=None, limit=100):
                return [r for r in m1 if r[0] >= (since or 0)][:limit]
        self.provider = P()

    def record_error(self, *a):
        pass


def p15(n):
    return pd.DataFrame([[T0 + i * Q, 100, 100.5, 99.5, 100] for i in range(n)], columns=["ts", "open", "high", "low", "close"])


def test_path_adds_the_closed_minutes_after_the_last_quarter_hour_and_continues_from_a_minute():
    m1 = [[T0 + 2 * Q + i * MIN, 100, 101 if i == 3 else 100.2, 99.9, 100.1] for i in range(10)]
    rt = RT(m1)
    now = T0 + 2 * Q + 8 * MIN + 1                                 # minutes 0..7 of the 3rd quarter are closed
    out = m1tail.path(rt, "BTC/USDT", T0 - Q, p15(2), now)
    assert [c[5] for c in out] == [Q, Q] + [MIN] * 8 and out[2][0] == T0 + 2 * Q
    mark = m1tail.mark(out[-1][0], out[-1][5])
    assert mark % Q != 0 and mark == T0 + 2 * Q + 7 * MIN + 1      # a minute mark
    rt2 = RT(m1)
    later = m1tail.path(rt2, "BTC/USDT", mark, p15(2), T0 + 2 * Q + 10 * MIN + 1)
    assert [c[0] for c in later] == [T0 + 2 * Q + 8 * MIN, T0 + 2 * Q + 9 * MIN]     # no minute twice, none skipped


def test_record_closes_on_a_target_touched_inside_the_current_quarter_hour():
    s = {"id": "s", "symbol": "BTC/USDT", "timeframe": "1h", "created_at": T0 - 1, "side": 1, "entry": 100.0, "stop": 99.0,
         "tp1": 100.4, "tp2": 100.45, "tp3": 100.48, "fill_status": "FILLED", "payload": json.dumps({"horizon_bars": 30})}
    path = p15(2).assign(high=100.3)                                # no target in the closed quarters
    tail = [(T0 + 2 * Q + i * MIN, 100.2, 100.6 if i == 4 else 100.25, 100.1, 100.2) for i in range(6)]
    without = tracking.evaluate_signal(s, path, None, T0 + 2 * Q + 6 * MIN)
    assert without["status"] == "OPEN" and not without["tp1_hit"]
    res = tracking.evaluate_signal(s, path, None, T0 + 2 * Q + 6 * MIN, tail=tail)
    assert res["status"] == "TP3" and res["closed_at"] == T0 + 2 * Q + 4 * MIN


def test_bot_mirrors_only_a_fresh_filled_record_call_on_the_same_side(monkeypatch):
    monkeypatch.setattr(B, "RECORD_MIRROR", True)
    db = Database("sqlite:///:memory:")
    db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
               "tp2, tp3, status, fill_status, filled_at, payload) VALUES ('c1', ?, 'ETH/USDT', '1h', 1, 'SELL', 'SELL', 10, -1, "
               "10.0, 10.5, 9.5, 9.2, 9.0, 'OPEN', 'FILLED', ?, ?)", (T0, T0, json.dumps({"leverage": 8, "grade": "A"})))
    eng = B.BotEngine.__new__(B.BotEngine)
    eng.db = db
    cfg = {"timeframe": "1h"}
    a = {"call": {"id": "c1", "status": "OPEN", "side": "SHORT", "fill_status": "FILLED"}}
    rec = eng._record_call(cfg, a, -1, T0 + 5 * MIN)
    assert rec["entry"] == 10.0 and rec["stop"] == 10.5 and rec["targets"] == [9.5, 9.2, 9.0] and rec["leverage"] == 8
    assert eng._record_call(cfg, a, 1, T0 + 5 * MIN) is False                     # other side
    assert eng._record_call(cfg, a, -1, T0 + 40 * MIN) is False                   # too late: never chase an old call
    assert eng._record_call(cfg, {"call": {**a["call"], "fill_status": "PENDING"}}, -1, T0) is False
    assert eng._record_call(cfg, {}, -1, T0) is False                             # not in the record: not taken
    assert eng._record_call({"timeframe": "1h", "demo_only": True}, {}, -1, T0) is None   # demo bots: own plan
