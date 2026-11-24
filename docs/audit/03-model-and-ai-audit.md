# 03 · Model and AI audit

Evidence: live model registry snapshot (`research-results/results/usage-latest.json`, 24 Nov 12:29 UTC, run for this audit),
model value study (`models-value-latest.json`, 17 Nov, 233 series), model-set study (`modelset-<tf>-latest.json`, 17 Nov),
challenger log (`v3-review.json`, 24 Nov), quick status (`reports/quick-status.json`, 24 Nov), code.

## 1. Are the models trained, fresh and loaded?

| Timeframe | Active bundles | Retrained in last 12 h (watched coins) | Oldest model (h) | Coins without a model |
|---|---|---|---|---|
| 15m | 46 | 0 of 30 | 105 | 0 |
| 1h | 46 | 0 of 30 | 33 | 0 |
| 4h | 45 | 26 of 30 | 33 | 1 |
| 12h | 41 | 25 of 30 | 33 | 1 |
| 1d | 37 | 26 of 30 | 33 | 3 |
| 3d | 28 | 22 of 30 | 4 | 8 |

* Training runs every night and **completed 7 of 7 nights** this week (train.yml). Load errors: **0**.
* **15m models are up to 4.4 days old** (F-11, P2): the nightly slices are cost-ordered and 15m (most expensive) rotates. For
  the fastest timeframe this is the stalest set. Check whether 15m should get a fixed share of each night.
* New coins lack history: 8 coins have no 3d model, 3 no 1d (expected; they publish nothing there).
* Champion / challenger is **on** (V3): 383 retrains judged since 21 Nov, 7 refused (kept the old model). Working as designed.

## 2. Are the models used as intended?

| Add-on | Switched on (where proven) | Evidence |
|---|---|---|
| Ensemble (every bundle) | 251 bundles | used for every analysis |
| Trade filter v1 (per model) | 15m 23/46 · 1h 11/46 · 4h 12/45 · 12h 13/41 · 1d 8/37 · 3d 3/28 | blocks calls on 1h/4h/12h/1d/3d; **off on 15m** since v2.64 (scores still computed) |
| Trade filter 2 (pooled) | 1d, 3d (exam passed: 3d +0.43R kept vs +0.38R all; 1d +0.02R vs −0.01R) | nightly exam |
| Runner ("let winners run") | 42 bundles | per-bundle exam |
| AI targets | 16 bundles | Brier-skill exam |
| Futures-data gate | 12 bundles | paired test per series |
| Higher-timeframe gate | 21 bundles | paired test per series |
| Series policy gate | built for 187 series, **blocks 0** (`SERIES_GATE` off by evidence) | |
| Sentiment gate | stub, off (needs ≥ 60 days of `news_sentiment`) | |
| Drift | used inside the capital-protection veto (last 100 live forecasts vs out-of-sample hit rate) | |
| Deep models (LSTM, GRU, Transformer) | 7 bundles on 15m, 6 weekly | forces a PyTorch install in every engine and training run (F-20, P3) |

All add-ons are switched on **only where their own out-of-sample test passed** — this is the right design and it is
implemented (`trainer.OFF_REASON`, per-bundle `enabled` flags).

## 3. Do the models add value? (17 Nov studies, out-of-sample)

**Skill vs the simple base rate (median over 233 series, Brier):**

| Model | Median skill | Series with positive skill | Mean ensemble weight |
|---|---|---|---|
| Random Forest | +0.0030 | 70 % | 0.41 |
| Transformer / LSTM / GRU (7 series only) | +0.003 | 57-71 % | 0.07-0.08 |
| Previous candle | −0.0001 | 48 % | 0.00 |
| Technical rules | −0.0030 | 21 % | 0.11 |
| Logistic regression | −0.0049 | 33 % | 0.13 |
| XGBoost | −0.0059 | 30 % | 0.10 |
| LightGBM | −0.0088 | 25 % | 0.08 |
| HistGradientBoosting | −0.0092 | 28 % | 0.09 |
| ARIMA | −0.0210 | 9 % | 0.08 |

**Finding F-12 (P1, evidence, not a bug):** only Random Forest beats the base rate in most series. Models with negative
median skill still get about **60 % of the ensemble weight** together (0.11 + 0.13 + 0.10 + 0.08 + 0.09 + 0.08). The weights come from walk-forward performance per
series, so a weak model can still win weight in a few series — but on average they dilute the forecast.

**But "Random Forest only" is not clearly better as a trading rule** (model-set study, test split, net R per trade):

| TF | All models | No ARIMA | RF only | RF-only better in |
|---|---|---|---|---|
| 15m | +0.070 (446) | +0.002 | +0.035 | 24 % of series |
| 1h | +0.007 (399) | −0.024 | +0.010 | 54 % |
| 4h | +0.036 (536) | +0.030 | +0.054 | 81 % |
| 12h | +0.009 (248) | **+0.090** (live since v2.57) | +0.056 | 80 % |
| 1d | −0.051 (115) | −0.084 | −0.035 | 60 % |
| 3d | −0.067 (16) | −0.218 | −0.299 | 1 % |

So the full ensemble is right for 15m, "no ARIMA" was right for 12h (already live), and 4h might gain from RF-only (81 %,
interval still includes zero → not proven). **Recommendation:** re-run the model-set study on 4h with the current
`research_verdict` before any change; do not remove models from 15m.

## 4. Calibration, edge and drift

* Ensemble skill > 0 in 91 % (15m), 84 % (1h), 74 % (4h), 33 % (12h), 14 % (1d), 4 % (3d) of series; calibration error
  1-2.5 % on 15m-4h, 4-10 % on 12h-3d (17 Nov study). Long timeframes are poorly calibrated — consistent with 1d being
  demo-only and 3d publishing almost nothing.
* **`edge_confirmed` = 0 of 251 bundles** (F-13, P1, evidence): no bundle passes the strict "edge confirmed" test. Signals
  are published because the owner switched the edge requirement off (v2.14). The live record since 4 Nov is positive
  (110 closed, +21.8R net, see 05), but the replay test split is thin (+0.016R per trade over 500 calls). Members should
  not read the grade as proven edge; the app already avoids showing a confidence % (v2.17).
* Look-ahead: features use closed candles; crowd data carries a 2-day publication lag; BTC context aligns to the latest
  BTC bar opened by the coin bar's open; OKX / liquidation data store `known_at`. No leak found in the code paths read.
  A full leakage test would need a dedicated replay (not run).
* Drift: checked per live call inside the capital-protection veto; no member-facing view (admin "AI check" exists).

## 5. AI texts (Gemini)

Briefing, coin reports, Guardian second opinion, advisor notes, Ask Cintel. All are advisory, numbers-checked
(`numbers_ok`), never change a decision. Fine. The daily Gemini usage is not shown on Health (F-21, P3).
