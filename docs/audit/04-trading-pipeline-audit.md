# 04 · Trading decision pipeline

Traced in code (`services/analysis.py`, `engine/*`, `ml/*`, `services/tracking.py`, `engine/manage.py`, `services/bots.py`,
`services/hesper.py`, `services/autopaper.py`, `views.py`, frontend `TradeCall`, `RecordDetails`, `paperFutures`).

## The path of one call

1. **Data** — closed candles from Binance spot (MEXC for futures-only coins), stored in SQLite, holes filled; stale candles →
   NO TRADE "stale". Candle quality checks in `data/quality.py`.
2. **Indicators + features** — `features/`, `engine/regime.py`, `engine/mtf.py`; higher-timeframe and futures features only
   where their gates passed.
3. **Model inference** — calibrated ensemble per coin × timeframe → probabilities up / neutral / down.
4. **Directional confidence + grade** — hit rate of comparable out-of-sample calls; A = trend + AI agree above the proven
   threshold, B = AI-led with an out-of-sample edge. Public: 15m / 1h / 3d grade A only, 4h / 12h A+B, 1d demo-only.
5. **Trade plan** — `engine/setup.py`: stop from structure/ATR, TP1 = 1R (50 %), TP2 1.25-2R and TP3 2-3R (25 % each) chosen
   by historical first-passage, capped by support / resistance; runner variant where the runner model passed.
6. **Gates (roughly in this order)** (each one turns the call into NO TRADE with a named flag; blocked calls are followed in
   `rejected_signals`): bigger-trend check · costs rule (1R ≥ 3 × round-trip cost) · stop too wide (15m 10x minimum) ·
   trade filters · volume wall · fee filter (1h/4h stop < 1.5 %) · same-side cap 12 (+ reserve) · grade-A-only TFs · call
   already running / cooldown · news guard (−45 / +30 min) · safety switch · BTC shock guard · liquidity-sweep guard ·
   capital-protection veto (volatility + loss stop + drift) · demo-only / watch-only.
7. **Record** — `tracking.log_signal`: market entry at the decision price (or a PENDING limit for pullback rules), net results
   after 0.15 % round trip + funding, followed on 15m candles, break-even after TP1, TP1 after TP2, time limit per call
   (15m 250, 1h 200, 4h 100, others 30 candles), admin changes logged and shown.
8. **Execution (virtual)** — demo bots, Hesper / Last Stand and members' auto-trade read the same call, size it, apply the
   same exit rules (`engine/manage.py` is the one implementation of the exit rules), with fees, slippage and funding.
9. **Reporting** — `views.py` builds track record, wins today, weekly report, achievements, public record from the same
   `record_clause`.

## Consistency checks

| Check | Result |
|---|---|
| Costs: record vs bots vs practice account | **Same**: futures fee 0.05 % + slippage 2 bp + half spread 0.5 bp per side = **0.15 % round trip** in `analysis.round_trip_cost`, `bots.py`, and the browser (`paperFutures.FEE`, `SLIP`). |
| Liquidation price: engine vs browser | **Same formula** (maintenance tier + exit fee) in `engine/futures.py` and `lib/paperFutures.ts`. Two copies, no test pinning them together (F-19). |
| Exit rules: record vs bots vs Hesper | **One implementation** (`engine/manage.py`), proven equal to the research simulator (`series_sim.follow`, test). |
| Card levels vs record | While a call is OPEN the card shows the **recorded** levels (`plan.recorded`). Consistent. |
| Win / loss definition | Net of costs everywhere (record, Telegram, weekly report, achievements, safety switch). Calls closed at market are shown as "Win/Loss at market" since today. |
| Time limits | Same per-call `horizon_bars` for record and bots. Re-tested today: longer or no limit FAILED (`exits-latest.json`). Keep. |
| Watch-only (silver) and demo-only (1d) calls | Never reach `signals`, bots (except the 1d demo bot), auto-trade or Telegram (side 0 in public rows). Verified in code. |

## Problems found

| ID | Priority | What | Evidence | Effect |
|---|---|---|---|---|
| F-02 | P1 | **Auto-trade treats an unknown market-risk state as "normal".** `risk_state.current()` returns None when the state is older than 2 h ("never safe, callers decide"), but `autopaper.protection()` → `practice_policy(None)` gives full size and allows new trades. | `worker.py` 1758-1759, `risk_state.py` 283-296 | If the risk step fails or stalls, members' auto-trade keeps opening full-size trades even if the market is in a SEVERE state. Fix: treat None as HIGH (half size) when the member follows market risk. |
| F-04 | P2 | **Daily loss limit only counts from the first auto-trade check of the UTC day.** If no auto-trade candidate appears that day, no start value is stored and manual-trade losses that day are not counted. | `autopaper.py` 112-116, 279-283 | Mild: the limit can start late. |
| F-05 | P2 | **The record is 96 % short.** Since 4 Nov, 106 of 110 published calls were shorts (longs: 4, −1.85R). Nothing in the pipeline is wrong, but the same-side cap (12) plus a falling market concentrates risk in one direction; the 21-23 Nov losses came from that. | `v3-guard-audit.json` `published` | Direction concentration risk; the BTC shock guard (live since 24 Nov) addresses the worst case. |
| F-06 | P2 | **Correlated exposure is not limited by coin family.** The cap counts calls per side, not how correlated they are (most alts move with BTC). A correlation-weighted cap was tested on 21 Nov and FAILED (−15 to −21R), so this stays as is; noted for completeness. | `research-results/results/risk-*.json` | None now. |

No incorrect financial calculation, no wrong-side stop, no wrong target order and no grade on a non-trade decision were
found in today's live data (`reports/audit.json`, 51 plans checked). The 34 "problems" that report lists are false alarms
from the outdated checker (it still assumes a 10x cap and an older liquidation formula — F-15).

## Signal page vs bots — the one real difference

Bots, Hesper and auto-trade open at **their** run's live price (with slippage), not at the recorded entry. A call published
at the end of a tick and taken on the next tick (≤ 4 min later) can differ by a few basis points. This is honest (the record
does not use the bots' fills, and vice versa) and is documented; no change recommended.
