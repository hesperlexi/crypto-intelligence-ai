-- Optional: run once on PostgreSQL with the TimescaleDB extension, after schema.sql.
CREATE EXTENSION IF NOT EXISTS timescaledb;
-- ts is epoch milliseconds, so the chunk interval is given in milliseconds (30 days).
SELECT create_hypertable('market_data', 'ts', chunk_time_interval => 2592000000,
                         if_not_exists => TRUE, migrate_data => TRUE);
