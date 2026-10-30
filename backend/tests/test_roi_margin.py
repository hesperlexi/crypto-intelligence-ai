"""ROI on margin: return_pct x the leverage the signal card suggests (engine/futures.py)."""
from app.db import Database, loads
from app.engine import futures as F
from app.services import tracking as T
from tests.test_audit_record import BAR, H1, _a


def test_roi_math_long_and_short_keep_the_sign():
    assert F.roi_on_margin(2.545, 10) == 25.45
    assert F.roi_on_margin(-1.2, 5) == -6.0                        # losses multiply too
    assert F.roi_on_margin(None, 5) is None and F.roi_on_margin(1.0, None) is None
    for ret in (3.1, -0.7, 0.0):
        roi = F.roi_on_margin(ret, 7)
        assert (roi > 0) == (ret > 0) and (roi <= 0) == (ret <= 0)  # win / loss classification unchanged


def test_signal_leverage_matches_the_futures_card():
    for entry, stop, side in ((100.0, 98.0, 1), (100.0, 103.5, -1), (0.00001234, 0.00001180, 1), (67000.0, 66900.0, 1)):
        a = {"symbol": "X/USDT", "status": "OK", "timeframe": "1h", "price": entry, "decision": "BUY" if side > 0 else "SELL",
             "setup": {"ideal_entry": entry, "stop": stop, "side_int": side, "valid": True, "targets": []}}
        card = F.futures_view(a, None)["plan"]["suggested_leverage"]
        assert F.signal_leverage(entry, stop) == card
        assert 1 <= card <= 10
    assert F.signal_leverage(100.0, None) is None


def test_new_signals_store_leverage_and_old_rows_derive_it():
    db = Database("sqlite:///:memory:")
    assert T.log_signal(db, _a(entry=100.0, stop=98.0), now=BAR + H1 + 1000)
    s = db.one("SELECT * FROM signals")
    lev = loads(s["payload"])["leverage"]
    assert lev == F.signal_leverage(100.0, 98.0)
    old = {"side": -1, "entry": 100.0, "stop": 103.0, "return_pct": -3.0, "payload": "{}"}
    m = T.margin_fields(old)
    assert m["leverage"] == F.signal_leverage(100.0, 103.0) and m["roi_pct"] == -3.0 * m["leverage"]
    stored = T.margin_fields({**old, "payload": {"leverage": 4}})
    assert stored == {"leverage": 4, "roi_pct": -12.0}


def test_views_carry_roi_pct():
    from app import views
    db = Database("sqlite:///:memory:")
    now = T.now_ms()
    ins = ("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, "
           "tp2, tp3, status, return_pct, closed_at, payload) VALUES (?, ?, 'BTC/USDT', '1h', ?, 'BUY', 'BUY', 100, 1, 100, 98, "
           "102, 103, 104, ?, ?, ?, ?)")
    db.execute(ins, ("w", now - 5000, 1, "TP2", 2.0, now - 1000, '{"leverage": 10}'))
    db.execute(ins, ("l", now - 5000, 2, "STOPPED", -2.0, now - 1000, "{}"))

    class V:
        exchange = "binance"

        def symbols(self):
            return []
    V.db = db
    rt = V()
    w = views.wins_today(rt)
    assert w["wins"][0]["roi_pct"] == 20.0 and w["wins"][0]["leverage"] == 10 and w["losses"] == 1
    tr = views.track_record(rt)
    lev_l = F.signal_leverage(100.0, 98.0)
    sigs = {x["status"]: x for x in tr["live"]["signals"]}
    assert sigs["TP2"]["roi_pct"] == 20.0 and sigs["STOPPED"]["roi_pct"] == -2.0 * lev_l
    summ = tr["live"]["summary"]
    assert summ["total_roi_pct"] == 20.0 - 2.0 * lev_l and summ["best_roi_pct"] == 20.0
    assert summ["total_return_pct"] == 0.0                       # price returns kept for transparency
    wk = views.weekly_report(rt, views.week_start(now))
    assert wk["total_roi_pct"] == summ["total_roi_pct"] and wk["best"][0]["roi_pct"] == 20.0 and wk["losses"] == 1
    best = next(a for a in tr["achievements"] if a["id"] == "best_trade")
    assert best["value"] == "+20.0% ROI" and best["roi_pct"] == 20.0
    assert T.signal_history(db)[0]["roi_pct"] is not None
