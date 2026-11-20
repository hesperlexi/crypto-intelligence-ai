"""v2.62 order-flow recorder + big-money alerts (app.flow_watch)."""
import json
import sqlite3

from app import flow_watch as F

T0 = 1_800_000_000_000 // F.BUCKET_MS * F.BUCKET_MS


def _trade(tid, px, sz, side, ts):
    return {"tradeId": str(tid), "px": str(px), "sz": str(sz), "side": side, "ts": str(ts)}


def test_parse_trades_counts_only_new_and_whales():
    rows = [_trade(5, 100, 30, "buy", T0 + 4000), _trade(4, 100, 1, "sell", T0 + 3000), _trade(3, 100, 9, "buy", T0 + 2000)]
    b, newest, gap, px = F.parse_trades(rows, ct_val=10.0, last_id=3, whale=25_000)
    k = b[T0]
    assert newest == 5 and px == 100 and not gap
    assert k["buy"] == 30_000 and k["sell"] == 1_000 and k["wbuy"] == 30_000 and k["nw"] == 1 and k["ntr"] == 2


def test_parse_trades_marks_a_gap_when_the_batch_does_not_reach_back():
    rows = [_trade(1000 - i, 100, 1, "buy", T0) for i in range(500)]
    _, _, gap, _ = F.parse_trades(rows, 1.0, last_id=10, whale=1e9)
    assert gap


def test_parse_book_depth_and_walls():
    d = {"bids": [["99.9", "10"], ["99.0", "500"], ["97.0", "999"]], "asks": [["100.1", "10"], ["100.8", "300"]]}
    b = F.parse_book(d, ct_val=1.0)
    assert round(b["mid"], 2) == 100.0
    assert b["bid05"] == 99.9 * 10 and b["bid1"] == 99.9 * 10 + 99.0 * 500
    assert b["wall_bid_px"] == 99.0 and b["wall_ask_px"] == 100.8


def test_parse_liqs_sides_and_since():
    rows = [{"details": [{"ts": str(T0 + 10), "sz": "2", "bkPx": "100", "posSide": "long", "side": "sell"},
                         {"ts": str(T0 + 20), "sz": "1", "bkPx": "100", "posSide": "short", "side": "buy"},
                         {"ts": str(T0 - 10), "sz": "9", "bkPx": "100", "posSide": "long"}]}]
    b, newest = F.parse_liqs(rows, ct_val=10.0, since=T0)
    assert b[T0]["long_usd"] == 2000 and b[T0]["short_usd"] == 1000 and newest == T0 + 20


def _db(tmp_path):
    return F.FlowDB(str(tmp_path / "flow.db"))


def _history(db, coin, n=48, wb=10_000, ws=9_000):
    for i in range(2, n + 2):
        db.add_trades(coin, {T0 - i * F.BUCKET_MS: {"buy": 1e6, "sell": 1e6, "wbuy": wb, "wsell": ws, "nw": 1, "ntr": 100, "maxtr": 5e4, "last_px": 100}}, False)


def test_detect_whale_burst_and_quiet(tmp_path):
    db = _db(tmp_path)
    _history(db, "BTC")
    assert F.detect(db, "BTC", T0 + 60_000, whale=25_000) == []
    db.add_trades("BTC", {T0: {"buy": 5e6, "sell": 1e6, "wbuy": 2_000_000, "wsell": 100_000, "nw": 9, "ntr": 300, "maxtr": 6e5, "last_px": 101}}, False)
    a = F.detect(db, "BTC", T0 + 60_000, whale=25_000)
    assert a and a[0]["kind"] == "whales" and a[0]["dir"] == 1 and a[0]["n"] == 9


def test_detect_needs_a_day_of_history(tmp_path):
    db = _db(tmp_path)
    db.add_trades("ETH", {T0: {"buy": 5e6, "sell": 1e6, "wbuy": 2e6, "wsell": 0, "nw": 9, "ntr": 300, "maxtr": 6e5, "last_px": 1}}, False)
    assert F.detect(db, "ETH", T0 + 60_000, whale=25_000) == []


def test_detect_wipeout(tmp_path):
    db = _db(tmp_path)
    _history(db, "SOL")
    db.add_liqs("SOL", {T0: {"long_usd": 900_000, "short_usd": 50_000, "n": 30}})
    a = [x for x in F.detect(db, "SOL", T0 + 60_000, whale=25_000) if x["kind"] == "wipeout"]
    assert a and a[0]["dir"] == -1
    title, body = F.message("SOL", a[0])
    assert "Forced closes" in title and "not a forecast" in body.lower()


def test_messages_never_predict():
    t, b = F.message("BTC", {"kind": "whales", "dir": -1, "size": 3e6, "ratio": 12, "buy": 1e5, "sell": 3.1e6, "n": 7})
    assert "selling" in t and "not a forecast" in b and "will" not in b.lower()


def test_outcomes_and_stats(tmp_path):
    db = _db(tmp_path)
    db.c.execute("INSERT INTO flow_alerts (coin, kind, dir, at, price, size_usd, ratio, msg) VALUES ('BTC','whales',1,?,100,1,1,'')", (T0,))
    for k, px in ((3, 101), (12, 102), (48, 99)):
        db.add_trades("BTC", {T0 + k * F.BUCKET_MS: {"buy": 1, "sell": 1, "wbuy": 0, "wsell": 0, "nw": 0, "ntr": 1, "maxtr": 1, "last_px": px}}, False)
    F.fill_outcomes(db, T0 + 5 * 3_600_000, {})
    s = F.stats(db)["whales"]
    assert s["alerts"] == 1 and s["p15"]["followed_pct"] == 100.0 and s["p240"]["followed_pct"] == 0.0


def test_audience():
    rules = [{"symbol": "ALL/USDT", "user_id": "u1"}, {"symbol": "ETH/USDT", "user_id": "u2"}, {"symbol": "BTC/USDT", "user_id": "local"}]
    assert F.audience(rules, "BTC") == ["u1", None]


def test_run_pass_records_and_alerts(tmp_path, monkeypatch):
    eng = tmp_path / "crypto_ai.db"
    c = sqlite3.connect(eng)
    c.executescript("CREATE TABLE watchlists (user_id TEXT, symbol TEXT, pinned INT, added_at INT);"
                    "CREATE TABLE alerts (id TEXT, user_id TEXT, type TEXT, symbol TEXT, timeframe TEXT, params TEXT, enabled INT);"
                    "CREATE TABLE app_settings (key TEXT, value TEXT);")
    c.execute("INSERT INTO watchlists VALUES ('local','BTC/USDT',0,0)")
    c.execute("INSERT INTO alerts VALUES ('a1','u9','BIG_MONEY','ALL/USDT','all','{}',1)")
    c.execute("INSERT INTO app_settings VALUES ('mkt_okx_support', ?)", (json.dumps({"ct_val": {"BTC": 0.01}}),))
    c.commit(); c.close()
    calls = {"n": 0}

    def fake(path, params=None):
        if path.endswith("/tickers"):
            return [{"instId": "BTC-USDT-SWAP", "volCcy24h": "100000", "last": "100000"}]
        if path.endswith("/trades"):
            calls["n"] += 1
            base = 100 * calls["n"]
            return [_trade(base + i, 100000, 1, "buy", T0 + 1000) for i in range(5, 0, -1)]
        if path.endswith("/books"):
            return [{"bids": [["99990", "100"]], "asks": [["100010", "100"]]}]
        return []
    monkeypatch.setattr(F, "_get", fake)
    r1 = F.run_pass(str(eng), now=T0 + 2000)
    r2 = F.run_pass(str(eng), now=T0 + 25_000)
    assert r1["coins"] == 1 and r2["errors"] == []
    db = F.FlowDB(str(tmp_path / "flow.db"))
    rows = db.rows("SELECT * FROM flow_5m")
    assert rows and rows[0]["ntr"] == 5          # the first pass only set the starting point
    assert db.rows("SELECT * FROM book_5m")
