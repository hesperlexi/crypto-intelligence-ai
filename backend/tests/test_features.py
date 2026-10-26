

def test_btc_context_lines_up_when_3d_candles_start_on_different_days():
    import numpy as np
    import pandas as pd
    from app.data.base import to_frame
    from app.features.dataset import build_frame, make_dataset

    day = 86_400_000
    rng = np.random.default_rng(1)

    def candles(start, n):
        ts = [start + i * 3 * day for i in range(n)]
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
        return to_frame([[t, x, x * 1.02, x * 0.98, x, 1000 + i] for i, (t, x) in enumerate(zip(ts, c))])
    btc = build_frame(candles(0, 700), "3d")
    coin = build_frame(candles(day, 600), "3d")                 # starts one day later: never the same open time
    ds = make_dataset(coin, btc)
    assert ds.trainable.sum() > 300                              # was 0 with exact-time matching
    X = ds.X
    k = X.index[400]
    prev_btc = btc.ind.index[btc.ind.index <= k][-1]
    assert prev_btc < k and prev_btc + pd.Timedelta(days=3) <= k + pd.Timedelta(days=3)   # closed by the coin bar's close
    assert abs(X.loc[k, "btc_tech"] - btc.ind.loc[prev_btc, "tech_score"]) < 1e-12
