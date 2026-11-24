# 01 · Platform inventory

Audit date: 24 Nov 2026 (Stage A, read-only). Code at `main` = `96fc3f9`. Nothing was changed in the app for this audit.

## Size

| Part | Files | Lines (approx.) |
|---|---|---|
| Frontend (`frontend/src`, React 18 + TypeScript + Vite 5 + Tailwind) | 28 pages, 77 components, 40 lib modules | ~24,900 |
| Engine (`backend/app`, Python) | 47 services, 21 ML modules, 11 engine modules, 11 data modules, 49 top-level modules | ~31,900 |
| Tests (`backend/tests`) | 87 files, 531 test functions; 4 Firestore-rules test files (`tests/rules`) | ~10,600 |
| GitHub Actions | 55 workflows (3 scheduled, the rest manual / on push) | — |
| Other | `chat-worker/` (Cloudflare Worker: Ask Cintel + edge views), `android/` (Bubblewrap TWA), `docs/manual` (PDF manual) | — |

## Pages (routes in `frontend/src/App.tsx`)

| Route | Page | Who | Status |
|---|---|---|---|
| `/` | Overview (`Dashboard.tsx`) | member, admin; landing for visitors | live |
| `/command` | AI Intelligence (`Command.tsx`; `/intelligence` redirects) | member | live |
| `/risk` | Market risk (`Risk.tsx`) | member | live (see finding F-07: same path as the risk disclosure) |
| `/signals` | Trade signals (`/futures` redirects) | member | live |
| `/paper` | Trade / practice account (`/trade` redirects) | member | live |
| `/portfolio` | Portfolio + auto-trade protection | member | live |
| `/results` | Track record · Demo bots (+ Hesper) · Signal log (+ Model accuracy) · Leaderboard (`/accuracy`, `/bots`, `/history`, `/track` redirect here) | member | live |
| `/coins` | All coins board (`/scanner` redirects) | member | live |
| `/flow` | Money flow (browser-side Binance futures streams) | member | live |
| `/radar` | Radar + coin scorecard | member | live |
| `/news` | News, calendar, news mood | member | live |
| `/asset/:symbol` | Coin page | member | live |
| `/community`, `/alerts`, `/settings` | Community feed, alert rules, settings | member | live |
| `/health` (+ tabs Guardian `/guardian`, Lab `/lab`) | Control room | admin only (`AdminOnly`) | live |
| `/rich` | Hesper Challenge (main + Last Stand) | admin; members via Results when shared | live |
| `/report`, `/achievements` | Share kit | admin | live |
| `/users` | Members, payments, referrals | admin | live |
| `/backtest`, `/replay` | Research tools | admin | live |
| `/about`, `/terms`, `/contact`, `/record`, `/risk` (disclosure) | Trust pages | public | live (disclosure unreachable for members, F-07) |
| `*` | 404 | all | live |

## Engine services (worker steps, `backend/app/worker.py`)

Market data & candles (`market`, `data/*`), analysis per coin × timeframe (`analysis`, `engine/*`, `ml/*`), record follow-up
(`tracking`), demo bots (`bots`), Hesper / Last Stand (`hesper`), members' auto-trade (`autopaper`), Trade Guardian
(`guardian`, recommend-only), market risk state (`risk_state`), BTC shock guard (`btc_shock`), sweep guard (`sweep_guard`),
capital-protection veto (`risk_shadow`), proof checks (`proof_checks`), alerts (`alerts`), news & calendar (`news`), news
sentiment (`sentiment`, collected, not used in decisions), AI briefing (`briefing`), coin reports (`coin_reports`), Telegram
autopilot (`telegram`, `cards`), leaderboard, referrals, market data (`market_data`, `market_extras`, `coinalyze`), turn
detector + turn watch (shadow), performance lab, coin scorecard, radar, health. Background threads in
`scripts/engine_loop.py`: fast price watch (30 s), order-flow recorder (20 s).

## ML models (`backend/app/ml`)

Ensemble members (`models.py`): prior baseline, previous candle, logistic regression, technical-rules model, Random Forest,
scikit-learn HistGradientBoosting, XGBoost, LightGBM, ARIMA(1,0,1) (not on 12h), LSTM / GRU / Transformer (`deep.py`, present in 7
15m bundles and 6 weekly bundles only). Around them: walk-forward training + calibration (`trainer.py`, `walkforward.py`,
`calibration.py`), directional confidence (`direction.py`), trade filter v1 (`trade_filter.py`), pooled trade filter 2
(`trade_filter2.py`), AI targets (`target_model.py`), runner model (`runner_model.py`), futures-data gate (`deriv_gate.py`),
higher-timeframe gate (`htf_gate.py`), sentiment gate (`sentiment_gate.py`, stub, off), series policy (`series_policy.py`),
drift (`drift.py`), champion / challenger (`challenger.py`, active), explanation (`explain.py`).

Live count (24 Nov, `research-results/results/usage-latest.json`): **251 active bundles** (30 watched coins × 6 timeframes +
weekly context + bundles of coins no longer watched), 2,229 predictions in the last 24 h.

## Data providers

Binance spot (data-api.binance.vision; candles, tickers), Hyperliquid (futures history), OKX (funding fallback, rubik stats,
liquidations, order flow), MEXC futures (MSTR, ANTHROPIC, SILVER), Binance data archive (OI, long/short, taker), Coinalyze
(liquidations, key in a secret), DefiLlama (stablecoins, unlocks), Deribit (DVOL, options), Yahoo chart API (macro),
alternative.me (Fear & Greed), CoinGecko (market cap), RSS news + economic calendar, Gemini (texts only, never decisions).
Browser: Binance spot + USDⓈ-M WebSockets (live prices, money flow).

## Scheduled jobs

| Workflow | Schedule (actual file) | Role |
|---|---|---|
| `engine.yml` | cron `*/30` + self-queue; each run ~5 h 50 min, tick every 4 min (`ENGINE_EVERY_S` 240) | the engine |
| `train.yml` | daily 02:17 UTC (often starts later, see F-03) | nightly training (15 slices + merge) |
| `watchdog.yml` | `7,37 * * * *` | push to the owner if the engine is late > 75 min |
| everything else | manual / on push | deploy, rules tests, research, probes, audits |

## Orphaned, duplicated or obsolete items (not deleted)

* Firestore views of removed coins still exist and never update: `*_TONUSDT_*` (TON renamed GRAM), `*_XAUTUSDT_*` (XAUT replaced by PAXG), many `perf_*_1w` (≈ 700-760 h old). Harmless for users, but clutter (F-16).
* Active model bundles for coins no longer watched (251 active vs about 188 needed: 30 coins × 6 timeframes + 8 weekly); 11 of the 41 active 12h bundles still contain ARIMA, which is excluded on 12h since v2.57 — most likely these old-coin bundles (suspected, F-17).
* `services/scalp_backfill.py`, `scalp_signals`, `proof.py` / `signal_proofs`: switched off by the owner on 2 Nov; kept on purpose (history).
* `components/Instruments.OrbitDial` and `SonarScope`: no longer rendered after today's Thinking Spectrum change (dead code, F-18).
* `scripts/audit_live.py` checks leverage against the old 10x rule and a liquidation formula without maintenance tiers → 34 false "problems" in today's run (F-15).
* Two implementations of the liquidation formula (engine `engine/futures.py`, browser `lib/paperFutures.ts`). They match today (same tiers, same fee); a test that keeps them in step is missing (F-19).
