"""v2: economic calendar + headlines, the news guard, and leak-free futures-positioning features."""
import json

import numpy as np
import pandas as pd

from app.data import derivs
from app.db import Database
from app.features.dataset import DERIV_COLS, build_frame, make_dataset
from app.services import news

from .helpers import synthetic_candles

HOUR = 3_600_000


class Resp:
    def __init__(self, code=200, data=None, content=b""):
        self.status_code, self._d, self.content = code, data, content

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Bitcoin jumps after CPI</title><link>https://x.test/a</link><pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;BTC up&lt;/p&gt;</description></item>
<item><title>Bitcoin jumps after CPI!</title><link>https://y.test/a</link><pubDate>Mon, 26 Oct 2026 09:00:00 GMT</pubDate></item>
</channel></rss>"""


class Sess:
    def __init__(self, cal):
        self.cal = cal

    def get(self, url, **kw):
        if "thisweek" in url:
            return Resp(200, self.cal)
        if "nextweek" in url:
            return Resp(404)
        return Resp(200, content=RSS)


def test_calendar_keeps_relevant_events_and_guard_pauses_entries():
    db = Database("sqlite:///:memory:")
    t = 1_793_000_000_000 // HOUR * HOUR
    iso = lambda ms: pd.Timestamp(ms, unit="ms", tz="UTC").isoformat()  # noqa: E731
    cal = [{"title": "CPI m/m", "country": "USD", "date": iso(t), "impact": "High", "forecast": "0.3%", "previous": "0.4%"},
           {"title": "Retail Sales", "country": "USD", "date": iso(t + 5 * HOUR), "impact": "Medium"},
           {"title": "Bank Holiday", "country": "USD", "date": iso(t), "impact": "Holiday"},
           {"title": "German ZEW", "country": "EUR", "date": iso(t), "impact": "Medium"}]
    st = news.sync_calendar(db, Sess(cal))
    assert st["events"] == 2 and not st["errors"]
    news.sync_calendar(db, Sess(cal))                       # idempotent
    assert len(news.events(db, t - HOUR, t + 10 * HOUR)) == 2
    assert news.event_risk(db, t - 40 * 60_000)["minutes"] == 40
    assert news.event_risk(db, t + 20 * 60_000) is not None and news.event_risk(db, t + 40 * 60_000) is None
    assert news.event_risk(db, t - 60 * 60_000) is None
    assert "Inflation" in news.events(db, t - HOUR, t + HOUR)[0]["explain"]
    due = news.due_notifications(db, now=t - 20 * 60_000)
    assert len(due) == 1 and due[0]["broadcast"] and news.due_notifications(db, now=t - 10 * 60_000) == []
    h = news.headlines(Sess(cal))
    assert len(h["items"]) == 1 and h["items"][0]["summary"] == "BTC up"    # near-duplicate dropped, tags stripped


class HL:
    """Fake Hyperliquid: hourly funding from `start` to `end`."""
    def __init__(self, start, end):
        self.start, self.end, self.calls = start, end, 0

    def post(self, url, json=None, timeout=None):
        self.calls += 1
        if json["type"] == "meta":
            return Resp(200, {"universe": [{"name": "BTC"}, {"name": "kPEPE"}]})
        s = max(self.start, int(json["startTime"]) // HOUR * HOUR + (HOUR if int(json["startTime"]) % HOUR else 0))
        ts = list(range(s, min(self.end, s + 500 * HOUR), HOUR))
        return Resp(200, [{"coin": json["coin"], "time": t + 7, "fundingRate": str(1e-5 * ((t // HOUR) % 7 - 3)),
                           "premium": str(-2e-4)} for t in ts])


def test_derivs_sync_forward_and_backfill():
    derivs._universe = None
    db = Database("sqlite:///:memory:")
    now = 1_793_000_000_000 // HOUR * HOUR
    hl = HL(now - 60 * 86_400_000, now)
    out = derivs.sync(db, ["BTC/USDT", "PEPE/USDT", "XAUT/USDT"], history_days=90, max_calls=50, session=hl, now=now)
    assert out["unsupported"] == ["XAUT/USDT"] and not out["errors"]
    df = derivs.load(db, "BTC/USDT")
    assert df["ts"].diff().dropna().eq(HOUR).all() and df["ts"].iloc[-1] >= now - 2 * HOUR
    assert 59 <= derivs.coverage_days(db, "BTC/USDT") <= 61 and len(derivs.load(db, "PEPE/USDT")) == len(df)


def test_deriv_features_have_no_look_ahead_and_keep_old_rows():
    base = synthetic_candles(3000, "1h", seed=5)
    ts = base["ts"].to_numpy()
    hrs = np.arange(ts[1000], ts[-1] + HOUR, HOUR)
    d = pd.DataFrame({"ts": hrs, "funding": np.sin(hrs / 7e7) * 1e-4, "premium": np.cos(hrs / 5e7) * 1e-3})
    full = make_dataset(build_frame(base, "1h"), deriv=d)
    assert all(c in full.feature_names for c in DERIV_COLS)
    assert full.X["deriv_avail"].iloc[:990].eq(0).all() and full.X["deriv_avail"].iloc[1100:].eq(1).all()
    plain = make_dataset(build_frame(base, "1h"))
    assert (full.trainable == plain.trainable).all()         # rows before the futures data are still trainable
    cut = 2500
    end = int(ts[cut - 1]) + HOUR
    part = make_dataset(build_frame(base.iloc[:cut], "1h"), deriv=d[d["ts"] <= end])
    A, B = full.X[DERIV_COLS].iloc[:cut].to_numpy(float), part.X[DERIV_COLS].to_numpy(float)
    assert np.allclose(A, B)
    # a bar sees the funding published at its close, not later
    k = 2000
    assert np.isclose(full.X["fund_1h"].iloc[k], d.loc[d["ts"] == ts[k] + HOUR, "funding"].iloc[0] * 1e4)
    # stale data (> 3 h old) counts as unavailable
    gap = make_dataset(build_frame(base, "1h"), deriv=d[d["ts"] <= ts[2000]])
    assert gap.X["deriv_avail"].iloc[2010:].eq(0).all()


def _store_series(db, symbol, ts, funding):
    db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, 'funding_1h', ?, ?)",
                   [(symbol, int(t), float(v)) for t, v in zip(ts, funding)])
    db.executemany("INSERT INTO derivs (symbol, kind, ts, value) VALUES (?, 'premium_1h', ?, 0)", [(symbol, int(t)) for t in ts])


def test_gate_turns_features_on_only_when_they_help():
    from app.ml import deriv_gate

    base = synthetic_candles(3200, "1h", seed=9)
    fr = build_frame(base, "1h")
    ts = base["ts"].to_numpy()
    c = base["close"].to_numpy()
    nxt = np.r_[c[2:] / c[1:-1] - 1, 0, 0]                     # the return of the bar AFTER the one closing at ts+1h
    rng = np.random.default_rng(1)
    good, noise = Database("sqlite:///:memory:"), Database("sqlite:///:memory:")
    _store_series(good, "BTC/USDT", ts + HOUR, nxt * 0.05 + rng.normal(0, 2e-4, len(ts)))
    _store_series(noise, "BTC/USDT", ts + HOUR, rng.normal(0, 1e-4, len(ts)))
    on = deriv_gate.decide(good, "BTC/USDT", "1h", fr, None, None)
    off = deriv_gate.decide(noise, "BTC/USDT", "1h", fr, None, None)
    assert on["on"] and on["hit_deriv"] > on["hit_base"], on
    assert not off["on"], off
    assert deriv_gate.cached(good, "BTC/USDT", "1h")["on"]
