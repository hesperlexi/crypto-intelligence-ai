# 08 · New features worth adding

Only features that use data the platform already has, cost nothing extra, and can be measured. Ranked.

| # | Feature | Problem it solves | Data exists? | New infra? | Affects trades? | How to measure | Effort | Priority |
|---|---|---|---|---|---|---|---|---|
| 1 | **Blocked-signal scoreboard for members** (Results: "What our filters held back and how it turned out") | Builds trust and shows the filters work (or not); today only the admin sees it | yes (`rejected_signals`, `v3_guard_audit`) | no | no | views, retention | S | P2 |
| 2 | **Long / short exposure meter** on Overview + Portfolio (open calls by side, and how far the book leans) | The record was 96 % short; members cannot see that concentration | yes (`signals`, positions) | no | no | — | S | P2 |
| 3 | **"Move already gone?" on the signal card** (distance of price from entry in R, with a warning above e.g. 0.5R) | Members join late after a fast move | yes (live price + plan) | no | no (display) | late entries in practice accounts | S | P2 |
| 4 | **Engine uptime + last gap + backup age on Health** | The 7-hour gap on 23 Nov was invisible on the page | yes (runs, `watch_status`, backups) | no | no | — | S | P1 |
| 5 | **Model health panel**: per timeframe fresh / stale models, skill vs base rate, calibration, challenger refusals | Stale 15m models (4.4 days) went unnoticed | yes (usage audit, proof checks, challenger log) | no | no | — | M | P2 |
| 6 | **Spot-led vs leverage-led move label** (price up with OI up + funding up = leverage-led; price up with OI flat = spot-led) | Leverage-led rallies unwind fast; useful context for the risk state | yes (OKX OI, funding, taker) | no | **only after a replay test** | replay verdict | M | P3 |
| 7 | **Market-regime transition warning** using the existing turn detector, shown to members as context (not a trade rule) | 21-23 Nov turn caught shorts out | yes (turn detector, shadow log) | no | no | shadow log after 3 weeks | S | P3 |
| 8 | **Personal trade review** on Portfolio: your win rate by timeframe / side vs the record's | Members learn from their own practice | yes (practice account) | no | no | — | S | P3 |
| 9 | **Unified timeline** (one feed: new call, target hit, stop, risk level change, news release, your auto-trades) | Information is spread over 5 pages | yes | no | no | — | M | P3 |
| 10 | **Order-flow features test** (OKX trades / book / liquidations recorded since 20 Nov) | Possible new edge for 15m | recording, 4 weeks by mid-December | no | only if it passes | replay verdict | M | P3 (December) |

Not recommended now: ETF flows and exchange in/outflows (no reliable free source with correct timestamps), more ML models
(the evidence says fewer, better models — see 03), a dedicated 15m strategy without new data (every 15m study so far
failed).
