# 09 · Prioritised action plan (for approval)

Nothing below is done yet. Each step is small, reversible and tested on its own. Engine / strategy changes go live only if
they pass the standard replay verdict (`research_verdict`).

## Findings register

C = confirmed (seen in code and / or live data) · S = suspected (needs one more check) · E = evidence / design question (not a bug).

| ID | Pri | Type | Area | Files / source | One line |
|---|---|---|---|---|---|
| F-01 | P1 | C | All pages, tablet | `components/AppNav.tsx`, `App.tsx` header | nav row wider than 768-1023 px screens → page scrolls sideways |
| F-02 | P1 | C | Auto-trade | `worker.py` 1758, `risk_state.py` 283-296, `autopaper.py` 100-119 | stale risk state → normal size (fails open) |
| F-03 | P1 | C | Engine uptime | Actions run history | 7 h gap 23 Nov, 2.8 h gap 24 Nov; self-queue fix unproven |
| F-04 | P2 | C | Auto-trade | `autopaper.py` 112-116, 279-283 | daily loss start value stored late |
| F-05 | P2 | E | Record | `v3-guard-audit.json` | 96 % of calls short |
| F-06 | P2 | E | Risk | `risk-*.json` | correlation cap tested, failed; no change |
| F-07 | P2 | C | Risk / disclosure | `App.tsx` 74, 412 | `/risk` used twice; members cannot open the disclosure |
| F-08 | P2 | C | Overview, Risk | `V3Home.tsx` 43, `risk_state.py` 36 | "Data late" after 20 min, publish every 30 min |
| F-09 | P3 | C | Results log (phone) | Results → Signal log | outcome line cut off |
| F-10 | P3 | C | Signals (phone) | Signals page timeframe row | no hint that the TF row scrolls |
| F-11 | P2 | C | Training | quick-status `model_age_h` | 15m models up to 105 h old |
| F-12 | P1 | E | Ensemble | `models-value-latest.json` | weak models hold ~60 % weight |
| F-13 | P1 | E | Edge | `usage-latest.json` | 0 of 251 bundles pass the strict edge test |
| F-14 | P1 | E | Filters | `v3-guard-audit.json` | cap / trade filter / VP wall blocked +77R live |
| F-15 | P3 | C | Tooling | `scripts/audit_live.py` 210-264 | outdated checks → 34 false alarms |
| F-16 | P3 | C | Firestore | `reports/audit.json` | ~40 stale views of removed coins |
| F-17 | P3 | S | Models | `usage-latest.json` | active bundles for unwatched coins |
| F-18 | P3 | C | Frontend | `Instruments.tsx` | OrbitDial / SonarScope unused |
| F-19 | P3 | C | Calculations | `engine/futures.py`, `lib/paperFutures.ts` | two liquidation formulas, no test pins them |
| F-20 | P3 | C | Infra | `usage-latest.json`, workflows | PyTorch installed for 13 bundles |
| F-21 | P3 | C | Health | `pages/Health.tsx` | Gemini usage not shown |
| F-22 | P3 | C | Signal card | `TradeCall.tsx` | no "move already gone" in R |
| F-23 | P3 | E | Bots | `services/bots.py` | reversal exit never studied |
| F-24 | P3 | E | Data | — | no free ETF / exchange-flow source |
| F-25 | P3 | C | Workflows | `backup-verify.yml` | concurrent pushes collide |
| F-26 | P3 | C | Health | — | backup age not shown |
| F-27 | P3 | C | Docs | `README.md` | outdated since 30 Oct |
| F-28 | P3 | E | Frontend | build output | Firebase 134 KB on first load for visitors |
| F-29 | P2 | C | Engine | quick-status | round 201 s of 240 s; max 279 s |
| F-30 | P2 | S | Rules | `firestore.rules.template` 16-18 | `isAdmin` without `email_verified` |

## Stage 1 — fix now (bugs, no effect on signals)

| Step | Finding | Change | Risk | Test |
|---|---|---|---|---|
| 1.1 | F-02 (P1) | Auto-trade: unknown / stale market risk → treat as HIGH (half size) for members who follow risk | very low | unit test on `protection()` |
| 1.2 | F-01 (P1) | Tablet nav row (768-1023 px): make it scroll inside itself or wrap; no page-wide sideways scroll | low | browser sweep at 768 / 820 / 1000 px |
| 1.3 | F-08 (P2) | "Data late" only after 45 min (publish cadence is 30 min) | none | screenshot |
| 1.4 | F-07 (P2) | Give the risk disclosure its own path (`/risk-disclosure`), keep `/risk` = Risk page, fix the three links; old `/risk` links for signed-out visitors still show the disclosure | low | route test as member + visitor |
| 1.5 | F-04 (P2) | Daily loss limit: store the day's start value on the first tick of the day, not the first candidate | low | unit test |
| 1.6 | F-30 (P2) | Rules: `isAdmin()` also requires `email_verified` | low | rules tests |

## Stage 2 — operations and monitoring

| Step | Finding | Change | Test |
|---|---|---|---|
| 2.1 | F-03 (P1) | Confirm the engine self-queue for 7 days; add "uptime 7 d / last gap" to Health | measure gaps next week |
| 2.2 | F-29 (P2) | Find the 3 slowest engine steps; move hourly work out of the 4-min round (target avg < 170 s) | step timings |
| 2.3 | F-11 (P2) | Training: give 15m a fixed share each night (no 15m model older than 48 h) | model ages in quick-status |
| 2.4 | F-26, F-25 | Backup age on Health; retry loop for workflows pushing to `research-results` | next backup-verify run |
| 2.5 | F-15, F-16 | Update `audit_live.py` to the current leverage / liquidation rules; one-time clean-up of views for removed coins (**deletes Firestore view docs — approval needed**) | audit report shows 0 false alarms |

## Stage 3 — evidence studies (read-only replays, then decide)

| Step | Question | Pass → change |
|---|---|---|
| 3.1 | Trade filter v1 off on 1h / 4h? (blocked +29.6R live) | switch off where it passes |
| 3.2 | Volume wall off? (blocked +9.2R live) | switch off if it passes |
| 3.3 | Same-side cap 12 vs 16 with the BTC shock guard on | change cap only if drawdown stays within +15 % |
| 3.4 | 4h Random-Forest-only ensemble (81 % of series better on 17 Nov) | per-timeframe model set |
| 3.5 | Reversal exit of the bots | keep or remove |

## Stage 4 — information for members (no effect on trades)

Long / short exposure meter · "move already gone?" on the signal card · blocked-signal scoreboard · confidence range on the
live record · side split on Results · coin page: BTC correlation. (See 08.)

## Stage 5 — documentation

README rewrite for V3 (pages, schedule 4 min, data sources); one version number story (app 2.1.0 vs engine 2.65.0 vs
V3) in CLAUDE.md; remove dead `OrbitDial` / `SonarScope` after the owner confirms the new dial; a test that pins the
browser and engine liquidation formulas together (F-19).

## Acceptance for the whole plan

All pages pass the browser sweep at 3 widths × 3 roles with 0 errors and 0 sideways scroll; backend tests green; rules
tests green; engine uptime ≥ 99 % over 7 days; no Firestore day above 15,000 writes; every strategy change has a PASS
verdict file in `research-results`.
