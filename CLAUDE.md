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

## Other features (where to look)
News & calendar `services/news.py` + `pages/News.tsx` · Radar `services/radar.py` + `pages/Radar.tsx` · Track
record / weekly report / achievements / wins_today `views.py` + `pages/Results.tsx`, `Report.tsx`,
`Achievements.tsx`, `components/WinsToday.tsx` · Telegram autopilot `services/telegram.py` (every win + daily/weekly/teaser as image cards from
`services/cards.py`, Pillow, Inter fonts + logo in `app/assets`) + `components/TelegramCard.tsx` · Live trading stream `frontend/src/lib/stream.ts` · Memberships
`services/membership.py`, `components/Membership.tsx` (prices 15/40/70/130 USDT, USDT only; Binance QR or MEXC UID 00183657; support email in
`config/membership`) · Manual `docs/manual/manual.md` → `python scripts/build_manual.py` (members only, no admin
instructions) · Promo video `frontend/public/demo.mp4` (70 s, original soundtrack).

Member menu: Home · Signals · Trade · News · Radar · Results · Community · Alerts · Settings. Owner extras: Weekly report,
Achievements, Health, Road to Rich, Users.

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
