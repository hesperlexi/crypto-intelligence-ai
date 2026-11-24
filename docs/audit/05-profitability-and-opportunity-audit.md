# 05 · Profitability and missed-opportunity audit

All figures are **net of the 0.15 % round trip and funding**, in R (1R = the call's stop distance). Sources:
`research-results/results/v3-guard-audit.json` (run for this audit, 24 Nov), `exits-latest.json` (24 Nov),
`modelset-*-latest.json`, `caps-latest.json`, `v265-latest.json`, `sweep-latest.json`, `turn-latest.json`.

**Read with care:** the live samples are small and come from one market phase (mid-November, BTC falling). Live figures
show what happened; only the replay test split (unseen data, several months) says something about the future, and it is
thin.

## 1. Four different things — never mixed

| What | Period | Calls / trades | Result |
|---|---|---|---|
| **Published signals (the record)** | 4 Nov → 24 Nov reset | 110 closed | 82 won (75 %), **+21.8R**, +0.20R per call, profit factor 1.85 |
| **Replay, unseen test split** (live rules, record exits) | months of history | 500 calls | +7.9R, **+0.016R per call**, max drawdown 35R |
| **Demo bots** (after the 24 Nov reset) | 24 Nov | few | 7 bots between −0.01 % and +0.08 % — too early |
| **Members' manual practice** | — | not measured here (private accounts; only the leaderboard aggregates exist) | unverified |

The live record is much better than the replay. Most likely reason: the live period was a clean downtrend and the system was
short 96 % of the time (106 shorts +23.6R, 4 longs −1.85R). **Expect the long-run average to be much closer to the replay
than to the live record.**

### Live record by timeframe (4-24 Nov)

| TF | Closed | Won | Net R | Per call | Profit factor |
|---|---|---|---|---|---|
| 15m | 21 | 13 | +6.4 | +0.31 | 1.94 |
| 1h | 11 | 7 | +1.8 | +0.16 | 1.40 |
| 4h | 53 | 38 | +10.0 | +0.19 | 1.75 |
| 12h | 20 | 19 | +2.1 | +0.10 | 2.97 |
| 1d | 5 | 5 | +1.5 | +0.31 | — |

### Replay test split by timeframe (24 Nov exits study, "base" = live rules)

| TF | Calls | Per call | Total |
|---|---|---|---|
| 15m | 147 | −0.046R | −6.8R |
| 1h | 26 | +0.223R | +5.8R |
| 4h | 327 | +0.027R | +8.9R |

15m loses slightly on unseen data, 4h is barely positive, 1h is positive on too few calls to judge. 1d is negative in
every replay (−0.05R), which is why it is demo-only.

## 2. What the filters blocked — did they block winners? (live, 14-24 Nov)

Every call a filter blocked was followed to its end with the record's rules (`rejected_signals`). 426 blocked calls closed:

| Filter | Blocked & closed | Won | Net R | Per call | Verdict on this sample |
|---|---|---|---|---|---|
| **Same-side cap (12)** | 142 | 92 | **+38.1** | +0.27 | blocked mostly winners |
| **AI trade filter ("FILTERED")** | 107 | 72 | **+29.6** | +0.28 | blocked mostly winners |
| Volume wall ahead | 32 | 21 | +9.2 | +0.29 | blocked winners |
| Target too small for costs | 17 | 10 | +0.2 | 0.00 | neutral |
| Grade A only | 100 | 51 | **−10.1** | −0.10 | **saved losses** |
| Stop too tight for fees | 15 | 4 | **−9.1** | −0.61 | **saved losses** |
| Against bigger trend | 11 | 3 | **−6.0** | −0.55 | **saved losses** |
| Capital protection / stop too wide | 2 | 0 | −2.1 | | saved losses |
| **All blocked** | 426 | 253 | **+49.8** | +0.12 | |

By BTC's 24 h move at the time, blocked calls lost money when BTC had just moved more than +3 % (30 calls, −19.1R) or
fallen more than 3 % (93 calls, −4.0R), and earned in calmer conditions (−3 %…+3 %: +72.9R).

**What this means (F-14, P1 — needs a proper test before any change):**

* Three filters blocked more winners than losers **in this sample**: the same-side cap, the AI trade filter and the volume
  wall. Together +77R left on the table in 10 days.
* But: the sample is 100 % shorts in a falling market, the blocked calls overlap each other (taking all of them at once
  would have meant far more open trades), and the earlier replays told a different story for the cap (cap 24 or none earned
  more but with a much deeper drawdown, 49R vs 37R) and for the volume wall (it passed as part of the v2.22 package).
* The three "saving" filters (grade A only, stop too tight, bigger trend) did their job.

**Recommendation:** run one replay study with the standard verdict (`research_verdict`) for (a) the trade filter v1 on 1h
and 4h switched off (it is already off on 15m), (b) the volume wall off, (c) cap 12 vs 16 with the BTC shock guard on —
and change only what passes. Do not change anything on the live sample alone.

## 3. Entries, exits, sizing

| Question | Finding |
|---|---|
| Entries too late? | Entries are at the decision price of a **closed** candle (honest). On 4h/12h a call can come up to one candle after the move started; the "Ready / Wait for entry" label exists, but the card does not show how far price has already run in R (F-22, P3). |
| Stops too tight? | The fee filter already blocks 1h/4h stops < 1.5 % — and it saved −9.1R. No sign of systematically tight stops. |
| Targets / break-even / trailing | Studied 15 Nov (early break-even, give-back, nearer TP1) and per coin (21 Nov): none passed. Live exits stay. |
| Time exits | Re-tested today: ×2, ×4 and no limit all FAILED (best bootstrap 67 %, needs 80 %). Keep. |
| Reversal exit (bots) | No dedicated study found (F-23, P3). |
| Sizing / leverage | 15m 10-50x by the engine's safe-leverage rule (liquidation ≥ 1.5 × stop distance beyond entry); other TFs ≤ 10x on the card, bots ≤ 20x. Consistent everywhere. |
| Missing data bypassing risk | One case: F-02 (stale risk state → normal sizing in auto-trade). |

## 4. Market intelligence used vs available

Used in decisions: BTC context, higher timeframes (per series), funding/premium (per series), Binance crowd data with a
2-day lag (per series), news calendar guard, BTC shock guard, sweep guard, volatility + loss-stop veto. Collected but **not
used** (by evidence): news sentiment (too short), liquidations (tested 23 Nov, FAIL), OKX order flow (recording since 20 Nov,
test due early December), market-turn detector (shadow). Not available free: ETF flows, exchange in/outflows (F-24).

## 5. Bottom line

* Nothing in the code is silently reducing profits (no bug that loses money was found).
* The thinnest point is the evidence itself: the out-of-sample edge is small (+0.016R per call), concentrated in 4h, and
  the live record so far is one market phase.
* The biggest *potential* gain is in the filters that blocked winners (§2). It must pass a replay first.
