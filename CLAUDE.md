# Crypto Intelligence AI — project notes for future work

Owner: Hesper (admin). Live site: https://crypapp-6a9b9.web.app · Repo: hesperlexi/crypto-intelligence-ai (public).
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
- `engine.yml` every 5 min (`python -m app.worker tick --budget 300`) · `train.yml` daily 02:17 UTC (60 min, full
  models + deriv gate + trade filter, then backup) · `watchdog.yml` every 30 min (push to owner if engine is stale
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
**v2.1 (Oct 2026): quick trades.** `MODEL_TIMEFRAMES = 15m/1h/4h` (12h/1d/3d/1w dropped from signals; 1d stays as chart
context), targets 0.5R/0.75R/1R (1:1 final, `engine/setup.py` + `ml/trade_filter.py` R_MULTIPLES), min R:R 1.0.
15m history 30000 bars via `CandleStore._deepen` (older-history backfill, 120 pages/run). Gold = `PAXG/USDT`
(added once, flag `gold_paxg_v21`), shown as GOLD; Pro chart `FOREXCOM:XAUUSD` (forex.com has no free API).
1. `services/analysis.py`: technical tilt + ensemble forecast (`ml/trainer.py`, walk-forward, calibrated).
2. Directional confidence = hit rate of comparable out-of-sample calls (`ml/direction.py`); per-model margin policy.
3. Grades: **A** tilt + AI agree above proven threshold; **B** AI-led where the model has an out-of-sample edge.
4. **Trade filter** (`ml/trade_filter.py`): meta-model on bot-rule trade outcomes, enabled per model only if it
   improved avg R on unseen data; filtered calls → NO TRADE. Enabled gradually as models retrain nightly.
5. **News guard** (`services/news.py`): no new entries 45 min before → 30 min after high-impact US releases.
6. Futures features (funding/premium, `data/derivs.py`, `features/dataset.py`) used only where `ml/deriv_gate.py`
   proves they help.

## Bots and auto-trade
- `services/bots.py`: thirds at TP1/TP2/TP3, break-even after TP1, trail to TP1 after TP2, time exit,
  **reversal exit** (signal flips → close, profit taken / loss cut, then take the new side), no hedging, size
  0.5–1.5x by grade/filter (`size_multiplier`), max 3 same-direction trades. Scorecard bots
  `futures-signal-ab-1h/4h` mirror the Signals page. One-time migrations use settings flags (`fresh_start_v2`,
  `watchlist_majors_v2`, `defaults_added`). Exchange renames: `RENAMED` in `worker.py` (TON→GRAM, 2026-07-02) rewrites the watchlist once.
- `services/autopaper.py`: members' auto-trade into `paper/{uid}_futures` (settings `auto_paper/{uid}`, log
  `auto_paper_state/{uid}`); same reversal/size/cap rules; manual trades never touched.

## Other features (where to look)
News & calendar `services/news.py` + `pages/News.tsx` · Radar `services/radar.py` + `pages/Radar.tsx` · Track
record / weekly report / achievements / wins_today `views.py` + `pages/Results.tsx`, `Report.tsx`,
`Achievements.tsx`, `components/WinsToday.tsx` · Telegram autopilot `services/telegram.py` +
`components/TelegramCard.tsx` · Live trading stream `frontend/src/lib/stream.ts` · Memberships
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
(OI, long/short, taker) as features · iPhone App Store ($99/yr, owner decision) · always-on server (~$5–10/mo,
owner decision) · real-money auto-trading (only after a proven record and a VARA check).
