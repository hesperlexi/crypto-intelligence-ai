# Crypto Intelligence AI — operations: deploy, roll back, recover

Paper trading and analysis only. No step here places a real order, and none deletes trading history.

## 1. Deploy (manual approval)
1. Work happens on a branch (e.g. `stages-3-7`). Run the checks first:
   `cd backend && python -m pytest -q`, `cd frontend && npx tsc --noEmit && npm run build`.
2. After the owner approves, fast-forward `main` to the reviewed commit (never a force push):
   `git push origin <commit>:refs/heads/main`.
3. `deploy.yml` then runs pytest, builds the website, deploys hosting + Firestore rules and moves the `engine-ok` tag.
   `rules-test.yml` runs the Firestore rules tests on the same push.
4. The engine picks up new code at its next ~64-minute segment (`scripts/engine_loop.py` follows `engine-ok`). To start a
   new run on the new code at once: `gh api -X POST repos/hesperlexi/crypto-intelligence-ai/actions/workflows/engine.yml/dispatches -f ref=main`.

## 2. Roll back
- **Code**: fast-forward `main` to a new commit that reverts the change (`git revert <commit>`; no history rewrite), or
  push the previous good commit as a new commit on top. `deploy.yml` redeploys the website and the rules; the engine
  follows `engine-ok` at its next segment.
- **Single features without a code change** (env vars in the workflows; take effect at the next engine run):
  `PORTFOLIO_GATE=shadow|off`, `MARKET_REGIME=0`, `FAST_RADAR=0`, `FAST_STRATEGY=0`, `RISK_VETO=0`, `SWEEP_GUARD=0`,
  `BTC_SHOCK_GUARD=0`, `CHALLENGER_ENFORCE=0`, `MODEL_MIN_OOS=<n>`. Website edge reads: localStorage `cia-edge-off=1`.

## 3. Database compatibility
- Every V3.x change is additive: new tables (`radar_opportunities`, `fast_trades`), new settings (`market_regime`,
  `market_regime_log`, `strategy_suitability`, `model_activation_log`, `fast_radar_state`, `radar_fast_snapshot`,
  `fast_strategy_state`, `fast_strategy_config`) and new fields in call payloads. Older code ignores them; nothing is
  dropped or rewritten. No migration deletes rows (the V3 reset archived to `archive_v3_*`).
- New Firestore documents: `views/market_regime` (members), `views/model_registry` (admin only, rule in
  `firestore.rules.template`). Removing them is not needed for a rollback.

## 4. Model rollback
- Every trained version stays in `model_versions` (files of inactive versions are kept 7 days).
- A new model goes live only if its file loads, it has at least `MODEL_MIN_OOS` out-of-sample predictions and a finite
  metric (`trainer.validate_candidate`), and the champion check does not hold it. Every decision is in setting
  `model_activation_log`; the Control room's Model registry shows status and reasons.
- To return a coin / timeframe to an earlier version (file still present):
  `UPDATE model_versions SET active = 0 WHERE symbol = ? AND timeframe = ?; UPDATE model_versions SET active = 1 WHERE id = ?;`
  (run in a one-off workflow against the engine state; the next tick loads it).

## 5. Restart and recovery
- **Engine restart / interrupted run**: state lives in SQLite (Actions cache + encrypted backup every ~6 h). A new run
  restores it (`scripts/state_guard.py` refuses to start on an empty state). Open record calls, bot books, challenge books
  and Fast-strategy trades are re-read from the database and followed from the candles they have not seen yet.
- **Provider outage**: guards that cannot read their data block NEW entries ("CHECK UNAVAILABLE", listed on Health);
  open positions keep their stops and targets and are checked on the candles when they arrive - nothing is assumed
  while prices are missing. Market-regime inputs show "Unavailable" / "Delayed" and the regime falls back to "uncertain".
- **Failed training**: the nightly merge reports completed / held / failed validation / failed training / unverified /
  not reached; failed or invalid models never replace the live one. Missing models are trained first the next night
  (`worker.shard_pairs`). Re-run by dispatching `train.yml`.
- **Firestore quota**: writes pace themselves (lean mode above the budget, 20-minute pause after a 429); reads are
  refused for 10 minutes after a quota refusal so a tick never stalls.

## 6. What is never automatic
ML filter enforcement, Fast-strategy promotion, live exit changes and any risk increase all need an explicit owner
decision after the evidence described in CLAUDE.md (research verdict, forward holdout).
