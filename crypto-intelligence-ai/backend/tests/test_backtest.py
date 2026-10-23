"""Backtest engine: execution timing, costs, stops and statistics."""
import numpy as np

from app.backtest import strategies as S
from app.backtest.benchmarks import vector_returns
from app.backtest.engine import BacktestConfig, run_backtest
from app.backtest.stats import equity_stats, max_drawdown
from app.data.base import to_frame
from app.features.dataset import build_frame
from tests.helpers import synthetic_candles

FREE = dict(fee_rate=0.0, slippage_bps=0.0, spread_bps=0.0, stop_atr=None)


def _flat_then_jump():
    """10 flat bars at 100, a gap to 110 at bar 10's open, then flat at 110."""
    rows = [[i * 3_600_000, 100, 100.5, 99.5, 100, 10] for i in range(10)]
    rows += [[i * 3_600_000, 110, 110.5, 109.5, 110, 10] for i in range(10, 20)]
    return to_frame(rows)


def test_signal_executes_on_next_bar_open_not_same_bar():
    df = _flat_then_jump()
    sig = np.zeros(20)
    sig[9] = 1    # decided at the close of bar 9 (price 100) -> filled at bar 10's OPEN (110): the gap is not captured
    r = run_backtest(df, sig, BacktestConfig(**FREE), "1h")
    assert len(r["trades"]) == 1 and r["trades"][0]["entry"] == 110.0
    assert abs(r["summary"]["net_return"]) < 1e-12
    sig = np.zeros(20)
    sig[8:] = 1   # decided one bar earlier -> filled at bar 9's open (100) -> earns the move
    r = run_backtest(df, sig, BacktestConfig(**FREE), "1h")
    assert abs(r["summary"]["net_return"] - 0.10) < 1e-9


def test_buy_and_hold_matches_price_return_without_costs():
    df = synthetic_candles(500, "4h")
    r = run_backtest(df, np.ones(len(df)), BacktestConfig(**FREE), "4h")
    expected = df["close"].iloc[-1] / df["open"].iloc[1] - 1
    assert abs(r["summary"]["net_return"] - expected) < 1e-9
    assert abs(r["summary"]["gross_return"] - r["summary"]["net_return"]) < 1e-12


def test_costs_reduce_returns_and_reconcile():
    df = synthetic_candles(800, "4h")
    fr = build_frame(df, "4h")
    sig = S.sma_cross(fr.ind, 5, 20)
    free = run_backtest(df, sig, BacktestConfig(**FREE), "4h")["summary"]
    cost = run_backtest(df, sig, BacktestConfig(fee_rate=0.001, slippage_bps=5, spread_bps=2, stop_atr=None), "4h")["summary"]
    assert cost["trades"] == free["trades"] > 5
    assert cost["net_return"] < free["net_return"]
    assert cost["fees"] > 0 and cost["slippage"] > 0
    # gross = net + fees + slippage (in money), exactly
    cap = 10_000.0
    assert abs(cap * (1 + cost["gross_return"]) - (cost["final_equity"] + cost["fees"] + cost["slippage"])) < 1e-6
    assert cost["gross_return"] > cost["net_return"]


def test_stop_loss_caps_the_loss_and_fills_pessimistically():
    rows = [[i * 3_600_000, 100, 100.5, 99.5, 100, 10] for i in range(5)]
    rows += [[5 * 3_600_000, 100, 103, 94, 95, 10]]            # touches both a 2% target and a 2% stop
    rows += [[i * 3_600_000, 95, 95.5, 94.5, 95, 10] for i in range(6, 10)]
    df = to_frame(rows)
    sig = np.ones(10)
    cfg = BacktestConfig(fee_rate=0.0, slippage_bps=0.0, spread_bps=0.0, stop_atr=None, stop_pct=0.02, take_profit_pct=0.02)
    r = run_backtest(df, sig, cfg, "1h")
    t = r["trades"][0]
    assert t["reason"] == "stop" and abs(t["exit"] - 98.0) < 1e-9          # stop assumed before target
    assert abs(r["summary"]["net_return"] + 0.02) < 1e-9
    assert len(r["trades"]) == 1                                             # no instant re-entry on the same signal


def test_risk_based_sizing_loses_the_configured_fraction_at_the_stop():
    rows = [[i * 3_600_000, 100, 100.5, 99.5, 100, 10] for i in range(5)]
    rows += [[5 * 3_600_000, 100, 100, 90, 91, 10]] + [[i * 3_600_000, 91, 91.5, 90.5, 91, 10] for i in range(6, 9)]
    cfg = BacktestConfig(fee_rate=0.0, slippage_bps=0.0, spread_bps=0.0, stop_atr=None, stop_pct=0.05, sizing="risk", risk_per_trade=0.01)
    r = run_backtest(to_frame(rows), np.ones(9), cfg, "1h")
    assert abs(r["summary"]["net_return"] + 0.01) < 1e-9


def test_long_only_ignores_short_signals_unless_allowed():
    df = synthetic_candles(300, "4h")
    sig = -np.ones(len(df))
    assert run_backtest(df, sig, BacktestConfig(**FREE), "4h")["summary"]["trades"] == 0
    short = run_backtest(df, sig, BacktestConfig(**FREE, allow_short=True), "4h")["summary"]
    assert short["trades"] == 1
    assert abs(short["net_return"] - (1 - df["close"].iloc[-1] / df["open"].iloc[1])) < 1e-9


def test_vector_returns_charge_turnover_and_use_prior_position():
    close = np.array([100.0, 110.0, 99.0, 99.0])
    pos = np.array([1.0, 0.0, 1.0, 1.0])
    r = vector_returns(pos, close, cost=0.01)
    assert np.allclose(r, [0.10 - 0.01, 0.0 - 0.01, 0.0 - 0.01])


def test_statistics():
    eq = np.array([100.0, 110.0, 99.0, 120.0])
    assert abs(max_drawdown(eq) - (99 / 110 - 1)) < 1e-12
    st = equity_stats(eq, "1d")
    assert abs(st["net_return"] - 0.2) < 1e-12 and st["sharpe"] is not None and st["max_drawdown"] < 0


def test_strategy_signals_are_causal():
    df = synthetic_candles(900, "4h", seed=9)
    full = build_frame(df, "4h").ind
    part = build_frame(df.iloc[:600], "4h").ind
    for name in ("sma_cross", "rsi_simple", "prev_candle", "technical"):
        fn = S.get_strategy(name)
        assert np.array_equal(fn(full)[:600], fn(part)), f"{name} changes its past signals when given future data"
