"""User-run backtests: any strategy vs Buy & Hold, random direction and a simple moving-average strategy,
all on the same bars with the same fees, spread and slippage."""
from __future__ import annotations

from typing import Any

import numpy as np

from ..backtest import strategies as S
from ..backtest.engine import BacktestConfig, run_backtest
from ..config import settings
from ..db import dumps, loads, new_id, now_ms
from ..features.dataset import InsufficientData
from ..ml import trainer
from .runtime import Runtime

RANDOM_RUNS = 30
CFG_KEYS = ("initial_capital", "fee_rate", "slippage_bps", "spread_bps", "sizing", "fraction", "risk_per_trade",
            "stop_atr", "take_profit_atr", "stop_pct", "take_profit_pct", "allow_short", "max_hold_bars")


def _config(p: dict[str, Any]) -> BacktestConfig:
    base = {"fee_rate": settings.fee_rate, "slippage_bps": settings.slippage_bps, "spread_bps": settings.spread_bps}
    base.update({k: p[k] for k in CFG_KEYS if k in p and p[k] is not None and p[k] != ""})
    for k in ("stop_atr", "take_profit_atr", "stop_pct", "take_profit_pct", "max_hold_bars"):
        if k in p and (p[k] is None or p[k] == "" or p[k] == 0):
            base[k] = None
    return BacktestConfig(**base)


def run(rt: Runtime, params: dict[str, Any]) -> dict[str, Any]:
    symbol, tf, strategy = params["symbol"], params.get("timeframe", "4h"), params.get("strategy", "technical")
    bid = new_id()
    try:
        result = _run(rt, symbol, tf, strategy, params)
        status = "done"
    except (InsufficientData, KeyError, ValueError) as exc:
        result, status = {"error": str(exc)}, "failed"
    rt.db.execute("INSERT INTO backtests (id, created_at, status, params, result) VALUES (?, ?, ?, ?, ?)",
                  (bid, now_ms(), status, dumps(params), dumps(result)))
    return {"id": bid, "status": status, "params": params, "result": result}


def _run(rt: Runtime, symbol: str, tf: str, strategy: str, params: dict[str, Any]) -> dict[str, Any]:
    fr = rt.frame(symbol, tf)
    ind = fr.ind
    ts = ind["ts"].to_numpy()
    cfg = _config(params)
    sp = {**S.STRATEGIES.get(strategy, {}).get("params", {}), **(params.get("strategy_params") or {})}
    notes: list[str] = []
    timeline = None
    start = int(params.get("start") or ts[0])
    end = int(params.get("end") or ts[-1])
    if strategy == "ai_ensemble":
        bundle = trainer.load_bundle(symbol, tf, rt.db)
        if bundle is None:
            raise InsufficientData(f"no trained model for {symbol} {tf}")
        oos = bundle["oos"]
        P = np.full((len(ts), 3), np.nan)
        pos = np.searchsorted(ts, oos["ts"])
        ok = (pos < len(ts)) & (ts[np.minimum(pos, len(ts) - 1)] == oos["ts"])
        P[pos[ok]] = oos["P_ens"][ok]
        signal = S.from_probabilities(P, float(sp.get("min_prob", 0.40)))
        o_start, o_end = int(oos["ts"][0]), int(oos["ts"][-1])
        if start < o_start or end > o_end:
            notes.append("Period clipped to the walk-forward out-of-sample range: the AI strategy is only ever "
                         "evaluated on bars its models had not seen.")
        start, end = max(start, o_start), min(end, o_end)
        timeline = {"folds": bundle["folds"], "sizes": bundle["sizes"], "model_version": bundle["version"]}
        notes.append(bundle["edge"]["verdict"])
    else:
        signal = S.get_strategy(strategy)(ind, **sp)
    m = (ts >= start) & (ts <= end)
    if m.sum() < 30:
        raise InsufficientData(f"only {int(m.sum())} candles in the selected period")
    lo, hi = int(np.argmax(m)), int(len(m) - np.argmax(m[::-1]))
    df, atr = fr.df.iloc[lo:hi], ind["atr"].to_numpy()[lo:hi]
    main = run_backtest(df, signal[lo:hi], cfg, tf, atr)
    bench = {}
    for name in ("buy_hold", "sma_cross"):
        r = run_backtest(df, S.get_strategy(name)(ind)[lo:hi], cfg, tf, atr)
        bench[name] = {"label": S.STRATEGIES[name]["label"], "summary": r["summary"], "equity_curve": r["equity_curve"]}
    rand = [run_backtest(df, S.random_direction(ind, seed=s)[lo:hi], cfg, tf, atr)["summary"]["net_return"]
            for s in range(RANDOM_RUNS)]
    bench["random"] = {"label": f"Random direction ({RANDOM_RUNS} runs)", "summary": {
        "net_return": float(np.median(rand)), "p05": float(np.quantile(rand, 0.05)), "p95": float(np.quantile(rand, 0.95)),
        "share_beaten": float(np.mean(np.array(rand) < main["summary"]["net_return"]))}}
    # stability: the same test split into four consecutive segments
    eq = np.array([cfg.initial_capital] + [p["equity"] for p in main["equity_curve"]])
    cuts = np.linspace(0, len(eq) - 1, 5).astype(int)
    segments = [{"segment": i + 1, "net_return": float(eq[cuts[i + 1]] / eq[cuts[i]] - 1)} for i in range(4)]
    net = main["summary"]["net_return"]
    verdict = "Beats Buy & Hold, SMA crossover and the median random run after costs" if (
        net > bench["buy_hold"]["summary"]["net_return"] and net > bench["sma_cross"]["summary"]["net_return"]
        and net > bench["random"]["summary"]["net_return"]) else "Does not beat every benchmark after costs"
    if main["summary"]["trades"] == 0:
        verdict = "No trades were taken in this period, so there is nothing to compare"
    notes.append("Results are net of fees, spread and slippage. One historical path; past performance does not "
                 "predict future returns.")
    return {"symbol": symbol, "timeframe": tf, "strategy": strategy, "strategy_label": S.STRATEGIES[strategy]["label"],
            "strategy_params": sp, **main, "benchmarks": bench, "segments": segments, "verdict": verdict,
            "walk_forward": timeline, "notes": notes}


def get(rt: Runtime, backtest_id: str) -> dict[str, Any] | None:
    row = rt.db.one("SELECT * FROM backtests WHERE id = ?", (backtest_id,))
    if not row:
        return None
    return {"id": row["id"], "created_at": row["created_at"], "status": row["status"],
            "params": loads(row["params"], {}), "result": loads(row["result"], {})}


def history(rt: Runtime, limit: int = 30) -> list[dict[str, Any]]:
    out = []
    for row in rt.db.query("SELECT id, created_at, status, params, result FROM backtests ORDER BY created_at DESC LIMIT ?",
                           (limit,)):
        p, r = loads(row["params"], {}), loads(row["result"], {})
        out.append({"id": row["id"], "created_at": row["created_at"], "status": row["status"], "symbol": p.get("symbol"),
                    "timeframe": p.get("timeframe"), "strategy": p.get("strategy"),
                    "net_return": (r.get("summary") or {}).get("net_return"), "error": r.get("error")})
    return out
