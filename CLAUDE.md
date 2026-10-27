# Crypto Intelligence AI — project notes for future work

Owner: Hesper (admin). Live site: https://crypapp-6a9b9.web.app (must ALWAYS stay active: Android app + existing links;
never redirect or retire it) and the custom domain https://cryptointelai.com (Tasjeel DNS, connected 27 Oct 2026 via
`custom-domain.yml`; www redirects to apex). Support email support@cryptointelai.com. Repo: hesperlexi/crypto-intelligence-ai (public).
Version **2.0.0** (web + Android TWA). Analysis and demo trading only: **no real orders, ever**.

## Ground rules
- Every result shown to members or the public comes from the real record. Never delete, hide or edit losing trades
  to improve figures (requested once; declined). The v2.0 "fresh start" counts the record from the launch date
  (`record_since` setting); older signals stay in the Signal log.
- The Firebase service-account key lives only in the GitHub secret `FIREBASE_SERVICE_ACCOUNT`. The Telegram bot token
  lives in Firestore `owner/telegram` (owner-only rule). Never print or commit secrets.
- The user is non-technical: answer in plain words, short. Commits end with the attribution lines given by the
  session's system reminder.

## Architecture
- **Frontend** `frontend/` React + Vite + Tailwind, Firebase Hosting, PWA + Android TWA (Bubblewrap, GitHub release
  `android`). Data comes from Firestore `views/*` (JSON written by the engine), live prices from Binance WebSockets.
- **Engine** `backend/app` Python, run by GitHub Actions; SQLite state in the Actions cache (`engine-state-*`),
  encrypted daily backup as release asset `engine-backup` (`scripts/engine_backup.sh`, auto-restore on cache miss).
- Firestore rules: `firestore.rules.template` (deployed by `deploy.yml`). Public docs: `views/wins_today`,
  `config/membership`. Owner-only: `owner/*`, `admin/*`. `presence/{uid}` (last_seen, country from time zone, device; written by the person every ≤4 min, read by admin on Users).

## Workflows (.github/workflows)
- `engine.yml` **always on** (v2.3): one run lives ~5 h 50 min, `scripts/engine_loop.py` runs
  `python -m app.worker tick` every 5 min (10 min after 3000 view writes in a run), cache save after each ~64-min
  segment, keeps the newest 4 state caches; cron */30 only keeps one run queued behind it. `train.yml` daily 02:17 UTC
  (15 slices, then `merge` in group `train-merge`: it waits until no engine run is in progress — the engine loop sees
  the running merge job and stops — merges, backs up and re-dispatches engine.yml) · `watchdog.yml` every 30 min (push to owner if engine is stale
  >75 min; weekly re-enable of schedules) · `deploy.yml` on push (pytest, build, Firebase deploy, Android APK) ·
  `diagnose.yml` (manual, gate replay + policy study → `reports` branch) · `evaluate.yml`, `probe.yml` (manual).
- From this sandbox: `gh workflow run` is blocked (GraphQL) → dispatch with
  `gh api -X POST repos/hesperlexi/crypto-intelligence-ai/actions/workflows/<file>/dispatches -f ref=main`.
  Log downloads are blocked; failed step names: `gh api repos/.../actions/runs/<id>/jobs`. Reports:
  `git fetch origin reports:refs/remotes/origin/reports; git show origin/reports:reports/diagnose-latest.json`.
- Browser futures streams: `wss://fstream.binance.com/market/stream` (aggTrade, kline) and `/public/stream` (depth); the legacy `/stream` path stopped pushing on 2026-04-23.
- Binance futures (fapi) is geo-blocked on the US runners; spot data via data-api.binance.vision; futures history
  from Hyperliquid; live funding fallback OKX.

## How a signal is made (engine v2)
**v2.2 (Oct 2026).** `MODEL_TIMEFRAMES = 15m/1h/4h/12h/1d/3d` (1w chart context only; `log_signal` skips non-model
TFs). Targets (`engine/setup.py`): TP1 exactly 1R closes 50% (stop → break-even), TP2 ∈ [1.25R, 2R] and TP3 ∈ [2R, 3R]
picked by max historical first-passage p·R, capped by S/R; 25% each (`TP_SPLIT`, used by bots, tracking, trade
filter). `risk_reward` = blended exits, min 1.25. 15m history 30000 bars via `CandleStore._deepen` (fills holes, 120
pages/run, flag `deep2:*`). Gold = `PAXG/USDT` (added once, flag `gold_paxg_v21`), shown as GOLD; Pro chart
`FOREXCOM:XAUUSD` (forex.com has no free API).
**v2.2 engine upgrades.** Nightly training = `train.yml` 15 slices (`worker train-shard`, no engine lock) + `merge`
(`worker train-merge`: `trainer.import_bundle`, `prune_files` >7 d inactive, funding + crowd sync, publish, backup).
Bigger-trend check (`analysis.higher_trend_check`: against both next higher TFs → NO TRADE, against one → A→B).
Live record (`tracking.update_signal_outcomes`) uses the bots' stops: break-even after TP1, TP1 after TP2 (one-time
re-follow of TP1/TP2 signals, flag `tracking_be_v23`). Safety switch `services/safety.py` (last 25 closed, ≥20, avg<0 & TP1<40% → pause; paused trades go to
`shadow_signals`; resume when ≥8 shadow closed, avg>0, TP1≥50%; listed on Health). AI targets `ml/target_model.py`
(per-R reach classifiers, used only with Brier skill ≥1% on last 30%; lift × base rate in `setup.pick`). Crowd data
`derivs.sync_crowd` (data.binance.vision daily metrics → `oi_1h`, `ls_top_1h`, `ls_acct_1h`, `taker_1h`; features
`dataset.crowd_features` with a 2-day publication lag); gate key `deriv_gate2|`.
1. `services/analysis.py`: technical tilt + ensemble forecast (`ml/trainer.py`, walk-forward, calibrated).
2. Directional confidence = hit rate of comparable out-of-sample calls (`ml/direction.py`); per-model margin policy.
3. Grades: **A** tilt + AI agree above proven threshold; **B** AI-led where the model has an out-of-sample edge.
4. **Trade filter** (`ml/trade_filter.py`): meta-model on bot-rule trade outcomes, enabled per model only if it
   improved avg R on unseen data; filtered calls → NO TRADE. Enabled gradually as models retrain nightly.
5. **News guard** (`services/news.py`): no new entries 45 min before → 30 min after high-impact US releases.
6. Futures features (funding/premium, `data/derivs.py`, `features/dataset.py`) used only where `ml/deriv_gate.py`
   proves they help.
7. **Let winners run** (v2.3, `ml/runner_model.py`): per coin/timeframe, trained nightly on out-of-sample calls; on only if
   'runner when scored, standard otherwise' beat 'always standard' by ≥0.04R on the last quarter. Runner = nothing closes
   at TP1, stop → BE at TP1, → TP1 at TP2, → TP2 at TP3, whole position at 1:4 (`setup.runner`, signal payload `runner`,
   bots `info.run_target`, tracking single exit). Signal card shows move % and ROI at the suggested leverage.
8. Higher-timeframe context (v2.3) used only where `ml/htf_gate.py` proves it helps (per series, paired Brier test,
   30-day cache `htf_gate1|`; slices pass decisions to the merge via `bundle_record.gates`). `USE_HTF_FEATURES=1` forces it on.
   BTC context aligns to the latest BTC bar opened by the coin bar's open (3d candles start on listing dates).

## Bots and auto-trade
- `services/bots.py`: 50/25/25 at TP1/TP2/TP3 (`TP_SPLIT`), break-even after TP1, trail to TP1 after TP2, time exit,
  **reversal exit** (signal flips → close, profit taken / loss cut, then take the new side), no hedging, size
  0.5–1.5x by grade/filter (`size_multiplier`), max 3 same-direction trades. **v2.3 line-up** (flag `fresh_start_v23`,
  27 Oct 2026: all bot books + admin practice trades cleared, `record_since` restarted): 5 spot `signal-ab-{15m,1h,4h,12h,1d}`
  + 5 futures `futures-signal-ab-*` (20x, safe-leverage per trade), all grades A+B. Scorecard bots
  `futures-signal-ab-1h/4h` mirror the Signals page. One-time migrations use settings flags (`fresh_start_v2`,
  `watchlist_majors_v2`, `defaults_added`). Exchange renames: `RENAMED` in `worker.py` (TON→GRAM, 2026-07-02) rewrites the watchlist once.
- `services/autopaper.py`: members' auto-trade into `paper/{uid}_futures` (settings `auto_paper/{uid}`, log
  `auto_paper_state/{uid}`); same reversal/size/cap rules; manual trades never touched.

## Other features (where to look)
News & calendar `services/news.py` + `pages/News.tsx` · Radar `services/radar.py` + `pages/Radar.tsx` · Track
record / weekly report / achievements / wins_today `views.py` + `pages/Results.tsx`, `Report.tsx`,
`Achievements.tsx`, `components/WinsToday.tsx` · Telegram autopilot `services/telegram.py` (every win + daily/weekly/teaser as image cards from
`services/cards.py`, Pillow, Inter fonts + logo in `app/assets`) + `components/TelegramCard.tsx` · Live trading stream `frontend/src/lib/stream.ts` · Memberships
`services/membership.py`, `components/Membership.tsx` (prices 15/40/70/130 USDT, USDT only; Binance QR or MEXC UID 00183657; support email in
`config/membership`) · Manual `docs/manual/manual.md` → `python scripts/build_manual.py` (members only, no admin
instructions) · Promo video `frontend/public/demo.mp4` (70 s, original soundtrack).

Member menu: Home · Signals · Trade · News · Radar · Results · Alerts · Settings. Owner extras: Weekly report,
Achievements, Health, Users.

## Testing
`cd backend && python -m pytest -q` in CI. In this sandbox pytest may be missing (PyPI blocked); run test functions
directly. Frontend type-check: `npx tsc --noEmit` (CI) — the sandbox has no node_modules.

## Ideas not done yet
Arabic (RTL) · referral programme · smarter exits per coin · parallel training matrix · Binance daily metrics
(OI, long/short, taker) as features · iPhone App Store ($99/yr, owner decision) · real-money auto-trading (only after a proven record and a VARA check).
