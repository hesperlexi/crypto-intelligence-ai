"""v2.6 components on synthetic data: news-sentiment collection (no look-ahead), pooled trade filter, structure stops,
analysis settings off by default."""
import numpy as np

from app.config import settings
from app.db import Database
from app.ml import sentiment_gate, trade_filter2 as TF2
from app.services import sentiment

H = 3_600_000


class FakeAdvisor:
    def __init__(self, answer):
        self.answer, self.model, self.calls, self.seen = answer, "fake", 0, []

    def available(self, now=None):
        return True

    def generate(self, task, data, schema, now=None):
        self.calls += 1
        self.seen.append(data)
        return self.answer


def test_sentiment_collects_once_per_hour_without_look_ahead():
    db = Database("sqlite:///:memory:")
    now = 1_760_000_000_000 // H * H + 10 * 60_000
    heads = {"items": [{"title": "ETF inflows hit record", "source": "X", "ts": now - 30 * 60_000},
                       {"title": "future headline", "source": "X", "ts": now + 60_000},          # not published yet
                       {"title": "old", "source": "X", "ts": now - 30 * H}]}
    adv = FakeAdvisor({"market": 0.6, "BTC": 2.0, "ETH": -0.1, "alts": "x"})
    st = sentiment.collect(db, heads, adv, now)
    assert st["scored"] == 3 and st["source"] == "headlines" and st["headlines"] == 1
    assert [h["title"] for h in adv.seen[0]["headlines"]] == ["ETF inflows hit record"]
    rows = {r["grp"]: r for r in db.query("SELECT * FROM news_sentiment")}
    assert rows["BTC"]["score"] == 1.0 and "alts" not in rows and rows["market"]["known_at"] == now
    assert sentiment.collect(db, heads, adv, now + 60_000)["skipped"] == "already scored this hour" and adv.calls == 1
    # a score is only visible from the moment it was made
    assert sentiment.as_of(db, now - 1) is None and sentiment.as_of(db, now) == 0.6
    # no headlines and no calendar: nothing is invented
    db2 = Database("sqlite:///:memory:")
    assert "skipped" in sentiment.collect(db2, {"items": []}, FakeAdvisor({"market": 0.1}), now)
    assert db2.one("SELECT COUNT(*) AS n FROM news_sentiment")["n"] == 0
    assert not sentiment_gate.decide(db)["on"]                    # collection only


def test_sentiment_falls_back_to_the_calendar():
    db = Database("sqlite:///:memory:")
    now = 1_760_000_000_000
    db.execute("INSERT INTO econ_events (id, ts, country, title, impact, updated_at) VALUES ('e', ?, 'USD', 'CPI y/y', 'High', ?)",
               (now + 2 * H, now))
    adv = FakeAdvisor({"market": -0.2, "BTC": -0.2, "ETH": -0.2, "alts": -0.3})
    st = sentiment.collect(db, None, adv, now)
    assert st["source"] == "calendar" and adv.seen[0]["calendar"][0]["title"] == "CPI y/y"


def test_filter2_switches_on_only_when_it_helps_on_unseen_trades():
    rng = np.random.default_rng(0)
    n = 1200
    F = rng.normal(size=(n, len(TF2.FEATURES)))
    ts = np.arange(n)
    good = F[:, 0] > 0
    R = np.where(rng.random(n) < np.where(good, 0.7, 0.3), 1.0, -1.0)
    on = TF2.train(F, R, ts)
    assert on["enabled"] and on["exam"]["avg_r_kept"] > on["exam"]["avg_r_all"]
    noise = TF2.train(F, np.where(rng.random(n) < 0.5, 1.0, -1.0), ts)
    assert "exam" in noise or "reason" in noise                 # trains or says why not - never crashes
    few = TF2.train(F[:100], R[:100], ts[:100])
    assert not few["enabled"] and "only 100" in few["reason"]
    assert TF2.score(few, F[0]) is None


def test_filter2_save_and_load(tmp_path):
    old = settings.model_dir
    settings.model_dir = str(tmp_path)
    try:
        db = Database("sqlite:///:memory:")
        rng = np.random.default_rng(1)
        F = rng.normal(size=(800, len(TF2.FEATURES)))
        R = np.where(F[:, 1] > 0, 1.0, -1.0) * np.where(rng.random(800) < 0.8, 1, -1)
        f = TF2.train(F, R, np.arange(800))
        TF2.save(db, "1h", f)
        g = TF2.load(db, "1h")
        assert (g is not None) == bool(f["enabled"])
        if g:
            assert abs(TF2.score(g, F[0]) - TF2.score(f, F[0])) < 1e-12
        TF2.save(db, "4h", {"enabled": False, "reason": "x"})
        assert TF2.load(db, "4h") is None
    finally:
        settings.model_dir = old


def test_structure_stop_in_the_live_setup():
    from app.engine.setup import build_setup
    from app.features.dataset import build_frame
    from app.features.structure import sr_zones
    from tests.helpers import synthetic_candles
    fr = build_frame(synthetic_candles(1500, "4h", seed=3), "4h")
    last = fr.ind.iloc[-1]
    zones = sr_zones(fr.swings, float(last["close"]), float(last["atr"]), len(fr.df))
    for side in (1, -1):
        a = build_setup(fr.ind, zones, side)
        b = build_setup(fr.ind, zones, side, stop_mode="struct")
        assert 1.0 - 1e-9 <= a["stop_distance_atr"] <= 3.0 + 1e-9
        assert 0.8 - 1e-9 <= b["stop_distance_atr"] <= 3.5 + 1e-9
        # targets are re-derived in R from the new stop
        d = abs(b["ideal_entry"] - b["stop"])
        assert abs(abs(b["targets"][0]["price"] - b["ideal_entry"]) - d) < 1e-9


def test_v26_settings_default_off_until_proven():
    # the proof (python -m app.research engine) decides the defaults; see CLAUDE.md "v2.6 accuracy upgrades"
    assert settings.news_sentiment is True                   # collection only, never used by a decision
    from app.services import series_nightly
    # defaults from the proof: entry rules and the pooled filter on; gate, per-series threshold, structure stops off
    assert settings.entry_rules and settings.trade_filter2
    assert not (settings.series_gate or settings.series_conf or settings.struct_stops)
    # without a nightly choice the v2.5 entry rule stays
    assert series_nightly.entry_rule(Database("sqlite:///:memory:"), "1h") == ("old", 0.0)


def test_confirmation_entry_in_the_record():
    """ENTRY_RULES confirm: PENDING until a 15m candle closes beyond the level; entered at that close, targets in R."""
    import pandas as pd
    from app.services import tracking

    class RT:
        def __init__(self, bars):
            self.db = Database("sqlite:///:memory:")
            self.df = pd.DataFrame(bars, columns=["ts", "open", "high", "low", "close", "volume"])

        def candles(self, s, tf):
            return self.df

    M15 = 900_000
    old = settings.entry_rules
    settings.entry_rules = True
    try:
        bars = [[0, 100, 100.2, 99.9, 100.1, 1], [M15, 100.1, 100.6, 100.0, 100.5, 1],     # closes above 100.25: confirmed
                [2 * M15, 100.5, 102.6, 100.4, 102.5, 1], [3 * M15, 102.5, 102.9, 102, 102.8, 1]]
        rt = RT(bars)
        rt.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                      "tp1, tp2, tp3, status, payload, fill_status) VALUES ('s', 0, 'BTC/USDT', '15m', ?, 'BUY', 'BUY', 100, 1, "
                      "100, 98, 102, 103.5, 105, 'OPEN', ?, 'PENDING')",
                      (-M15, '{"entry_rule": {"mode": "confirm", "k": 0.25, "level": 100.25, "price": 100, "atr": 1}}'))
        tracking.update_signal_outcomes(rt, now=4 * M15)
        r = rt.db.one("SELECT * FROM signals")
        assert r["fill_status"] == "FILLED" and abs(r["entry"] - 100.5) < 1e-12 and r["filled_at"] == 2 * M15
        assert abs(r["tp1"] - (100.5 + 2.5)) < 1e-12                       # 1R from the actual entry (risk 2.5)
        # the candle that confirmed is not part of the trade; the next one does not reach TP1 (103) -> still open
        assert r["status"] == "OPEN" and not r["tp1_hit"]
        # never confirmed, stop traded first -> NOT_FILLED, no return
        rt2 = RT([[0, 100, 100.2, 97.9, 98.5, 1], [M15, 98.5, 101, 98.4, 100.9, 1]])
        rt2.db.execute("INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, "
                       "tp1, tp2, tp3, status, payload, fill_status) VALUES ('s', 0, 'BTC/USDT', '15m', ?, 'BUY', 'BUY', 100, 1, "
                       "100, 98, 102, 103.5, 105, 'OPEN', ?, 'PENDING')",
                       (-M15, '{"entry_rule": {"mode": "confirm", "k": 0.25, "level": 100.25, "price": 100, "atr": 1}}'))
        tracking.update_signal_outcomes(rt2, now=2 * M15)
        r2 = rt2.db.one("SELECT * FROM signals")
        assert r2["status"] == "NOT_FILLED" and r2["return_pct"] is None
    finally:
        settings.entry_rules = old
