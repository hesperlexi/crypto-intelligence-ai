# Crypto Intelligence AI — project notes for future work

Owner: Hesper (admin). Live site: https://crypapp-6a9b9.web.app (must ALWAYS stay active: Android app + existing links;
never redirect or retire it) and the custom domain https://cryptointelai.com (Tasjeel DNS, connected 27 Oct 2026 via
`custom-domain.yml`; www redirects to apex). Support email support@cryptointelai.com. Repo: hesperlexi/crypto-intelligence-ai (public).
Version **2.1.0** (fresh start 30 Oct 2026: `reset_v1.py`, record counted from the reset) (web + Android TWA). Analysis and demo trading only: **no real orders, ever**.

## Ground rules
- Every result shown to members or the public comes from the real record. Never delete, hide or edit losing trades
  to improve figures (requested once; declined). The v2.0 "fresh start" counts the record from the launch date
  (`record_since` setting); older signals stay in the Signal log. Per-timeframe restarts after a rule change
  (`record_since_tf`, e.g. 15m on 27 Oct 2026 with the costs rule, again 19:10 Dubai after the no-flip fix, flag `reset_15m_v23b`) go through `views.record_clause` — wins and losses alike, shown on Results.
- The Firebase service-account key lives only in the GitHub secret `FIREBASE_SERVICE_ACCOUNT`. The Telegram bot token
  lives in Firestore `owner/telegram` (owner-only rule). Never print or commit secrets.
- The user is non-technical: answer in plain words, short. Commits end with the attribution lines given by the
  session's system reminder.

## Architecture
- **Frontend** `frontend/` React + Vite + Tailwind, Firebase Hosting, PWA + Android TWA (Bubblewrap, GitHub release
  `android`). Data comes from Firestore `views/*` (JSON written by the engine), live prices from Binance WebSockets.
- **Engine** `backend/app` Python, run by GitHub Actions; SQLite state in the Actions cache (`engine-state-*`),
  encrypted daily backup as release asset `engine-backup` (`scripts/engine_backup.sh`, auto-restore on cache miss).
- **Firestore quota (Spark/free plan: 20,000 writes/day, day = midnight US Pacific).** 27-28 Oct 2026 the always-on
  engine used it up by ~23:00 Dubai and nothing published for ~12 h. `sinks.BaseSink` now counts writes per quota day
  (`fs_writes`), paces coin analyses (`worker.ANALYSIS_EVERY_S`, immediately when `analysis_core` - the call - changes),
  goes lean (essentials only, every 30 min) above `FIRESTORE_DAILY_BUDGET` (15000), and on a 429 pauses writes for 20 min
  (`fs_blocked_until`, lifted early by a successful heartbeat; unpublished views go out afterwards). Heartbeat ≤ 1/min. Health shows
  `firestore_writes_today`. Upgrading Firebase to Blaze removes the hard stop (owner decision).
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
Live record (`tracking.update_signal_outcomes`, v2.4: followed on 15m candles `tracking.PATH_TF` like the bots, so a hit inside a
4h/12h/1d candle shows within minutes; removed coins with OPEN signals keep syncing in `market.sync_all`) uses the bots' stops: break-even after TP1, TP1 after TP2 (one-time
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

## Testing mode v2.4 (from 28 Oct 2026, two weeks)
Flag `testing_v24` (`worker.sync_config`): watchlist = `worker.TEST_COINS` (10: BTC ETH BNB XRP SOL DOGE LTC AAVE AVAX + PAXG
gold (XAUT swapped for PAXG same day, flag `testing_v24b`), ranked by proven out-of-sample edges), `config/limits.member_coins_max = 0`, only the 5 futures bots (spot bots
removed, reset_token v24), all bot books + all practice accounts cleared, `record_since` restarted, `record_since_tf`
cleared, `testing_since` shown on Results. Trade limits: auto-trade ≤3 open, ≤6 new/day (`autopaper.MAX_OPEN_CAP`,
`MAX_NEW_PER_DAY`); manual practice futures ≤5 open trades+orders (`paperFutures.MAX_OPEN_TRADES`), spot ≤5 coins.
To end testing: restore the watchlist/limits and re-add spot bots (no automatic undo).

## Bots and auto-trade
- `services/bots.py`: 50/25/25 at TP1/TP2/TP3 (`TP_SPLIT`), break-even after TP1, trail to TP1 after TP2, time exit,
  **reversal exit** (signal flips → close, profit taken / loss cut, then take the new side), no hedging, size
  0.5–1.5x by grade/filter (`size_multiplier`), max 3 same-direction trades. **v2.3 line-up** (flag `fresh_start_v23`,
  27 Oct 2026: all bot books + admin practice trades cleared, `record_since` restarted; 20:39 Dubai all members' practice accounts, trades and auto-trade logs cleared too, flag `members_practice_v23`): 5 spot `signal-ab-{15m,1h,4h,12h,1d}`
  + 5 futures `futures-signal-ab-*` (20x, safe-leverage per trade), all grades A+B. Costs rule (v2.3): a signal needs
  1R ≥ 3x the futures round-trip cost (`analysis.beats_costs`, ~0.45%), spot bots 3x the spot cost; bots skip a trade the
  position cap would shrink below half its planned risk; spot bots' cap 100% of balance (`bots_spotcap_v23`). 15m (v2.3): no opposite 15m call while a 15m call on the
  coin is OPEN (`analysis.ONE_CALL_TFS`); 15m bots never reverse (`bots.NO_FLIP_TFS`), held to stop/targets/time. Scorecard bots
  `futures-signal-ab-1h/4h` mirror the Signals page. One-time migrations use settings flags (`fresh_start_v2`,
  `watchlist_majors_v2`, `defaults_added`). Exchange renames: `RENAMED` in `worker.py` (TON→GRAM, 2026-07-02) rewrites the watchlist once.
- `services/autopaper.py`: members' auto-trade into `paper/{uid}_futures` (settings `auto_paper/{uid}`, log
  `auto_paper_state/{uid}`); same reversal/size/cap rules; manual trades never touched.

## v2.5 engine / audit upgrade (30 Oct 2026, PR #1)
- Record integrity: calls followed only from the first 15m candle opened after `created_at`; recorded entry = card entry
  (ideal entry), pullbacks `fill_status` PENDING → FILLED / NOT_FILLED (`FILL_WINDOW_BARS`, excluded from stats);
  stale candles → NO TRADE (`stale`); one OPEN/PENDING call per coin/timeframe (`record_status`, `call` on analysis rows);
  wall-clock expiry, VOID when no data; `wins_today` also has `closed`/`losses`. Contract: `docs/v1-contract.md`.
- `engine/manage.py`: one implementation of the exit rules (record + bots). Managed exits (give-back, ATR trail,
  time stop) behind `MANAGED_EXITS` = **off**: `research.yml` (read-only replay → branch `research-results`) showed them
  worse on unseen calls (−0.04R vs +0.02R, 30 Oct). Re-entry cooldown/cap. `decisions` table → `views/decisions_recent`.
- Gemini advisor `services/ai_advisor.py` (secret `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_DAILY_LIMIT` 150): rationale,
  regime label, post-trade review; advisory only, never changes a decision; `AI_PARAMS` off.
- Security: rules validate presence/users/jobs/push_tokens; jobs limited per user/day; test pushes only to the owner.
  App Check (reCAPTCHA v3) site key in `frontend/.env.production`; enforcement is a console switch (not on).
- Brand: `backend/app/brand.py` + `frontend/src/lib/brand.ts` (www.cryptointelai.com, support email, footer).
  web.app host, Firebase authDomain and the Android host stay unchanged. `ENGINE_VERSION` 2.5.0 in config.
- Website: split bundle, SVG logo (`components/Logo.tsx`), glass surfaces, Beginner/Pro mode (`lib/mode.tsx`),
  trust pages (`pages/Trust.tsx`), 404/error pages, security headers in `firebase.json`.

## v2.6 accuracy upgrades (30 Oct 2026, branch `engine-v26`; `ENGINE_VERSION` 2.6.0)
- Proof: `python -m app.research engine` (`research_engine.py`, run by `research.yml` → `research-results/results/engine-*.json`).
  The models' walk-forward out-of-sample calls of every series are replayed through the live decision rules
  (`ml/series_policy.decide`), simulated with the record's exits + 0.15% costs (`ml/series_sim.follow`, proven equal
  to `manage.follow`), one call at a time; first 70% of each series chooses, last 30% is the untouched test.
- Nightly in `train-merge` (`services/series_nightly.py`): `series_policy1|SYM|TF`, `entry_policy1|TF`, `trade_filter2|TF`.
- Settings (default from the 30 Oct test, file `results/engine-20261030T180454Z.json`, 1516 test trades):
  `SERIES_GATE` off (−0.062R vs −0.043R; series edges barely persist, corr 0.17), `SERIES_CONF` off (−0.073R),
  `STRUCT_STOPS` off (−0.087R, drawdown 246R vs 134R), `ENTRY_RULES` **on** (per timeframe, nested choice: market
  entry 15m/12h, confirm 0.1 ATR 1d; −0.040R), `TRADE_FILTER2` **on** (pooled per timeframe, on only where its own
  exam passes: 1d; −0.042R, DD 128R). All proven together: −0.038R, DD 128R vs OLD −0.043R, DD 134R. Gains are small
  and not significant (series bootstrap: better in ~66% of resamples). The pipeline is still negative after costs on
  15m (−0.17R) and 1h (−0.10R); 4h (+0.06R) and 12h are the only positive timeframes.
- Market inputs (item 6): deriv/htf gates are tested per series; ~4 series use futures data, ~8 use higher-timeframe
  context. 3d had no htf map → now tested against 1w. BTC regime/tech in the trade's direction are filter2 features.
- **15m trade calls paused** (owner decision 30 Oct 2026; superseded by v2.8 below): live
  15m decisions → NO TRADE ("TIMEFRAME PAUSED"), chart/forecast unchanged, research replays unaffected; 15m bots removed
  once (flag `pause_15m_v26`) and never re-added. 1h kept by owner choice although −0.10R on the test.
- News sentiment: `services/sentiment.py` hourly Gemini score of the RSS headlines (calendar only if none) →
  table `news_sentiment` (known_at, no look-ahead); `ml/sentiment_gate.py` stub, off until ≥60 days. `NEWS_SENTIMENT`.

## v2.8 timeframe policy + admin close (31 Oct 2026, owner decisions)
- Study `python -m app.research horizon|scalp15` (branch `research-horizon`, workflow `research-horizon.yml`, results
  `research-results/results/horizon-*.json`, `scalp15-*.json`): longer time limits help only 4h (+0.056R → +0.092R);
  1h 200 weak; 12h/1d/15m worse. 15m grade A is ~2-3 calls/week (too few to judge); a nearer TP1 raises win rate, not profit.
- Live: `analysis.PAUSED_TFS` "1d,3d"; `A_ONLY_TFS` "1h"; `DEMO_ONLY_TFS` "15m" (public NO TRADE "DEMO BOTS ONLY", call in
  analysis `demo`, taken only by bots with `demo_only`). Time limit per call `tracking.HORIZON_BARS` (15m 250, 1h 200,
  4h 100, else 30), stored in the call payload `horizon_bars` at publication (older calls keep 30). One-time
  `tf_policy_v28`: 1d bots removed, 1h bots grade A + 200 bars, 4h bots 100 bars, `bots.DEMO_15M` added (grade A,
  `tp1_only`, 20x safe leverage, 250 bars). `worker._off_bot` decides which bots stay off.
- Admin "Close now" (`adjust.close`, job `adjust_signal` with `action: close`): closes an open call at the engine's
  price; candles closed before the click follow normal rules; `signal_adjustments.field = 'close'`, exit_reason
  `admin_close` ("Closed by admin"); bots holding it close too; members notified.

## v2.9 sealed-signal proof (31 Oct 2026)
`services/proof.py`: at publication (`tracking.log_signal`) each call gets `signal_proofs` {text = CIA-SEAL-1|id|symbol|TF|side|
levels|published|salt, hash = SHA-256}. Telegram autopilot (`telegram.proofs`, option `post_proofs`, sent directly, never drafts)
posts the fingerprint within 30 min of publication (older ones marked -1, never back-dated) and the text after close.
Record rows carry `proof` {hash, sealed_at, text only when closed}; `components/SealProof.tsx` (row pill, VerifyBox),
public page `/verify` (Trust kind "verify"). No extra Firestore documents.

## Other features (where to look)
News & calendar `services/news.py` + `pages/News.tsx` · Radar `services/radar.py` + `pages/Radar.tsx` · Track
record / weekly report / achievements / wins_today `views.py` + `pages/Results.tsx`, `Report.tsx`,
`Achievements.tsx`, `components/WinsToday.tsx` · Telegram autopilot `services/telegram.py` (every win + daily/weekly/teaser as image cards from
`services/cards.py`, Pillow, Inter fonts + logo in `app/assets`) + `components/TelegramCard.tsx` · Live trading stream `frontend/src/lib/stream.ts` · Memberships
`services/membership.py`, `components/Membership.tsx` (prices 15/40/70/130 USDT, USDT only; Binance QR or MEXC UID 00183657; support email in
`config/membership`) · Manual `docs/manual/manual.md` → `python scripts/build_manual.py` (members only, no admin
instructions) · Promo video `frontend/public/demo.mp4` (70 s, original soundtrack).

Member menu: Home · Signals · Trade · News · Radar · Results · Community · Alerts · Settings. Owner extras: Weekly report,
Achievements, Health, Users.

## 31 Oct 2026 features (branch `features-oct31`)
- Sign-in: Google or email + password (`lib/account.ts`, `components/AuthPanel.tsx`: sign in / create / forgot, "Check your
  inbox" with 60 s client resend limit). Unverified email accounts never reach Firestore (rules need `email_verified`).
  Needs the **Email/Password provider enabled in the Firebase console**. `users/{uid}.provider` = google | password.
- Usernames: optional; offered once to new accounts (`UsernameScreen`, "Later" skips, localStorage `ask-username-<uid>`), required
  only to post (Community composer shows `UsernameForm`). Existing members are never blocked. `usernames/{name}` = {uid, created_at} + `users/{uid}.username`
  in one batch (owner: `owner/profile.username`); reserved list kept in step between `account.ts` and the rules.
- Community `pages/Community.tsx`: `posts/{id}` {author_uid, username, text 1-500, created_at, admin?}, 20 per page; rules pace
  posts with `post_meta/{uid}.last` (≥30 s). Trade page: stable newest-first order (`format.byNewest`), memoized rows,
  `PositionDrawer`, pair names switch the chart; auto-trades carry `signal` (`autopaper.origin_of`). Signal log filters
  `components/LogFilters.tsx` (URL query). Privacy page removed (text in `docs/legal/privacy-policy.md`); app-shell footer
  has no links (`SiteFooter links={false}`).

## Testing
`cd backend && python -m pytest -q` in CI. In this sandbox pytest may be missing (PyPI blocked); run test functions
directly. Frontend type-check: `npx tsc --noEmit` (CI). UI preview without Firebase: `cd frontend && npx vite --config
dev/vite.preview.config.ts --port 5193`, `/?preview=admin|member|pending|signedout|unverified|nousername` (mocks in `dev/mocks`, data `dev/seed.ts`).

## Ideas not done yet
Arabic (RTL) · referral programme · smarter exits per coin · parallel training matrix · Binance daily metrics
(OI, long/short, taker) as features · iPhone App Store ($99/yr, owner decision) · real-money auto-trading (only after a proven record and a VARA check).
