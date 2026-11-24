# 07 · Performance and security audit

## 1. Frontend performance (production build measured for this audit)

| What | Size (gzip) |
|---|---|
| First load: app code `index` | 74.5 KB |
| React | 53.8 KB |
| Firebase (auth + Firestore with on-device cache) | **133.9 KB** — the largest piece |
| CSS | 43.9 KB |
| **First load total** | **≈ 306 KB** |
| Charts (lightweight-charts), loaded with chart pages | 51.7 KB |
| Results page | 25.6 KB; Paper 15.3 KB; Rich 14.2 KB; Users 13.1 KB; world map data 20.1 KB (lazy) |

Every page is lazy-loaded; the landing page does not load charts. Static files: coin logos 2.1 MB (self-hosted SVG, cached
30 days), demo video 11 MB (cached a year, loaded only on play), manual PDF 4.5 MB (on demand).

**Assessment:** acceptable for a data app. The only clear saving is Firebase (F-28, P3): load Firestore after the first paint
on public pages (visitors on the landing page do not need it until they sign in). Expected gain ~130 KB for visitors only.

Runtime: live prices throttled to ≤ 2 updates/s per context (`useLive`), listeners detach when the tab is hidden ≥ 60 s,
member views come from the Cloudflare edge with one batched poll every 30 s. No leak or duplicate listener was seen in code
review; the sweep found **no console errors on any page**.

## 2. Engine performance

Rounds average **201 s** (max 279 s) on a 240 s cycle (`quick-status`, last 48 rounds). **F-29 (P2):** the average round
now takes 84 % of the cycle and the slowest round is longer than the cycle, so the next round starts late. Rounds grew from
156 s (22 Nov) to 201 s (24 Nov) as features were added (risk state, BTC shock, sweep guard, Coinalyze, market extras).
Per-step timings exist (`step_times`, Health admin). Recommendation: check the three slowest steps and move hourly work to
the hourly slot.

Training: 7 / 7 nights succeeded, ~20-30 min. PyTorch is installed in every engine and training run only because 13
bundles still contain LSTM / GRU / Transformer members (F-20).

## 3. Security

| Area | Result |
|---|---|
| Secrets | Firebase key, Telegram token, Coinalyze key, Gemini keys, Cloudflare token: GitHub secrets / Firestore owner docs only. Error texts are redacted (`redact.py`). Not printed anywhere in this audit. |
| Firestore rules | Admin by e-mail list; members limited to their own `users/{uid}`, `paper/{uid}_*`, `auto_paper/{uid}`; trades readable only by their owner; admin views (`health_admin`, `guardian`, `perf_lab`, `market_turn`, `hesper` unless shared) protected; jobs signed and per-user limited. **Tested on every push (107 passing runs this week).** |
| Admin-only pages | `AdminOnly` in the app **and** the matching rules behind every admin view and job (frontend checks are backed by rules). |
| Practice-account integrity | `validPaper` rule limits balance changes to real deposits; auto-trade settings are clamped by the engine (daily loss 0.5-100 %, exposure 5-100 %). |
| **F-30 (P2, hardening)** | `isAdmin()` checks the e-mail in the token but not `email_verified`. With Firebase's default "one account per e-mail" this cannot be abused today (the admin e-mail already exists), but adding `email_verified == true` closes the door for good. |
| Real orders | None. No exchange keys exist anywhere; all trading code writes to virtual accounts only. |
| Dependencies | `npm audit` / `pip-audit` could not be run here (no registry access to the advisory database) — **unverified**. |

## 4. Reliability

* Fail-closed checks for stale data, calendar and filter errors are in place and logged on Health.
* One fail-open path found: F-02 (stale market-risk state → auto-trade at normal size).
* Lost-state guard, backup rotation and restore are working (backup verified today).
* Engine availability 92 % last week (F-03, see report 06).
