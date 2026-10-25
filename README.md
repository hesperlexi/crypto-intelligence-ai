# Crypto Intelligence AI

Multi-model crypto forecasting, market-regime and trading-signal research platform, with demo trading bots
that measure how accurate the predictions really are.

It estimates the **probability distribution** of the next move, classifies the market regime, turns that into
transparent buy / sell / hold signals with risk-defined trade plans, and **refuses to trade when the evidence is
insufficient**. It never places real orders: the bots and the paper account use virtual money. Every number on
screen comes from live market data, a model evaluation or a recorded outcome. Nothing is hardcoded.

> Research tool, not financial advice.

---

## 1. How it runs (all free)

```
 Firebase Hosting  ──  the website (React), Google sign-in
        │  reads / writes
 Cloud Firestore   ──  published results (views/*), your settings, alert rules, demo-bot settings,
        ▲               paper account, job queue
        │  writes every 15 minutes
 GitHub Actions    ──  the Python engine: downloads candles from Binance's public data API, trains models,
                        runs every analysis, the demo bots, alerts and queued backtests / replays
 Your browser      ──  live prices, charts and order books come straight from Binance's public API
```

* **Engine:** `.github/workflows/engine.yml` runs every 15 minutes (GitHub sometimes starts scheduled runs a few
  minutes late). `train.yml` refreshes models with the full model set once a day. State (candles, models,
  predictions, bot books) is kept in the GitHub Actions cache between runs.
* **Website:** `deploy.yml` runs the tests and deploys the site and the Firestore security rules on every push.
* **Cost:** Firebase Spark (free) plan + a **public** GitHub repository (unlimited free Actions minutes).
  A private repo only has 2,000 free minutes a month, which a 15-minute schedule would exceed.

## 2. Deploy (one time, about 20 minutes)

You need a Google account (the one that owns the Firebase project) and a free GitHub account.

**A. Firebase console** (https://console.firebase.google.com, project `crypapp-6a9b9`)

1. **Firestore:** Build → Firestore Database → *Create database* → pick a location (e.g. `eur3` or
   `me-central2`) → *Start in production mode*.
2. **Sign-in:** Build → Authentication → *Get started* → Sign-in method → **Google** → Enable → Save.
3. **Key for GitHub:** Project settings (gear icon) → *Service accounts* → *Generate new private key*. A JSON file
   downloads. Keep it private: it is the engine's password to your database.
4. **Permissions for deploying:** open https://console.cloud.google.com/iam-admin/iam?project=crypapp-6a9b9 ,
   click the pencil next to the account named `firebase-adminsdk-…`, *Add another role* → **Firebase Admin**,
   add another → **Service Usage Consumer** → Save.

**B. GitHub**

5. Create a new **public** repository (e.g. `crypto-intelligence-ai`), with nothing in it.
6. Unzip the project and upload its **contents** (not the outer folder) with *Add file → Upload files*, dragging
   the folders in. GitHub accepts 100 files per upload, so upload `backend` first, commit, then everything else.
   Make sure the hidden `.github` folder is included (macOS: press Cmd+Shift+. in Finder to show it).
   Alternatively use GitHub Desktop, which handles all of this in one go.
7. Settings → Secrets and variables → Actions:
   * *Secrets* tab → New repository secret → name `FIREBASE_SERVICE_ACCOUNT`, value = the **whole contents** of
     the JSON key file from step 3.
   * *Variables* tab → New repository variable → name `ADMIN_EMAILS`, value = the Google e-mail(s) allowed to
     use the site, comma-separated. Optional: `SYMBOLS` to change the starting coin list.
8. Actions tab → enable workflows if asked → run **Test and deploy website** (or push any change), then run
   **Engine (every 5 minutes)** once by hand with *Run workflow*.

Open **https://crypapp-6a9b9.web.app** and sign in with Google.

**What to expect:** the first engine run downloads history and trains a fast first model set (about 10-15
minutes). Until it finishes, pages say the engine has not published yet. From then on everything refreshes
every 15 minutes; the daily training run upgrades models to the full set (XGBoost, LightGBM, ARIMA, random
forest and others) over the following days.

**If something fails:** the Actions tab shows a red run with the error. The usual causes are a missing secret or
variable (the message says which), Firestore not created (step 1), or the deploy account missing a role (step 4).
Paste the error into this chat and it can be fixed.

## 3. Using it

* **Asset pages, Dashboard, Scanner, Accuracy, Signals, Health:** read the engine's latest published results.
  Prices, charts, order books and funding data stream live from Binance in your browser.
* **Demo bots (new):** four bots start automatically. **Signal bots** (1H, 4H) trade only the engine's final
  BUY / SELL decisions with the trade plan's entry, stop and three targets. **Prediction trackers** (1H, 4H) trade
  every model call for exactly one bar, which measures the raw prediction accuracy. Each bot shows equity vs
  buy & hold of the same coins, win rate, direction accuracy with a confidence interval, accuracy by model
  probability, profit factor, drawdown, fees and every trade. You can pause, reset, edit, add or delete bots.
* **Members (v1.2):** anyone can sign in with Google; new accounts see "Request sent" until you approve them on the
  **Users** page (admins = the emails in ADMIN_EMAILS). Members see all predictions, Futures, Accuracy and the bots,
  can run backtests / replays, and get their own spot and futures paper accounts, alerts and notifications.
  Only admins change coins, bots, engine settings and users. Enforced by the Firestore rules, not just the UI.
* **Futures (v1.1):** a Futures page with a LONG / SHORT / NO TRADE call per coin and timeframe (1H, 4H, 12H, 1D),
  the up / down probabilities, the trade plan (entry, stop, three targets), a suggested leverage that keeps the
  liquidation price at least 1.5x the stop distance away (max 10x), the liquidation price, and live funding,
  open interest and long/short ratios from Binance futures (fetched by your browser). A leverage & liquidation
  calculator is included. **Futures demo bots** (signal 4H, signal 1H, prediction tracker 1H) trade the same calls
  as perpetuals with isolated margin, 0.05% fees, 8-hourly funding and liquidation. **Futures paper trading**
  (Paper → Futures) lets you open longs and shorts with 1-50x leverage, stop-loss and take-profit; triggers are
  checked on every 15-minute candle, including while the app was closed. Virtual money only.
* **Deep models:** LSTM, GRU and Transformer encoder models are trained by the daily training run (CPU PyTorch is
  installed by the workflows). Existing models are retrained once to include them; this can take two or three
  daily runs for all coins.
* **Backtest, Replay, Retrain, Fit weights:** these are queued and run by the next engine cycle, so results
  arrive within about 15 minutes.
* **Watchlist, settings, alert rules:** saved immediately; the engine applies them on its next cycle.
* **Paper trading:** manual virtual orders, filled at the live Binance price plus costs, stored in Firestore.

**Free-tier limits.** Firestore's free quota is 20,000 writes a day. With 10 coins the engine uses roughly 7,000;
unchanged documents are skipped. Adding many more coins can approach the limit. GitHub disables scheduled
workflows in a repository with no commits for 60 days; re-enable them in the Actions tab if that happens.

**Install it as an app (PWA).** Open the site in Chrome or Edge (computer or Android) and click **Install app**
in the top bar, or the install icon in the address bar. On iPhone / iPad: open it in Safari → **Share** →
**Add to Home Screen**. It then opens full-screen with its own icon. Live data still needs internet.
On phones, the main sections are in the bottom bar; the rest are under **More**.

## 4. What has and has not been verified

Written in a sandbox with no access to Binance, Firebase, GitHub, PyPI or npm, so:

| Area | State |
|---|---|
| Indicators, structure, models, walk-forward, calibration, edge test, backtester, engines | **Tested** (72 automated tests, synthetic candles) |
| Engine cycle: config sync, model bootstrap, analyses, alerts, jobs, demo bots, publishing | **Tested** end to end against a local stand-in for Firestore |
| Demo bot accounting: fills, partial targets, break-even stops, pullback limits, prediction tracking, costs | **Tested** |
| Every website page, reading real engine output and writing settings / jobs / alerts | **Tested** in a headless browser with stand-ins for Firebase, the router and the chart library |
| Real Firebase (sign-in, Firestore, rules, Hosting deploy), GitHub Actions workflows | **Written, not run** |
| Binance data from GitHub's servers (`data-api.binance.vision`) and from the browser | **Written, not run** |
| XGBoost, LightGBM, ARIMA (installed on the runner), Tailwind styling, real chart library | **Written, not run** |

No result on real market data exists yet. The first deploy is the first real run, so expect to fix a few small
integration issues. Binance blocks its main API from US servers, which is where GitHub runs, so the engine uses
Binance's public market-data mirror; if that is also refused, the engine run shows the error.

---

## How the analysis works

```
exchange (CCXT REST + WebSocket)  ->  candle store (SQLite / Postgres)  ->  closed candles only
        |                                                                        |
   live tickers  -> /ws -> UI                 indicators, structure, volatility, volume  (all causal)
                                                                                 |
                              +--------------------------+-----------------------+----------------------+
                              |                          |                                              |
                       regime engine              feature matrix                              component scores
                       (rule-based)        (60+ stationary features)                  trend / momentum / volume / structure
                              |                          |                                              |
                              |             walk-forward: train -> calibrate -> test                    |
                              |             models -> calibrated probabilities -> weighted ensemble     |
                              |             edge test vs benchmarks, forecast ranges, confidence        |
                              +--------------------------+-----------------------+----------------------+
                                                         |
                          signal engine (weighted, explained)  +  multi-timeframe confirmation
                                                         |
                          entry / stop / targets  ->  decision gates  ->  BUY | BUY ON PULLBACK | HOLD | SELL | NO TRADE
                                                         |
                          risk sizing (independent of the model), alerts, paper trading, tracking
```

### Forecasting

* **One model set per timeframe.** The 1H forecast comes from the 1h model, 24H from the 1d model, 7D from the
  1w model, each one bar ahead. Nothing is extrapolated from a shorter timeframe.
* **Targets.** Direction class (up / neutral / down, neutral band = 0.25 bar-sigmas), expected return,
  probability of touching +2 / +5 / +10% and -2 / -5%, and 50 / 80 / 95% forecast ranges.
* **Models.** Class-prior and previous-candle baselines, logistic regression, a technical-rules model, random
  forest, scikit-learn gradient boosting, XGBoost, LightGBM, ARIMA, and optionally LSTM / GRU / Transformer.
  A model whose library is missing is listed as unavailable, never silently replaced.
* **Walk-forward validation.** Rolling train -> validation -> test windows with a purge gap, never shuffled.
  Scalers are fitted on training rows only. The **Accuracy** page draws the timeline.
* **Calibration.** Platt (200+ validation rows) or isotonic (1000+), and only if it lowers Brier score on
  the part of the validation window it was not fitted on. Raw and calibrated probabilities are both shown.
* **Ensemble.** Weights come from recent out-of-sample Brier skill versus the class prior, multiplied by
  prediction stability, with regime-specific weights where a regime has enough rows. Models whose *live*
  Brier score falls below the prior are halved.
* **Forecast ranges.** Quantiles of volatility-standardised out-of-sample errors, rescaled by current volatility.
  Their real coverage on held-out errors is reported next to them.
* **Confidence.** The realised hit-rate of past out-of-sample predictions with the same class, the same
  probability bin and (when there are at least 30 such cases) the same volatility state. If there are too few
  comparable cases, no confidence is shown.

### The edge test

A model is described as having an edge only if, on out-of-sample bars and after fees, spread and slippage, it

1. earns more than Buy & Hold, previous-candle, SMA-cross and simple-RSI strategies,
2. beats randomly-timed versions of itself (same exposure and turnover) at `EDGE_ALPHA`,
3. classifies direction better than the class prior at `EDGE_ALPHA`,
4. has at least `MIN_OOS_FOR_EDGE` out-of-sample predictions.

Otherwise the UI shows **NO STATISTICALLY CONFIRMED EDGE**, and by default the ML probability is left out of the
signal score (`REQUIRE_EDGE_FOR_ML`). Set `REQUIRE_EDGE_FOR_TRADE=true` to refuse all trades without an edge.

### Signals and decisions

Signal score = weighted sum of eight component scores in [-1, +1]: trend 20%, momentum 15%, volume 10%,
market structure 15%, ML probability 20%, volatility 5%, liquidity/order flow 5%, higher timeframes 10%.
Weights are editable in **Settings**; unavailable components are dropped and their weight redistributed, and
the effective weights are shown with every signal. RSI below 30 alone never produces a BUY.

A BUY or SELL *signal* becomes a BUY or SELL *decision* only if all of these hold: volatility is not extreme,
a trained model exists and predicts the same direction, model agreement >= 60%, confidence >= `MIN_CONFIDENCE`,
and the trade plan is valid (no obstacle nearer than 1R, risk/reward >= 1.5, and a historical base-rate
expectancy that is not clearly negative). Otherwise the decision is **NO TRADE** with the reason.

Note on the confidence scale: accuracy here is 3-class (up / neutral / down), where chance is about 40%, so the
default `MIN_CONFIDENCE=0.45` is deliberately modest. Expect many `NO TRADE` decisions.

### Anti-overfitting and anti-leakage measures

* Only closed candles reach features and models; the forming candle is dropped.
* Swings, break-of-structure and divergences are used only after their confirmation delay.
* Tests assert that deleting future candles leaves every past feature, signal and replayed analysis unchanged.
* The backtester executes on the next bar's open and assumes the stop fills first when a bar touches both.
* The AI strategy can only be backtested on walk-forward out-of-sample bars.
* Live statistics contain only predictions this installation actually issued; nothing is back-filled.

---

## Pages

| Page | What it shows |
|---|---|
| Dashboard | market status, regimes, top signals, forecast table, heatmap, opportunities, risks, sentiment context |
| Asset | chart with EMA / VWAP / Bollinger / structure / trade plan, forecast and ranges, model consensus, multi-timeframe matrix, trade setup, why-this-signal, risk sizing, regime, liquidity |
| Scanner | sortable / filterable universe, watchlist search, add, remove, pin |
| Accuracy | edge verdict, benchmarks, model comparison, walk-forward timeline, calibration, live accuracy, drift |
| Backtest | any strategy vs Buy & Hold, SMA cross and random runs; gross -> fees -> slippage -> net |
| Replay | rebuilds the past, forecasts, then reveals what happened, with a look-ahead audit |
| Signals | history of logged signals with TP / stop outcomes |
| Futures | long / short calls, trade plan, suggested leverage, liquidation, live funding / OI / long-short ratio, leverage calculator |
| Demo bots | automated virtual trading (spot and futures) of signals and raw predictions, with accuracy statistics |
| Paper | manual virtual accounts: spot, and futures with leverage, stop-loss, take-profit, liquidation and funding |
| Alerts | 12 alert types with debounce and cooldown |
| Health | feed, exchange, database, data quality per series, models, errors |
| Settings | risk profile, signal weights (with a data-fitted suggestion), forecast refresh |

## Local HTTP API (optional local mode)

All routes exist both with and without the `/api` prefix. Symbols in URLs: `BTC-USDT`, `BTCUSDT` or `BTC`.

```
GET  /market/{symbol}                 GET  /market/{symbol}/ohlcv?timeframe=&limit=
GET  /market/{symbol}/orderbook       GET  /market/{symbol}/derivatives
GET  /analysis/{symbol}?timeframe=    GET  /signal/{symbol}?timeframe=
GET  /forecast/{symbol}               GET  /forecast/{symbol}/{timeframe}
GET  /regime/{symbol}                 GET  /indicators/{symbol}
GET  /models/{symbol}?timeframe=      POST /models/train            GET /models/status
GET  /performance                     GET  /performance/{symbol}?timeframe=
POST /backtest                        GET  /backtest/{id}           GET /backtests
GET  /replay/{symbol}?as_of=&timeframe=                             GET /replay/{symbol}/range
GET  /scanner   GET /dashboard   GET /cross-asset   GET /context    GET /signals/history
GET|POST|DELETE /watchlist            GET  /search?q=
GET|POST|PUT|DELETE /alerts           GET|POST /paper ...           GET|PUT /settings
POST /risk/position-size              GET  /system/health           WS  /ws
```

## Project layout

```
backend/
  app/
    config.py  db.py  schema.sql  timescale.sql  main.py  cli.py
    worker.py (batch engine)  sinks.py (Firestore / local)  views.py (published payloads)
    data/       base.py (provider protocol)  binance_public.py  ccxt_provider.py  csv_provider.py  store.py  stream.py  quality.py
    features/   indicators.py  structure.py  volatility.py  liquidity.py  dataset.py
    ml/         models.py  deep.py  walkforward.py  calibration.py  metrics.py  distribution.py
                trainer.py  drift.py  explain.py
    engine/     regime.py  scores.py  signal.py  mtf.py  setup.py  risk.py  cross_asset.py  commentary.py
    backtest/   engine.py  strategies.py  benchmarks.py  stats.py
    services/   runtime.py  market.py  analysis.py  training.py  tracking.py  alerts.py  paper.py
                backtests.py  replay.py  scanner.py  health.py  jobs.py  bots.py (demo bots)
    api/        routes.py
  tests/
frontend/
  src/  App.tsx  pages/  components/  lib/
firebase.json  firestore.rules.template  .github/workflows/ (engine, train, deploy)
docker-compose.yml  docker-compose.postgres.yml (local mode)
```

Database tables: `users, watchlists, market_data, predictions, prediction_outcomes, signals, trades,
paper_accounts, paper_positions, backtests, model_versions, model_metrics, alerts, alert_events,
system_health, app_settings`. Every prediction has a unique id and a model version.

Adding a coin: search and add it on the **Scanner** page (or `POST /watchlist`); history downloads and
models train automatically. Adding an exchange: any CCXT id works via `EXCHANGE`; a non-CCXT source needs a
class implementing the `MarketDataProvider` protocol in `data/base.py`.

## External services and keys

| Service | Used for | Key needed |
|---|---|---|
| Exchange public API via CCXT | candles, tickers, order book, trades | No |
| Perpetuals venue (`DERIVATIVES_EXCHANGE`) | funding rate, open interest | No |
| CoinGecko `/global` | total market cap, BTC dominance, stablecoin share (context only) | No (rate-limited) |
| alternative.me | Fear & Greed index (context only) | No |

No private exchange keys are used anywhere. If trading keys are ever added they must stay server-side.

## Not included, or simpler than the brief

* **News, social sentiment, search trends, liquidation feeds**: need paid or keyed data sources; not implemented.
* **BTC dominance, total market cap, stablecoin flows, Fear & Greed**: shown as context only. They are not
  model or regime inputs because free history to backtest them was not available.
* **Regime-specific models**: implemented as regime-specific *ensemble weights*, not separately trained models.
* **SARIMA / SARIMAX**: only ARIMA(1,0,1) is wired in.
* **AI commentary**: built from templates over calculated values. No language model is called.
* **Redis**: not used; an in-process cache covers a single-node deployment.
* **Users / login**: the Firebase site uses Google sign-in restricted to `ADMIN_EMAILS`. The optional local API has no login.
* **Alert delivery**: in-app only (list + toast while the site is open). No email or Telegram.
* **Multiple exchanges at once**: the store is keyed by exchange and providers are pluggable, but the running
  app reads from one primary exchange.
* **Paper trading**: manual orders. Automated virtual trading is done by the demo bots.
* **Anchored VWAP**: the function exists (`indicators.anchored_vwap`) but is not drawn on the chart.
* **Survivorship bias**: models are per-asset, so there is no cross-sectional selection inside a model, but the
  default watchlist is today's large caps. Cross-asset conclusions inherit that bias.
* **Multiple testing**: 60 symbol/timeframe models are each tested at alpha = 0.01, so an occasional false
  "edge confirmed" is expected by chance. Treat a single confirmation with caution.

## Running locally instead (optional)

* Run one backend process (the background workers and caches live in-process): `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
* Put it behind a reverse proxy that forwards `/api` and upgrades `/ws` (see `frontend/nginx.conf`), and add
  authentication before exposing it.
* Use PostgreSQL / TimescaleDB for long histories: set `DATABASE_URL`, then optionally run `app/timescale.sql`.
* Persist `MODEL_DIR` and the database volume. Memory use is roughly 0.5-1 GB with the default watchlist.
