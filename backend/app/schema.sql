-- Portable schema: runs unchanged on SQLite (default, local) and PostgreSQL.
-- For TimescaleDB, additionally run timescale.sql after this file.
-- All timestamps are UTC epoch milliseconds (BIGINT). JSON payloads are stored as TEXT.

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlists (
  user_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,
  added_at BIGINT NOT NULL,
  PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS market_data (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  ts BIGINT NOT NULL,              -- candle OPEN time
  open DOUBLE PRECISION NOT NULL,
  high DOUBLE PRECISION NOT NULL,
  low DOUBLE PRECISION NOT NULL,
  close DOUBLE PRECISION NOT NULL,
  volume DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (exchange, symbol, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS model_versions (
  id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  data_start BIGINT,
  data_end BIGINT,
  n_samples INTEGER,
  n_oos INTEGER,
  edge_confirmed INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  path TEXT,
  summary TEXT                      -- JSON: weights, folds, edge test, notes
);
CREATE INDEX IF NOT EXISTS ix_model_versions_sym ON model_versions (symbol, timeframe, active);

CREATE TABLE IF NOT EXISTS model_metrics (
  model_version_id TEXT NOT NULL,
  model TEXT NOT NULL,
  metric TEXT NOT NULL,
  value DOUBLE PRECISION,
  PRIMARY KEY (model_version_id, model, metric)
);

CREATE TABLE IF NOT EXISTS predictions (
  id TEXT PRIMARY KEY,
  created_at BIGINT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bar_ts BIGINT NOT NULL,           -- open time of the last CLOSED candle the prediction used
  target_ts BIGINT NOT NULL,        -- time at which the outcome becomes known
  model_version_id TEXT NOT NULL,
  price DOUBLE PRECISION NOT NULL,
  p_down DOUBLE PRECISION NOT NULL,
  p_neutral DOUBLE PRECISION NOT NULL,
  p_up DOUBLE PRECISION NOT NULL,
  predicted_class INTEGER NOT NULL,
  neutral_band DOUBLE PRECISION NOT NULL,
  expected_return DOUBLE PRECISION,
  confidence DOUBLE PRECISION,
  detail TEXT,                      -- JSON: per-model probabilities, intervals
  UNIQUE (symbol, timeframe, bar_ts, model_version_id)
);
CREATE INDEX IF NOT EXISTS ix_predictions_sym ON predictions (symbol, timeframe, bar_ts);

CREATE TABLE IF NOT EXISTS prediction_outcomes (
  prediction_id TEXT PRIMARY KEY,
  resolved_at BIGINT NOT NULL,
  actual_return DOUBLE PRECISION NOT NULL,
  actual_class INTEGER NOT NULL,
  correct INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  created_at BIGINT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bar_ts BIGINT NOT NULL,
  signal TEXT NOT NULL,
  decision TEXT NOT NULL,
  score DOUBLE PRECISION,
  confidence DOUBLE PRECISION,
  regime TEXT,
  price DOUBLE PRECISION NOT NULL,
  side INTEGER NOT NULL DEFAULT 0,  -- +1 long setup, -1 short setup, 0 none
  entry DOUBLE PRECISION,
  stop DOUBLE PRECISION,
  tp1 DOUBLE PRECISION,
  tp2 DOUBLE PRECISION,
  tp3 DOUBLE PRECISION,
  rr DOUBLE PRECISION,
  status TEXT NOT NULL DEFAULT 'OPEN',   -- OPEN | STOPPED | TP1 | TP2 | TP3 | EXPIRED | INFO
  tp1_hit INTEGER NOT NULL DEFAULT 0,
  tp2_hit INTEGER NOT NULL DEFAULT 0,
  tp3_hit INTEGER NOT NULL DEFAULT 0,
  stop_hit INTEGER NOT NULL DEFAULT 0,
  closed_at BIGINT,
  return_pct DOUBLE PRECISION,
  model_version_id TEXT,
  payload TEXT,
  UNIQUE (symbol, timeframe, bar_ts)
);
CREATE INDEX IF NOT EXISTS ix_signals_created ON signals (created_at);

CREATE TABLE IF NOT EXISTS paper_accounts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  starting_balance DOUBLE PRECISION NOT NULL,
  cash DOUBLE PRECISION NOT NULL,
  created_at BIGINT NOT NULL,
  benchmark_symbol TEXT,
  benchmark_price DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS paper_positions (
  account_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  avg_price DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS trades (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  mode TEXT NOT NULL DEFAULT 'PAPER',   -- this application never places real orders
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  price DOUBLE PRECISION NOT NULL,      -- fill price incl. slippage
  mark_price DOUBLE PRECISION NOT NULL, -- market price at the time of the order
  fee DOUBLE PRECISION NOT NULL,
  slippage_cost DOUBLE PRECISION NOT NULL,
  realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
  note TEXT
);
CREATE INDEX IF NOT EXISTS ix_trades_account ON trades (account_id, created_at);

CREATE TABLE IF NOT EXISTS backtests (
  id TEXT PRIMARY KEY,
  created_at BIGINT NOT NULL,
  status TEXT NOT NULL,
  params TEXT NOT NULL,
  result TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  type TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL DEFAULT '4h',
  params TEXT,
  cooldown_s INTEGER NOT NULL DEFAULT 3600,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_state TEXT,
  last_fired_at BIGINT,
  created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
  id TEXT PRIMARY KEY,
  alert_id TEXT NOT NULL,
  created_at BIGINT NOT NULL,
  symbol TEXT NOT NULL,
  type TEXT NOT NULL,
  message TEXT NOT NULL,
  is_read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_alert_events_created ON alert_events (created_at);

CREATE TABLE IF NOT EXISTS system_health (
  id TEXT PRIMARY KEY,
  ts BIGINT NOT NULL,
  component TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_system_health_ts ON system_health (ts);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- ---- batch-engine (Firebase deployment) tables ---------------------------------------------------
CREATE TABLE IF NOT EXISTS published (
  doc_id TEXT PRIMARY KEY,
  hash TEXT NOT NULL,
  ts BIGINT NOT NULL,
  core TEXT
);

CREATE TABLE IF NOT EXISTS engine_runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  started_at BIGINT NOT NULL,
  finished_at BIGINT,
  status TEXT NOT NULL,
  detail TEXT
);

CREATE TABLE IF NOT EXISTS bots (
  id TEXT PRIMARY KEY,
  config TEXT NOT NULL,
  state TEXT NOT NULL,
  reset_token TEXT,
  created_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_trades (
  id TEXT PRIMARY KEY,
  bot_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side INTEGER NOT NULL,
  opened_at BIGINT NOT NULL,
  closed_at BIGINT NOT NULL,
  entry DOUBLE PRECISION NOT NULL,
  exit DOUBLE PRECISION NOT NULL,
  qty DOUBLE PRECISION NOT NULL,
  pnl DOUBLE PRECISION NOT NULL,
  fees DOUBLE PRECISION NOT NULL,
  return_pct DOUBLE PRECISION NOT NULL,
  r_multiple DOUBLE PRECISION,
  exit_reason TEXT NOT NULL,
  correct INTEGER,
  info TEXT
);
CREATE INDEX IF NOT EXISTS ix_bot_trades_bot ON bot_trades (bot_id, closed_at);

CREATE TABLE IF NOT EXISTS bot_equity (
  bot_id TEXT NOT NULL,
  ts BIGINT NOT NULL,
  equity DOUBLE PRECISION NOT NULL,
  benchmark DOUBLE PRECISION,
  PRIMARY KEY (bot_id, ts)
);

-- economic calendar (US data releases etc.), kept so past events stay known to replays
CREATE TABLE IF NOT EXISTS econ_events (
  id TEXT PRIMARY KEY,
  ts BIGINT NOT NULL,
  country TEXT NOT NULL,
  title TEXT NOT NULL,
  impact TEXT NOT NULL,
  forecast TEXT,
  previous TEXT,
  actual TEXT,
  notified_at BIGINT,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_econ_events_ts ON econ_events (ts);

-- futures-market history used as model features: funding rate events and the hourly premium index
CREATE TABLE IF NOT EXISTS derivs (
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL,              -- 'funding' (event time) | 'premium_1h' (bar open time)
  ts BIGINT NOT NULL,
  value DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (symbol, kind, ts)
);

-- v2.2 safety switch: trades a paused coin/timeframe would have taken (tracked like signals, never shown as signals)
CREATE TABLE IF NOT EXISTS shadow_signals (
  id TEXT PRIMARY KEY,
  created_at BIGINT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bar_ts BIGINT NOT NULL,
  signal TEXT NOT NULL,
  decision TEXT NOT NULL,
  score DOUBLE PRECISION,
  confidence DOUBLE PRECISION,
  regime TEXT,
  price DOUBLE PRECISION NOT NULL,
  side INTEGER NOT NULL DEFAULT 0,
  entry DOUBLE PRECISION,
  stop DOUBLE PRECISION,
  tp1 DOUBLE PRECISION,
  tp2 DOUBLE PRECISION,
  tp3 DOUBLE PRECISION,
  rr DOUBLE PRECISION,
  status TEXT NOT NULL DEFAULT 'OPEN',
  tp1_hit INTEGER NOT NULL DEFAULT 0,
  tp2_hit INTEGER NOT NULL DEFAULT 0,
  tp3_hit INTEGER NOT NULL DEFAULT 0,
  stop_hit INTEGER NOT NULL DEFAULT 0,
  closed_at BIGINT,
  return_pct DOUBLE PRECISION,
  model_version_id TEXT,
  payload TEXT,
  UNIQUE (symbol, timeframe, bar_ts)
);

-- v2.5 (audit v1): every trade-management decision (logged / skipped / cooldown / re-entry cap / stale / fill /
-- not filled / each exit), with the inputs it was made on
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  ts BIGINT NOT NULL,
  symbol TEXT,
  timeframe TEXT,
  signal_id TEXT,
  rule TEXT NOT NULL,
  inputs TEXT,
  ai_rationale TEXT,
  engine_version TEXT,
  app_version TEXT
);
CREATE INDEX IF NOT EXISTS ix_decisions_ts ON decisions (ts);
CREATE INDEX IF NOT EXISTS ix_decisions_pair ON decisions (symbol, timeframe, ts);
