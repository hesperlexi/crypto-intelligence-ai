"""Central configuration. Everything is overridable through environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional: load backend/.env or project .env if python-dotenv is installed
    from dotenv import load_dotenv

    for _p in (Path(__file__).resolve().parents[1] / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if _p.exists():
            load_dotenv(_p, override=False)
except Exception:  # pragma: no cover
    pass

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "SUI/USDT",
]

TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "3d", "1w"]
TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800,
}
# Forecast horizon -> the timeframe whose own model produces it (one bar ahead).
# A 1h model is never extrapolated into a daily forecast.
HORIZONS = {"1H": "1h", "4H": "4h", "12H": "12h", "24H": "1d", "3D": "3d", "7D": "1w"}
MODEL_TIMEFRAMES = ["1h", "4h", "12h", "1d", "3d", "1w"]
MTF_TIMEFRAMES = ["15m", "1h", "4h", "12h", "1d", "1w"]
MTF_WEIGHTS = {"15m": 0.08, "1h": 0.14, "4h": 0.22, "12h": 0.16, "1d": 0.24, "1w": 0.16}

# How many closed candles to keep per timeframe (history depth for training / charts).
HISTORY_BARS = {
    "1m": 1500, "5m": 1500, "15m": 3000, "30m": 2000, "1h": 20000, "4h": 12000,
    "12h": 5000, "1d": 3000, "3d": 1200, "1w": 600,
}

# Walk-forward window sizes in bars: (train, validation, test).
# 1h = 12m/1.5m/1.5m, 4h..1d = 24m/3m/3m, 3d ~ 2.5y/4m/4m, 1w = 3y/6m/6m.
WALK_FORWARD = {
    "1h": (8760, 1080, 1080),
    "4h": (4380, 540, 540),
    "12h": (1460, 180, 180),
    "1d": (730, 90, 90),
    "3d": (300, 40, 40),
    "1w": (156, 26, 26),
}

CLASSES = ["DOWN", "NEUTRAL", "UP"]  # class index 0, 1, 2

DEFAULT_SIGNAL_WEIGHTS = {
    "trend": 0.20, "momentum": 0.15, "volume": 0.10, "structure": 0.15,
    "ml": 0.20, "volatility": 0.05, "liquidity": 0.05, "htf": 0.10,
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    exchange: str = field(default_factory=lambda: _env("EXCHANGE", "binance"))
    derivatives_exchange: str = field(default_factory=lambda: _env("DERIVATIVES_EXCHANGE", "binanceusdm"))
    symbols: list[str] = field(
        default_factory=lambda: [s.strip() for s in _env("SYMBOLS", ",".join(DEFAULT_SYMBOLS)).split(",") if s.strip()])
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./data/crypto_ai.db"))
    model_dir: str = field(default_factory=lambda: _env("MODEL_DIR", "./data/models"))
    csv_dir: str = field(default_factory=lambda: _env("CSV_DIR", "./data/csv"))
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173").split(",")])

    # refresh cadences (seconds). Prediction refresh is independent from retraining.
    forecast_refresh_s: int = field(default_factory=lambda: int(_f("FORECAST_REFRESH_S", 300)))
    candle_refresh_s: int = field(default_factory=lambda: int(_f("CANDLE_REFRESH_S", 60)))
    retrain_interval_h: float = field(default_factory=lambda: _f("RETRAIN_INTERVAL_H", 168))
    enable_background_jobs: bool = field(default_factory=lambda: _b("ENABLE_BACKGROUND_JOBS", True))
    enable_websocket_feed: bool = field(default_factory=lambda: _b("ENABLE_WEBSOCKET_FEED", True))
    enable_deep_models: bool = field(default_factory=lambda: _b("ENABLE_DEEP_MODELS", False))
    enable_external_context: bool = field(default_factory=lambda: _b("ENABLE_EXTERNAL_CONTEXT", True))

    # modelling
    neutral_band_sigma: float = field(default_factory=lambda: _f("NEUTRAL_BAND_SIGMA", 0.25))
    min_train_samples: int = field(default_factory=lambda: int(_f("MIN_TRAIN_SAMPLES", 150)))
    min_oos_for_edge: int = field(default_factory=lambda: int(_f("MIN_OOS_FOR_EDGE", 300)))
    edge_alpha: float = field(default_factory=lambda: _f("EDGE_ALPHA", 0.01))
    require_edge_for_ml: bool = field(default_factory=lambda: _b("REQUIRE_EDGE_FOR_ML", True))
    require_edge_for_trade: bool = field(default_factory=lambda: _b("REQUIRE_EDGE_FOR_TRADE", False))

    # signal policy
    min_confidence: float = field(default_factory=lambda: _f("MIN_CONFIDENCE", 0.45))
    min_model_agreement: float = field(default_factory=lambda: _f("MIN_MODEL_AGREEMENT", 0.60))
    min_risk_reward: float = field(default_factory=lambda: _f("MIN_RISK_REWARD", 1.5))

    # costs (defaults for backtests / paper trading)
    fee_rate: float = field(default_factory=lambda: _f("FEE_RATE", 0.001))
    slippage_bps: float = field(default_factory=lambda: _f("SLIPPAGE_BPS", 2.0))
    spread_bps: float = field(default_factory=lambda: _f("SPREAD_BPS", 1.0))

    def ensure_dirs(self) -> None:
        Path(self.model_dir).mkdir(parents=True, exist_ok=True)
        Path(self.csv_dir).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
