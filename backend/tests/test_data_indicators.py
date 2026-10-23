"""Market-data plumbing and indicator maths."""
import asyncio
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from app.data.base import closed_only, resample_ohlcv, tf_ms, to_frame
from app.data.csv_provider import CSVProvider
from app.data.quality import check_candles
from app.features import indicators as I
from tests.helpers import synthetic_candles


def test_sma_and_bollinger_mid_match():
    df = synthetic_candles(300)
    mid, upper, lower, width, pctb = I.bollinger(df["close"])
    assert np.allclose(mid.dropna(), I.sma(df["close"], 20).dropna())
    assert (upper.dropna() >= lower.dropna()).all()
    assert abs(I.sma(pd.Series([1.0, 2, 3, 4, 5]), 5).iloc[-1] - 3.0) < 1e-12


def test_rsi_extremes():
    up = pd.Series(np.arange(1.0, 60.0))
    down = pd.Series(np.arange(60.0, 1.0, -1))
    assert I.rsi(up).iloc[-1] == 100.0
    assert I.rsi(down).iloc[-1] < 1e-9
    r = I.rsi(synthetic_candles(500)["close"]).dropna()
    assert r.between(0, 100).all()


def test_macd_and_atr_identities():
    df = synthetic_candles(400)
    line, sig, hist = I.macd(df["close"])
    assert np.allclose((line - sig).dropna(), hist.dropna())
    assert (I.atr(df).dropna() > 0).all()
    adx, pdi, mdi = I.adx(df)
    assert adx.dropna().between(0, 100).all()


def test_donchian_excludes_current_bar():
    df = synthetic_candles(100)
    upper, lower, _ = I.donchian(df, 20)
    i = 50
    assert upper.iloc[i] == df["high"].iloc[i - 20:i].max()
    assert lower.iloc[i] == df["low"].iloc[i - 20:i].min()


def test_ichimoku_cloud_is_lagged_not_leading():
    df = synthetic_candles(300)
    tenkan, kijun, span_a, span_b = I.ichimoku(df)
    i = 200
    assert abs(span_a.iloc[i] - (tenkan.iloc[i - 26] + kijun.iloc[i - 26]) / 2) < 1e-9


def test_resample_matches_manual_aggregation():
    base = synthetic_candles(4000, "15m")
    h4 = resample_ohlcv(base, "15m", "4h")
    row = h4.iloc[10]
    chunk = base[(base["ts"] >= row["ts"]) & (base["ts"] < row["ts"] + tf_ms("4h"))]
    assert len(chunk) == 16
    assert row["open"] == chunk["open"].iloc[0] and row["close"] == chunk["close"].iloc[-1]
    assert row["high"] == chunk["high"].max() and row["low"] == chunk["low"].min()
    assert abs(row["volume"] - chunk["volume"].sum()) < 1e-6


def test_closed_only_drops_forming_candle():
    df = synthetic_candles(50, "1h")
    last_open = int(df["ts"].iloc[-1])
    assert len(closed_only(df, "1h", last_open + tf_ms("1h") - 1)) == 49      # still forming
    assert len(closed_only(df, "1h", last_open + tf_ms("1h"))) == 50          # just closed


def test_quality_detects_gaps_duplicates_and_bad_candles():
    df = synthetic_candles(200, "1h")
    now = int(df["ts"].iloc[-1]) + tf_ms("1h")
    assert check_candles(df, "1h", now)["quality_pct"] == 100.0
    gappy = df.drop(df.index[[50, 51, 120]])
    q = check_candles(gappy, "1h", now)
    assert q["missing"] == 3 and q["quality_pct"] < 100 and len(q["gaps"]) == 2
    bad = df.copy()
    bad.iloc[10, bad.columns.get_loc("high")] = bad["low"].iloc[10] / 2      # high below low
    assert check_candles(bad, "1h", now)["malformed"] == 1
    raw = pd.concat([df, df.iloc[-3:]])
    assert check_candles(to_frame(raw), "1h", now, raw_rows=len(raw))["duplicates"] == 3
    assert check_candles(df, "1h", now + 10 * tf_ms("1h"))["status"] == "STALE"
    assert check_candles(df.iloc[:0], "1h", now)["status"] == "NO DATA"


def test_csv_provider_reads_binance_export_and_never_invents_data():
    d = Path(tempfile.mkdtemp())
    df = synthetic_candles(120, "4h")
    rows = df[["ts", "open", "high", "low", "close", "volume"]].copy()
    rows["close_time"] = rows["ts"] + tf_ms("4h") - 1
    rows["ts"] = rows["ts"] * 1000                      # newer Binance dumps use microseconds
    rows.to_csv(d / "BTCUSDT_4h.csv", header=False, index=False)
    p = CSVProvider(str(d))
    got = asyncio.run(p.fetch_ohlcv("BTC/USDT", "4h", limit=1000))
    assert len(got) == 120 and int(got[0][0]) == int(df["ts"].iloc[0])
    try:
        asyncio.run(p.fetch_ohlcv("ETH/USDT", "4h"))
        raise AssertionError("a missing file must raise, never fabricate candles")
    except FileNotFoundError:
        pass
