# v1 upgrade: backend ↔ frontend data contract

All new fields are optional. Old documents lack them; the UI must render cleanly without them.

## Signal row (views `signals`, `track_record.signals[]`, `analysis_*.call`, futures rows `.call`)
| field | type | meaning |
|---|---|---|
| `fill_status` | "PENDING" \| "FILLED" \| "NOT_FILLED" | pullback entries wait for price to trade through `entry`; NOT_FILLED = never entered, excluded from win rate |
| `peak_r` | number | best open profit reached since publication, in R (1R = entry→stop distance) |
| `peak_pct` | number | same, in % price move |
| `exit_reason` | "tp3" \| "stop" \| "admin_stop" \| "break_even" \| "trail" \| "giveback" \| "time" \| "expired" \| null | how the call ended |
| `managed` | 0/1 | 1 = closed by a managed exit (giveback / trail / time) |
| `app_version`, `engine_version` | string | stamped on every new row |
| `payload.ai` | `{rationale, regime, review?, model, at}` \| absent | Gemini advisor note (plain language, advisory only) |

## Analysis / futures rows
- `ai`: `{rationale, regime, model, at}` or absent (latest advisor note for that coin/timeframe call).
- `call`: the currently tracked call for that coin/timeframe or null:
  `{id, status, fill_status, side, entry, stop, tp1, tp2, tp3, peak_r, peak_pct, exit_reason, managed, created_at}`.
- `adjustments` (v2.7, signal rows, track-record rows and `call`; absent when none): the admin's public, forward-only
  changes `[{at, field: "stop"|"tp1", old, new, note}]`, oldest first. On `call`, `stop` / `tp1` are the levels now in
  force and `stop0` / `tp1_0` the published ones; signal / track-record rows keep the published levels.
- `record_status`: "logged" | "already_open" | "not_logged" (why a shown call is / isn't in the record).
- `stale`: true when candles are too old to trade on (decision is then NO TRADE).

## Public `views/wins_today`
Adds `closed` (all closed calls in the same window) and `losses` (count), so the sign-in page can show losses beside wins.

## `views/decisions_recent`
Last 100 trade-management decisions: `{ts, symbol, timeframe, signal_id, rule, inputs, ai_rationale, engine_version, app_version}`.

## Brand
Backend `app/brand.py` and frontend `src/lib/brand.ts` hold the same values:
`name = "Crypto Intelligence AI"`, `url = "https://www.cryptointelai.com"`, `supportEmail = "support@cryptointelai.com"`,
`tagline = "AI market analysis for crypto traders"`, `disclaimer = "Analysis only, not financial advice. No guaranteed profits."`.
Footer: `Crypto Intelligence AI v{version} · www.cryptointelai.com · support@cryptointelai.com · Analysis only, not financial advice.`
