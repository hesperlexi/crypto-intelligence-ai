"""Per-asset analysis: assembles regime, multi-timeframe view, model forecast, signal, trade plan and risk
into the structured output the API returns. Every number originates in an engine, a model or the database."""
from __future__ import annotations

import copy
import json
import os

import time
from typing import Any

import numpy as np

from ..backtest.benchmarks import NO_EDGE
from ..config import HORIZONS, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, settings
from ..data.base import tf_ms
from ..data.quality import check_candles
from ..engine import mtf as mtf_engine
from ..engine.commentary import build_commentary
from ..engine.regime import describe_regime
from ..engine.risk import position_size
from ..engine.setup import build_setup
from ..engine.signal import build_signal
from ..features.dataset import InsufficientData
from ..features.liquidity import order_book_metrics
from ..features.structure import fib_levels, liquidity_zones, sr_zones, supply_demand_zones
from ..features.volatility import vol_state_name
from ..ml import direction as dirview, trainer
from . import tracking
from .runtime import Runtime, ttl_get
from ..redact import error_text

TRADE_DECISIONS = ("BUY", "BUY ON PULLBACK", "SELL")
# v2.3: a trade is only worth taking when target 1 (= 1R) clearly beats the cost of getting in and out. Futures:
# 0.05 % taker fee + slippage/spread per side; target 1 must be at least COST_MULT x the round trip.
COST_MULT = 3.0
ONE_CALL_TFS = ("15m",)
# timeframes whose trade calls are paused (owner decision 30 Oct 2026: 15m lost money on unseen data, -0.17R per trade);
# v2.32 (owner, 14 Nov 2026): Binance bStocks (tokenized shares) not tradable on MEXC / most accounts: no new calls,
# removed from the watchlist once nothing runs on them (worker.retire_coins, flag RETIRE_FLAG)
# v2.69 (owner, 22 Nov 2026): watch-only coins - the call is worked out and shown for study (`watch`), but it is never
# published as a signal, traded by bots / Hesper / auto-trade, or counted in the record; followed privately in
# `rejected_signals` (flag WATCH ONLY) so the admin can see how its calls would have done
WATCH_ONLY_COINS = tuple(c.strip() for c in os.environ.get("WATCH_ONLY_COINS", "XAG/USDT").split(",") if c.strip())
RETIRING_COINS = tuple(c.strip() for c in os.environ.get("RETIRING_COINS", "MSTRB/USDT,SPCXB/USDT").split(",") if c.strip())
RETIRE_FLAG = "retire_bstocks_v232"
# the analysis, chart and forecast still run, only no trade call is issued. Env PAUSED_TFS, comma separated ("" = none).
# v2.8 (owner decision 31 Oct 2026, from the time-limit / timeframe study `research_horizon.py`): 1d and 3d paused
# (they lost after costs on unseen calls); 1h grade A only; 15m demo bots only (grade A, never on the public list)
def _tfs(name: str, default: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in os.environ.get(name, default).split(",") if t.strip())


PAUSED_TFS = _tfs("PAUSED_TFS", "")      # v2.10 (1 Nov 2026): 1d / 3d moved to demo-only
# v2.11 (2 Nov 2026): 15m public, grade A only; v2.12 (2 Nov 2026): 1d / 3d public too, grade A only
A_ONLY_TFS = _tfs("A_ONLY_TFS", "15m,1h,1d,3d")   # v2.42: 15m back to grade A only (owner, 16 Nov 2026)
# demo-only timeframes: the public decision is NO TRADE ("DEMO BOTS ONLY"); the call the demo bots may take is in `demo`
DEMO_ONLY_TFS = _tfs("DEMO_ONLY_TFS", "1d")    # v2.64 (21 Nov 2026): 1d demo-only again (replay −0.10 to −0.15R in every cap variant; weak models)
# v2.64 (21 Nov 2026, live check guard15-live.json): since 16 Nov the AI trade filters blocked 67 of 67 15m calls that
# reached them, 72 % won, +0.38R avg net. On these timeframes neither trade filter blocks; the scores are still kept.
FILTER_OFF_TFS = _tfs("FILTER_OFF_TFS", "15m")
FILTER_OFF_MIN_CLOSED = 10      # safety net: after this many closed calls the filter would have blocked ...
FILTER_OFF_CHECK_S = 600


RISK_VETO = os.environ.get("RISK_VETO", "1") != "0"


def _risk_shadow(rt: Any, symbol: str, timeframe: str | None = None) -> dict[str, Any]:
    """v2.65 capital-protection assessment (services/risk_shadow.py); `would_block` = the veto's verdict.
    V3.2 (audit R-01): an error no longer returns None (= no veto); it returns an assessment marked unavailable."""
    try:
        from . import risk_shadow
        return risk_shadow.assess(rt, symbol, timeframe=timeframe)
    except Exception as exc:
        try:
            rt.record_error(f"capital protection {symbol} {timeframe}", exc)
        except Exception:
            pass
        why = f"assessment failed ({type(exc).__name__}: {exc})"[:160]
        return {"would_block": False, "reason": None, "unavailable": ["assessment"], "unavailable_reason": why}


def _guard_unavailable(rt: Any, gate: str, label: str, symbol: str, timeframe: str, detail: str) -> str:
    """V3.2 (audit R-01): a new-entry guard that cannot give a verdict. Logged, listed on Health, NO TRADE reason."""
    try:
        rt.record_error(f"{gate} {symbol} {timeframe}", RuntimeError(detail))
    except Exception:
        pass
    gate_failure(rt, gate, symbol, timeframe, detail)
    return f"the {label} could not be checked ({detail}) - fail-safe: no new entry"


# V3.2 (Fable 5.2 audit R-02): the trade filters and the runner model run in SHADOW until validated - they record what
# they would have done (payload `filter_bypassed` / `filter_shadow` / `runner_shadow`, private) and do not block or change
# exits. Validated = the bundle's live threshold came from embargoed out-of-fold scores AND its kept share on the
# unseen last fold is within 10 points of keep_fraction (ml/oof.py). Enforcement then still needs the owner's switch
# (TRADE_FILTER_ENFORCE=1 / RUNNER_MODEL_ENFORCE=1) after the live kept-share check (`filter_shadow_stats`, 2 weeks).
# The v2.64 safety net stays: once >= 10 shadowed calls the filters would have blocked closed with an average net R
# below 0, the filters block again on that timeframe (`filter_off_revoked|TF`).
FILTER_ENFORCE = os.environ.get("TRADE_FILTER_ENFORCE", "0") == "1"
RUNNER_ENFORCE = os.environ.get("RUNNER_MODEL_ENFORCE", "0") == "1"
SHADOW_STATS_KEEP_MS = 14 * 86_400_000
SHADOW_STATS_MAX = 3000


def filter_bypass(rt: Any, timeframe: str, view: dict[str, Any] | None) -> bool:
    """True = the trade filter only records (shadow); False = it may block this live call."""
    if filter_off(rt, timeframe):                 # v2.64 FILTER_OFF_TFS rule, unchanged
        return True
    if FILTER_ENFORCE and (view or {}).get("validated"):
        return False
    return filter_off(rt, timeframe, any_tf=True)


def runner_enforced(view: dict[str, Any] | None) -> bool:
    return bool(RUNNER_ENFORCE and (view or {}).get("validated"))


def shadow_stat(rt: Any, name: str, timeframe: str, symbol: str, bar_ts: int, score: float, threshold: float,
                keep_fraction: float | None) -> None:
    """Live kept-share log of a shadowed model (one row per coin and candle, last 14 days): Health / the 2-week check
    compare the observed kept share with keep_fraction."""
    try:
        key = f"filter_shadow_stats|{name}|{timeframe}"
        now = int(time.time() * 1000)
        cur = rt.db.get_setting(key, None) or {}
        rows = [r for r in (cur.get("rows") or []) if now - int(r[1]) < SHADOW_STATS_KEEP_MS]
        rid = f"{symbol}|{int(bar_ts)}"
        if any(r[0] == rid for r in rows):
            return
        rows.append([rid, now, 1 if score >= threshold else 0])
        rows = rows[-SHADOW_STATS_MAX:]
        kept = sum(r[2] for r in rows)
        rt.db.set_setting(key, {"rows": rows, "n": len(rows), "kept_share": round(kept / len(rows), 4),
                                "keep_fraction": keep_fraction, "at": now})
    except Exception:
        pass


def filter_off(rt: Any, timeframe: str, any_tf: bool = False) -> bool:
    """v2.64 safety net (owner: "we don't need bad results"): the trade filters stay off on a FILTER_OFF_TFS timeframe only
    while the published calls they would have blocked are not losing. Once >= FILTER_OFF_MIN_CLOSED of them closed with an
    average net R below 0, the filters block again on that timeframe for good (setting `filter_off_revoked|TF`, shown on
    Health; clear it by hand to retry). Checked at most every FILTER_OFF_CHECK_S."""
    if timeframe not in FILTER_OFF_TFS and not any_tf:
        return False
    db = rt.db
    if db.get_setting(f"filter_off_revoked|{timeframe}", None):
        return False
    key = f"filter_off_since|{timeframe}"
    since = db.get_setting(key, None)
    now = int(time.time() * 1000)
    if not since:
        db.set_setting(key, now)
        return True
    chk = db.get_setting(f"filter_off_check|{timeframe}", None) or {}
    if now - int(chk.get("at") or 0) < FILTER_OFF_CHECK_S * 1000:
        return True
    from . import tracking
    closed = tuple(tracking.CLOSED_STATUSES)
    rows = db.query(f"SELECT * FROM signals WHERE timeframe = ? AND created_at >= ? AND status IN ({','.join('?' * len(closed))}) "
                    "AND payload LIKE '%\"filter_bypassed\": true%'", (timeframe, int(since), *closed))
    rs = []
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED":
            continue
        net, e, st = tracking.net_pct(r), r.get("entry"), r.get("stop")
        if net is not None and e and st:
            risk = abs(float(e) - float(st)) / float(e) * 100
            if risk > 0:
                rs.append(net / risk)
    avg = sum(rs) / len(rs) if rs else None
    db.set_setting(f"filter_off_check|{timeframe}", {"at": now, "closed": len(rs), "avg_r": avg})
    if len(rs) >= FILTER_OFF_MIN_CLOSED and avg is not None and avg < 0:
        db.set_setting(f"filter_off_revoked|{timeframe}", {"at": now, "closed": len(rs), "avg_r": avg})
        return False
    return True

# fields kept inside the engine only (bots read them from analyze() directly); stripped from published views
PRIVATE_FIELDS = ("demo", "risk_shadow", "filter_bypassed", "filter_shadow", "runner_shadow")   # v2.65: shadow fields stay engine-side


def watch_gate(symbol: str, decision: str, grade: str | None) -> tuple[dict[str, Any] | None, tuple[str, str | None, str]]:
    """v2.69: a trade call on a watch-only coin -> (the call kept for display, (NO TRADE, None, reason));
    anything else -> (None, unchanged)."""
    if decision in TRADE_DECISIONS and symbol in WATCH_ONLY_COINS:
        return ({"decision": decision, "grade": grade},
                ("NO TRADE", None, "watch only: this call is shown for study - not traded by the bots and not counted in the results"))
    return None, (decision, grade, "")


def public_view(a: dict[str, Any]) -> dict[str, Any]:
    """The analysis as members may see it: without the demo bots' held-back call (`demo`)."""
    return {k: v for k, v in a.items() if k not in PRIVATE_FIELDS} if isinstance(a, dict) else a


def round_trip_cost(futures: bool = True) -> float:
    """Fraction of price paid to enter and exit once (fees + slippage + half spread, both sides)."""
    from ..engine.futures import FUTURES_FEE_RATE
    side = (FUTURES_FEE_RATE if futures else settings.fee_rate) + (settings.slippage_bps + settings.spread_bps / 2) / 1e4
    return 2 * side


def beats_costs(entry: float, stop: float, futures: bool = True, mult: float = COST_MULT) -> bool:
    return bool(entry and stop) and abs(entry - stop) / entry >= mult * round_trip_cost(futures)


def model_forecast(rt: Runtime, symbol: str, timeframe: str, as_of: int | None = None,
                   bundle: dict[str, Any] | None = None, explain: bool = False,
                   multipliers: dict[str, float] | None = None) -> dict[str, Any]:
    """Forecast for the next bar of `timeframe` from that timeframe's own model.
    v3.1 (25 Nov 2026, "loops" too long): a live forecast is computed once per engine cycle and coin / timeframe and
    reused (each coin's six analyses asked for the same six horizon forecasts again: ~1,460 model runs a cycle instead
    of ~210). Each cycle is a fresh process and the candles do not change inside it, so the result is identical."""
    if as_of is not None or bundle is not None or multipliers is not None:
        return _model_forecast(rt, symbol, timeframe, as_of, bundle, explain, multipliers)
    memo = rt.__dict__.setdefault("_fc_memo", {})
    b = trainer.load_bundle(symbol, timeframe, rt.db) if timeframe in MODEL_TIMEFRAMES else None
    key = (symbol, timeframe, explain, (b or {}).get("created_at"), (b or {}).get("version") or id(b))
    if key not in memo:
        memo[key] = _model_forecast(rt, symbol, timeframe, None, b, explain, None) if b is not None \
            else _model_forecast(rt, symbol, timeframe)
        if memo[key].get("available"):
            _fc_store_put(rt, symbol, timeframe, memo[key])
    return copy.deepcopy(memo[key])


# v3.1: the slow timeframes' forecasts only change when a new candle closes (or the model is retrained), yet every
# cycle loaded their models again just to show the 12H / 24H / 3D horizons on the quicker timeframes' pages. The last
# live forecast is kept per coin / timeframe with its candle and model version, and reused for those horizon rows only
# while both are unchanged (trade decisions always use a forecast made in the current cycle).
HORIZON_REUSE_TFS = ("12h", "1d", "3d")


def _fc_store_table(db: Any) -> None:
    db.execute("CREATE TABLE IF NOT EXISTS fc_store (symbol TEXT NOT NULL, timeframe TEXT NOT NULL, bar_ts INTEGER, "
               "model_version TEXT, at INTEGER, json TEXT, PRIMARY KEY (symbol, timeframe))")


def _fc_store_put(rt: Runtime, symbol: str, timeframe: str, fc: dict[str, Any]) -> None:
    if timeframe not in HORIZON_REUSE_TFS:
        return
    try:
        _fc_store_table(rt.db)
        keep = {k: fc.get(k) for k in ("available", "expected_return", "distribution", "probabilities", "predicted",
                                        "confidence", "edge_confirmed", "bar_ts", "model_version")}
        rt.db.execute("INSERT INTO fc_store (symbol, timeframe, bar_ts, model_version, at, json) VALUES (?, ?, ?, ?, ?, ?) "
                      "ON CONFLICT (symbol, timeframe) DO UPDATE SET bar_ts = excluded.bar_ts, model_version = "
                      "excluded.model_version, at = excluded.at, json = excluded.json",
                      (symbol, timeframe, int(fc.get("bar_ts") or 0), str(fc.get("model_version")), int(time.time() * 1000),
                       json.dumps(keep, default=float)))
    except Exception as exc:                         # a cache never breaks an analysis
        rt.record_error("forecast store", exc)


def _fc_store_get(rt: Runtime, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """The stored forecast when its candle is still the latest closed one and its model is still the active one."""
    if timeframe not in HORIZON_REUSE_TFS:
        return None
    try:
        _fc_store_table(rt.db)
        row = rt.db.one("SELECT bar_ts, model_version, json FROM fc_store WHERE symbol = ? AND timeframe = ?", (symbol, timeframe))
        if not row:
            return None
        av = trainer.active_version(symbol, timeframe, rt.db)
        df = rt.candles(symbol, timeframe)
        if av is None or df is None or not len(df) or str(av.get("id")) != str(row["model_version"]) \
                or int(df["ts"].iloc[-1]) != int(row["bar_ts"]):
            return None
        return json.loads(row["json"])
    except Exception:
        return None


def _model_forecast(rt: Runtime, symbol: str, timeframe: str, as_of: int | None = None,
                    bundle: dict[str, Any] | None = None, explain: bool = False,
                    multipliers: dict[str, float] | None = None) -> dict[str, Any]:
    if timeframe not in MODEL_TIMEFRAMES:
        return {"available": False, "status": "NOT MODELLED",
                "reason": f"no model is trained on {timeframe}; forecasts exist for {', '.join(MODEL_TIMEFRAMES)}"}
    if as_of is not None and bundle is None:
        # a historical replay may only use a model trained on data before the replay date
        return {"available": False, "status": "MODEL NOT TRAINED",
                "reason": "no model trained before the replay date was supplied"}
    bundle = bundle or trainer.load_bundle(symbol, timeframe, rt.db)
    if bundle is None:
        st = rt.training.get(f"{symbol}|{timeframe}", {})
        reason = st.get("error") or ("training in progress" if st.get("state") == "running"
                                     else "model not trained yet for this timeframe")
        return {"available": False, "status": "INSUFFICIENT DATA" if st.get("insufficient") else "MODEL NOT TRAINED",
                "reason": reason}
    try:
        ds = rt.dataset(symbol, timeframe, bundle["uses_btc"], as_of, htf_tf=bundle.get("uses_htf"))
        # replays: none, unless the caller supplies the weights as they stood then (scalping rebuild)
        mult = tracking.live_multipliers(rt.db, bundle) if as_of is None else dict(multipliers or {})
        fc = trainer.predict(bundle, ds, multipliers=mult)
    except InsufficientData as exc:
        return {"available": False, "status": "INSUFFICIENT DATA", "reason": str(exc)}
    except Exception as exc:  # model failure: surface it, never substitute a made-up forecast
        rt.record_error(f"forecast {symbol} {timeframe}", exc)
        return {"available": False, "status": "MODEL ERROR", "reason": error_text(exc, 200)}
    # v2.17 switches (default on = unchanged behaviour): TRADE_FILTER / TARGET_MODEL / RUNNER_MODEL = 0 turn the per-model
    # trade filter, AI target lifts and runner model off. Off = None: no filter, plain historical base rates in
    # setup.pick, standard 50/25/25 exits.
    fc["trade_filter"] = fc["target_lift"] = fc["runner"] = None
    x_row = None
    if settings.trade_filter_v1:
        try:
            from ..ml import trade_filter
            x_row = ds.X[bundle["feature_names"]].to_numpy(float)[-1]
            fc["trade_filter"] = trade_filter.score(bundle.get("trade_filter"), x_row, fc["probabilities"])
        except Exception as exc:
            rt.record_error(f"trade filter {symbol} {timeframe}", exc)
            fc["trade_filter"] = None
            fc["trade_filter_error"] = f"{type(exc).__name__}: {exc}"[:160]      # v2.13: fail closed (analyze)
    if (settings.target_model or settings.runner_model) and x_row is None:
        try:
            x_row = ds.X[bundle["feature_names"]].to_numpy(float)[-1]
        except Exception:
            pass
    if settings.target_model:
        try:
            from ..ml import target_model
            fc["target_lift"] = target_model.lifts(bundle.get("target_model"), x_row, fc["probabilities"])
        except Exception:
            fc["target_lift"] = None
    if settings.runner_model:
        try:
            from ..ml import runner_model
            fc["runner"] = runner_model.score(bundle.get("runner_model"), x_row, fc["probabilities"])
        except Exception:
            fc["runner"] = None
    edge = bundle["edge"]
    fc.update({
        "available": True, "status": "OK", "timeframe": timeframe,
        "edge_confirmed": bool(edge["edge_confirmed"]), "edge_verdict": edge["verdict"],
        "edge_failed_checks": edge["failed_checks"], "trained_at": bundle["created_at"],
        "model_age_h": (time.time() * 1000 - bundle["created_at"]) / 3.6e6,
        "interval_coverage": bundle["interval_coverage"], "live_downweighted": sorted(mult),
        "best_model": bundle["best_model"]["name"] if bundle["best_model"]["supported"] else None,
    })
    if explain:
        try:
            fc["explanation"] = trainer.explain_prediction(bundle, ds)
        except Exception as exc:
            rt.record_error(f"explain {symbol} {timeframe}", exc)
            fc["explanation"] = None
    return fc


def horizon_forecasts(rt: Runtime, symbol: str, as_of: int | None = None) -> list[dict[str, Any]]:
    """1H / 4H / 12H / 24H / 3D / 7D - each from the model of the matching timeframe, never extrapolated."""
    out = []
    memo = rt.__dict__.get("_fc_memo", {}) if as_of is None else {}
    for label, tf in HORIZONS.items():
        fc = None
        if as_of is None and not any(k[0] == symbol and k[1] == tf for k in memo):
            fc = _fc_store_get(rt, symbol, tf)
        fc = fc or model_forecast(rt, symbol, tf, as_of)
        row: dict[str, Any] = {"horizon": label, "timeframe": tf, "available": fc["available"]}
        if fc["available"]:
            dist = fc.get("distribution") or {}
            row.update({
                "expected_return": fc["expected_return"], "expected_price": dist.get("expected_price"),
                "p_up": fc["probabilities"]["up"], "p_down": fc["probabilities"]["down"],
                "p_neutral": fc["probabilities"]["neutral"], "predicted": fc["predicted"],
                "interval80": (dist.get("intervals") or {}).get("80"),
                "confidence": fc["confidence"]["confidence"], "edge_confirmed": fc["edge_confirmed"],
                "bar_ts": fc["bar_ts"], "model_version": fc["model_version"],
            })
        else:
            row.update({"status": fc["status"], "reason": fc["reason"]})
        out.append(row)
    return out


def _levels(fr: Any, price: float) -> dict[str, Any]:
    last = fr.ind.iloc[-1]
    atr = float(last["atr"]) if np.isfinite(last["atr"]) else float("nan")
    n = len(fr.df)
    zones = sr_zones(fr.swings, price, atr, n)
    return {
        "zones": zones,
        "liquidity": liquidity_zones(fr.df, fr.swings, atr),
        "supply_demand": supply_demand_zones(fr.df, fr.ind["atr"]),
        "fibonacci": fib_levels(fr.swings, n),
        "pivots": {k: (float(last[k]) if np.isfinite(last[k]) else None) for k in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3")},
        "swings": [{"ts": int(fr.df["ts"].iloc[s["pos"]]), "price": s["price"], "kind": s["kind"], "label": s["label"]}
                   for s in fr.swings[-40:]],
    }


def _events(fr: Any, bars: int = 150) -> list[dict[str, Any]]:
    """BOS / CHoCH markers for the chart."""
    tail = fr.ind.iloc[-bars:]
    out = []
    for col, name in (("bos", "BOS"), ("choch", "CHoCH")):
        for ts, v, px in zip(tail["ts"], tail[col], tail["close"]):
            if v:
                out.append({"ts": int(ts), "type": name, "direction": int(v), "price": float(px)})
    return sorted(out, key=lambda e: e["ts"])


def _snapshot(last: Any) -> dict[str, Any]:
    keys = ["rsi", "stoch_k", "stoch_d", "macd", "macd_signal", "macd_hist", "adx", "plus_di", "minus_di", "atr",
            "cci", "willr", "roc", "momentum", "bb_upper", "bb_mid", "bb_lower", "bb_width", "bb_pctb", "vwap",
            "rel_volume", "vol_roc", "obv", "cmf", "mfi", "sma_20", "sma_50", "sma_100", "sma_200", "ema_9",
            "ema_21", "ema_50", "ema_200", "tenkan", "kijun", "span_a", "span_b", "dc_upper", "dc_lower",
            "kc_upper", "kc_lower", "rv", "hv", "vol_pct", "atr_pct", "range_ratio", "buy_pressure", "sigma_bar"]
    return {k: (float(last[k]) if k in last and np.isfinite(last[k]) else None) for k in keys}


def analyze(rt: Runtime, symbol: str, timeframe: str = "4h", as_of: int | None = None,
            bundle: dict[str, Any] | None = None, detail: bool = True, use_cache: bool = True,
            multipliers: dict[str, float] | None = None) -> dict[str, Any]:
    key = (symbol, timeframe, detail)
    if as_of is None and bundle is None and use_cache:
        hit = ttl_get(rt.analysis_cache, key, min(rt.refresh_seconds(), 60))
        if hit is not None:
            return hit
    live = as_of is None
    frames, unavailable = {}, {}
    for tf in dict.fromkeys(MTF_TIMEFRAMES + [timeframe]):
        try:
            frames[tf] = rt.frame(symbol, tf, as_of)
        except InsufficientData as exc:
            unavailable[tf] = str(exc)
    base = {"symbol": symbol, "timeframe": timeframe, "as_of": as_of, "generated_at": int(time.time() * 1000),
            "exchange": rt.exchange}
    if timeframe not in frames:
        out = {**base, "status": "INSUFFICIENT DATA", "reason": unavailable.get(timeframe), "decision": "INSUFFICIENT DATA",
               "signal": {"signal": "INSUFFICIENT DATA"}, "flags": ["INSUFFICIENT DATA"], "price": rt.live_price(symbol),
               "bar_ts": None, "regime": {"regime": "INSUFFICIENT DATA"}, "forecast": {"available": False,
               "status": "INSUFFICIENT DATA", "reason": unavailable.get(timeframe)}}
        return out
    fr = frames[timeframe]
    ind, last = fr.ind, fr.ind.iloc[-1]
    close = float(last["close"])
    # V3.2 (Fable 5.2 audit R-14): the live price carries its source, timestamp and quality. Without a valid ticker the
    # analysis still runs on the last close, but `price_quality` says so and the record refuses a market fill on it
    # (tracking._plan); pending-fill entries (limit / confirm rules) are filled later from candles as before.
    pq = live_quote(rt, symbol, close) if live else None
    price = pq["price"] if pq else close
    regime = describe_regime(ind)
    matrix = mtf_engine.mtf_matrix(frames, unavailable)
    htf = mtf_engine.higher_tf_score(matrix, timeframe)
    vol_state = vol_state_name(last["vol_state"])

    fc = model_forecast(rt, symbol, timeframe, as_of, bundle, explain=detail, multipliers=multipliers)
    flags: list[str] = []
    ml_score = None
    if fc["available"]:
        if fc["edge_confirmed"] or not settings.require_edge_for_ml:
            ml_score = fc["probabilities"]["up"] - fc["probabilities"]["down"]
        if not fc["edge_confirmed"]:
            flags.append(NO_EDGE)
        if fc["model_agreement"] < settings.min_model_agreement:
            flags.append("LOW MODEL AGREEMENT")
    else:
        flags.append(fc["status"])

    book = ttl_get(rt.order_books, symbol, 30) if live else None
    liq = order_book_metrics(book) if book else None
    lean = int(np.sign(last["tech_score"])) if np.isfinite(last["tech_score"]) else 0
    sig = build_signal(ind, timeframe, ml_score, htf, liq["imbalance"] if liq else None, rt.signal_weights(),
                       mtf_engine.alignment_with(matrix, lean), matrix["conflict"])
    direction = sig.get("direction") or 0
    levels = _levels(fr, price)
    lift_of = lambda side: ((fc.get("target_lift") or {}).get("long" if side > 0 else "short") if fc.get("available") else None)  # noqa: E731
    stop_kw = {"stop_mode": "struct", "struct_buffer_atr": settings.struct_stop_buffer_atr} if settings.struct_stops else {}
    # V3.2 (Fable 5.2 audit R-10): target odds over the call's own horizon (the record follows it this long)
    stop_kw["horizon"] = tracking.horizon_for(timeframe)
    setup = build_setup(ind, levels["zones"], direction, settings.min_risk_reward, live_price=price,
                        lift=lift_of(direction), **stop_kw) if direction else None
    if vol_state == "EXTREME":
        flags.append("UNSTABLE MARKET — REDUCED CONFIDENCE")

    # ---- confidence -------------------------------------------------------------------------------------
    # engine v2: the confidence quoted for a long / short call is DIRECTIONAL: how often comparable past
    # out-of-sample calls (same side, similar UP-vs-DOWN margin) got the direction right. The old 3-class figure
    # (exact class incl. "neutral") is kept as class_confidence for reference.
    confidence, conf_detail, dv = None, None, None
    if fc["available"]:
        bun = bundle if bundle is not None else trainer.load_bundle(symbol, timeframe, rt.db)
        dv = dirview.view(fc, bun)
        conf_detail = {"class_confidence": fc["confidence"].get("confidence"), "class_basis": fc["confidence"].get("basis")}
        if dv and dv.get("confidence") is not None:
            confidence = float(dv["confidence"])
            if vol_state == "HIGH":
                confidence = 0.5 + (confidence - 0.5) * 0.85     # shrink towards a coin flip in turbulent markets
                conf_detail["volatility_haircut"] = 0.85
            conf_detail.update({"basis": dv["confidence_detail"].get("basis"), "n": dv["confidence_detail"].get("n"),
                                "ci95": dv["confidence_detail"].get("ci95"), "side": dv["side"], "margin": dv["margin"]})
        conf_detail["applied"] = confidence

    # ---- decision (engine v2) ---------------------------------------------------------------------------
    # A trade needs the technical tilt and the AI to point the same way (or, with no tilt, a model lean that clears
    # its own out-of-sample threshold), a directional confidence above a coin flip and a valid trade plan.
    #   grade A: firm technical tilt + model lean above its threshold + good model agreement + confidence >= A level
    #   grade B: everything else that passes (weak tilt confirmed by the model, or a model-led call)
    decision, why, grade, basis = "HOLD", None, None, None
    # v2.6: per coin/timeframe policy computed nightly from out-of-sample history (series gate, grade-B threshold)
    spol = series_policy_view(rt, symbol, timeframe) if bundle is None else {"blocked": False, "reason": None, "conf_b": None}
    conf_b_min = spol["conf_b"] if spol["conf_b"] is not None else settings.min_dir_confidence_b
    idx = sig.get("label_index")
    weak = idx in (2, 4)
    if sig["signal"] == "INSUFFICIENT DATA":
        decision, why = "INSUFFICIENT DATA", "not enough closed candles"
    elif vol_state == "EXTREME":
        decision, why = ("NO TRADE" if direction else "HOLD"), "volatility is extreme (above its 95th percentile)"
    elif not fc["available"]:
        decision, why = ("NO TRADE" if direction else "HOLD"), f"no validated model for {timeframe} ({fc['reason']})"
    elif settings.require_edge_for_trade and not fc["edge_confirmed"]:
        decision, why = ("NO TRADE" if direction else "HOLD"), "no proven edge: the model's walk-forward edge test not passed"
        if direction:
            flags.append("NO PROVEN EDGE")
    else:
        mside = dv["side"] if dv else 0
        clears = bool(dv and dv["clears_policy"])
        model_led = direction == 0 and clears and bool(dv and dv["policy_edge"])
        side = direction if direction and mside == direction else (mside if model_led else 0)
        agree = fc["model_agreement"]
        if side == 0:
            if direction == 0:
                why = "no directional tilt, and the AI lean is below its proven threshold"
            else:
                why = f"the AI leans {'up' if mside > 0 else 'down'}, against the {'bullish' if direction > 0 else 'bearish'} technical tilt"
        else:
            if side != direction:          # model-led call: build the plan on the model's side
                setup = build_setup(ind, levels["zones"], side, settings.min_risk_reward, live_price=price, lift=lift_of(side),
                                    **stop_kw)
            firm = bool(direction) and not weak
            conf_ok_a = confidence is not None and confidence >= max(settings.min_dir_confidence_a, conf_b_min)
            conf_ok_b = confidence is not None and confidence >= conf_b_min
            if firm and clears and agree >= settings.min_model_agreement and conf_ok_a:
                grade, basis = "A", "technical tilt and AI agree, AI lean above its proven threshold"
            elif conf_ok_b and agree >= settings.min_agreement_b and (clears or firm):
                grade = "B"
                basis = ("AI-led: the AI lean clears its proven threshold" if model_led else
                         "technical tilt confirmed by the AI lean" if not clears else "weak technical tilt, AI lean above its threshold")
            if grade is None:
                if confidence is None:
                    why = "too few comparable out-of-sample calls to state a confidence"
                elif not conf_ok_b:
                    why = f"directional confidence {confidence:.0%} is not above a coin flip"
                elif agree < settings.min_agreement_b:
                    why = f"model agreement {agree:.0%} is too low"
                else:
                    why = "the tilt is weak and the AI lean is below its proven threshold"
                decision = "HOLD" if weak or not direction else "NO TRADE"
            elif not setup or not setup["valid"]:
                decision, why, grade = "NO TRADE", (setup or {}).get("reason") or "no valid trade setup", None
            elif side > 0:
                decision = "BUY ON PULLBACK" if setup["extended"] else "BUY"
            else:
                decision = "SELL"
            if grade:
                direction = side
    # v2.24 proof checks: the call as formed, before any filter; a filter that blocks it logs it in `rejected_signals`
    pre_gate = ((decision, dict(setup), grade, len(flags))
                if decision in TRADE_DECISIONS and setup and setup.get("valid") else None)
    # v2.13 (C2): a graded call needs a PROVEN edge: the model's walk-forward edge test passed (`edge_confirmed`) AND
    # its directional policy is reliably better than a coin flip (`policy_edge`: lower 95 % bound of the chosen margin's
    # out-of-sample hit rate > 50 %). Setting REQUIRE_EDGE_FOR_TRADE (default OFF since v2.14, owner).
    edge_why = edge_gate(fc, dv) if decision in TRADE_DECISIONS else None
    if edge_why:
        decision, grade, why = "NO TRADE", None, edge_why
        flags.append("NO PROVEN EDGE")
    # bigger-trend check (v2.2): a trade against BOTH of the next two higher timeframes' trends is refused; against
    # one of them, a grade A call is lowered to B. Quick timeframes are where this matters most.
    trend_check = higher_trend_check(matrix, timeframe, direction if decision in TRADE_DECISIONS else 0)
    if decision in TRADE_DECISIONS and trend_check:
        if trend_check["against"] >= 2:
            decision, why, grade = "NO TRADE", f"the bigger trend points the other way ({trend_check['label']})", None
            flags.append("AGAINST BIGGER TREND")
        elif trend_check["against"] == 1 and grade == "A":
            grade = "B"
            basis = f"{basis}; one higher timeframe disagrees ({trend_check['label']})" if basis else trend_check["label"]
    # trade filter: the model's own record of which setups reach their targets before the stop
    tf_view = (fc or {}).get("trade_filter") if fc.get("available") else None
    filter_score = None
    filter_bypassed = False
    filter_shadow: list[dict[str, Any]] = []
    if tf_view and decision in TRADE_DECISIONS:
        tside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        filter_score = tf_view["p_long"] if tside > 0 else tf_view["p_short"]
        bypass = live and bundle is None and as_of is None and filter_bypass(rt, timeframe, tf_view)
        if live and bundle is None and as_of is None:
            shadow_stat(rt, "trade_filter", timeframe, symbol, int(last["ts"]), filter_score, tf_view["threshold"],
                        tf_view.get("keep_fraction"))
        if filter_score < tf_view["threshold"] and bypass:
            filter_bypassed = True
            filter_shadow.append({"filter": "trade_filter", "score": round(float(filter_score), 4),
                                  "threshold": tf_view["threshold"], "validated": bool(tf_view.get("validated")),
                                  "method": tf_view.get("threshold_method")})
        if filter_score < tf_view["threshold"] and not bypass:
            decision, why = "NO TRADE", (f"the trade filter scores this setup {filter_score:.0%}, below the "
                                         f"{tf_view['threshold']:.0%} bar at which past setups paid off")
            grade = None
            flags.append("FILTERED")

    if decision in TRADE_DECISIONS and fc.get("trade_filter_error"):
        decision, grade, why = "NO TRADE", None, "the trade filter could not be checked (fail-safe: no trade)"
        flags.append("CHECK UNAVAILABLE")
        gate_failure(rt, "trade_filter", symbol, timeframe, fc["trade_filter_error"])
    # v2.6 proven-only series gate: a coin/timeframe whose out-of-sample + live expectancy is not credibly positive
    if decision in TRADE_DECISIONS and spol["blocked"]:
        decision, why, grade = "NO TRADE", spol["reason"], None
        flags.append("NO PROVEN EDGE")
    # v2.6 pooled trade filter (one per timeframe, trained on the calls the pipeline itself made)
    filter2 = None
    if decision in TRADE_DECISIONS and settings.trade_filter2 and setup and setup.get("valid") and bundle is None:
        try:
            from ..ml import trade_filter2 as TF2
            f2 = TF2.load(rt.db, timeframe)
            if f2 is not None:
                fside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
                row = TF2.live_features(fc, confidence, grade, fside, last, matrix, _btc_last(rt, symbol, timeframe, as_of, last),
                                        setup, int(last["ts"]) + tf_ms(timeframe))
                sc = TF2.score(f2, row)
                if sc is not None:
                    filter2 = {"score": sc, "threshold": f2["threshold"]}
                    bypass2 = live and as_of is None and filter_bypass(rt, timeframe, f2)
                    if live and as_of is None:
                        shadow_stat(rt, "trade_filter2", timeframe, symbol, int(last["ts"]), sc, f2["threshold"],
                                    (f2.get("summary") or {}).get("keep_fraction"))
                    if sc < f2["threshold"] and bypass2:
                        filter_bypassed = True
                        filter_shadow.append({"filter": "trade_filter2", "score": round(float(sc), 4),
                                              "threshold": f2["threshold"], "validated": bool(f2.get("validated"))})
                    if sc < f2["threshold"] and not bypass2:
                        decision, grade = "NO TRADE", None
                        why = (f"the {timeframe.upper()} trade filter scores this call {sc:.0%}, below the {f2['threshold']:.0%} "
                               "bar at which comparable past calls paid off")
                        flags.append("FILTERED")
        except Exception as exc:
            rt.record_error(f"trade filter2 {symbol} {timeframe}", exc)
            # v2.13 fail closed: a required check that cannot run blocks the call (shown on Health)
            decision, grade, why = "NO TRADE", None, f"the {timeframe.upper()} trade filter could not be checked (fail-safe: no trade)"
            flags.append("CHECK UNAVAILABLE")
            gate_failure(rt, "trade_filter2", symbol, timeframe, exc)

    # costs (v2.3): a target 1 that barely covers fees and slippage is no trade (mostly tight 15m setups)
    if decision in TRADE_DECISIONS and setup and setup.get("valid") and not beats_costs(setup["ideal_entry"], setup["stop"]):
        rp = abs(setup["ideal_entry"] - setup["stop"]) / setup["ideal_entry"] * 100
        decision, grade = "NO TRADE", None
        why = (f"target 1 is only {rp:.2f}% away: too small to beat trading costs "
               f"(about {round_trip_cost() * 100:.2f}% to get in and out; it needs at least {COST_MULT:g}x that)")
        flags.append("TARGET TOO SMALL FOR COSTS")
    # v2.14 leverage policy (owner, 3 Nov 2026): futures trades use 10-50x chosen by the engine; a stop so wide that even
    # 10x would leave liquidation within 1.5x the stop distance (coin tier + closing fee) is no trade. Checked at the
    # card's entry and at the live price (the record's market entry), so card, record, bots and auto-trade agree.
    lev_why = leverage_gate(setup, price, symbol, grade, timeframe) if decision in TRADE_DECISIONS else None
    if lev_why:
        decision, grade, why = "NO TRADE", None, lev_why
        flags.append("STOP TOO WIDE")

    # v2.22 admin Hold: while a withdrawn call on this coin / timeframe would still be running, no new call there
    if decision in TRADE_DECISIONS and live and bundle is None and as_of is None:
        from .hold import held_open
        if held_open(rt.db, symbol, timeframe):
            decision, grade, why = "NO TRADE", None, "the admin withdrew the last call here; no new call until it would have ended"
            flags.append("WITHDRAWN BY ADMIN")
    # v2.32 (owner, 14 Nov 2026): coins being taken off the watchlist get no new calls; running ones finish first
    if decision in TRADE_DECISIONS and live and bundle is None and as_of is None and symbol in RETIRING_COINS \
            and not rt.db.get_setting(RETIRE_FLAG, False):
        decision, grade, why = "NO TRADE", None, "this coin is being removed from the watchlist; running trades finish first"
        flags.append("COIN BEING REMOVED")
    # v2.22 combination (owner-approved 14 Nov 2026, services/combo_gates.py): volume profile, fee and same-side cap,
    # live calls only (research replays and rebuilds keep measuring every call)
    if decision in TRADE_DECISIONS and live and bundle is None and as_of is None and setup and setup.get("valid"):
        from . import combo_gates as CG
        nside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        try:
            atr_now = float(fr.ind["atr"].iloc[-1])
        except Exception:
            atr_now = 0.0
        for flag, reason in (("VOLUME WALL AHEAD", CG.vp_block(fr.df, nside, float(price), atr_now)),
                             ("STOP TOO TIGHT FOR FEES", CG.fee_block(timeframe, float(price), setup.get("stop"))),
                             ("TOO MANY SAME-SIDE CALLS", CG.cap_block(rt.db, nside, timeframe))):
            if reason:
                decision, grade, why = "NO TRADE", None, reason
                flags.append(flag)
                break

    # paused timeframes (v2.6): live calls only, so research replays still measure every timeframe
    if decision in TRADE_DECISIONS and timeframe in PAUSED_TFS and live and bundle is None and as_of is None:
        decision, grade = "NO TRADE", None
        why = (f"{timeframe.upper()} trade calls are paused: on past calls they lost money after costs. "
               "The chart and forecast stay available")
        flags.append("TIMEFRAME PAUSED")
    if decision in TRADE_DECISIONS and timeframe in A_ONLY_TFS and grade != "A" and live and bundle is None and as_of is None:
        decision, grade = "NO TRADE", None
        why = f"{timeframe.upper()} trade calls are grade A only; this setup is grade B"
        flags.append("GRADE A ONLY")

    # one call at a time on quick timeframes (v2.3): while a 15m call on this coin is still running, an opposite 15m
    # call is not issued (the 15m view can swing within the hour; flip-flopping cut winners and entered losers)
    if decision in TRADE_DECISIONS and timeframe in ONE_CALL_TFS and live and bundle is None and as_of is None:
        nside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        running = rt.db.one("SELECT side, created_at FROM signals WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' "
                            "AND side != 0 ORDER BY created_at DESC LIMIT 1", (symbol, timeframe))
        if running and int(running["side"]) == -nside:
            decision, grade = "NO TRADE", None
            why = (f"the previous {timeframe.upper()} {'long' if nside < 0 else 'short'} call on this coin is still "
                   "running; no opposite call until it closes")
            flags.append("CALL STILL RUNNING")

    # let winners run (v2.3): where the runner model proved itself on unseen trades and scores this setup above its
    # threshold, the whole position stays open at TP1 and the stop follows the price up to the 1:4 runner target
    run_view = (fc or {}).get("runner") if fc.get("available") else None
    runner_shadow = None
    if run_view and decision in TRADE_DECISIONS and setup and setup.get("valid"):
        rside = 1 if decision in ("BUY", "BUY ON PULLBACK") else -1
        rp = run_view["p_long"] if rside > 0 else run_view["p_short"]
        if live and bundle is None and as_of is None:
            shadow_stat(rt, "runner_model", timeframe, symbol, int(last["ts"]), rp, run_view["threshold"], None)
        shadow_only = live and bundle is None and as_of is None and not runner_enforced(run_view)
        if rp >= run_view["threshold"] and shadow_only:
            # V3.2 (audit R-02): runner model in shadow - standard exits; what it would have done is recorded
            runner_shadow = {"would_run": True, "score": round(float(rp), 4), "threshold": run_view["threshold"],
                             "rr": float(run_view.get("run_r") or 4.0), "validated": bool(run_view.get("validated"))}
        elif rp >= run_view["threshold"]:
            dist = abs(setup["ideal_entry"] - setup["stop"])
            rr = float(run_view.get("run_r") or 4.0)
            tgt = float(setup["ideal_entry"] + rside * rr * dist)
            setup["runner"] = {"on": True, "target": tgt, "rr": rr, "score": rp, "threshold": run_view["threshold"],
                               "move_pct": float(rside * (tgt / setup["ideal_entry"] - 1) * 100),
                               "basis": "AI: let it run - nothing closes at TP1; the stop moves to break-even at TP1, "
                                        f"to TP1 at TP2, to TP2 at TP3; the whole position closes at 1:{rr:g}"}

    # safety switch (v2.2): a coin/timeframe whose recent live signals lost pauses; its would-be trades are
    # tracked as hidden practice trades until they recover
    safety_state, shadow = None, None
    if live and bundle is None and timeframe in MODEL_TIMEFRAMES:
        try:
            from . import safety
            from ..views import record_for
            safety_state = safety.check(rt.db, symbol, timeframe, record_for(rt, timeframe))
        except Exception as exc:
            # v2.13 fail closed: without the safety switch's verdict no new call is issued
            safety_state = {"paused": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
            if decision in TRADE_DECISIONS:
                decision, why, grade = "NO TRADE", "the safety switch could not be checked (fail-safe: no trade)", None
                flags.append("CHECK UNAVAILABLE")
            gate_failure(rt, "safety", symbol, timeframe, exc)
        if safety_state and safety_state.get("paused") and decision in TRADE_DECISIONS and setup and setup.get("valid"):
            shadow = (decision, setup)
            decision, why, grade = "NO TRADE", safety_state["reason"], None
            flags.append("PAUSED")
    # high-impact US data release (CPI, jobs report, Fed): pause fresh entries around it
    news_risk = None
    news_down = None
    try:
        from .news import event_risk
        news_risk = event_risk(rt.db, (as_of if as_of is not None else int(time.time() * 1000)))
        if live and bundle is None:
            news_down = calendar_unavailable(rt.db)
    except Exception as exc:
        news_risk = None
        news_down = f"{type(exc).__name__}: {exc}"[:160]
    if news_down and decision in TRADE_DECISIONS:
        # v2.13 fail closed: the news guard cannot see the calendar, so it cannot say the next hour is clear
        decision, why, grade = "NO TRADE", "the economic calendar is unavailable, so the news guard cannot run (fail-safe: no trade)", None
        flags.append("CHECK UNAVAILABLE")
    if news_down:
        gate_failure(rt, "news_calendar", symbol, timeframe, news_down)
    if news_risk:
        flags.append("NEWS RISK")
        if decision in TRADE_DECISIONS:
            held = decision
            decision, why = "NO TRADE", news_risk["reason"]
            basis = f"{held} paused for the news" if basis is None else f"{basis} (paused: {news_risk['title']})"
            grade = None
    # stale data (audit A3): if the newest closed candle is older than 2 bars, or the data-quality check fails hard,
    # nothing is traded on it - the candle sync must have failed
    quality = check_candles(fr.df, timeframe, as_of)
    recent_q = check_candles(fr.df.tail(300), timeframe, as_of)     # hard failures judged on the recent candles
    stale = bool(live and bundle is None and is_stale(recent_q, int(last["ts"]), timeframe))
    if stale:
        flags.append("STALE DATA")
        if decision != "INSUFFICIENT DATA":
            decision, why, grade = "NO TRADE", "market data is stale", None
    # v2.65 capital-protection veto: last word over every live call (record, demo bots, Hesper, Last Stand, auto-trade)
    risk_check = _risk_shadow(rt, symbol, timeframe) if (decision in TRADE_DECISIONS and live and bundle is None) else None
    if risk_check is not None:            # v2.78 shadow only: would the market-turn pause have held this call back?
        try:
            from . import turn_watch
            from .guardian import side_of
            risk_check["turn"] = turn_watch.against(rt, symbol, side_of(decision))
        except Exception:
            pass
        try:                                   # V3.0: market risk state at publication (shadow; judged by replay later)
            from . import risk_state
            rs = risk_state.current(rt.db)
            risk_check["state"] = (rs or {}).get("state") or "UNKNOWN"
            risk_check["state_score"] = (rs or {}).get("score")
        except Exception:
            pass
    if decision in TRADE_DECISIONS and live and bundle is None:
        decision, grade, why = entry_guards(rt, symbol, timeframe, decision, grade, why, flags, risk_check)
    watch = None
    if live and bundle is None and as_of is None:
        watch, held = watch_gate(symbol, decision, grade)
        if watch:
            decision, grade, why = held
            flags.append("WATCH ONLY")
    demo = None
    if decision in TRADE_DECISIONS and timeframe in DEMO_ONLY_TFS and live and bundle is None and as_of is None:
        # v2.8: the demo bots may take it (their own grade rule applies); it is never published or recorded as a signal
        demo = {"decision": decision, "grade": grade}
        decision, grade = "NO TRADE", None
        why = f"{timeframe.upper()} calls go to the demo bots only while they are tested"
        flags.append("DEMO BOTS ONLY")
    if decision == "NO TRADE":
        flags.append("NO TRADE")

    risk = None
    if setup and setup.get("ideal_entry"):
        risk = position_size(rt.risk_profile(), setup["ideal_entry"], setup["stop"],
                             float(last["sigma_bar"]) if np.isfinite(last["sigma_bar"]) else None, timeframe)
    tk = rt.ticker(symbol) if live else None
    out: dict[str, Any] = {
        **base, "status": "OK", "bar_ts": int(last["ts"]), "bar_close_ts": int(last["ts"]) + tf_ms(timeframe),
        "price": price, "last_close": close, "price_quality": pq,
        "change_24h_pct": tk.get("change_pct") if tk else None, "quote_volume_24h": tk.get("quote_volume") if tk else None,
        "regime": regime, "volatility": {
            "state": vol_state, "percentile": _n(last["vol_pct"]), "realized": _n(last["rv"]), "historical": _n(last["hv"]),
            "atr": _n(last["atr"]), "atr_pct": _n(last["atr_pct"]), "bb_width": _n(last["bb_width"]),
            "bb_width_percentile": _n(last["bb_width_pct"]), "range_expansion": bool(last["range_expansion"]),
            "range_compression": bool(last["range_compression"])},
        "stale": stale,
        "signal": sig, "decision": decision, "decision_reason": why, "flags": list(dict.fromkeys(flags)), "trend_check": trend_check,
        "filter_bypassed": bool(filter_bypassed and decision in TRADE_DECISIONS),
        "filter_shadow": filter_shadow if (filter_shadow and decision in TRADE_DECISIONS) else None,
        "runner_shadow": runner_shadow if decision in TRADE_DECISIONS else None,
        "risk_shadow": risk_check,
        "safety": safety_state,
        "grade": grade, "demo": demo, "watch": watch, "decision_basis": basis, "direction_view": dv, "news_risk": news_risk,
        "filter_score": filter_score, "filter_threshold": (tf_view or {}).get("threshold"), "filter2": filter2,
        "series_policy": spol if (spol.get("blocked") or spol.get("conf_b") is not None) else None,
        "confidence": confidence, "confidence_detail": conf_detail,
        "forecast": fc, "mtf": matrix, "setup": setup, "risk": risk,
        "model_agreement": fc.get("model_agreement") if fc["available"] else None,
        "mtf_alignment": matrix["alignment"],
        "liquidity": {"order_book": liq, "relative_volume": _n(last["rel_volume"]), "volume_spike": bool(last["volume_spike"]),
                      "buy_pressure": _n(last["buy_pressure"]), "volume_divergence": int(last["volume_divergence"] or 0)},
    }
    out["now"] = {"breakout": int(last["breakout"] or 0), "bos": int(last["bos"] or 0), "choch": int(last["choch"] or 0),
                  "range_expansion": bool(last["range_expansion"])}
    if detail:
        out["horizons"] = horizon_forecasts(rt, symbol) if live else []
        out["levels"] = levels
        out["events"] = _events(fr)
        out["indicators"] = _snapshot(last)
        out["data_quality"] = quality
    out["commentary"] = build_commentary(out)
    if live and bundle is None:
        if fc["available"]:
            tracking.log_prediction(rt.db, symbol, timeframe, fc)
        tracking.log_signal(rt.db, out)                  # sets out["record_status"] (logged / already_open / not_logged)
        if out.get("record_status") is None and decision in TRADE_DECISIONS:
            out["record_status"] = "not_logged"
        if decision in TRADE_DECISIONS:
            only_recorded(rt.db, out)
        if shadow and not stale:
            tracking.log_shadow(rt.db, out, shadow[0], shadow[1])
        if pre_gate and decision not in TRADE_DECISIONS and not stale and as_of is None:
            try:
                from . import proof_checks
                flag = proof_checks.blocking_flag(flags[pre_gate[3]:])
                if flag:
                    proof_checks.log_rejected(rt.db, out, pre_gate[0], pre_gate[1], pre_gate[2], flag, why)
            except Exception as exc:              # the log never blocks an analysis
                rt.record_error(f"rejected log {symbol}", exc)
        if tracking.SCALPING_ON and timeframe in tracking.SCALP_TFS and (demo or (decision in TRADE_DECISIONS and grade == "A")):
            # admin scalping log: its own table, never the record; `out` is not changed (views stay byte-identical)
            try:
                tracking.log_scalp(rt.db, out)
            except Exception as exc:              # the log never blocks an analysis
                rt.record_error(f"scalp log {symbol}", exc)
        out["call"] = tracking.current_call(rt.db, symbol, timeframe)
        ai = tracking.latest_ai(rt.db, symbol, timeframe)
        if ai:
            out["ai"] = ai
        rt.analysis_cache[key] = (time.time(), out)
    return out


TICKER_MAX_AGE_S = float(os.environ.get("TICKER_MAX_AGE_S", "300"))   # one engine cycle (snapshot taken every tick)


def live_quote(rt: Any, symbol: str, close: float, now: int | None = None) -> dict[str, Any]:
    """{'price', 'source': 'ticker' | 'last_close', 'quality': 'live' | 'missing' | 'stale' | 'invalid', 'ts', 'age_s'}.
    'live' = a ticker with a positive last price no older than TICKER_MAX_AGE_S."""
    now = int(time.time() * 1000) if now is None else int(now)
    try:
        tk = rt.ticker(symbol)
    except Exception:
        tk = None
    last = None
    try:
        last = float(tk.get("last")) if tk and tk.get("last") is not None else None
    except (TypeError, ValueError):
        last = None
    ts = None
    try:
        ts = int(tk.get("ts")) if tk and tk.get("ts") else None
    except (TypeError, ValueError):
        ts = None
    if ts is None:
        feed = getattr(rt, "feed", None)
        ts = getattr(feed, "taken_ms", None) or getattr(feed, "last_update_ms", None)
    age = (now - int(ts)) / 1000 if ts else None
    if tk is None or last is None:
        q = "missing"
    elif not np.isfinite(last) or last <= 0:
        q = "invalid"
    elif age is None or age > TICKER_MAX_AGE_S or age < -TICKER_MAX_AGE_S:
        q = "stale"
    else:
        q = "live"
    if q == "live":
        return {"price": last, "source": "ticker", "quality": q, "ts": int(ts), "age_s": round(age, 1)}
    return {"price": close, "source": "last_close", "quality": q, "ts": int(ts) if ts else None,
            "age_s": round(age, 1) if age is not None else None}


def entry_guards(rt: Any, symbol: str, timeframe: str, decision: str, grade: str | None, why: str | None,
                 flags: list[str], risk_check: dict[str, Any] | None) -> tuple[str, str | None, str | None]:
    """The last new-entry guards of a live call, in their live order: liquidity sweep, BTC shock, capital protection.
    V3.2 (Fable 5.2 audit R-01): each one fails CLOSED - an error, missing / short / stale input = NO TRADE with flag
    "CHECK UNAVAILABLE", a logged error and a Health entry (`gate_failures`). Only new entries are affected: open
    positions, their stops and exits are managed elsewhere (engine/manage.py, tracking) and never read this.
    Appends to `flags`; stores the per-guard state in risk_check['guards']."""
    # v2.79 liquidity-sweep guard (proven: research_sweep.py, PASS): no new call against a fresh stop run on the coin.
    # V3.2 (audit R-01): fail closed - missing, short or stale 1h history, or an error, = NO TRADE "CHECK UNAVAILABLE".
    guard_status: dict[str, Any] = {}
    if decision in TRADE_DECISIONS:
        from . import sweep_guard
        from .guardian import side_of
        sd = side_of(decision)
        try:
            st = sweep_guard.status(rt, symbol, sd)
        except Exception as exc:
            st = {"state": "unavailable", "hit": None, "reason": f"{type(exc).__name__}: {exc}"[:160]}
        guard_status["sweep_guard"] = st["state"]
        if st["state"] == "block":
            decision, grade = "NO TRADE", None
            why = sweep_guard.reason(st["hit"], sd)
            flags.append(sweep_guard.FLAG)
        elif st["state"] == "unavailable":
            decision, grade = "NO TRADE", None
            why = _guard_unavailable(rt, "sweep_guard", "liquidity-sweep guard", symbol, timeframe, st["reason"])
            flags.append("CHECK UNAVAILABLE")
    # V3.0 adaptive BTC shock guard (proven: research_btc.py, PASS): no new call against an unusually large BTC move.
    # V3.2 (audit R-01): fail closed - BTC 1h candles missing, fewer than 30 days, newest older than 2 h, or an error.
    if decision in TRADE_DECISIONS:
        from . import btc_shock
        from .guardian import side_of
        sd = side_of(decision)
        try:
            bs = btc_shock.status(rt, sd)
        except Exception as exc:
            bs = {"state": "unavailable", "hit": None, "reason": f"{type(exc).__name__}: {exc}"[:160]}
        guard_status["btc_shock"] = bs["state"]
        if bs["state"] == "block":
            decision, grade = "NO TRADE", None
            why = btc_shock.reason(bs["hit"], sd)
            flags.append(btc_shock.FLAG)
        elif bs["state"] == "unavailable":
            decision, grade = "NO TRADE", None
            why = _guard_unavailable(rt, "btc_shock", "BTC shock guard", symbol, timeframe, bs["reason"])
            flags.append("CHECK UNAVAILABLE")
    if RISK_VETO and risk_check and risk_check.get("would_block") and decision in TRADE_DECISIONS:
        decision, grade = "NO TRADE", None
        why = f"capital protection: {risk_check.get('reason')}"
        flags.append("CAPITAL PROTECTION")
    # V3.2 (audit R-01): a capital-protection rule that could not be evaluated is not a pass
    if RISK_VETO and risk_check and risk_check.get("unavailable") and decision in TRADE_DECISIONS:
        decision, grade = "NO TRADE", None
        why = _guard_unavailable(rt, "capital_protection", "capital-protection veto", symbol, timeframe,
                                 risk_check.get("unavailable_reason") or ", ".join(risk_check["unavailable"]))
        flags.append("CHECK UNAVAILABLE")
    if risk_check is not None and guard_status:
        risk_check["guards"] = guard_status
    return decision, grade, why


def leverage_gate(setup: dict[str, Any] | None, price: float | None, symbol: str | None, grade: str | None,
                  timeframe: str | None = None) -> str | None:
    """v2.14: why a trade call is refused under the 10-50x leverage policy (stop too wide for 10x at the card's entry or
    at the live price, the record's market entry), or None when it may trade. Only on the policy timeframes
    (futures.POLICY_TFS, owner: 15m); every other timeframe is never refused for this (v2.13)."""
    from ..engine.futures import TOO_WIDE_REASON, engine_leverage, in_policy
    if not in_policy(timeframe) or not setup or not setup.get("valid") or not setup.get("stop"):
        return None
    entries = [e for e in (setup.get("ideal_entry"), price) if e]
    if entries and all(engine_leverage(e, setup["stop"], symbol, grade, timeframe) is not None for e in entries):
        return None
    e0 = entries[0] if entries else None
    rp = abs(float(e0) - float(setup["stop"])) / float(e0) * 100 if e0 else None
    return f"{TOO_WIDE_REASON}: the stop is {rp:.1f}% away" if rp is not None else TOO_WIDE_REASON


def edge_gate(fc: dict[str, Any] | None, dv: dict[str, Any] | None, required: bool | None = None) -> str | None:
    """v2.13 (C2): why a graded call is refused for lack of a proven edge, or None when it may trade.
    Proven = the model's walk-forward edge test (`edge_confirmed`) AND the direction policy's edge (`policy_edge`)."""
    if not (settings.require_edge_for_trade if required is None else required):
        return None
    ok_model, ok_dir = bool((fc or {}).get("edge_confirmed")), bool(dv and dv.get("policy_edge"))
    if settings.edge_rule == "policy":
        ok_model = True
    if ok_model and ok_dir:
        return None
    missing = [x for x, ok in (("the model's walk-forward edge test", ok_model),
                               ("a direction hit rate reliably above 50% on unseen data", ok_dir)) if not ok]
    return "no proven edge: " + " and ".join(missing) + " not passed"


def series_policy_view(rt: Runtime, symbol: str, timeframe: str) -> dict[str, Any]:
    """The cached nightly policy of this coin/timeframe as the live decision uses it (all off unless enabled)."""
    if not (settings.series_gate or settings.series_conf):
        return {"blocked": False, "reason": None, "conf_b": None}
    try:
        from ..ml import series_policy
        return series_policy.apply(series_policy.cached(rt.db, symbol, timeframe))
    except Exception:
        return {"blocked": False, "reason": None, "conf_b": None}


def _btc_last(rt: Runtime, symbol: str, timeframe: str, as_of: int | None, own_last: Any) -> Any:
    if symbol.startswith("BTC/"):
        return own_last
    try:
        return rt.frame("BTC/USDT", timeframe, as_of).ind.iloc[-1]
    except Exception:
        return None


def is_stale(quality: dict[str, Any], last_ts: int, timeframe: str, now: int | None = None) -> bool:
    """Newest closed candle older than 2 bars of its timeframe, or a hard data-quality failure."""
    now = int(time.time() * 1000) if now is None else now
    step = tf_ms(timeframe)
    if now - (int(last_ts) + step) > 2 * step:
        return True
    return quality.get("status") == "NO DATA" or (quality.get("quality_pct") is not None and quality["quality_pct"] < 90.0)


def higher_trend_check(matrix: dict[str, Any], timeframe: str, side: int) -> dict[str, Any] | None:
    """How many of the next two higher timeframes trend against `side` (+1 long / -1 short)."""
    if not side:
        return None
    from ..config import TF_SECONDS

    rows = sorted((r for r in matrix.get("rows", []) if r.get("available") and r.get("direction") is not None
                   and TF_SECONDS.get(r["timeframe"], 0) > TF_SECONDS.get(timeframe, 0)),
                  key=lambda r: TF_SECONDS[r["timeframe"]])[:2]
    if not rows:
        return None
    against = [r["timeframe"] for r in rows if r["direction"] == -side]
    label = ", ".join(f"{r['timeframe'].upper()} {r['direction_label'].lower()}" for r in rows)
    return {"checked": [r["timeframe"] for r in rows], "against": len(against), "label": label}


def _n(v: Any) -> float | None:
    return float(v) if v is not None and np.isfinite(v) else None


def final_signal(a: dict[str, Any]) -> dict[str, Any]:
    """The compact structured output (one object per asset)."""
    fc, setup, sig = a.get("forecast") or {}, a.get("setup") or {}, a.get("signal") or {}
    p = fc.get("probabilities") or {}
    tps = setup.get("targets") or []
    show = bool(setup.get("valid"))
    return {
        "asset": a["symbol"], "timeframe": a["timeframe"], "price": a.get("price"),
        "regime": (a.get("regime") or {}).get("regime"), "regime_confidence": (a.get("regime") or {}).get("confidence"),
        "signal": sig.get("signal"), "signal_score": sig.get("score"), "confidence": a.get("confidence"),
        "bullish": p.get("up"), "neutral": p.get("neutral"), "bearish": p.get("down"),
        "forecast": {h["horizon"]: h.get("expected_return") for h in a.get("horizons", [])},
        "entry": setup.get("entry_zone") if show else None, "stop": setup.get("stop") if show else None,
        "tp1": tps[0]["price"] if show and tps else None, "tp2": tps[1]["price"] if show and len(tps) > 1 else None,
        "tp3": tps[2]["price"] if show and len(tps) > 2 else None,
        "risk_reward": setup.get("risk_reward") if show else None,
        "multi_timeframe_alignment": a.get("mtf_alignment"), "model_agreement": a.get("model_agreement"),
        "warnings": sig.get("warnings"), "flags": a.get("flags"), "decision": a.get("decision"),
        "decision_reason": a.get("decision_reason"),
    }


# ---- v2.13 fail closed ------------------------------------------------------------------------------------------
# A required gate that cannot be evaluated (exception, or the calendar not refreshed) turns the call into NO TRADE with
# a reason, and is listed on Health (setting `gate_failures`, last occurrence per gate). An expired / missing nightly
# entry rule is NOT a failure: the record then uses the v2.5 rule, which since v2.13 enters at the market price (honest).
CALENDAR_MAX_AGE_MS = int(float(os.environ.get("NEWS_CALENDAR_MAX_AGE_H", "72")) * 3_600_000)
GATE_FAILURES_KEEP_MS = 24 * 3_600_000


def calendar_unavailable(db: Any, now: int | None = None) -> str | None:
    """Why the news guard cannot run, or None. The calendar counts as unavailable when it was synced before but not in
    the last NEWS_CALENDAR_MAX_AGE_H hours (a database that never synced one - fresh installs, tests - is not blocked)."""
    now = int(time.time() * 1000) if now is None else now
    last = int(db.get_setting("calendar_synced_at", 0) or 0)
    if last and now - last > CALENDAR_MAX_AGE_MS:
        return f"calendar last refreshed {round((now - last) / 3_600_000)} h ago"
    return None


def gate_failure(rt: Any, gate: str, symbol: str, timeframe: str, err: Any) -> None:
    """Remember a gate that could not run (Health shows the last 24 h)."""
    try:
        now = int(time.time() * 1000)
        cur = {k: v for k, v in (rt.db.get_setting("gate_failures", {}) or {}).items()
               if now - int((v or {}).get("at") or 0) < GATE_FAILURES_KEEP_MS}
        prev = cur.get(gate) or {}
        cur[gate] = {"at": now, "symbol": symbol, "timeframe": timeframe, "detail": str(err)[:160],
                     "count": int(prev.get("count") or 0) + 1 if prev else 1}
        rt.db.set_setting("gate_failures", cur)
    except Exception:
        pass


def gate_failures(db: Any, now: int | None = None) -> dict[str, Any]:
    now = int(time.time() * 1000) if now is None else now
    return {k: v for k, v in (db.get_setting("gate_failures", {}) or {}).items()
            if now - int((v or {}).get("at") or 0) < GATE_FAILURES_KEEP_MS}


def only_recorded(db: Any, out: dict[str, Any]) -> None:
    """v3.1 (owner, 25 Nov 2026: "a trade has been taken, while it's not showing in results"): bots and members'
    auto-trades follow the published decision, so a call the record did not take (re-entry pause after a closed or
    admin-closed call, a call already on this candle ...) becomes NO TRADE for everyone. The record's running call on
    the same side stays tradable."""
    if out.get("decision") not in TRADE_DECISIONS:
        return
    st = out.get("record_status")
    if st == "logged":
        return
    if st == "already_open":
        oc = tracking.open_call(db, out["symbol"], out["timeframe"])
        if oc is not None and (1 if int(oc["side"]) > 0 else -1) == int((out.get("setup") or {}).get("side_int") or 0):
            return
    out["decision_reason"] = f"No new entry: {out.get('record_reason') or 'the track record did not take this call'}"
    out["decision"], out["grade"] = "NO TRADE", None
    out["flags"] = list(dict.fromkeys([*(out.get("flags") or []), "NOT IN RECORD", "NO TRADE"]))
