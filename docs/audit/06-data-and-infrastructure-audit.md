# 06 · Data and infrastructure audit

Evidence: GitHub Actions run history 17-24 Nov (all workflows), `reports/quick-status.json` (24 Nov 12:30 UTC),
`reports/audit.json` (live audit, 24 Nov 12:27 UTC), `research-results/results/backup-verify.json` (24 Nov),
`v3-review.json`, workflow files.

## 1. Engine uptime (the most important finding here)

Engine runs 17 Nov 00:00 → 24 Nov 12:30 UTC (7.5 days): **92.2 % covered**. Gaps longer than 20 minutes:

| Gap (UTC) | Length | Cause (most likely) |
|---|---|---|
| 17 Nov 00:00 → 03:19 | 200 min | start of the measured window / nightly hand-over |
| **23 Nov 14:10 → 21:06** | **417 min (7 h)** | GitHub did not start the scheduled run (cron skipped) |
| 24 Nov 02:40 → 05:27 | 168 min | same; training that night started late (08:13) |

During a gap no calls are analysed, no stops are followed (the record catches up from candles afterwards, so results stay
correct, but alerts, bots and auto-trade act late). **F-03 (P1):** the self-queue added to `engine.yml` on 24 Nov should stop
this; it is **not yet proven** — check the next 7 days. The watchdog (every 30 min, alert after 75 min) did run 114 times
successfully. Recommendation: show "engine uptime last 7 days" and the last gap on Health.

## 2. Workflows (17-24 Nov)

| Workflow | Runs | Notes |
|---|---|---|
| Engine | 35 success, 78 cancelled, 1 running | "Cancelled" are queued runs replaced by a newer queued run (normal for this design). |
| Train (daily) | 7 / 7 success | start time drifts (02:17 → up to 08:13 UTC) because it waits for a free slot. |
| Watchdog | 114 / 114 | |
| Deploy | 69 success, 36 cancelled (newest wins), 4 failed (all 18 Nov, fixed the same day) | Android APK step failed once today and passed on re-run (transient). |
| Rules tests | 107 success | Firestore rules are tested on every push. |
| Backup verify (today) | restore OK, integrity OK; the *report commit* failed | **F-25 (P3):** several read-only workflows push to `research-results` at the same time and collide. Add a retry loop like `reset-inventory.yml` has. |

## 3. Backups

Encrypted backup restores on a throwaway runner: integrity **ok**, 1.1 GB, 25,517 signal-like rows, 2.79 M candles,
3,759 model versions, newest candle 24 Nov 08:15 UTC. Backups every ~6 h. **Backup age is not on Health** (F-26, P3).

## 4. Firestore free plan

Today at 12:30 UTC: **2,512 writes** (lean point 15,000; hard limit 20,000), **1,519 reads** (limit 50,000), 7 active members,
member reserve 420. Healthy margin. The write pacing (per view
`min_interval_s`, edge-first, lean mode) is working.

**F-16 (P3):** 1,021 view documents exist; about 40 have not changed for 700+ hours — views of removed coins (TON, XAUT) and
weekly perf pages. They cost nothing to keep but make the live audit noisy. A one-time clean-up of views for coins not in
the watchlist is safe (read-only for members; needs approval, deletes Firestore documents only).

## 5. Data providers

| Provider | Used for | Freshness today | Notes |
|---|---|---|---|
| Binance spot (data-api.binance.vision) | candles, tickers | 5 min (15m/1h/4h views), 67 min (12h/1d/3d, by design) | primary; futures API blocked on US runners |
| MEXC futures | MSTR, ANTHROPIC, SILVER candles | live | malformed bars repaired (v2.69) |
| Hyperliquid | futures history | nightly | |
| Binance archive | OI, long/short, taker (427 days) | 2-day lag (by design) | |
| Coinalyze | liquidations (1h: 68 days, 4h: 252, daily: 1,499) | hourly | key in a secret |
| OKX | funding fallback, rubik stats (40 days), liquidations, order flow | hourly / 20 s | |
| DefiLlama, Deribit, Yahoo, alternative.me, CoinGecko | stablecoins, unlocks, DVOL, macro, F&G, market cap | hourly | context only |
| RSS + calendar | news guard, briefing | live | fail-closed when the calendar is older than 72 h |
| Funding history | 929 days | hourly | |

Missing-data handling: stale candles → NO TRADE; stale calendar → NO TRADE "CHECK UNAVAILABLE"; missing BTC data →
risk state HIGH; funding gaps use a documented default (0.01 % per 8 h). **One fail-open path:** F-02 (stale risk state →
auto-trade at normal size).

## 6. Documentation

| Document | Problem |
|---|---|
| `README.md` | Last updated 30 Oct; still describes the Scanner page, "every 5 minutes", the old design (F-27, P3). |
| `CLAUDE.md` | Says "Version 2.1.0" (true for the app package) while the engine reports `ENGINE_VERSION` 2.65.0 and features are V3 / v2.80. The engine workflow is named "every 5 minutes" but runs every 4 (`ENGINE_EVERY_S` 240). |
| `scripts/audit_live.py` | Checks for a 10x cap and an older liquidation formula → 34 false alarms (F-15, P3). |
