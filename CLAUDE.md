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
- The user is non-technical: answer in plain words, short. **Look and alignment matter most to the owner** (17 Nov 2026; Results page: keep as is, owner said skip the redesign):
  every page change is screenshot-checked on desktop and phone (even card edges, no hollow or stretched cards, no wrapping
  controls) and shown as a preview before going live. Commits end with the attribution lines given by the
  session's system reminder.

## Architecture
- **Frontend** `frontend/` React + Vite + Tailwind, Firebase Hosting, PWA + Android TWA (Bubblewrap, GitHub release
  `android`). Data comes from Firestore `views/*` (JSON written by the engine), live prices from Binance WebSockets.
- **Engine** `backend/app` Python, run by GitHub Actions; SQLite state in the Actions cache (`engine-state-*`),
  encrypted backup (every ~6 h, v2.13) as release asset `engine-backup` (`scripts/engine_backup.sh`, auto-restore on cache miss; the job fails rather than start on an empty state).
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

## Audit fixes (31 Oct 2026, branch `audit-fixes`)
- Version has one source: `frontend/package.json` (read by `vite.config.ts`, the preview config, `deploy.yml` APK and `brand.py`).
- Rules: `jobs` signed (`by` == token email), readable only by the creator or admin; posts need id `<uid>_<created_at>`;
  payment screenshots must match `^data:image/(png|jpeg|webp);base64,`. New proofs go to `payment_proofs/{uid}`
  (owner write, admin read; payment keeps `proof: null, has_proof: true`); old inline proofs still shown. Users page loads
  the image only in the proof viewer; the admin badge uses two narrow queries (`status == pending`, `payment.status == submitted`).
- Write budget: `sinks.BaseSink` reserves members' writes (people seen in 24 h × `FIRESTORE_MEMBER_WRITES_PER_DAY` 60, cap
  `FIRESTORE_MEMBER_RESERVE_MAX` 8000, engine floor 3000), refreshed hourly from `presence`; lean at `engine_budget()`. Health shows it.
- Published analysis views drop `demo` (`analysis.public_view`); bots keep it. Missing `config/bots` → `worker.policy_default_bots()`.
- Live prices: `useLive()` context ≤2 updates/s; `useFastTickers()` (trade terminal, futures practice) and `useTicker(sym)` full speed.
- Videos: `?v=` = content hash (`lib/media.ts`, `__MEDIA_VERSIONS__`), not the build id.

## 1 Nov 2026 (branch `live-status`)
- Owner decision 1 Nov 2026: the 15m demo bot (`bots.DEMO_15M`) and its trades are **intentionally visible to members**
  (Demo bots / Results); only the public signal stays NO TRADE "DEMO BOTS ONLY".
- Track record live status (`components/RecordDetails.tsx`): OPEN rows show a "Live" price, move %, ROI on margin at the
  card's leverage (signal-card formula, never stored), targets hit, stop in force (admin stop tightened by break-even /
  TP1 rules) and distances; pending pullbacks "waiting for entry". Rows are clickable / keyboard (Enter) → `RecordSheet`
  (portal; bottom sheet on phones): levels with hits, time limit + time left, adjustments, seal, AI note, "Open chart"
  (`/asset/<slug>?tf=` - Asset reads `?tf`), "Practise this trade" (open filled calls → `/paper?...`). Row extras from
  `views.live_fields`: tp1-3_hit, stop_hit, filled_at, `horizon_bars` (payload, default 30), `expires_at`.
  Method text built from `tracking.HORIZON_BARS` (`views.horizon_text`). Results never change.
- Payment screenshots (free plan storage): accepting / rejecting deletes `payment_proofs/{uid}` and clears an inline
  proof in the same batch (`membership.grantMembership/rejectPayment`, shape `writeShapes.paymentWithoutProof`:
  proof null, has_proof false, proof_deleted_at). Users page: "Delete screenshot" in the proof viewer, "Delete all
  checked screenshots" (accepted/rejected only, never `submitted`) with an in-app confirm (`ConfirmSheet`). Deleting a
  user also deletes their proof. Rules already allowed it (admin); rules tests added. `rules-test.yml` also runs on push
  to main and on pull requests (results committed only on pushes).
- Firestore reads (free plan 50,000/day): `BaseSink` counts reads per quota day (`fs_reads`, `reads_today()`, Health
  "Engine reads today"; an empty query counts 1). `sink.query(col, field, op, value)` (==, <, >=). Users fully re-read
  every `worker.USERS_EVERY_S` (1800) into settings `users_cache` (no images); in between only `payment.status ==
  submitted` (proof push stays prompt). Jobs: queued by query; clean-up hourly by `created_at < 3 days`. Auto-trade
  reads only `auto_paper` with `enabled == true`; a member missing from the cache is checked with one `users/{uid}` read.
  Presence estimate reads only `last_seen >= 24 h`. `user_coins` not read while `member_coins_max` is 0.
  Approvals / blocks reach alerts and auto-trade within 30 min. `views/health` stays member-readable (header engine chip).
- Website job wait (`api.queueJob`) gives up after 15 min (`JOB_TIMEOUT_MS`) with a clear message. `*.mp4` cached a year
  (immutable; the app links them with `?v=<hash>`). `scripts/build_manual.py` default version = `frontend/package.json`.

## v2.10 demo-only 1d / 3d (owner decision 1 Nov 2026)
`analysis.PAUSED_TFS` "" and `DEMO_ONLY_TFS` "15m,1d,3d": 1d / 3d calls are never public or recorded; they go to demo bots
`futures-demo-ab-1d` / `-3d` (`bots.DEMO_BOTS`, grades A+B, standard 50/25/25 exits, 20x safe leverage, 30 candles), added
once (flag `demo_1d3d_v210`). Calls published before stay in the record until they close. Signals tabs said "demo only". **Superseded by v2.12.**

## Scalping scorecard (admin, 2 Nov 2026, branch `scalping`)
- 15m is demo-only, so 15m calls never reach `signals`. Every live 15m **grade-A** demo call (analysis `demo`) is logged
  in its own table **`scalp_signals`** (same columns as `signals`) by `tracking.log_scalp` (called in `analysis.analyze`
  after the record's logging; never changes the analysis): record's entry / stop / targets / fill rules (`_plan`), time
  limit `tracking.horizon_for('15m')` (250), one OPEN/PENDING call per coin and the re-entry cooldown/cap (`entry_gate`
  on `scalp_signals`). Followed by `tracking.update_signal_outcomes(rt, table="scalp_signals")` (worker step
  `scalp_outcomes`). It never writes `signals`, `shadow_signals`, `decisions` or `signal_proofs`, and nothing that builds
  the record, safety switch, achievements, weekly report, wins_today, Telegram, proofs, training or bots reads it
  (`market.sync_all` only keeps candles coming for open scalp calls of removed coins). Test
  `tests/test_scalping.py` proves track_record / wins_today / weekly_reports / achievements stay byte-identical.
- Settings: **`scalping_since`** (set once by `worker.sync_config`, flag `scalping_v1`; counting starts there).
  **`scalping_visibility`** lives in Firestore `config/scalping.visibility` ('admin' default when missing | 'members'),
  written by the admin (rules: only fields visibility/updated_at/by). Rule: `views/scalping` readable by the admin, or by
  active members only when that field is 'members'; never signed-out/pending/expired. Rules tests in `tests/rules`.
- View `views/scalping` (`views.scalping`, one document, hash-dedup, `min_interval_s` 900 with `core` = calls
  logged/filled/hit/closed): since, summary (`views.scalping_stats`: win rate, avg/total return, profit
  factor, best/worst, avg hold, TP1-3 hit rates, streak, max drawdown of the cumulative curve), open calls with
  live_fields, last 60 closed/missed calls, curve, 15m demo bot block (`futures-demo-a-15m` from the bots report).
  Before fees. Skipped in lean mode.
- UI: Results tab "Scalping" (`components/Scalping.tsx`, admin or members when opened), Health summary, admin
  visibility toggle with confirm, share PNG drawn in the browser (`lib/scalpCard.ts`, cardCanvas style, "Demo results -
  15m scalping - since <date>"; nothing posted). Record rows open `RecordSheet` with `scalp` (no Adjust/Close).
- **Return only (owner, 2 Nov 2026):** every scalping figure (view, tiles, curve, tables, best/worst, live figures,
  share image, Health summary) is the trade's plain price return % (50/25/25 blended, no leverage), before fees; no
  ROI on margin (`scalping_stats` has no roi fields; rows keep `leverage` as info only; `LiveRoi plain`, `ReturnFigure`
  in `RecordDetails.tsx`). Demo-bot block: equity change % and each trade's P/L ÷ position size ("of position").
- **1-2 Nov rebuild** (`services/scalp_backfill.py`, branch `scalping-2`): one-time migration (flag
  `scalping_since_nov1`) sets `scalping_since` = 1 Nov 00:00 Dubai (2026-10-31T20:00Z), the old value kept in
  `scalping_live_since`. Each closed 15m candle from then to the live start is replayed: call time = `predictions.created_at`
  of the live forecast for that candle (none = engine did not analyse it = skipped), model = that forecast's
  `model_version_id` (file must exist; trained after the candle -> skipped), `analysis.analyze(as_of=close,
  bundle, multipliers=live_multipliers(until=t))`; live-only gates replayed as of t (AI lean threshold from the live
  probabilities, news, safety read-only, filter2 only if trained before t, record one-call read-only), then
  `log_scalp(extra=..., gate=gate_as_of)` (open / cooldown / re-entry judged on closes known by t) and followed at once
  (`update_signal_outcomes(ids=...)`). Rows: payload `backfilled`, `rebuilt_at`, `replay` {as_of, model, live vs replay
  probabilities}, `overlaps_live` (rebuilt call still running when a live call on the coin was logged; both kept).
  Cursor/state `scalp_backfill_state`, done flag `scalp_backfill_v1`; worker step `scalp_backfill` (≤120 s /
  `SCALP_BACKFILL_BUDGET_S`, ≤150 replays / `SCALP_BACKFILL_MAX` per tick); CLI `python -m app.worker scalp-backfill`.
  `prune_keep_versions` stops `trainer.prune_files` deleting the needed model files until done. View: `backfill`
  (state, progress, note), `split` {rebuilt, live}, `counts`; UI "rebuilt" tags + note. Entry rule = the current nightly
  `entry_policy1|15m` (only the latest is stored). Tests `tests/test_scalp_backfill.py`.

## v2.11 public 15m, grade A (owner decision 2 Nov 2026)
`analysis.A_ONLY_TFS` "15m,1h", `DEMO_ONLY_TFS` "1d,3d": 15m grade-A calls are public and counted in the record like 1h/4h
(time limit 250, `record_since_tf['15m']` restarted). One-time flag `public_15m_v211`: the 15m demo bot is replaced by
`futures-signal-ab-15m` (grade A, standard 50/25/25 exits, 250 candles, fresh book). The scalping log keeps logging the
same 15m grade-A calls (`tracking.log_scalp` accepts a public call); the scalping bot block reads `views.SCALP_BOT_IDS`.

**Scalping switched off (owner, 2 Nov 2026, after v2.11):** 15m grade A is in the main record, so the Results "Scalping"
tab and Health summary are removed and the engine no longer logs / follows / rebuilds scalp calls or publishes
`views/scalping` (`tracking.SCALPING_ON`, env `SCALPING=1` restores it). `scalp_signals` and its history are kept.

**Sealed proofs removed (owner, 2 Nov 2026):** no fingerprints at publication (`tracking.SEALED_PROOFS`, env
`SEALED_PROOFS=1` restores), Telegram `post_proofs` default off, no `proof` on record rows, `/verify` page, footer link,
Seal pill and VerifyBox deleted (`components/SealProof.tsx` gone). `signal_proofs` table and old rows kept.
## v2.12 public 1d / 3d grade A + Signals "All" (owner decision 2 Nov 2026, branch `signals-sort`)
- `analysis.A_ONLY_TFS` "15m,1h,1d,3d", `DEMO_ONLY_TFS` "" (`PAUSED_TFS` ""): 1d / 3d grade-A calls are public and counted
  in the record (30 candles, `tracking.HORIZON_BARS` default). One-time flag `public_1d3d_v212` (`worker.sync_config`):
  demo bots `futures-demo-ab-1d/-3d` removed; `futures-signal-ab-1d` / `-3d` added (grade A, standard exits, 30 candles,
  reset_token v212) unless a non-demo bot is already on that timeframe; the record is NOT restarted for 1d / 3d
  (earlier calls keep counting - ground rule). The 3d bot is `bots.FUTURES_3D`
  (not in `BOT_TFS`/`DEFAULT_BOTS`, so no spot 3d bot is ever auto-added); `policy_default_bots()` includes it.
  Frontend `Signals.tsx` TF_NOTES: 15m/1h/1d/3d "grade A". Tests `test_tf_policy_v28.py` (`test_public_1d3d_*`).
- Signals page: timeframe "All" (`components/SignalsAll.tsx` `AllList`) = every coin × timeframe with a trade call from the
  six `/futures?timeframe=` boards (loaded only while "All" is open); "Show waits" adds the waits. Row: coin, TF chip,
  grade, call, entry now ("Ready" = live price inside `plan.entry_zone`, else "Wait for entry"), confidence, entry /
  stop / TP1, status + live ROI. Click → that coin on its timeframe. `SortMenu` (both modes): Ready first (default:
  calls, grade A, in zone, confidence) · Strongest · Newest (`call.created_at`/`bar_ts`) · Coin A–Z · Timeframe (All only).
  URL query: `timeframe` (incl. `all`), `sort`, `waits=1`, `symbol`.

**Less text (owner, 2 Nov 2026):** page subtitles ≤ 1 short line, card notes ≤ 1 sentence; longer details behind "ⓘ".

## Road to Rich (Hesper) (admin, owner decisions 2 Nov 2026, branch `hesper-rich`)
- `services/hesper.py` (`Hesper(BotEngine)`): all-in demo bot, virtual money. Runs start at $100 (`START_BALANCE`); takes only
  fresh public grade-A calls from `signals` (status OPEN, payload grade A, published ≤ `FRESH_MS` 30 min ago, not demo-only /
  paused TFs; best = confidence, tie → newer; a call is never taken twice), one trade at a time (a pullback limit counts).
  Margin = whole balance × `ALL_IN` 0.995, leverage ≤ 25 lowered by `futures.safe_leverage` (liquidation 1.5x the stop distance
  beyond entry), futures fees/slippage/funding. Exits = the bots' `_manage_decision` (50/25/25, BE after TP1, TP1 after TP2,
  runner, call's `horizon_bars` from opening, admin stop/TP1 changes and "Close now" via `adjust._hesper`, reversal except 15m).
  Run ends only by itself when flat: liquidated or balance < $1 ("busted") → FAIL, realised ≥ $1,000 → SUCCESS; next run at
  $100 at once. Tables `hesper_runs`, `hesper_trades` (never deleted; a finished run never changes); state setting
  `hesper_state`, start flag `hesper_v1` + `hesper_since` (set by the first `run`). Worker step `hesper` after `bots`.
- Not a `bots` row → never in the bots report / Results "Demo bots" / record / auto-trade / Telegram / training. View
  `views/hesper` (`hesper.view`, last 100 trades, ≤500 runs, curves of the last 20 runs, `core`, min 900 s, skipped in lean
  mode); rules: admin only. Page `/rich` (`pages/Rich.tsx`, Admin menu "Road to Rich"), share PNG `lib/hesperCard.ts`.
  Tests `tests/test_hesper.py`; preview data `dev/seed.ts` `hesper()`.

- **Open-ended runs (owner, 14 Nov 2026, branch `hesper-open`):** a run no longer ends at $1,000. `GOAL` is a milestone:
  the first time the run's balance (equity at the engine's price) reaches it, `goal_reached_at` is stored on the state and
  on `hesper_runs` (column added by `db.MIGRATIONS`), event `goal_reached`, and the run keeps trading. Runs still end by
  themselves only as FAIL (liquidated / busted). Admin "End run & start new" on `/rich` (confirm sheet, `EndRun`) = job
  `hesper_new_run` {run} (admin only; refused when that run already ended) → `Hesper.stop_run`: open position closed at
  the engine's price (`_reduce` + `_close_trade`, exit reason "stopped by admin"), pending order refunded, run result
  STOPPED / reason "stopped" with its final balance, next run at $100 at once (`_finish`; taken calls carried over), then
  `views/hesper` re-published (core changes → at once). Old SUCCESS / "goal" runs keep their result. View: `open_ended`,
  `current.goal_reached_at`, runs `goal_reached_at`, score `stopped`, `milestones` (SUCCESS or goal_reached_at), `best_end`.
  UI: subline "$100 start · runs until stopped or liquidated · $1,000 milestone", milestone badge on the run card,
  "Stopped · Nx" + "$1k ✓" tags in Runs, tile "Reached $1,000"; share card tile "REACHED $1,000". No extra Firestore writes.
- **Members view (owner, 2 Nov 2026):** admin switch "Who can see it" on `/rich` writes `config/hesper.visibility`
  ('admin' default when missing | 'members'; rules like `config/scalping`). When 'members', active members (approved,
  not expired; never pending/expired/signed-out) read `views/hesper` and get a Results tab "Hesper Challenge"
  (`Rich embedded`, view only: no Share, no switch, line "Demo challenge with virtual money. Not a trading plan.").
  Shown everywhere (admin menu, page, share image) as **"Hesper Challenge"** (owner, 2 Nov 2026); "Road to Rich" is only the
  internal name in code comments. Rules tests in `tests/rules`.

## Safety fixes v2.13 (3 Nov 2026, branch `safety-v213`; no change to signals, grades, the record or results)
- **Lost-state guard.** `scripts/state_guard.py` (engine.yml, train.yml slices + merge, diag-tick.yml) fails the job when no
  usable state was restored (no DB / no settings / no candles) unless repo variable `FRESH_INSTALL=1`; engine loops, cache
  save and backups are skipped then. In code, `worker.migration_guard` (start of `sync_config`): one-time flags listed in
  `worker.MIGRATION_FLAGS` (a NEW migration must add its flag there; a test checks) count as done when SQLite **or**
  Firestore `admin/migrations.flags` has them (mirrored by `worker.mirror_migrations` when the set grows; read again at most
  every 6 h while one is missing); on a DB that looks fresh (no `signals` rows and no flag) every historical migration is
  marked done instead of run (never `clear_all_practice`, bot resets, `record_since` restarts or `reset_v1` on an empty state).
- **Backups** (`scripts/engine_backup.sh`): key = secret `ENGINE_BACKUP_KEY` if set, else SHA-256 of
  `FIREBASE_SERVICE_ACCOUNT`; restore tries both and falls back to older copies (exit 0 restored / 2 none / 1 failed).
  3 rotating slots by 6-hour period; engine.yml runs `ensure` after every hourly segment (backup when the newest is > 6 h).
- **train.yml merge** fails (no merge, no save, no backup) if the engine is still running after 60 min; next night retries.
- **Alerts**: `worker.alert_row` validates member-written alerts (bad ones skipped, insert errors counted
  `bad_alerts_skipped`); rules `validAlert` (keys, type list, symbol `^[A-Z0-9]{1,20}/[A-Z0-9]{2,10}$`, cooldown int
  60..31536000, timeframe list); members may only toggle `enabled`. Alerts page clamps the cooldown.
- **Public reports** (`reports` branch / job logs): `quick_status`, `coin_probe`, `fs_probe`, `audit_live`, `verify_engine` print
  counts only (no coin + side / grade / levels / record rows). Old commits on `reports` still hold such data.
- **Engine code**: `scripts/engine_loop.py` moves only to tag `engine-ok`, which `deploy.yml` (test job, after pytest, on main)
  force-moves forward; no tag yet → code unchanged.
- **Errors**: `app/redact.py` (`redact`, `error_text`, log formatter) strips Telegram tokens (`bot\d+:[\w-]+`), URL query
  secrets, Google keys; used by `rt.record_error`, step errors, providers' `last_error`, Telegram status, job errors and all
  worker logs. `views/health` (member-readable) has no raw error text (`recent_errors_count`, `has_error`); texts go to
  `views/health_errors` (admin only in the rules; Health page reads `/system/errors`). Tests `tests/test_safety_v213.py`.
## v2.13 honest record + stricter grading (3 Nov 2026, branch `honest-v213`, owner-approved audit steps 2-3)
- **Entry (C1)** `tracking._plan`: a call FILLED at publication is recorded at the live / decision price (`a["price"]`),
  targets rebuilt in R from it with the same stop (`entry_rule` {mode market, ideal_entry}); price at/beyond the stop →
  not recorded (`skip_entry` decision). BUY ON PULLBACK / confirm / pullback rules stay PENDING limits. Runner target
  rebuilt from the recorded entry (`_runner_for`). Signal card: `futures_view` shows the RECORDED levels while the call is
  OPEN on the same side (`plan.recorded`, "Entry (recorded)").
- **Net results**: closed calls store `return_net_pct` = `return_pct` − `cost_pct` (`analysis.round_trip_cost(futures=True)`,
  0.15 %) − `funding_pct` (stored hourly `derivs` funding_1h per coin, default 0.01 %/8 h for missing hours; on the open
  share: 100 % → 50 % after TP1 → 25 % after TP2, runner 100 %; longs pay). `tracking.net_pct/result_fields/net_sql`.
  Track record, Signal log summary, wins_today, weekly report, achievements, Telegram/cards, safety switch use NET as the
  headline and judge win/loss on net (>0); `gross_return_pct` kept; ROI on margin = net × leverage. Old rows: estimate.
- **Fills** `engine/manage.py`: stop / break-even / trail exit on a candle opening beyond the level fills at the OPEN
  (`stop_fill`, `GAP_FILLS`); limits fill only when traded THROUGH by one tick (`trades_through`, `TICK_FRAC` 1e-5).
  `series_sim.follow(open_=...)` + `fill` the same (test proves equality with gaps); `fill` mode "ideal" = old record.
- **Restart** flag `honest_record_v213`: **merged into the v2.14 fresh restart** (that one sets the flag; on its own
  `worker.honest_record_v213` only marks the flag, never moves the record). `honest_record_since` no longer shown.
- **Grading (C2)** `REQUIRE_EDGE_FOR_TRADE` (switch kept) default **OFF** since v2.14 (owner, 3 Nov 2026: "no edge rule");
  when on: grade A/B need `fc.edge_confirmed` AND `dv.policy_edge` (`analysis.edge_gate`, `EDGE_RULE` both|policy;
  research `series_policy.decide(require_edge=)`); else NO TRADE "no proven edge …".
- **Fail closed**: trade filter (v1) error, filter2 exception, safety switch exception, news calendar unavailable
  (synced before but older than `NEWS_CALENDAR_MAX_AGE_H` 72 h, or an error) → NO TRADE "CHECK UNAVAILABLE";
  `analysis.gate_failure` → setting `gate_failures` → Health `fail_closed` card "Fail-safe checks". An expired / missing
  nightly entry rule is NOT a failure: the v2.5 rule applies (now honest market entry).
- **Liquidation** `engine/futures.py`: `MAINTENANCE_TIERS` / `maintenance_rate(symbol)` (approx. Binance tier 1: BTC/ETH
  0.4 %, large caps 0.5 %, alts 1 %, PAXG / memecoins 2-2.5 %, unknown 1 %); `liquidation_price` includes the exit fee;
  `safe_leverage` buffer ≥ 1.5 (`MIN_BUFFER`), symbol-aware everywhere (bots, Hesper, autopaper, cards, alerts);
  frontend `paperFutures.MMR_TIERS/mmrOf/liqPrice(…, symbol)`.
- **Auto-trade**: (v2.13 cap 20x, replaced by v2.14 10–50x below); reversal only closes an auto
  position / order opened from the SAME timeframe (`pos.signal.timeframe`); otherwise the new call is skipped.
- Impact study: `python -m app.research v213` (`research_v213.py`, workflow `research-v213.yml`, results
  `research-results/results/v213-*.json`): live record since 30 Oct old / fills / new entry, gross vs net; research replay
  current vs edge-required grading × ideal vs market entry on the 30 % test split. Tests `tests/test_v213.py`.
- **Impact (3 Nov, `results/v213-20261103T153721Z.json`)**: replay test split, 163 series: old record entry (ideal,
  filled at once) +0.10R/trade vs honest market entry −0.04R (the ideal entry inflated results by ~0.14R). Edge required
  (edge test AND policy) leaves 3 test trades (only LINK 12h has both; 1 of 190 active models) → effectively NO public
  calls; `EDGE_RULE=policy` (direction-policy edge only) keeps ~74 % of trades but is still −0.057R. Live record since
  30 Oct: 11 calls, all would fail the edge rule; 2 of 5 closed wins become net losses with market entry.

## v2.14 fresh restart, 10–50x leverage on 15m only, $1,000 practice + Add funds (3 Nov 2026, owner decisions, branch `release-v214`)
- **Fresh restart** (`app/fresh_restart_v214.py`, flag `fresh_restart_v214` in `worker.MIGRATION_FLAGS`, run from
  `worker.sync_config`; dry run `python -m app.fresh_restart_v214 dry-run`). Owner chose "delete permanently", wins and
  losses alike. DELETES (SQLite): `signals`, `shadow_signals`, `scalp_signals`, `signal_proofs`, `signal_adjustments`,
  `decisions`, `bot_trades`, `bot_equity`, `bots` rows (re-created from `config/bots`, same line-up and settings, `reset_token` v214),
  `hesper_runs`, `hesper_trades`, settings `hesper_state/_since/_v1` (next cycle = Run #1 at $100),
  `safety:*`, `honest_record_since/_prev`, `record_restart`, `scalp_backfill_state`, the `published` cache (every view
  re-published from the empty record); Firestore `owner/telegram_drafts` items, `views/scalping`, legacy `views/bot_*`.
  Sets `record_since` = now, `record_since_tf` {}, `record_restart` {at, text "Fresh start <d Mon yyyy, Dubai>: real
  entry prices, after fees."} (Results shows only this line, `views.restart_note` → track_record `restart`),
  `tg_win_last` = now, `honest_record_v213` = true. KEPT: candles, models, training data, predictions, news, users,
  memberships, alerts, Telegram token/options, other settings, and members' `paper*` / `auto_paper*` (owner). Never on a
  fresh / empty DB (guard marks it done; the module also only sets the flag when no history exists); runs once (Firestore
  mirror). Tests `tests/test_v214.py`.
- **Leverage policy — 15m ONLY** (owner, 3 Nov 2026; `futures.POLICY_TFS` = ("15m",), env `LEVERAGE_POLICY_TFS`,
  `futures.in_policy(tf)`). On 15m: `engine_leverage(entry, stop, symbol, grade, timeframe)` = clamp(safe max × grade
  factor, 10, 50), A 100 %, B (or none) 75 %; safe max = `safe_max_leverage` (v2.13 tiers + closing fee, liquidation
  ≥ 1.5× the stop distance, measured up to 125x); safe max < 10 → None = not taken ("stop too wide for 10x minimum",
  `TOO_WIDE_REASON`): `analysis.leverage_gate(..., timeframe)` → NO TRADE "STOP TOO WIDE", record skip_entry, bots /
  Hesper / auto-trade skip. **Every other timeframe keeps v2.13 exactly** (`futures.leverage_for(…, timeframe, cap)` →
  `safe_leverage` capped, never refused for a wide stop): card / record `signal_leverage` ≤ 10x (`CARD_MAX_LEVERAGE`),
  futures bots ≤ their config (20x, `MAX_LEVERAGE` 20), Hesper ≤ 25x (`hesper.MAX_LEVERAGE`), auto-trade v2.13 (cap 20x,
  "signal" = the card's suggestion, else the member's setting, ≤ safe); 15m auto-trades use the engine's choice (member
  setting ignored). `futures_view` sets `plan.leverage_policy` only on 15m; UI shows "10–50x · chosen by engine" only
  then (TradeCall), else "Nx suggested" / "liq." as before. AutoTrade selector = v2.13 + note "15m auto-trades use the
  engine's 10–50x"; Hesper "$100 → $1,000 · all-in · up to 25x (15m: 10–50x)". The fresh restart keeps bot configs
  (leverage 20) - only `reset_token` changes.
- **Practice accounts**: new accounts $1,000 (`writeShapes.PAPER_START`, `newPaperFields`; `autopaper.START_BALANCE`);
  existing accounts unchanged. "Add funds" (Trade → Assets: +$1,000 / +$5,000 / custom) = `paper.addFunds` /
  `paperFutures.addFunds` → `writeShapes.paperTopUp`: balance + amount, `deposited` (total in; older accounts: their
  starting_balance), `deposit_count` +1, `deposits` (last 50). Return / P&L = equity vs `deposited` (Assets shows
  Deposited and P&L). Cap $1,000,000 deposited. Reset → new $1,000 account. Rules (`firestore.rules.template`,
  `validPaper`): new account (new `id`) 0 < start ≤ 1e6, deposited = start, count 0; same account: start fixed,
  deposited never down, a rise ≤ 1e6 total with count +1 and the balance up by the same amount (±0.01); rules tests in
  `tests/rules` ("paper: …").
- **No edge rule** (owner): `REQUIRE_EDGE_FOR_TRADE` default off (see v2.13).
- Impact study: `research_v213.replay` → `leverage_v214` (per timeframe: removed by the 10x minimum, avg / median leverage,
  R before / after) in `research-results/results/v213-*.json`.
- **Leverage impact (3 Nov, `results/v213-20261103T174735Z.json`, test split, current grading, honest entry):** with the
  policy on 15m only, calls removed = **0 %** (15m: 368 trades before and after, 0 too wide; median stop 1.29 %; avg
  25.5x, median 24x; 1.6 % at 50x, 2.7 % at 10x; avg R −0.101 unchanged). Other timeframes unchanged (v2.13). For
  reference, the rule on every timeframe would have removed 4h 49 %, 12h 68 %, 1d 87 %, 3d 94 % (overall 1552 → 1121).

- **v2.18 fresh restart** (owner, 4 Nov 2026 13:10 Dubai, after the morning updates): flag `fresh_restart_v218` (in
  `MIGRATION_FLAGS`), runs once after v2.14 via `fresh_restart_v214.maybe_run(..., flag, token="v218", version="2.18")`:
  the same deletion (record, bot books, Hesper, side tables), record restarts, members' practice accounts kept.

## UI v2.15 design system (3 Nov 2026, branch `ui-v215`, frontend only)
- Shared blocks in `components/kit.tsx`: `Tile` (label / value / sub; `variant` plain | box | strip = a `.metric-strip`
  cell; `big` 28 px), `Badge` (tones bull/bear/warn/accent/mute/ai/text, pill, `caps`), `Segmented` (the `.seg` track:
  timeframes, Futures/Spot, view switches; `strong` = gold fill), `Chip` / `.chip` (standalone filter pills: News,
  Signal log), `TabStrip` (underlined page tabs: Results, Track record). Old names stay as thin wrappers: `ui.Stat`,
  `ui.Badge` (caps), `SignalExtras.Pill`, `TradeCall.GradeBadge`, `ui.Tabs` / `TfTabs`; `ui.tsx` re-exports Tile/Segmented/Chip.
- Type scale 12 / 14 / 16 / 20 / 28 px = `text-xs / sm / base / xl (= lg) / 2xl` (tailwind.config `lg` 20 px, `2xl` 28 px);
  nothing under 12 px on phones (`text-[10/11px]` removed); larger only on the signed-out landing and the Home hero.
- Touch: under 768 px or `(pointer: coarse)` every `.btn`, `.input`, `.seg` button and `.chip` is ≥ 44 px; `.tap` gives a
  small inline control (ⓘ, ★, theme button) a 44 px box without moving the text, `.tap-h` only the height. Desktop stays compact.
- Radius: cards 12 px (`--r-card`, `.panel`, `.tile`, `.metric-strip`), controls 8 px (`--r-control`), pills full (`--r-pill`, Badge, Chip).
- Colours only from theme tokens. Charts/canvas: pass a token name (`"--bull"`, `"--bear"`, `"--accent"`, `"--warn"`,
  `"--ai"`, `"--mute"`) as a line colour; `appearance.themeColor()` resolves it at draw time (charts rebuild on theme
  change). SVG uses `rgb(var(--x))` (FearGreed zones). Achievements' medal canvas keeps its fixed gold (share art).
- "Not published yet" (404-type waits) render as neutral `Empty` inside `ErrorBox` (`ui.isNotReady`); real errors stay red.
- Navigation: phone More sheet grouped Markets (News, Radar) · Tools (Scanner, Backtest, Replay) · Account (Alerts,
  Community, Settings) · Admin (+ Users with the pending count); unread in-app alerts (`useLive().alerts`) badge Alerts.
  Desktop: "Tools" dropdown after Radar (sidebar: Tools group). `/users` wrapped in `AdminOnly`. Below 380 px the header
  wordmark is "Crypto Intel AI".
- Notifications (Android): `NotifyPrompt` key `cia-notify-asked2` {result, at}: only granted / denied are final; a closed
  question ("default") shows "Allow notifications" and re-asks at most once a day. `push.enable` says "You closed the
  question…" for default, wraps the token save ("could not be saved to your account…"), and no longer treats a server
  PERMISSION_DENIED as "blocked". `push.appWithoutChrome()` (was Settings `oldApk`), `push.APK_URL`, `push.ANDROID_STEPS`;
  `components/NotifyHelp.tsx`: `BlockedHelp` (collapsible steps), `ChromeWarning` (Settings, Alerts), `AppChromeBanner`
  (app-wide, Android app without Chrome), `useApkInfo` / `apkVersion` (APK "v2.1.0 (run number)" from `/download/android.json`).
  Settings → About shows "v<version> · build <BUILD_ID>"; the landing footer has an "Android app (APK)" link.
- Removed dead files: `pages/Futures.tsx`, `pages/Track.tsx`, `components/Scalping.tsx`, `lib/scalpCard.ts`.
- Small screens ≥ 280 px (Z Fold cover, 4 Nov 2026, branch `fold-v218`): tested at 280/320/344/360/390. No custom screen
  (an `xs` in `extend.screens` would sort after `sm`); use `max-[359px]:` / `min-[360px]:` (and `min-[340px]`/`min-[380px]`
  for the header wordmark: logo only < 340, "Crypto Intel AI" < 380). More sheet: `.more-grid` (auto-fill
  minmax(7.25rem) → 3 / 2 / 1 columns), labels wrap in their cell, Count `shrink-0`; the panel scrolls, the wrapper
  spans top→bar with `pointer-events-none`. `.seg` buttons 36 px wide (44 tall) < 360 so six timeframes fit a row.
  ROI / Live labels (`RoiFigure`, `LiveRoi`) wrap on phones (`sm:whitespace-nowrap`); Track record phone cards put the
  result on its own row < 360. Coin tiles < 360: 28 px logo, `text-base` price, badge row wraps. Check for overlaps
  with a mobile-emulated browser at a fixed width: `innerWidth` grows when content overflows, so compare to the set width.

## v2.16 growth: coins, AI briefing & coin reports, Telegram funnel, smarter alerts, 7-day card (4 Nov 2026, branch `growth-v216`)
Firebase stays on the free Spark plan (owner, 3 Nov 2026): everything below is paid for by write savings in the same change.
- **Coins**: live watchlist on 3 Nov was 20 (TEST_COINS + PEPE ENA GALA NVDAB ZEC SPCXB MSTRB TRX U UNI, admin-added).
  `worker.GROWTH_COINS` LINK ADA SUI DOT NEAR appended once to `config/watchlist` (not pinned, only if the exchange lists
  them, renames applied) by `worker.add_growth_coins`, flag `coins_growth_v216` (in `MIGRATION_FLAGS`; a fresh DB marks it
  done instead). Removing one later sticks. Candles / 15m deepening / funding / crowd / tick bootstrap handle them as any
  new coin; bots use `symbols: all`. `shard_pairs` now trains missing, then oldest models first within each cost tier.
- **Write savings**: `worker.PERF_EVERY_S` 3600 (perf_ pages changed every candle; ~73 writes/coin/day saved),
  `ANALYSIS_EVERY_S['15m']` 1800 (env `ANALYSIS_15M_EVERY_S`; a changed call still goes out at once), Telegram status doc
  only when something was sent / errors changed / hourly (`telegram.STATUS_EVERY_MS`, was every cycle).
- **AI market briefing** `services/briefing.py`: on hourly analyses, refreshed every 4 h or (≥1 h) when the mood / BTC / ETH
  4H regime group changes (`core`). Facts = engine numbers only (4H mood + breadth, BTC/ETH regime, 24h change and 4H AI
  lean, Fear & Greed, dominance, movers, next 24 h High USD releases, open calls by side). Gemini text (`TASK`, ≥25 calls
  kept free, `AI_RESERVE`) accepted only if `acceptable()`: ai_advisor.clean_text, no predictions / profit / advice
  (`PREDICT_RE`), every number in the input (`numbers_ok`), 2-6 sentences; else `template()`. Bullets always deterministic.
  Stored in setting `briefing`, published as `briefing` inside `views/market_context` (core = its `at`, so it goes out at once).
  Home: `Polish.BriefingLine` replaces the hero sub-line (3 lines + More on phones, facts as Badges).
- **AI coin reports** `services/coin_reports.py`: per coin on hourly analyses (needs 12H): trend (4H + 1D regime groups),
  nearest 4H support / resistance, AI lean + directional confidence 4H / 12H (`direction_view`, `confidence`), open call
  (stop in force after TP1 / TP2), main risk, invalidation. No live price inside. Optional Gemini line per coin (open calls
  first, ≤3 per cycle, ≤40 a day, renewed only when `core` changed and ≥4 h; same checks as the briefing). ONE document
  `views/coin_reports` (min 3600 s, hash-dedup). Asset page `components/CoinReport.tsx` (api path `/coin-reports/<slug>`).
- **Telegram funnel** (`services/telegram.py`, options default on, only while the autopilot is enabled): `post_daily_call`
  = the first grade-A public call of each UTC day (publication order) whose entry FILLED (an earlier pending call holds the
  choice; NOT_FILLED / VOID are skipped), posted `CALL_DELAY_MS` 2 h after the fill, result (after fees) when it closes;
  both sent directly, never drafts (state `tg_daily_calls`, start `tg_daily_since`); replaces the old teaser while on.
  `post_briefing` at 05:00 and 13:00 UTC (briefing ≤5 h old). `post_week7` Mondays ≥06:00 UTC = `views.recent_summary`
  (last 7 days, after fees) card `cards.week7_card`; replaces the old `post_weekly` while on. Settings toggles in `TelegramCard`.
- **Smarter alerts** (`services/alerts.py`): types ENTRY_REACHED, TP2_REACHED, TP3_REACHED, SIGNAL_CLOSED (stop, BE / time
  limit after a target, admin close, NOT_FILLED), SIGNAL_UPDATES (`params.events` ⊆ entry,tp1,tp2,tp3,closed), MOOD_CHANGE
  (4H watchlist mood flips BULL↔BEAR, setting `market_mood`). Symbol `ALL/USDT` = every coin, timeframe `all`. Worker step
  `call_alerts` (`alerts.lifecycle` + `alerts.mood`) after analyses; one per rule per call per event (`alert_marks`), new
  rules primed (`last_state = 'primed'`, past events never sent), ≤ `MAX_EVENTS_PER_DAY` 30 per member. Delivered as
  alert_events (→ `alerts_u_{uid}`) + push (`worker.PUSH_TITLES`). Rules `validAlert` types + timeframe 'all'; rules tests.
  Alerts page: quick-start Chips "My signals: entry / TP / SL" and "Market mood change", event picker, "All coins".
- **Last 7 days** `views.recent_summary` → `track_record.last_7d` (no time stamps inside, so no extra writes; sample note
  under `MIN_SAMPLE` 30) → Results card `TrackRecord.Last7`; same numbers as the Telegram week7 card.
- Tests `tests/test_growth_v216.py`; preview seed: market_context.briefing, views/coin_reports, alerts_u_* events, last_7d.
## v2.16 referrals + leaderboard (3 Nov 2026, owner decisions, branch `community-v216`; Firebase stays on the free plan)
- **Referrals.** Member code: `ref_codes/{code}` {uid, created_at} + `users/{uid}.ref_code` in one batch (`lib/referral.ts`
  `createMyCode`, 8 chars a-z 2-9; rules: active member, once, never changed; `ref_codes` get when signed in, no list). Link
  `https://cryptointelai.com/?ref=<code>`: `referral.captureRef` (on load) keeps the code 30 days in localStorage `cia-ref`
  and strips it from the address. A NEW users record (`session.tsx`, or `membership.submitPayment` when it creates the record)
  gets `referred_by` (referrer uid) + `ref_via` (code) via `writeShapes.newUserRecord(…, ref)`; rules `validReferral`: both or
  neither, code exists and belongs to that uid, not yourself; members can never add / change it later. Reward:
  `membership.grantMembership` is now a transaction; when `writeShapes.referralDue` (friend's FIRST paid approval: price > 0,
  not free, no earlier paid entry, no `referral_reward` yet) the referrer (only if `status == approved`; expired restarts from
  now; no end date = kept) gets `writeShapes.freeMonth` (+1 month, history entry `kind: "referral"`, amount 0, free, `ref_uid`,
  `ref_name`) and the friend `referral_reward` {to, at, by} - once per friend. Returns {to, reward}. Reward entries never
  count as income or payments (`writeShapes.isRewardEntry`, Users `paidLine`). Engine `services/referrals.py`: counts from
  `users_cache` (no reads) → `users/{uid}.referral_stats` {joined, paid, months} written only when changed. UI: Settings →
  "Invite friends" (`components/InviteCard.tsx`, active members), Users: "Invited" filter, "Invited by …" / "Invited N · paid ·
  free mo" lines (`RefLine`), card "Referrals & prizes" (`RewardsCard`).
- **Practice leaderboard** (`services/leaderboard.py`, worker step `leaderboard`; Results tab "Leaderboard",
  `components/Leaderboard.tsx`). Futures practice account only (documented choice). Calendar month, Dubai time.
  return = (equity − equity at month start − deposits) / (equity at start + deposits); equity = wallet + order reserves +
  Σ max(0, margin + P/L at the engine's price) (Trade-page formula; coins outside the watchlist: one public ticker call).
  Ranked: active members WITH a username (privacy; others not shown), not in `owner/leaderboard.excluded`, ≥ 5 closed trades
  (`totals.count` delta), no account reset in the month. Hourly at most (`LEADERBOARD_EVERY_S`), skipped in lean mode. Reads:
  `paper/{uid}_futures` only when the member was seen since the last read (`fs_presence_seen`, saved by
  `sinks.refresh_member_estimate` from the presence query it already makes), the reading is > 6 h old
  (`LEADERBOARD_STALE_S`, auto-trade), or a month began; other accounts are re-priced from the stored reading. Tables
  `leaderboard_entries` (start + last reading per month/uid), `leaderboard_winners` (decided once at the first run after the
  month ends; that reading closes the old month and opens the new one; exact ties share #1). Docs: `views/leaderboard`
  (top 50 usernames, return, trades, last winner, `badges` by username; no uid/email) and `admin/leaderboard` (JSON: every
  entry with uid, start, deposits, equity, `flags` "balance changed without trades" / "return above 300%" / reset; winners),
  written only when changed. Prize: admin "Award prize" (`lib/leaderboard.ts awardPrize`, transaction): +1 free month
  (`kind: "prize"`), `users/{uid}.badges` += `lb:YYYY-MM`, `owner/leaderboard.awarded.{month}.{uid}` (refused twice or for a
  non-approved member); never automatic. "Keep out" = `owner/leaderboard.excluded`. 🥇 shown in Community and the ranking.
- **Cost (free plan):** engine reads ≈ members-with-username × 4/day (6 h refresh) + 1 per active member-hour + 24
  (`owner/leaderboard`); writes ≤ 48/day (two docs, hash-dedup) + referral counts only on change. 50 members ≈ 300 reads,
  ≤ 50 writes/day; 200 members ≈ 1,000-1,300 reads, ≤ 60 writes/day. Members: 1 read per leaderboard / Community open,
  2 writes once per code, 1 read at a referred sign-up, admin +1 read/+1 write per rewarded approval.
- Tests: `backend/tests/test_leaderboard.py`, `test_security.py` (rules template), `tests/rules` ("referral: …", "rewards: …",
  "leaderboard: …"). Preview seed: `dev/seed.ts` `leaderboard()`, sara_k has a code, referrals and a badge.

## v2.17 AI add-on switches + no confidence % for members (owner, 4 Nov 2026, branch `tidy-v217`)
- **AI add-ons stay ON pending a crash / volatility-regime study** (owner decision 4 Nov 07:16; switching them off is
  postponed). The strict holdout test (`research-results/results/aiv3-final-20261103T204940Z.json`, Holm-corrected block
  bootstrap) passed none except the higher-timeframe context of SOL/USDT 15m. Switches (`config.Settings`, default on =
  release-v216 behaviour; env 0 turns one off): `TRADE_FILTER` (v1 per-model filter, `trade_filter_v1`), `TRADE_FILTER2`
  (pooled filter), `RUNNER_MODEL` ("let winners run"), `TARGET_MODEL` (AI target lifts; off = plain historical base rates in
  `setup.pick`), `USE_DERIV_FEATURES` (futures-data gate per series), `HTF_GATES` (higher-timeframe gate per series; when 0,
  only `HTF_GATE_KEEP` = "SOL/USDT|15m" still runs it, `settings.htf_gate_on`). A switched-off add-on is neither trained
  (`trainer.train_bundle` stores `{"enabled": False, "reason": trainer.OFF_REASON}`, `training.train_one` skips the gates,
  `series_nightly.run` skips filter2) nor scored (`analysis.model_forecast` → `trade_filter` / `target_lift` / `runner` None,
  no fail-closed). Bot trade info now also stores `grade`.
- **No confidence % for members** (the next-candle hit rate overstates, negative Brier skill). Grade (`A · strong` /
  `B · moderate`, `TradeCall.gradeWord`) instead on the signal card (Pro "AI view"), Signals All ("Grade" column, sort
  "Strongest (grade)" = grade then the hidden confidence), Home opportunities (`scanner.dashboard` adds `grade`, sorted by
  grade), Asset header, Scanner (sort "Strongest (grade)"), Replay, Demo bots (signal-confidence buckets admin only),
  Track record KPI (admin only), Signal log column (admin only), copy text, coin reports (`coin_reports._expect` has no
  `confidence`; "weak" only), briefing facts (no confidence, so Gemini never sees one), advisor note inputs, alert texts
  (`TRADE_SETUP` message, `CONFIDENCE_ABOVE` text; the Alerts page no longer offers confidence alerts / minimum
  confidence; old rules keep working), manual + PDF. The admin still sees it labelled "Model hit rate (next candle)".
  Internal value kept for sorting, grading, Hesper and research. Tests `tests/test_v217.py`.

## v2.20 Overview + sidebar (owner, 4 Nov 2026, branch `home-v220`, frontend only)
- **Desktop sidebar is the default** (`lib/appearance.tsx`: `nav` default "side"; the saved object used to carry the old
  "top", so only `navChosen: true` - set whenever the person picks Top bar / Sidebar - keeps "top"). Sidebar only at
  ≥ 1024 px (`lg`); 768-1023 px always get the classic header + top nav row, phones the header + bottom bar (unchanged).
  `components/AppNav.tsx`: `Sidebar` (logo, groups main · Markets · Tools (folds, localStorage `cia-side-open-Tools`) ·
  Account · Admin, icons `Ico`, accent bar on the active row `.side-link`, collapse to icons = `appearance.sideCollapsed`,
  bottom: Theme switch light ↔ last dark theme (`cia-last-dark`) + Help & support mailto), desktop top bar `PageTitle`
  (title + one-line subtitle per path, not an h1), `LiveChip` (feed status, ticking clock, engine age from views/health),
  `AlertsBell` (`useLive().alerts`), `ProfileMenu` (initials, username, "Owner" / "Member · until <date>" from the
  users/{uid} listener the session already has; Settings, Alerts, Sign out). Admin group = `ADMIN_NAV` + Users (icon map
  has `/guardian`). App.tsx keeps NAV / ADMIN_NAV / TOOLS_NAV; sidebar groups memoised.
- **Home = Overview** (`pages/Dashboard.tsx` + `components/Overview.tsx`), only real data:
  row 1 BTC price (live ticker + 24h, sparkline = last 24 hourly closes) · Total market cap (`market_context.pulse`, else
  `context.market`; no cap history exists, so the line is BTC dominance 7d, labelled) · BTC 24h volatility (realised vol of
  the last 24 hourly log returns, annualised ×√8760; line = rolling 24h vol over 7 days; plus 24h range) · Market
  sentiment (4H `dashboard_4h.market_status` mood word + Fear & Greed gauge). Candles via `lib/klines.ts useKlines`
  (Binance futures klines, spot fallback, module cache shared by cards and chart: 1h × 200 = one request per 5 min,
  only while visible). Row 2 BTC chart (CandleChart lazy, 1H/4H/1D/1W, choice in `cia-home-chart-tf`) + "Market
  intelligence" = v2.16 briefing (mood chip, 1-2 sentence headline, 3 bullets, View details = full text). Row 3 Global
  market status (BTC, ETH, total cap, F&G, altcoin strength = `market_context.altseason`), Active signals
  (`track_record.live.signals` OPEN; Live % = `RecordDetails.liveOf().move`, no leverage, before fees; status rule
  `Overview.healthOf`: position of the price between the stop in force (0) and the next target (1): Healthy ≥ 0.5,
  Watch 0.25-0.5, At risk < 0.25 or beyond the stop; all targets hit = Healthy; pending = Waiting; rows open
  `RecordSheet`), Trade Guardian card (admin only, `views/guardian` via `/guardian`; renders nothing when missing).
  Row 4 Recent activity (record opens / closes, the member's alert events `/alert-events` = views/alerts_u_<uid>,
  briefing time) and Performance overview (`track_record.live.summary` win rate / total / profit factor, max drawdown
  from `live.curve`, 7-day toggle from `last_7d`; "Too early to judge: N closed since <date>" under 30).
  Below: the old Home (market line + Know why + quick actions on top as `OverviewHead`; Market overview TF tabs,
  My coins, then "More market detail" fold, `cia-home-detail`: regimes, top signals, sentiment, Market insights,
  forecasts, heatmap, opportunities, risks). Old `Polish.DashboardHero` removed.
- Reads: + `views/track_record` (1 per Home open) for everyone, + `views/guardian` for the admin; everything else was
  already subscribed (dashboard_4h, market_context, context, alerts_u, health). No new sockets. Price-driven parts
  subscribe themselves (`useTickerThrottled` 1 s, table rows memoised) so the page does not re-render on every tick.
- Preview: `dev/preview.tsx` mocks Binance klines (random walk ending at the sample price); `dev/seed.ts` has a
  `views/guardian` sample.
## v2.19 Trade Guardian (admin, RECOMMEND-ONLY; owner-approved 4 Nov 2026, branch `guardian-v219`)
- `services/guardian.py`, worker step `guardian` (after `hesper`) + `guardian_publish` (after `jobs`). Flag `GUARDIAN`
  (default on; `GUARDIAN=0` off). No migration flag (nothing one-time; `guardian_mirror_checked` is a plain setting).
  It NEVER changes a call: stop / targets / time limits run exactly as before; only the admin's Apply changes anything.
- Each tick (GitHub Actions: ~5 min, cannot reliably go lower) every OPEN + FILLED `signals` call (also after TP1): 1m
  candles of coins with open calls + BTC (provider `fetch_ohlcv(…,"1m")`, incremental SQLite cache `guardian_m1`, 3 h),
  15m ATR. Deterministic points (constants at the top of the module): adverse move 5/15/60 min in ATR (≤30), distance to
  the stop in force in R (`stop_in_force` = manage rules: admin stop, BE after TP1, TP1 after TP2; ≤25, halved after TP1),
  give-back after TP1 (≤25), BTC shock against (1m ≥0.6 % / 15m ≥1.5 %; not for BTC / PAXG; ≤20), 1m volatility ratio
  while moving against (≤15), own-TF analysis flipped (25) / grade lost (8), funding z ≥3 against (5, estimate; OI not
  used: 2-day lag). Severity <50 nothing, 50–74 TIGHTEN, ≥75 CLOSE. Proposed stop (`propose_stop`): tighter of 15-min
  1m extreme ± 0.1 ATR and price ∓ 1 ATR, ≥0.3 ATR from the price, ≥0.05 R tighter; validated (`stop_problem` ≥0.2 ATR,
  right side, tighter) and by `adjust.validate`. Stale (1m >3 min, BTC stale for alts, analysis older than
  `ANALYSIS_MAX_AGE_MS`, no ATR) → no recommendation, counted `skipped_stale`; 1m vs engine price >2 % → `skipped_price`.
- Gemini (`second_opinion`): numbers only in, {explanation 2–3 sentences, verdict agree|downgrade}; may lower one step
  (CLOSE→TIGHTEN, TIGHTEN→none = status `downgraded`), never raise; rejected when numbers not in the input / predictions /
  advice (`ai_acceptable`: briefing checks + `ADVICE_RE`) → rules + template. Respects `briefing.ai_room` reserve, ≤3 calls
  per tick. `ai.path` ai_agreed | ai_downgraded | rules_only | ai_rejected.
- Table `guardian_recs` (status live | applied | dismissed | expired | rejected | void | superseded | downgraded). Dedupe
  (`should_create`): one per call per rules level; escalation TIGHTEN→CLOSE supersedes; after expired / rejected / void /
  downgraded only when the band persisted `PERSIST_TICKS` (3) ticks; applied / dismissed block that level. Expiry 30 min
  (+10 min grace for a click made in time). Lost DB: rows restored once from `views/guardian`.
- Admin push (no uid, no broadcast; skipped if `ADMIN_EMAILS` empty) per new live recommendation; optional private
  Telegram DM only with env `GUARDIAN_TELEGRAM_CHAT` (refused if it equals the public channel). Never in `decisions`
  (member-readable `decisions_recent`).
- Apply = job `adjust_signal` with `guardian_id` (TIGHTEN: `stop` = the proposed level exactly; CLOSE: `action: close`):
  admin check, `request_problem` (wrong level / signal → refused, recommendation stays live), `revalidate` (expired, call
  closed / pending / changed after the recommendation, price too close) → marked rejected / expired; then exactly
  `adjust.apply` / `adjust.close` (bots, Hesper, member broadcast) → applied. Dismiss = job `guardian_dismiss` (admin only).
- Shadow (`shadow_outcome`, when the call closes): `tracking.evaluate_signal` with vs without the change at the
  recommendation time (applied ones: without = minus the applied adjustment), net R = (return − cost) / original risk %
  (funding ignored, same both sides). `scoreboard`: net / saved / cost, applied vs not, by level. Never writes `signals`.
- `views/guardian` (admin only in the rules; rules tests "guardian: …"): status, live, last 50 history, scoreboard,
  config; hash-dedup, `min_interval_s` `PUBLISH_EVERY_S` 240 (v2.21; was 1800, "Last check" looked late) → ≤≈288 writes/day; lean mode: only a new CLOSE. Reads: 0 per tick (1 once after a lost DB; 1 per Telegram
  DM if enabled). Page `/guardian` (`pages/Guardian.tsx`, Admin menu "Trade Guardian"), seed `dev/seed.ts guardian()`.
  Tests `tests/test_guardian.py`.
## Health command centre v2.19 (admin, 4 Nov 2026, branch `health-v219`, frontend only)
`pages/Health.tsx` rebuilt as a command centre (layout only; nothing dropped): KPI row (Engine LIVE/LATE/STALE + last cycle,
writes today vs lean point / 20,000 with bar, reads vs 50,000, open record calls + closed since restart → Results) ·
"System health" service tiles (dot ok / warn / down / off; tap opens + scrolls to the matching details): engine loop,
market data, futures data (funding map in `views/bots`), news & calendar (`views/news` generated_at / errors), Telegram
(`owner/telegram_status`), training, fail-safe checks, safety switch, database / lean, live prices; a "Trade Guardian"
tile linking `/guardian` appears only when `views/guardian` exists · open signals (top 5, Oldest / Newest, side bar) ·
data sources with freshness · models summary (active, edge, oldest, libraries) · demo bots (return since restart,
open / closed) · safeguards (safety switch + fail-safe lists). Collapsible details: database use, engine &
configuration, market data + candle series table, models table, recent errors (count badge). Not in any view yet
(so not shown): Gemini calls today, backup age, Hyperliquid history freshness. Preview seed: `views/bots`,
`owner/telegram_status`, `views/news.generated_at`.

## Other features (where to look)
News & calendar `services/news.py` + `pages/News.tsx` · Radar `services/radar.py` + `pages/Radar.tsx` · Track
record / weekly report / achievements / wins_today `views.py` + `pages/Results.tsx`, `Report.tsx`,
`Achievements.tsx`, `components/WinsToday.tsx` · Telegram autopilot `services/telegram.py` (every win + daily/weekly/teaser as image cards from
`services/cards.py`, Pillow, Inter fonts + logo in `app/assets`) + `components/TelegramCard.tsx` · Live trading stream `frontend/src/lib/stream.ts` · Memberships
`services/membership.py`, `components/Membership.tsx` (prices 15/40/70/130 USDT, USDT only; Binance QR or MEXC UID 00183657; support email in
`config/membership`) · Manual `docs/manual/manual.md` → `python scripts/build_manual.py` (members only, no admin
instructions) · Promo video `frontend/public/demo.mp4` (70 s, original soundtrack).

Member menu: Home · Signals · Trade · News · Radar · Results · Community · Alerts · Settings. Owner extras: Weekly report,
Achievements, Health, Road to Rich, Trade Guardian, Users.

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
Arabic (RTL) · smarter exits per coin · parallel training matrix · Binance daily metrics
(OI, long/short, taker) as features · iPhone App Store ($99/yr, owner decision) · real-money auto-trading (only after a proven record and a VARA check) ·
MetaTrader 5 link (owner, 16 Nov 2026: noted, NOT now - after testing / launch, only if members ask): view-only MT5
indicator that reads a small signal feed and draws entry / stop / TP1-3 / grade on the member's chart, never trades
(mind free-plan reads); MT5 auto-trading EA or MQL5 copy-trading = real orders → same rule as real-money auto-trading.
Broker crypto CFDs have other prices / spreads than Binance, so levels and results would not match the record.

## v2.21 notifications (4 Nov 2026, branch `notify-fix`)
- Telegram: `post_each_win` now every win after fees (TP1/TP2/TP3, net > 0); new `post_news` (default on): the
  high-impact US release heads-up (same items as the phone push, `news.due_notifications`) sent directly by
  `telegram.post_news` (never a draft). "Ask me before posting" (`approve_first`, default on) still holds wins /
  briefing in `owner/telegram_drafts` until the owner presses Post.
- Members: `worker.ensure_call_alerts` gives the admin (`alerts/auto_calls_owner`) and every active member
  (`alerts/auto_calls_<uid>`) one SIGNAL_UPDATES rule (every coin / timeframe: entry, TP1-3, close) once; settings
  `auto_call_alerts` remembers who got one, so a switched-off or deleted rule is never re-added.
- Results "let it run" (owner, 5 Nov 2026): `views.live_fields` adds `runner` {on, rr, target} for AI runner calls;
  `RecordDetails` shows "Let it run · 1:4", stop at TP2 after TP3 (`stopNow`), next target = final 1:rr (`liveOf`), the
  sheet's level notes ("nothing closes") and the final target row; runner rows' live figure = whole position (no 50/25/25).

## v2.22 (14 Nov 2026, owner-approved)
- **UI** (branch `ui-v222`, live): `components/PositionInfo.tsx` (`PositionGrid` Binance-style block: PNL (USDT), ROI,
  Realized PNL, Size, Margin, Leverage, Entry, Mark, Liq., TP/SL with "All targets"; `botFacts`) on Demo bots positions and
  the Hesper open trade; record sheet "Position (example)" (`RecordDetails.signalFacts`, example margin localStorage
  `cia-ref-margin`, default 100 USDT at the card's leverage; closed targets booked at their price, before fees);
  practice futures positions get `realized` (closes of that position − open fee − funding, `paperFutures.subscribe`).
  Signals page status filter (URL `status`): Active (default, hides closed) / Running / Waiting entry / Closed / All.
  VRVP on every `CandleChart` (`lib/vrvp.ts` series primitive, 48 rows over the visible candles, POC / VAH / VAL; switch
  remembered in localStorage `cia-vrvp`). No engine writes.
- **Engine combination** (branch `engine-v222`, `services/combo_gates.py`, live calls only in `analysis.analyze`): volume
  profile filter (POC/VAH just above a long or POC/VAL just below a short within 0.5 ATR, last 200 bars, flag "VOLUME
  WALL AHEAD"), fee filter (1h/4h stop < 1.5 %, "STOP TOO TIGHT FOR FEES"; 15m left out), same-side cap 8 running calls
  (all coins/TFs, filled only, "TOO MANY SAME-SIDE CALLS"). Env `VP_FILTER`, `FEE_FILTER_TFS`, `FEE_MIN_STOP_PCT`,
  `SAME_SIDE_CAP` (0 = off). Proof: `research_ideas.py` on branch `engine-ideas`, `research-results/results/combo-latest.json`
  (test −0.021R → +0.013R, max DD 130R → 31R, ~half the calls). Record not restarted. Tests `tests/test_combo_gates.py`.
- Live review: `python -m app.research review` (`research_review.py`, branch `review-nov14`): record as stored and
  re-assessed without admin decisions, by TF/side/coin/session, bots, Hesper, Guardian.
- **Admin Hold** (owner, 14 Nov 2026, `services/hold.py`, job `hold_signal`, admin only): within `HOLD_WINDOW_MIN` (15)
  of publication the admin withdraws a call: row MOVED from `signals` to `held_signals` (held_at/by/hold_note; never
  deleted), bots / Hesper `apply_close`, member broadcast "withdrawn", `analysis` gate "WITHDRAWN BY ADMIN" (no new call
  on that coin/TF while the held one would still run). `held_signals` followed by `update_signal_outcomes(table=...)`;
  `hold.scoreboard` → `views/guardian.held` → Guardian page "Hold scoreboard"; public `track_record.withdrawn` {count,
  window_min} → Results line ("N calls were withdrawn ... not counted"). UI: `SignalAdjust` Hold button + `HoldModal`.
## v2.22 live market data + market turn detector (admin, RECOMMEND-ONLY; owner, 14 Nov 2026, branch `market-data`)
- `services/market_data.py` (worker step `market_data`, hourly with the detector, `BUDGET_S` 35 s, OKX 5 req / 2 s): OKX public
  rubik statistics per watchlist coin OKX supports (`support-coin`, daily cache `mkt_okx_support`; BTC / ETH every run, the
  rest rotate via `mkt_data_cursor`): open interest + volume, taker buy / sell, long / short account ratio (hourly, only
  COMPLETED hours) -> SQLite `mkt_okx` (coin, kind, ts, value, `known_at`); recent liquidation orders -> `mkt_liq` (USD =
  sz x ctVal x bkPx); DefiLlama total stablecoin supply (daily, completed days) -> `mkt_daily`. No Firestore writes.
  ETF flows: no clean free JSON source -> not recorded. Status setting `mkt_data_status`.
- `services/turn_detector.py` (worker step `market_turn`): per coin, established 4h trend (EMA50 +- 0.3 ATR + slope, judged
  without the newest 3 bars; 4h and 1d must agree, else "range"); points for a turn against it: 4h swing break (<=30),
  1d swing break (20), 200-bar volume-profile value-area break (15), OKX 24 h taker ratio against the trend (<=15), price
  against the trend with OI +3 % (10), trend-side liquidations >= 3x the 7-day average (10), crowded funding z >= 2 (10).
  >= 50 "turning up/down", 25-49 "weakening", else "trend intact". Market = 0.5 BTC points + 0.5 breadth. Never changes a
  call; not proven to predict turns (test once weeks of OKX data exist - `known_at` makes that look-ahead free).
- `views/market_turn` (admin only in the rules + rules test "market turn: ..."): min 1800 s, `core` = market + coin states,
  skipped in lean mode -> <= ~48 writes/day, 0 engine reads. UI `components/MarketTurn.tsx`: Health ("Market turn" tile +
  card `hc-turn`) and Trade Guardian (compact card). Seed `dev/seed.ts marketTurn()`. Tests `tests/test_market_turn.py`.
- **Glass & crystal look** (owner, 14 Nov 2026, `index.css`): Midnight Gold lightened (ink 26 24 21, panel 37 34 30,
  raised 49 45 40); with Glass on (default) every theme gets translucent cards (`--panel-a` 0.62, blur 18px, saturate
  165 %), a top-left sheen (`--crystal-sheen`), a crystal edge (`--crystal-edge`, bright inset top line), sheen on tiles,
  buttons and bars, and two extra cool / accent background lights so the frosting picks up colour. Glass off = solid.
- **Hesper v2.23** (owner, 14 Nov 2026): "Stop run" (job `hesper_new_run`, now stop only) ends the run (record kept) and
  leaves the challenge idle (state `{"idle": True, ...}`, `run()` does nothing, view `idle`, `current` null); "Start new
  run" (job `hesper_start_run` {amount}, admin, 10–1,000,000 USDT) starts the next run with that amount
  (`Hesper.start_new`). Each run stores `start_balance` / `goal` = 10x start (milestone, `goal_of`); liquidation / bust
  still restart at once with the same amount. Members see the open trade's full PositionGrid with every target.

## v2.24 proof checks (admin, owner-approved 14 Nov 2026, branch `proof-v224`)
`services/proof_checks.py`. (1) **Filter check**: in `analysis.analyze` (live only) the call as formed (`pre_gate`: decision,
setup, grade, flags count) is kept; when a measured filter (`proof_checks.FLAGS`: bigger trend, edge, trade filters, costs,
stop too wide, VP / fee / same-side cap, paused TF, grade A only, call running, news) makes it NO TRADE, `log_rejected`
stores it in **`rejected_signals`** (signals columns + `reject_flag` / `reject_reason`; record's `_plan` with entry rules;
skipped while the record or the table has a call open there; check failures / Hold / safety pause / stale not logged).
Followed by worker step `rejected_outcomes` (`update_signal_outcomes(table=...)`). Never read by the record, bots,
Telegram, training or safety. (2) **AI check**: `calibration` scores live `predictions` per TF (3-class Brier vs base
rates of the 30 days before; last 7 d vs prior; reliability buckets; state ok / drift / no skill / overconfident / too
few, warnings). `tp1_check`: record calls now store payload `expect` {p_tp, expectancy_r} → TP1 expected vs reached.
`checks()` cached hourly in setting `proof_checks`, published as `views/guardian.checks` (no new docs, no reads).
UI `components/ProofChecks.tsx` (`FilterBoard`, `ModelCheck`) on Trade Guardian; Health tile "AI check". Tests
`tests/test_proof_checks.py`.

## v2.25 Performance Lab + Trade chart tools (owner, 14 Nov 2026, branch `lab-v225`)
- `services/perf_lab.py` (worker step `perf_lab`, every 2 h, setting `perf_lab_at`, skipped in lean mode) → ONE admin-only
  doc `views/perf_lab` (rules + rules test): record since `record_clause` in net R; calls with admin adjustments re-followed
  with the live rules only (`no_admin`, `admin`); splits by tf / side / grade / coin / session / entry / runner; weekday ×
  session `heat`; R `histogram`; `curve` (R + drawdown); `streaks`; losers in profit first; hold times; exits; `dots`
  (last 300 closed calls for the orbit); `proof` (proof_checks summary). 0 reads, ≤12 writes/day. Tests `tests/test_perf_lab.py`.
- Page `/lab` (`pages/Lab.tsx`, Admin menu "Performance Lab"): "observatory" look (`.xeno-panel`, `.xeno-sweep` in
  `index.css`, motion off under reduced motion): Orbit (each closed call a glowing dot on its timeframe ring, warn outline =
  admin changed), Pulse (equity), Spectrum (R histogram), "Where it works" split bars, Hive (hex weekday × session),
  Specimens. Seed `dev/seed.ts perfLab()`.
- Trade page chart (`TradeTerminal.ChartPanel`, AI mode): chips EMA / VWAP / Bollinger (browser `lib/ta.overlays`) and
  Structure / Trade plan (engine analysis of the coin; 1m/5m use 15m) via shared `lib/chartLevels.ts`; choice in
  localStorage `cia-trade-chart-tools` (default EMA, Structure, Trade plan). The coin page (`Asset.tsx`) keeps its own set.

## v2.26 chart tools everywhere + Overview layout (owner, 14 Nov 2026, branch `ui-v226`, frontend only)
- `components/ChartTools.tsx` (`useChartTools(symbol, tf, candles, on, fixed?)` + `ToolChips`): EMA / VWAP / Bollinger
  (browser `lib/ta`) and Structure / Trade plan (`lib/chartLevels`, engine analysis; 1m/5m → 15m, 1w → 3d; Replay passes
  the as-of analysis as `fixed`). Choice shared by all charts (localStorage `cia-chart-tools`). Used by the Trade chart,
  the Overview BTC chart and Replay; the coin page keeps its own toolbar.
- Overview desktop: rows 3-4 are two stacked columns (status · Guardian · performance | open calls · activity);
  "More market detail" columns: regime + top risks | top signals + opportunities | sentiment; heatmap fills its row
  (`.card-fill`). Guardian page shows `last_error` only if < 6 h old (amber).
- Observatory look (owner, 14 Nov 2026, `components/Xeno.tsx`): `CosmicBackdrop` (fixed starfield + nebula + slow orbit,
  z -1, mounted in `main.tsx`, fainter on light / glass off), `MarketRadar` (4H watchlist as radar blips inside the
  Overview "Market intelligence" card, `.ai-scan`), welcome page `HoloOrbit` behind the example ticket + `CyberHorizon`
  grid floor. Overview stacks end level (`.ov-stack`: last card fills). Motion off under reduced motion.
- v2.27 alien touches on every page (shared hooks, `index.css` "v2.27"): `PageHeader` title gets `AiGlyph` (orbit icon);
  header underline = beam with travelling glint; `.panel-hero` HUD corner brackets; `.ai-card` aura + scan line; card
  titles a signal diamond; empty states a mini radar; skeletons AI-tinted; active sidebar key glows + blip; primary
  buttons an occasional glint. Welcome page: `Constellation` (coins network with pulses), `SignalWave` dividers, final
  card with `HoloOrbit label={false}` around the logo + `CyberHorizon`. All motion off under reduced motion.
- Bots + Hesper visuals (owner, 14 Nov 2026, `Xeno.tsx`): Results → Demo bots opens with `FleetHero` (`Bots.tsx`):
  `FleetOrbit` (each bot a `BotDrone` saucer on its timeframe ring around the AI core, green/red by return, satellites =
  open positions), fleet tiles, `FleetPulse` (every bot's % return on one oscilloscope); bot cards are `ai-card` with a
  drone in the title; "How the bots work" is an ⓘ beside the heading. Hesper run card: `Mission` (log-scale voyage from
  the start world past 2x / 5x to the 10x world, craft at the live balance, liquidation black hole below).

## v2.28 logo (owner, 14 Nov 2026: "A original with the effects of C")
- `frontend/brand-source/make_logo.py` → `logo.svg` + `art.png` (the original artwork, cropped inside its frame, made
  round) set in a space tile: cyan core glow, gold ring + gold tick ring, dashed cyan ring, tilted cyan orbit + satellite,
  stars, violet nebula, gold rim. `render_logo_assets.cjs` (Playwright) rasterises it into `public/brand/logo-{96,192,384}`
  (.png palette + .webp via Pillow), `public/brand/logo-art-{192,384}.webp` (the round artwork), `public/icons/*`
  (maskable / Apple = full-bleed), `public/favicon.png`, `public/brand/og-image.png`, `backend/app/assets/logo.png`
  (Telegram cards); the manual and the APK use `icons/icon-512.png`.
- `components/Logo.tsx`: `LiveLogo` = the same layers drawn live (tick ring turns, dashed ring counter-turns, core pulses,
  radar sweep inside the artwork, satellite runs its orbit via SVG animateMotion, stars twinkle; `.logox-*` in index.css,
  off under reduced motion). `HeroLogo` (welcome hero + final card, sign-in, access, error / 404) and `LogoSpinner`
  (boot loader "Waking up the AI…" + `.boot-bar`) use it; header / static logos use the still images. Hesper `Mission`
  craft = the round artwork.
- Manual v2.29 (owner, 14 Nov 2026): updated for Overview, chart tools, Signals status filter, exchange-style positions,
  My signals alert, bot fleet, Hesper (open-ended, 10x milestone), withdrawn calls, the new WAIT reasons, record start
  4 Nov; new section 15 "Behind the scenes" with screenshots of the admin tools (Trade Guardian, Filter check, AI check,
  Performance Lab, Market turn, Health; captioned "examples with sample data, not results"; no admin instructions).
  Screenshots `docs/manual/img/*.jpg` (preview seed data, 1600 px JPEG); `build_manual.py` embeds `![alt](img/x.jpg)` as
  captioned figures (`.shot`).

## v2.30 "new signal" notification (owner, 14 Nov 2026: no notification when a signal was generated / a trade taken)
Cause: "My signals" (SIGNAL_UPDATES) knew only entry / TP / closed, and "entry" fires only when a pending limit fills
LATER; since v2.13 most calls are entered at the market price at publication, so nothing fired. `alerts.CALL_EVENTS` now
starts with **"new"** (every published call; type `NEW_SIGNAL`, push title "New signal"; message with grade, entry or
"waiting for entry", stop, TP1-3). One-time: `alerts.NEW_PRIMED_FLAG` marks calls already running as seen (no burst);
`worker.ensure_call_alerts` adds "new" to the existing auto "My signals" rules once (flag `auto_call_new_v230`, in
`MIGRATION_FLAGS`; local table updated too); `AUTO_CALL_EVENTS` includes it for new members. Alerts page: event chip
"New signal". Tests in `tests/test_growth_v216.py`.
- Hesper Challenge pushes (owner: "very important"): `Hesper.run` events (open, limit, fill, expired, new `tp` for a target
  hit on a still-open trade, close / liquidated with `pnl` + `balance`, run_end, goal_reached; each carries `run`) →
  `hesper.push_messages` (text `push_text`) → `sink.send_push` in the worker step `hesper_push`. Admin always (url `/rich`);
  active members too, one copy per uid (url `/results?tab=challenge`), only while `config/hesper.visibility == 'members'`
  (`worker.hesper_members`: one Firestore read, only on a tick with a challenge event). Tests `test_hesper_push.py`.

## v2.31 fast price watch (owner, 14 Nov 2026: "why do notifications need to wait for engine? cant we do it same time?")
`backend/app/watch.py`, run every 30 s by a background thread in `scripts/engine_loop.py` (also during ticks; env
`FAST_WATCH=0` turns it off). Opens the SQLite file read-only, prices the open calls' and Hesper's coins from
data-api.binance.vision (one batch request), and pushes at once when the price touches an entry (pending), TP1-3 or the
stop in force (admin stop, break-even after TP1, TP1 after TP2) — text "price touched TP1 … Confirmed at the 15-minute
candle close." Audience = owners of primed call rules wanting that event (skipped when `alert_marks` shows the engine
already sent it); Hesper = admin + setting `hesper_push_members` (refreshed by the tick ≤ every 30 min). Already sent:
`backend/data/watch_sent.json` (7 days); status `watch_status.json` → Health `engine.watch_*`. The engine's confirmed push
uses the same tag (`<call id>-<event>`, `hesper-<run>-<type>-<coin>-<tp>`) so the phone replaces the early one. Never
changes the record, bots, Hesper or Firestore. Tests `tests/test_watch.py`.

## v2.32 bStocks removed (owner, 14 Nov 2026: MSTRB not on MEXC / not findable on Binance; "after they complete their running trades")
`analysis.RETIRING_COINS` (env `RETIRING_COINS`, default MSTRB/USDT, SPCXB/USDT = Binance bStocks, tokenized shares, spot
only): live calls → NO TRADE "COIN BEING REMOVED" (in `proof_checks.SKIP_FLAGS`). `worker.retire_coins` (in
`sync_config`, before `wanted`) removes each from `config/watchlist` once `coin_busy` is false (no OPEN record call incl.
pending, no bot position/order, no Hesper trade/order); flag `retire_bstocks_v232` (in `MIGRATION_FLAGS`) when all are
gone — afterwards the gate is off, so the admin may re-add them. MEXC's "MSTR" is a different product (other price).
Tests `tests/test_retire_v232.py`.

## v2.33 coin scorecard + coin study (owner, 14 Nov 2026, branch `coins-v233`)
- `services/coin_scorecard.py` → `views/radar.scorecard` (built in the hourly radar step): each watchlist coin from the real
  record (`record_clause`, net, last 30 days or since the record start; per coin from `added_at`): calls, closed, wins, avg /
  total net %, open, blocked (`rejected_signals`). Category best / working (≥3 closed, avg > 0; best = win rate ≥ 50 %),
  losing (≥4 closed, avg < 0), quiet (no public call, ≥7 days watched), early. `suggest_remove` = quiet, or losing with
  win rate < 40 % over ≥6 closed; never pinned coins. Nothing removed automatically. UI `components/CoinScorecard.tsx` on
  Radar ("Your coins: how their signals did"; admin "Suggested to remove" with an inline confirm → `DELETE /watchlist/:x`).
  Tests `tests/test_coin_scorecard.py`; seed `views/radar.scorecard`.
- Coin study `app/research_coins.py` (`python -m app.research coin-candidate --symbols X/USDT` | `coin-baseline`), workflow
  `research-coins.yml` (matrix, one job per candidate + baseline, read-only state copy): listings (Binance spot / USD-M
  futures via data.binance.vision daily files, MEXC spot / futures APIs), candles, `training.train_one` on 15m/1h/4h,
  `research_engine.evaluate` test split (net R). Results `research-results/results/coins-*.json`.
- Study results 14 Nov (`results/coins-20261114*.json`, aggregates in `backend/app/assets/coin_study.json`, read by
  `coin_scorecard.load_study`): current coins −0.044R/trade on the test split (1250 trades). Candidates (fresh models):
  HBAR +0.19R (81 trades), SHIB +0.09 (45) = "add" (≥0.05R, ≥30 trades, Binance + MEXC futures); ETC +0.33 / APT +0.19 /
  BONK +0.07 / SEI +0.06 (<30 trades) = "promising"; FIL +0.08 no MEXC futures; OP −0.47, ARB −0.29 avoid. Watchlist
  coins with a past test ≤ −0.15R over ≥30 trades (and no positive live record) are also suggested for removal
  (UNI −0.20R/74, ZEC −0.19/31, NEAR −0.27/31, LTC −0.16/42, XLM). Re-run `research-coins.yml` and refresh the JSON to update.

## v2.34 News visuals (owner, 14 Nov 2026, branch `news-v234`, frontend only)
`components/NewsViz.tsx` (real data, observatory look, `index.css` "v2.34", motion off under reduced motion):
`Intercept` (top of News) = every headline of the last 24 h as a glowing packet arriving at a receiver dish (x = time,
lane = source, newest pulses; hover/focus shows the title, links open the story), the news-mood series as the carrier
wave; drawn 1:1 at the measured width (`useWidth`, ResizeObserver) so dots never stretch; the dish is its own square SVG
(hidden < 360 px). `OrbitTrack` (top of the calendar card) = next 7 days, high-impact releases as red worlds (next one
pulses), medium as amber, dark bands = the news-guard pause (45 min before → 30 min after). Lead headline `.news-lead` tint.
- Layout (owner: "one is too long one is short"): headlines (lead + 9, "Show N more", footer pinned) | right stack =
  calendar + `CoinConstellation` (coins mentioned as stars around the AI core, size = headlines, tap = filter; the coin
  filter state lives in `News`, phones scroll to the headlines) + `NewsSpectrum` (headlines per hour, 24 h, busiest
  hour gold; `flex-1` so both columns end level).
- v2.36 (owner): News overview cells get visuals: `ReleaseDial` (full ring = next 7 days, now at the top, gold arc = time
  to wait, red world = the release, dark arc = the signal-pause window, countdown inside) and `SignalBeacon` (running =
  gold radar sweep + green blip; paused = red rings pulse, "Resumes in …" from `risk_now.ts` + 30 min; else "Next pause
  in …" = next high-impact − 45 min). Share cards v2.35 (`cards.py`, `cardCanvas.ts`): gold-black kept, gold dust stars,
  faint gold orbit, gold HUD corners, orbit rings round the hero, context tag (`_base(title, tag)`, `header(…, tagText)`).

## v2.37 premium share images (owner, 14 Nov 2026: "a premium look that attracts users")
`frontend/src/lib/luxCard.ts` (weekly report post + story, achievement badge + poster, Hesper card; Telegram cards keep
`cards.py`): warm black with a diagonal gold light, fine gold grain, the round logo artwork as a faint sepia watermark,
gold-foil frame with diamonds, brand line with spaced name + site and a foil-outlined tag, Sora figures filled with a
metallic gold gradient (`foil`; losses stay plain red), left-aligned editorial layout, `curveChart` (week's running total /
Hesper balance, log), `statRow` hairline stats, ledger rows with hairlines, `luxFooter` foil CTA. `views.weekly_report`
adds `curve` (running total in closing order, ROI when every trade has one, else price; ≤61 points) + `curve_basis`.

## v2.38 fixes (owner, 15 Nov 2026: demo bots not loading on some phones; Telegram + achievement cards still old)
- Demo bots: each bot's equity chart mounts only near the screen (`components/LazyMount.tsx`, IntersectionObserver) - the
  page created ~40 canvases at once and blanked low-memory phones; `views/bots` is published slimmed
  (`BotEngine.slim`: latest 60 trades, ≤300 curve points per bot; was ~390 KB). Stats unchanged (computed on everything).
- Telegram cards (`cards.py`) now use the premium look of the website's share images (`_background`, `_frame`, Sora
  `assets/fonts/Sora.ttf` (OFL) via `_s`, `_foil_text`, spaced brand line, foil tag, gain figures in foil, losses red,
  `assets/logo-art.png` watermark). Drafts keep their recipe (`add_draft(..., card)` → item `card`), and `post_draft`
  redraws the card in the current design when the owner posts it (old drafts without a recipe post their stored image).
- Achievements page tiles: SVG `Medal` (foil ring, tick ring, orbit) + `.foil-text` values + `.lux-tile`.
- `luxCard.ts` polyfills canvas `roundRect` (Chrome < 99 / Safari < 16 could not draw the share images).

## v2.39 (owner, 15 Nov 2026)
- Demo bots on Z Fold 4 still not loading: the live data renders fine (UI probe `ui-probe.yml` + `scripts/ui_probe*.{py,cjs}`:
  real views copied into `frontend/dev/live/*.json` on the runner only (gitignored; `seed.ts liveView`), Playwright at
  Fold / phone sizes, errors only → `reports/ui-probe.json`). Cause taken as GPU load: the page is wrapped in `.fx-lite`
  (no backdrop blur, no scan line, no orbit / blip / glint animation on touch screens), the fleet SVG blur filters
  (`fl-glow`, `fp-glow`) are gone, and the fleet picture + each bot card sit in `SafePart` error boundaries.
- Guard study `python -m app.research guard15` (`research_guard15.py`, workflow `research-guard15.yml`, results
  `research-results/results/guard15-*.json`; `series_policy.decide(htf_check=False)` research switch). 15 Nov: live since
  the record start 15m published 12 closed +0.79R avg; blocked 26 (20 closed) +0.28R: GRADE A ONLY 9 closed, 89 % won,
  +0.74R; FILTERED (AI trade filter) −0.23R; same-side cap −0.44R; costs / VP 1 each. Replay test split: allowing grade B
  on 15m adds 87 calls at +0.088R (56 % won), all timeframes −0.0065R → +0.0185R, drawdown 37R → 28R; bigger-trend / VP
  blocked 1 call each (both losers); cap blocked 9 (+0.18R) but drawdown 37R → 65R without it.

## v2.40 15m grades A+B (owner, 15 Nov 2026, after the guard15 study)
`analysis.A_ONLY_TFS` "1h,1d,3d": 15m grade-B calls are public and counted (record not restarted; 15m leverage policy
B = 75 %). The 15m bot `futures-signal-ab-15m` stays grade A (`worker._policy_bot` keeps 15m bots at A). Signals 15m tab
note removed. Other guards unchanged.
- Exit study `python -m app.research exits` (`research_exits.py`, workflow `research-exits.yml` on branch `exits-v240`,
  results `research-results/results/exits-*.json`, 15 Nov): early break-even at +0.5R / +0.7R, lock +0.3R at +0.7R,
  close on give-back, TP1 0.7R / 0.8R vs the live exits on the same out-of-sample calls (15m/1h/4h). None beat the live
  exits overall on both halves; 4h worse with nearly all; 15m TP1 0.8R slightly better (+0.005R vs −0.028R test; small).
  Live exits unchanged. Owner-approved trial: bot `futures-test-tp08-15m` (`bots.TEST_TP08_15M`, grade A, TP1 at
  `tp1_r` 0.8R from its own entry, otherwise = the 15m signal bot), added once (flag `test_tp08_v240`; env
  `TEST_BOT_TP08=0` skips it - tests/conftest.py does). Compare its book with `futures-signal-ab-15m` after ~2 weeks.

## v2.41 lively profit / loss lines (owner, 15 Nov 2026)
Every P/L curve is green above its baseline and red below, with a soft matching glow fill (`components/PnlGradients.tsx`,
userSpaceOnUse gradients split at the baseline, no SVG filters): Demo bots `FleetPulse` (+ end dots and latest % per
bot, lines draw in once: `.fp-live .fp-line` in index.css) and each bot's equity (`LineChart` series `baseline` =
lightweight-charts baseline series, dotted "start" line, end marker), Track record `Curve`, Overview performance
`Sparkline split={0}`, Hesper `BalanceCurve` (baseline = run start), Lab `Pulse` (filter removed), Backtest strategy line.

## v2.42 15m back to grade A + lenient Guardian on 15m (owner, 16 Nov 2026)
15m grade B (v2.40) lost live → `analysis.A_ONLY_TFS` "15m,1h,1d,3d" again. Owner (testing mode, 5 free test members):
the stopped test is left out of the record - setting `record_excludes` [{timeframe 15m, grade B, from 15 Nov 12:00Z, to
the migration time}] (flag `exclude_15m_b_v242`), applied in `views.record_clause` (json_extract payload grade), and
DISCLOSED on Results with its own figures (`track_record.excluded_tests`: calls, won, lost, total net, open). Rows are
never deleted; they stay in the Signal log. Test `tests/test_exclude_v242.py`.
Trade Guardian on 15m only: TIGHTEN ≥ 65, CLOSE ≥ 90 (`guardian.TF_BANDS`, env `GUARDIAN_15M_TIGHTEN_AT/_CLOSE_AT`);
other timeframes 50 / 75.

## v2.43 radar moving on phones + news impact after a release (owner, 16 Nov 2026)
- Demo bots radar sweep moves again on touch screens (`.fx-lite .xeno-sweep` 12 s, transform only); blips / glint stay off.
- News: after a high-impact release (`news.after_release`, in `news_view` with the engine's BTC 15m candles): surprise
  reading when the calendar has the actual (`SURPRISE` rules: hot inflation / strong economy / higher rate = usually
  bearish, weaker jobs = usually bullish; else "Why it matters" from `EXPLAIN`) + BTC's real reaction (release candle open
  → close 1 h / 4 h later; verdict bullish / bearish ≥ ±0.3 %, else calm; "moved against the usual reading" note).
  Calendar rows `after`, view `last_high` (≤ 12 h). UI `News.ImpactNote`: Overview "Just out" block, released High items
  stay in the list 12 h ("out N ago"). Tests `tests/test_news_after_v243.py`.

## v2.44 premium upgrade (owner, 16 Nov 2026, branch `premium-v244`; frontend only, real data, no new Firestore docs)
`components/Premium.tsx` (+ CSS "v2.44" in index.css): `TradeProgress` (signal card: stop → entry → TP1-3 track, live
price dot, filled won / lost part, R from entry), `WhyChips` (grade / trend / AI lean / reward from the card's own row),
`ProofWall` (Track record: Dubai-day calendar of green / red days from the record rows, monthly bars, best / worst week,
trust strip), `Ring`, `Burst` (CSS gold burst), `ResultTicker` (latest closed calls, wins and losses), `FirstWeek` +
`markVisited / wasVisited / useMarkVisited` (localStorage `cia-fw-*`, guide hidden key `cia-firstweek-<uid>`).
`components/ShareSignal.tsx`: signal share image 1080×1350 (luxCard kit) = teaser only (coin, side, TF, grade, move since
entry) - never entry / stop / targets; phone share sheet or download. `components/CoinPassport.tsx` (coin page): our
record on the coin (`views/radar.scorecard`), AI lean strip on the six `/futures` boards, nearest support / resistance
ladder. `components/TodayPulse.tsx` (Home hero): open-signal health ring (`Overview.healthOf`), closed today, ticker;
`FirstWeekGuide` (members, first 14 days from `approved_at`/`requested_at`: alerts, signals, practice, Telegram).
`components/PlanCards.tsx` (Landing + Membership): foil "Best value" card, savings from the monthly price, included list.
Landing: trust strip, FAQ +3 (payment, renewing early, free Telegram). Trade page: practice win toast + burst + win streak.

## v2.45 Command Centre (owner, 16 Nov 2026; an extra page, nothing else changed)
`pages/Command.tsx`, route `/command`, nav "Command Centre" in the Markets group (`App.COMMAND`, sidebar / More / top bar;
icon + title in `AppNav`). Real data only: Crypto galaxy (watchlist from `views/dashboard_4h`: orbit tier = 24h volume
rank, planet size = volume, colour = live 24h change, gold dashed ring = OPEN record call; phones use a tighter
geometry `useNarrow`), Opportunity radar (six `/futures` boards: slice = timeframe, distance = grade + |AI lean|, max 5
per slice, unlabeled grey = AI leaning without a call; no confidence shown), Intelligence core (4H mood, coin trend /
regime, AI up/down, 4H call + grade, decision_basis / news / flags, engine age from `views/health`), Market universe
(BTC hub, 5 largest coins: line width = 7-day hourly-return correlation from public Binance klines in the browser,
7-day change; breadth, alt strength), Mission control (live prices socket, engine age, models, market feed, writes vs
free limit, error count - from `views/health`, never simulated), Deep-space scan (picked coin: dashboard row RSI / ADX /
trend / volatility, ticker volume + spread, analysis 4H levels, 4H call, AI note → `/asset`). CSS "v2.45" (`.cc-*`).
Concept canvas (sample data) = Design artifact "Command Centre concept". Ideas: AI chat for members (Cloudflare Worker
free + separate Gemini key, reads only on-page data, member sign-in check, daily cap) - owner: later.

## v2.46 (owner, 16 Nov 2026)
- Practice-win toast (`TradeTerminal`): own 2.8 s timer (was reset by price updates and never closed), `cheer-life`
  pop / hold / float-away animation, bigger `Burst big`, tap to close.
- MSTR/USDT: Binance USDⓈ-M stock perpetual (Strategy) added like gold - `TradeTerminal.FUT_ONLY` {XAUT GOLD, MSTR STOCK},
  shown on the Futures tab when `listedPairs().fut` has it: live chart, order book, demo trading; no AI signals (engine is
  spot-only); `paperFutures.MMR_TIERS.MSTR` 2.5 %.
- `components/CommandPlus.tsx` on Command Centre: `SignalJourneys` (OPEN record calls: stop → entry → TP1-3 track,
  targets lit when hit, stop in force mark, live craft, R), `HeatGlobe` (sun-lit globe, Tokyo / Dubai / London / New York
  stock sessions lit while open, BTC last-hour volume vs 48 h from public klines, next US release from views/news),
  `CoinCompare` (up to 3 coins: 7-day lines from public klines, trend / AI lean / volatility / RSI from dashboard_4h,
  our record from views/radar - read only once the panel is used). Trade page: `PracticeBadges` (first win, 10 trades,
  5-win streak, +10 % account, 20 trades without liquidation) from the practice account already open. Firebase: + views/news
  on Command Centre (1 read), + views/radar only on use; everything else already loaded or public Binance data.
- Command Centre redesign (owner: "match the concept, more attractive"): Opportunity radar = live calls only (3 strongest
  per timeframe drawn on the slice centre line, label outside the dot with a panel-colour outline `.rd-label`, lit slice
  where a timeframe has calls, 5° instrument tick ring, gold centre, top 4 calls as chips `.rd-chip` below). Market
  universe = solar system: BTC gold sun (7-day % inside), 5 biggest coins on elliptic orbits - closer orbit + thicker
  flowing beam (`.un-flow`) = higher 7-day hourly correlation with BTC (% shown), planet size = 7-day move.


## v2.47 (owner, 16 Nov 2026)
- Command Centre timeframe switch (`cc-tfbar`, Segmented 15M-3D, remembered `cia-cc-tf`): galaxy (`views/dashboard_<tf>`,
  ring = OPEN record call on that timeframe), AI core, breadth, deep-space scan (analysis + call of that timeframe) follow
  it; the radar keeps all six slices and outlines the chosen one. 1 read per switch (the dashboard view).
- Radar page `components/RadarScope.tsx` (top of /radar, real radar look, gold phosphor): views/radar picks (gold) +
  extended (amber) as contacts; BTC centre; range = 7-day outperformance vs BTC (sqrt scale, rings +5/+15/+30/+50 %);
  bearing fixed per coin (hash); dot size = volume surge; CSS conic sweep `.scope-sweep` (6 s) with afterglow, each blip
  `.scope-ping` delayed by its bearing so it lights as the sweep passes; 3° tick ring + bearings; readout (contacts,
  sweep, last scan) + contact list (BRG / VOL / 30d / 7d) → scrolls to the pick card (`#pick-<SYM>`). No extra data.
- v2.48 MSTR findable (owner, 17 Nov 2026): coin searches (Home "My coins", Scanner) are spot-only, so MSTR never showed.
  `binance.searchFuturesOnly` (USDⓈ-M perps with no spot pair) + `components/FutOnlyHits.tsx` under both search boxes:
  "Futures only … open in Trade ›" → `/paper?market=futures&symbol=X/USDT`. Trade pair menu: search box, futures-only
  pairs (`FUT_ONLY`) also on the Spot tab (tap switches to Futures), shown even when the listing check fails.
- v2.49 MSTR/USDT AI signals (owner, 17 Nov 2026: "we want to have it on signals"): MSTR has no Binance spot pair and
  Binance futures is blocked on the runners, so `data/futures_only.py` (`FUT_ONLY` {"MSTR/USDT": "MSTRSTOCK_USDT"},
  `MexcFutures`) serves its candles / ticker / book / trades from MEXC futures public REST inside `BinancePublicProvider`
  (same shapes; 12h / 3d built from 4h / 1d, epoch-aligned; empty windows before listing skipped). `search_markets`
  lists it; `watch.py` prices it from MEXC. Added once to the watchlist (flag `mstr_v249`, env `ADD_MSTR=0` in tests).
  Signals only where its nightly models prove an edge, like every coin; no crowd/funding features (not on Hyperliquid).
  Frontend: `binance.isFutOnly` (`FUT_ONLY_PAIRS`) routes charts / book to USDⓈ-M futures and keeps it out of spot
  batches and streams; Asset page streams futures; Trade "learning" note until its first analysis. Probe
  `mstr-probe.yml` → `reports/mstr-probe.json`. Prices can differ from Binance MSTRUSDT by a few cents.
- v2.50 (owner, 17 Nov 2026): premium top bar (`tb-*` in index.css: gold hairline `.tb-premium`, `LiveChip` = market
  clock capsule with gold seconds + date + engine age, `compact` on phones via `StatusPill`; ringed avatar `.tb-avatar`,
  "Member · N days left"). Results Proof wall: the day calendar is replaced by `DailyBars` (Premium.tsx: last 14-30 Dubai
  days, green/red day bars + gold running total, hover/tap details). `bots.SCORECARD_IDS` / `Bots.tsx SCORECARD` = all
  public timeframes (15m, 1h, 4h, 12h, 1d, 3d), not only 1h / 4h.
- v2.51 (owner, 17 Nov 2026): Results track record redesigned (`components/ResultsBoard.tsx`, no line/bar charts: period
  switch all / last 7 days, win-rate ring + won/lost/open, facts incl. best/worst week; "How the signals ended" stacked
  bar + outcome table; "Recent form" tiles of the last 20 closed + month totals). `ProofWall` / `Curve` no longer on the
  page (compact hero unchanged). Light theme "Ivory" is now cream (ink 240 235 223, panel 250 246 237, no pure white).
  Alternate row shading: `main table tbody tr:nth-child(even)`, `main .divide-y > *:nth-child(even)`, `.zebra`.
- v2.52 audit step 1 (owner, 17 Nov 2026; audit doc "Crypto Intelligence AI — Audit v2.51"): Firestore on-device cache
  (`lib/firebase.ts` `persistentLocalCache` + multi-tab; `dropLocalCache` on sign-out and once per account when the role
  becomes expired / blocked, flag localStorage `cia-cache-wiped-<uid>-<role>`; `session.watchRole` ignores a cached
  "no record" so an offline start never creates a record). Background pause: `lib/awake.ts` `usePageAwake` (hidden ≥ 60 s →
  `useApi` listeners and the `views/meta` listener detach; shown data kept; re-attach on return). Firebase chunk +24 KB gz
  (cache code). Icons / og-image recompressed (libimagequant, stored truecolor, ~2x smaller). Removed dead `ProofWall`,
  `DailyBars`, `FuturesPaper.tsx` and their CSS. PyTorch install kept in engine / train: 7 active 15m bundles still hold
  LSTM / GRU / Transformer members (loading them needs torch) - skip it once those retrain without deep models.
- Model value study `python -m app.research models-value` (`research_models.py`, workflow `research-models.yml`, results
  `research-results/results/models-value-*.json`, 17 Nov: 233 active series): Random Forest best in 154 series, skill > 0 in
  70 %, mean weight 0.41; ARIMA skill < 0 in 91 % of series (weight 0.08 in 80); technical rules < 0 in 79 %; boosted trees /
  logistic positive on 15m but strongly negative on 12h / 1d / 3d. Ensemble skill > 0 in 91 % (15m), 84 % (1h), 74 % (4h),
  33 % (12h), 14 % (1d), 4 % (3d); calibration error 1-2.5 % (15m-4h) vs 4-10 % (12h-3d). Nothing changed live.
- v2.53 (owner, 17 Nov 2026): light theme "Ivory" softened (low glare: ink 222 216 202, panel 234 229 217, raised 216 209 193,
  text 38 34 28; bull / bear / warn / accent deepened, all ≥ 4.4:1 on raised; glass sheen / edge / input dimmed).
  Command Centre "Market heat" = `components/MarketGlobe.tsx` (lazy): real Earth (Natural Earth 1:110m land via
  world-atlas → `src/data/land110.json`, dynamic import) on a canvas with `d3-geo` orthographic, turns 6°/s (~20 fps, only
  on screen / tab visible, still under reduced motion), drag to spin, night side from the real sun, TSE / DFM / LSE / NYSE
  glow while open (UTC winter hours, weekdays). Insights: exchange status + countdown, BTC change and volume share per
  session (Asia 0-8, Europe 8-14, US 14-21, Late US 21-24 UTC) over the last 24 closed 1h candles, hourly volume heat,
  last hour vs 48 h, next high-impact US release with countdown. Old `HeatGlobe` removed. No Firestore reads.
- Model-set study `python -m app.research modelset --timeframes X` (`research_modelset.py`, workflow `research-modelset.yml`,
  one job per timeframe on branch `models-v253`, results `research-results/results/modelset-<tf>-*.json`): retrain each coin
  as control (all models) / no_arima / rf_only, judge on the test split (net R), series bootstrap vs control.
- v2.54 alignment pass (owner, 17 Nov 2026: "cards not aligned"): Health = KPI row · System health / Open signals / Data
  sources · Models / Demo bots / Safeguards · Market turn (full width) · details; service tiles `auto-rows-fr`, line clamped
  to 2, an odd last tile spans the row. CSS `.grid-even` (cards fill their grid cell) and `.ov-stack` last-card fill also for
  wrapped cards; Settings columns use `ov-stack`, paired grids stretch; Users prices / limits `grid-even`; Report image +
  side cards (`ov-stack`); Signals coin list sticky beside the long signal card on computers (scrolls inside). Check script:
  scratchpad `align.js` (uneven bottoms / unfilled rows per page).
- v2.55 (owner, 17-18 Nov 2026, branch `redesign-v255`): Health = status banner (`.hc-banner`, meters, service chips) +
  flowing cards (`.hc-flow`). Results: only a period switch added (since start / Today / This week / Last 7 days /
  Last 30 days, `ResultsBoard.periodStart`, viewer's local time; "since start" = the same live figures; owner: do not
  redesign Results). Command Centre order: galaxy alone (wide orbits `KX`) · Intelligence core + Mission control ·
  radar + universe · signal journeys (slim lanes `.sj-*`, comet, flaring targets) + Coin vs coin · Market heat ·
  Deep-space scan (unchanged). Live prices: every trade on every device (`live.LITE` only with localStorage `cia-live-lite`=1);
  `connected` = spot OR futures stream delivered < 10 s ago (`futLive`). Health cards = two level stacks (`.hc-col`).
- **v2.56 THE INTELLIGENCE OBSERVATORY** (owner brief, 18 Nov 2026, branch `obs-v256`, frontend only): design system in
  `frontend/src/styles/observatory.css` (loaded after index.css, wins over older passes): deep-space tokens for theme id
  "gold" (now named "Observatory"), Geist for text and numbers (Sora for titles), obsidian cards (`--lift`, hairline,
  no card blur on phones), the "horizon" (gold→blue line) under the top bar / page titles / lead cards, gold only for
  active / primary / key figures, AI = electric blue edge. Removed v2.27 glints (title glyph, diamonds, HUD corners,
  button glint, AI scan line). Sidebar `SideStatus`; top bar compact title. Pages: Home = Intelligence Deck
  (`components/Deck.tsx` `MarketDial`, `OpportunityBoard`; live lanes = `CommandPlus.SignalJourneys`); Signals tickets
  (direction light, AI reason `.sc-reason`, age, coin rail `.sig-pick`, glowing `ptrack`); Command Centre `MissionStrip`,
  galaxy constellations / orbit lights / hologram `.cc-holo`; charts: faint grid, gold dashed crosshair, Geist
  (`chartColors` gridV/cross/crossBg); `TabStrip` = `.obs-tabs`; `kit.TickFlash` live price flash; coin page planet header.
  Batch 5: Results outcome pills `.res-pill` + row edges `.res-row-*` + form stats `.rb-formstats`; Trade `.obs-buy/.obs-sell`;
  Community feed + rail (practice leaders from `views/leaderboard`, posting limits). Hesper Challenge page layout untouched
  (owner likes it; only shared colours apply). Live 18 Nov 2026.
- **v2.57 no ARIMA on 12h** (owner, 18 Nov 2026, after the model-set study `results/modelset-*-latest.json`):
  `settings.model_exclude` (env `MODEL_EXCLUDE`, default "12h:arima"; "" = every model everywhere) → `models.default_models(fast,
  timeframe)` used by `trainer.train_bundle` and `worker._missing_models(summary, tf)` (so 12h bundles without ARIMA are not
  retrained again and again). Study: 12h no-ARIMA +0.090R vs +0.009R/trade, better in 99% of resamples, DD 66R vs 76R;
  15m without ARIMA clearly worse (0.00R vs +0.07R) → kept; 1h/4h/1d/3d no clear difference → unchanged. Live 12h models
  switch at their next nightly retrain. Tests `tests/test_model_exclude_v257.py`.
- **v2.58 logo planet** (owner, 18 Nov 2026): Command Centre galaxy centre = `Command.LogoPlanet` (the round logo artwork
  `/brand/logo-art-384.webp` clipped to a sphere, light from the upper left `lp-shade`, breathing gold atmosphere `.lp-atmo`,
  tilted ring behind + in front, blue moon on the ring via SVG animateMotion, skipped under reduced motion). Live.
- **v2.59 UX round** (owner, 18 Nov 2026, live): Signals card details fold (`.sc-more`, localStorage `cia-sc-details`), coin
  rail phones only; Home "More market detail" without repeated opportunities / F&G gauge ("Market context" + Top risks |
  regime); sidebar Admin folds (`NavGroup.icon`, count when closed); `TickerTape` only on `/`, `/signals`, `/paper`
  (`App.TAPE_PATHS`); top bar `PriceChips` BTC/ETH ≥ 1400 px (socket, no reads); phone theme switch in the More sheet;
  coin page dossier (`.asset-dossier`: chart + report | trade call, report joins the side when no call, chart height
  460-760 follows the side column; missing analysis = `.asset-wait` line).
- **v2.60** (owner, 18 Nov 2026, live): computers with the sidebar show the page title in the top bar (`AppNav.PageTitle`
  `.tb-title`; CSS `.nav-side .page-title` hidden, `PageHeader` classes `ph-nosub` / `ph-noact` drop an empty header,
  `phoneSub` = sub only where the page title shows); BTC/ETH `PriceChips` ≥ 1600 px off tape pages. Results 4 tabs
  (Track record · Demo bots [+ Hesper Challenge switch] · Signal log [+ Model accuracy switch] · Leaderboard; old `?tab=`
  values map via `Results.PARENT`; Tools tab dropped). Trade chart toolbar two rows (`.tt-tools`), badges after positions,
  phone badge strip. Admin menu = Control room (`/health`; tabs Health · Trade Guardian · Performance Lab) · Hesper
  Challenge · Share kit (`/report`; tabs Weekly report · Achievements) · Users (`components/AdminTabs.tsx`,
  `ADMIN_ALIASES` light the sidebar entry). Inter no longer loaded (Geist; canvases too).
- **v2.61 Ask Cintel** (owner, 18-20 Nov 2026): member AI chat = Cloudflare Worker `chat-worker/` (free plan, deployed by
  `chat-worker.yml` with repo secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CHAT_GEMINI_API_KEY` (own Gemini
  project); KV `cia-chat`; address https://cia-chat.cryptointelai.workers.dev). Verifies the Firebase ID token (Google
  JWKs), checks membership by reading `users/{uid}` via Firestore REST with the member's own token (+ forwarded App Check
  token), caches the role 30 min in KV, daily caps MEMBER_DAILY 20 / ADMIN_DAILY 100 / GLOBAL_DAILY 400 (Dubai day). Gemini
  answers ONLY from the page's figures sent by the app (`lib/chat.ts pageContext`), no advice / predictions; model list
  `GEMINI_MODEL` tried in order on 404/429/500/503 (gemini-2.5-flash is closed to new keys), working one remembered.
  `/diag` = Gemini check + model list + last problem (no keys). UI `components/AskAI.tsx` ("✦ Ask Cintel", round on
  phones); `VITE_CHAT_URL`, `VITE_CHAT_MEMBERS=1` = members (live 21 Nov 2026; 0 = owner only). `deploy.yml` concurrency = newest run wins.
- **v2.62 Money flow** (owner, 20 Nov 2026): page `/flow` (`pages/Flow.tsx`, `components/MoneyFlow.tsx`), all from Binance
  futures public streams / REST in the browser (no Firestore): `FlowRiver` canvas (aggTrade: buyers in green from the left,
  sellers out red to the right, forceOrder bursts amber), `FlowStats`, `WhaleBalance` + `WhaleWatch` / `WipeOuts` (calm
  lists: merged per coin/side, new rows every 4 s, pause on hover / button), `LiquidityMap` (futures depth 1000, 40 price
  bands, walls, 30 s), `FundingBars` (markPrice), `NetFlowSankey` (24 h taker-buy vs total quote volume of 1h klines, moving
  dots). Preview mocks in `dev/preview.tsx` (FlowSocket, depth, kline taker fields).
- **v2.62 order-flow recorder + big-money alerts** (`backend/app/flow_watch.py`, thread `start_flow` in
  `scripts/engine_loop.py` every 20 s, `FLOW_WATCH=0` off): OKX public trades / books / liquidations of watchlist coins with
  an OKX USDT swap (`mkt_okx_support.ct_val`) → own SQLite `backend/data/flow.db` (`flow_5m`, `book_5m`, `liq_5m`,
  `flow_alerts`; state `flow_state.json`; 120 days) - research data, NOT used by calls until tested (known_at = bucket
  end). Whale size = clamp(24h USD volume × 2e-5, 25K, 500K). Alerts type `BIG_MONEY` (rules + `alerts.ALERT_TYPES` +
  Alerts page preset "Big money moves"): whale burst (net ≥ 8× whale and ≥ 6× the 24 h median, ≥ 3 big trades) or
  forced-close wave (≥ max(10× whale, 6× 24 h average)); 45 min cooldown per coin/kind; push only (url `/flow`); price
  after 15 m / 1 h / 4 h stored → `flow_watch.stats` in Health `engine.flow_alerts`. Plan (owner approved): after ~4-6
  weeks test flow / book / liquidation features with the research replay and switch on only where they help.

## v2.63 Last Stand (owner, 21 Nov 2026)
`services/hesper.LastStand(Hesper)`: a second all-in run inside the Hesper Challenge page (switch "Main run | Last Stand",
`/rich?c=laststand`, members `/results?tab=challenge&c=laststand`). Same calls/rules as Hesper, own state `laststand_state`,
tables `laststand_runs` / `laststand_trades`. Never starts by itself (`AUTO_START`/`AUTO_RESTART` False): the admin starts
each run with any amount ≥ $5 (job `laststand_start`), ends it (`laststand_stop`), or closes its trade (`laststand_close`
{fraction 1 | 0.5}, `admin_close`; half close sets `leg_scale` so TP legs take 50/25/25 of what is left - bots.py reads it,
default 1). After a liquidation it waits for the admin. Published inside `views/hesper` as `laststand` (`worker.publish_hesper`,
no new doc/rule). Pushes titled "Last Stand · run #N". Share images (`lib/hesperCard.ts` drawLastStandCard / drawTradeCard /
drawRunCard) for both challenges, each with "Post to Telegram" (`lib/telegramShare.ts`: JPEG into `owner/telegram_drafts`,
then job `telegram_post`). Tests `tests/test_laststand.py`.
Last Stand leverage (v2.63b, owner "a bit aggressive"): up to 50x on every timeframe, liquidation 1.15x the stop distance beyond the entry (`LastStand.MAX_LEVERAGE`, `LIQ_BUFFER`; Hesper stays 25x / 1.5x). The stop still comes first.

## v2.64 15m trade filters off (21 Nov 2026, Claude's call at the owner's request "decide, I want best results")
Live check (`app/guard15_live.py`, workflow `guard15-live.yml`, `research-results/results/guard15-live.json`): since 16 Nov
0 of 152 15m calls were published; the AI trade filters ("FILTERED") blocked 67 (72 % won, +0.38R avg net), the same-side
cap 59 (+0.29R), bigger-trend 6 (all lost). `analysis.FILTER_OFF_TFS` "15m": neither trade filter (per-series nor filter2)
blocks on 15m; scores are still computed. Bigger-trend, costs, grade A only and the same-side cap stay. Re-check with
`guard15-live.yml` in ~1 week; the cap needs a replay before any change.
- v2.64 also: auto-trade up to 10 open / 20 new a day (`autopaper.MAX_OPEN_CAP` / `MAX_NEW_PER_DAY`, UI `AUTO_MAX_OPEN`);
  number boxes in Auto-trade settings use `NumField` (free typing, clamped on leaving the box - before, every keystroke was
  clamped so a box could not be cleared). Cap study `app/research_caps.py` (workflow `research-caps.yml`, results
  `research-results/results/caps-*.json`). 1d / 3d stay public for now (1d live 3 of 3 won; 3d publishes nothing).
- v2.64 safety net (owner: "we don't need bad results"): `analysis.filter_off(rt, tf)` - the 15m filters stay off only while
  the published calls they would have blocked (payload `filter_bypassed`) are not losing; ≥10 closed with avg net R < 0 →
  filters block again for good (setting `filter_off_revoked|TF`; Health `engine.filter_off`). Replays (as_of) keep the
  filters on. Test `tests/test_filter_off.py`.
- v2.64 same-side cap 8 → 12 (`combo_gates.SAME_SIDE_CAP`), from `research-results/results/caps-latest.json` (886 test
  calls): total +15.1R → +34.1R, better in both halves (4.0 → 16.6, 11.2 → 17.5), avg 0.027 → 0.049R, max drawdown
  32.6R → 37.4R. Cap 24 / none earned more (+53R) but drawdown 49R - not taken. 1d negative in every variant (−0.10 to −0.15R, 28 calls).
- v2.64 1d demo-only again (`analysis.DEMO_ONLY_TFS` default "1d"; replay −0.10 to −0.15R in every cap variant, ensemble
  skill > 0 in only 14 % of 1d series): one-time flag `demo_1d_v264` (in `MIGRATION_FLAGS`) removes the public 1d bots and adds
  `futures-demo-ab-1d` (grade A, reset_token v264). Open 1d calls run to their end. tests/conftest.py sets `DEMO_ONLY_TFS=""`
  for the older policy tests; `tests/test_demo_1d_v264.py` covers the migration. Signals 1D tab note "demo only".

## v2.65 audit + risk controller study (21 Nov 2026)
- Audit doc (Claude Docs) "Crypto Intelligence AI — Engine Audit (21 Nov 2026)": inventory, evidence, plan, rejected ideas.
- `app/research_verdict.py`: ONE verdict for every study (same unseen calls; PASS = better in both halves, drawdown ≤ 15 %
  deeper, week-block bootstrap ≥ 80 %, ≥ 100 calls differ, else INCONCLUSIVE / FAIL). `research_caps.collect` returns the
  live-guarded test calls. `app/research_risk.py` (workflow `research-risk.yml`, `research-results/results/risk-*.json`):
  BTC-shock pause (rarely triggers), daily / weekly loss stops, correlation-weighted BTC exposure caps (FAIL: −15 to −21R),
  4h abnormal-volatility pause, regime split. Best: volatility pause + loss stop 3R / 6R: +34.1R → +48.4R, drawdown
  37.4R → 31.9R, both halves better, bootstrap 98 %, but 86 calls differ → INCONCLUSIVE.
- Hence SHADOW mode: `services/risk_shadow.py` records `risk_shadow` {volatile, day_r, week_r, loss_stop, would_block} in
  every published call's payload (never blocks; `analysis.PRIVATE_FIELDS` keeps it and `filter_bypassed` out of member
  views). The weekly check-up compares would_block calls with the rest and promotes only on proof.
- Deep audit (21 Nov, doc tab "Deep audit v2.64"; live counts `app/audit_usage.py`, workflow `audit-usage.yml` →
  `research-results/results/usage-latest.json`): `ml/challenger.py` is NEVER called (every retrain goes live via
  `trainer.register`); drift / calibration are display-only; the 15m/1h/4h blocking filter is the per-model v1 trade filter
  (on in 46 of those 129 models; pooled filter2 is off there, on only 12h / 1d); regime ensemble weights used by 137 models,
  never compared with plain weights. v2.65 plan in the doc (7 changes, each behind `research_verdict`).

## v2.65 capital-protection veto + champion/challenger (21 Nov 2026, live)
- Study `app/research_v265.py` (workflow `research-v265.yml`, `research-results/results/v265-latest.json`): the veto
  package (drift + abnormal volatility + loss stop 3R day / 6R week) PASSES `research_verdict` on 886 unseen calls:
  +34.9R → +53.2R, max drawdown 37.4R → 30.0R, worst streak 14 → 11, profit factor 1.13 → 1.23, both halves better
  (15.9 → 30.0, 19.0 → 23.2), bootstrap 98 % (5th pct +3.8R), 113 calls differ. Each rule alone was INCONCLUSIVE.
  The per-model trade filter v1 cannot be replayed (contexts carry no feature matrix): INCONCLUSIVE, judged on live data.
- Live: `services/risk_shadow.assess(rt, symbol, timeframe=)` (volatile, loss stop, `drift` = last 100 resolved live
  forecasts vs the bundle's OOS hit rate, block below ref − 2 se) applied LAST in `analysis.analyze` (after safety / news /
  stale, before demo-only) to every live call → NO TRADE flag "CAPITAL PROTECTION" (in `proof_checks.FLAGS`, so blocked
  calls are followed in `rejected_signals`). Env `RISK_VETO=0` turns it off (assessment still recorded in `risk_shadow`).
- Champion / challenger wired (`services/training._challenge` → bundle `challenger` → `bundle_record` →
  `trainer.register`/`activate_or_hold`; log setting `challenger_log`, last 400). Shadow by default
  (`CHALLENGER_ENFORCE=0`: every retrain still goes live); turn on after a week of logs shows sensible refusals.
  `save_bundle` caches only an activated bundle. Tests `tests/test_challenger_v265.py`. `ENGINE_VERSION` 2.65.0.
- v2.65 worst move per call: `engine/manage.follow` tracks `trough_r` (worst R against the call while open; fill candle =
  its close; a stop = the stop fill) → column `trough_r` (`db.MIGRATIONS`, every signal-like table) via `tracking.TRACKED`.
- v2.65 tiny prices (owner: BONK TP/SL unreadable): `format.pricePrecision` keeps 4 significant digits after the leading zeros below 0.01 (0.00002153, max 12 decimals) - used by `fmtPrice`, charts and the adjust inputs; `hesperCard.fmtPx` uses it too.
- v2.65 Anthropic (owner, 21 Nov 2026: ANT/USDT - Aragon, delisted 2023 - had been added by mistake for "Anthropic"):
  `futures_only.FUT_ONLY["ANTHROPIC/USDT"] = "ANTHROPIC_USDT"` (MEXC pre-IPO perpetual since 14 Apr 2026; probe
  `anthropic-probe.yml` → `reports/anthropic-probe.json`: 222 daily bars, OKX also lists it, Binance USDⓈ-M ANTHROPICUSDT
  since 2 Jun 2026). One-time flag `anthropic_v265` (in `MIGRATION_FLAGS`, gated by `ADD_MSTR` like MSTR) replaces ANT/USDT
  with ANTHROPIC/USDT in `config/watchlist`. Margin tier 2.5 % (engine + `paperFutures`). Frontend `FUT_ONLY_PAIRS`
  ANTHROPICUSDT, Trade label "PRE-IPO". Signals only where its nightly models prove an edge. Test `tests/test_anthropic_v265.py`.

## Manual v3 (21 Nov 2026)
`docs/manual/manual.md` (16 sections, `## Title {#id data-kicker="NN" data-line="..."}`, HTML blocks `cards/steps/tip/note/pro/pair/glossary/faq`
with `markdown` attr) → `python scripts/build_manual.py` (dark/gold design, Sora + Inter, 2-pass clickable contents with
page numbers via pypdf) → `frontend/public/manual.pdf`. Screenshots `docs/manual/img/v3/` (m-* = phone). Owner rule: no prices,
payment details or changing limits in the manual (point to the website / Settings → Membership). Old version in `docs/manual/legacy/`.

## v2.66 premium instruments (owner, 21 Nov 2026, frontend only)
`components/Instruments.tsx`: `CoinBead` (real coin logo as an SVG sphere; GOLD = "Au", initials when no logo), `OrbitDial`
(Home hero, replaces `Deck.MarketDial`: logos around a gold-rimmed dial grouped bull → neutral → bear, names radial,
Fear & Greed arc, BTC live centre; hover shows that coin), `SonarScope` (Market intelligence card, replaces `Xeno.MarketRadar`:
up coins top half, down coins bottom, distance = strength, phosphor sweep, 3 strongest per side labelled). Command Centre
`Universe` = tilted solar system (BTC logo sun with corona, 5 logo planets, beams, starfield with faded edges). CSS `.ins-*`,
`.uv-*` in observatory.css (motion off under reduced motion). Preview seed has 29 coins on dashboard rows.

## v2.67 signal journeys + Cloudflare edge views (owner, 22 Nov 2026)
- Journeys show up to 12 running calls (`CommandPlus.JOURNEY_MAX`, same-side cap is 12) + "+N more" → Results. Owner picked:
  Home = `SignalDeck` arc gauges (`.gd-*`: SL left → last TP right, risk arc red, entry tick gold, target diamonds lit when
  hit, live price needle, Healthy / Watch / At risk); Command Centre = `SignalJourneys` summary strip (`.fc-sum`) + slim rows
  (`DeckRow`, `.sl-*`: entry dot gold, target dots, price dot + trail, R, next target; best first). Shared `legOf`.
- **Edge views** (free Cloudflare, to cut Firestore reads AND writes): engine `sinks.BaseSink.view` also queues every
  member view matching `sinks.EDGE_RE` (same regex in `chat-worker/src/index.ts` and `frontend/src/lib/edge.ts`; a test
  checks) → `flush_edge` POSTs chunks ≤ 450 KB to `<EDGE_URL>/ingest` (header `X-Edge-Key` = sha256("cia-edge-v1|" +
  FIREBASE_SERVICE_ACCOUNT), set as Worker secret `EDGE_KEY` by `chat-worker.yml`) → Durable Object `ViewStore` (SQLite, free
  plan). Table `edge_published` (hash per view). Every 10 min the engine reads one view back (`_edge_probe`). While the edge
  is healthy (`edge_status.ok_at` < 30 min, no later fail) those views go to Firestore at most every `EDGE_FS_EVERY_S` (900 s;
  a changed `core` still at once); any failure → every change to Firestore again. `EDGE=0` turns it off. Health
  `engine.edge` + `engine.firestore_writes_by` (writes per view family today, setting `fs_writes_by`).
- Worker `GET /v?n=a,b&e=etags` (Firebase token + member check as the chat; role cached in memory + KV 2 h; views kept in
  isolate memory 20 s; responses assembled as text - free plan CPU) → `{views: {name: {etag, at, data}|{same}|{none}}}`;
  `/edge-health`. App: `lib/edge.ts` `edgeView` used by `api.view()` for eligible names: one batched poll every 30 s while
  visible; on 401/403/network/none that view (or all) falls back to the Firestore listener (retry after 5 min). Kill switch
  localStorage `cia-edge-off=1` / `VITE_EDGE_VIEWS=0`. Off in preview. Cloudflare token has no D1 / R2 rights (cf-probe.yml).
