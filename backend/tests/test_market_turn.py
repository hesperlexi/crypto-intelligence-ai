"""v2.22 live market data (OKX parsing, completed hours only, rate-limit budget) and the market turn detector."""
import numpy as np

from app.db import Database
from app.services import market_data as MD
from app.services import turn_detector as TD
from app.sinks import LocalSink

H = 3_600_000
NOW = 1_800_000_000_000 - (1_800_000_000_000 % H) + 10 * 60_000     # 10 min into an hour


def ok(rows):
    return {"code": "0", "data": rows}


def test_parsers_keep_only_completed_hours():
    cur, prev = NOW - NOW % H, NOW - NOW % H - H
    oi = MD.parse_oi_volume(ok([[str(cur), "100", "5"], [str(prev), "90", "4"]]), NOW)
    assert oi == [("oi_usd", prev, 90.0), ("vol_usd", prev, 4.0)]
    tk = MD.parse_taker(ok([[str(prev), "7", "9"]]), NOW)               # OKX order: sell, buy
    assert ("taker_sell", prev, 7.0) in tk and ("taker_buy", prev, 9.0) in tk
    assert MD.parse_ratio(ok([[str(prev), "1.4"]]), NOW) == [("ls_ratio", prev, 1.4)]
    assert MD.parse_oi_volume({"code": "50011", "msg": "rate limit"}, NOW) == []
    assert MD.parse_taker(ok([["x", "1", "2"], [str(prev)]]), NOW) == []   # junk rows are skipped


def test_liquidation_and_stablecoin_parsing():
    body = ok([{"details": [{"ts": "1000", "bkPx": "50000", "sz": "2", "posSide": "long"},
                            {"ts": "2000", "bkPx": "51000", "sz": "1", "side": "buy", "posSide": "net"},
                            {"ts": "bad"}]}])
    rows = MD.parse_liquidations(body, 0.01)
    assert rows[0] == (1000, "long", 50000.0, 2 * 0.01 * 50000)
    assert rows[1][1] == "short"                      # one-way mode: a buy closes (liquidates) a short
    st = MD.parse_stablecoins([{"date": "1700000000", "totalCirculatingUSD": {"peggedUSD": 1.5e11}}, {"date": "x"}])
    assert st == [(1700000000000, 1.5e11)]


class FakeResp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class FakeSession:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        prev = str(NOW - NOW % H - H)
        if "support-coin" in url:
            return FakeResp(ok({"contract": ["BTC", "ETH", "SOL"]}))
        if "instruments" in url:
            return FakeResp(ok([{"instId": "BTC-USDT-SWAP", "ctVal": "0.01"}]))
        if "open-interest-volume" in url:
            return FakeResp(ok([[prev, "100", "5"]]))
        if "taker-volume" in url:
            return FakeResp(ok([[prev, "7", "9"]]))
        if "long-short" in url:
            return FakeResp(ok([[prev, "1.2"]]))
        if "liquidation" in url:
            return FakeResp(ok([{"details": [{"ts": prev, "bkPx": "50000", "sz": "3", "posSide": "short"}]}]))
        if "llama" in url:
            return FakeResp([{"date": str((NOW - 3 * 86_400_000) // 1000), "totalCirculatingUSD": {"peggedUSD": 2e11}}])
        return FakeResp({}, 404)


def test_run_records_hourly_with_known_at_and_skips_unsupported_coins():
    db = Database("sqlite:///:memory:")
    s = FakeSession()
    out = MD.run(db, ["BTC/USDT", "PAXG/USDT", "SOL/USDT"], session=s, now=NOW, sleep=lambda _: None)
    assert out["done"] == ["BTC", "SOL"] and out["rows"] == 10            # PAXG has no OKX statistics: skipped
    assert MD.series(db, "BTC", "taker_buy", 0) == [(NOW - NOW % H - H, 9.0)]
    assert MD.series(db, "BTC", "taker_buy", 0, until=NOW - 1) == []      # known only from NOW (no look-ahead)
    assert MD.liquidations(db, "BTC", 0)["short"][0][1] == 3 * 0.01 * 50000
    assert MD.stablecoins(db)[0][1] == 2e11
    assert MD.run(db, ["BTC/USDT"], session=s, now=NOW + 60_000)["skipped"] == "not due"


def test_run_respects_its_time_budget():
    db = Database("sqlite:///:memory:")
    out = MD.run(db, ["BTC/USDT", "ETH/USDT", "SOL/USDT"], session=FakeSession(), now=NOW, sleep=lambda _: None, budget_s=0)
    assert out["done"] == [] and not out["errors"]


def _candles(n, start, drift, last_jump=0.0, vol=1.0, noise=1.5):
    rng = np.random.default_rng(3)
    c = start + np.cumsum(drift + rng.normal(0, noise, n))
    c[-1] += last_jump
    o = np.r_[c[0], c[:-1]]
    return {"o": o, "h": np.maximum(o, c) + 0.3, "l": np.minimum(o, c) - 0.3, "c": c, "v": np.full(n, vol)}


def test_downtrend_without_evidence_is_intact_and_a_breakout_turns_it():
    calm = _candles(260, 300, -0.5)
    r = TD.score_coin(calm, None, None, None, None, NOW)
    assert r["trend"] == "down" and r["state"] == "trend intact" and r["points"] < TD.WEAK
    # a sharp close above the last swing high and the value area, with taker buying and shorts liquidated
    brk = _candles(260, 300, -0.5, last_jump=25.0)
    okx = {"taker_buy": [(NOW - 2 * H, 150.0)], "taker_sell": [(NOW - 2 * H, 100.0)], "oi_usd": []}
    liq = {"short": [(NOW - 2 * H, 900.0)] + [(NOW - d * 86_400_000, 30.0) for d in range(2, 8)], "long": []}
    r2 = TD.score_coin(brk, None, okx, liq, None, NOW)
    codes = {x["code"] for x in r2["reasons"]}
    assert {"structure_4h", "taker_flow", "liquidations"} <= codes
    assert r2["state"] == "turning up" and r2["points"] >= TD.TURN


def test_range_and_market_state():
    flat = _candles(260, 300, 0.0)
    assert TD.score_coin(flat, None, None, None, None, NOW)["state"] in ("range", "trend intact")
    coins = {"BTC/USDT": {"trend": "down", "state": "turning up", "points": 70, "reasons": [{"code": "x"}]},
             "ETH/USDT": {"trend": "down", "state": "weakening", "points": 30},
             "SOL/USDT": {"trend": "down", "state": "trend intact", "points": 0}}
    m = TD.market_state(coins)
    assert m["trend"] == "down" and m["score"] == round(0.5 * 70 + 0.5 * 100 * (1 + 0.5) / 3)
    assert m["state"] == "turning up" and m["breadth"] == {"trending": 3, "turning": 1, "weakening": 1}


def test_publish_is_admin_view_and_skipped_in_lean(tmp_path):
    class RT:
        def __init__(self):
            self.db = Database("sqlite:///:memory:")

        def candles(self, s, tf):
            import pandas as pd
            c = _candles(260, 300, -0.5)
            return pd.DataFrame({"ts": np.arange(260) * 4 * H, "open": c["o"], "high": c["h"], "low": c["l"], "close": c["c"], "volume": c["v"]})

    sink = LocalSink(tmp_path)
    out = TD.publish(RT(), sink, ["BTC/USDT"], NOW)
    assert out["coins"] == 1
    class Lean:
        lean = True
    assert TD.publish(RT(), Lean(), ["BTC/USDT"], NOW)["skipped"] == "lean"


def test_rules_keep_market_turn_admin_only():
    import pathlib
    rules = (pathlib.Path(__file__).resolve().parents[2] / "firestore.rules.template").read_text()
    assert "(id == 'market_turn' && isAdmin())" in rules and "id != 'market_turn' &&" in rules
