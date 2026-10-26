"""Training pipeline (walk-forward evaluation -> edge test -> live fit) and inference from a saved bundle.

Training is slow and runs in a background worker. Inference only loads the saved bundle and scores the
latest closed candle - a forecast refresh never retrains anything.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np

from ..backtest import strategies as S
from ..backtest.benchmarks import edge_test
from ..backtest.engine import BacktestConfig, run_backtest
from ..config import CLASSES, WALK_FORWARD, settings
from ..db import Database, dumps, loads, now_ms
from ..features.dataset import Dataset, Frame, InsufficientData, make_dataset
from . import explain
from .distribution import (confidence_lookup, forecast_distribution, interval_coverage, touch_probabilities)
from .drift import reference_bins
from .metrics import (brier, brier_skill_test, classification_metrics, regression_metrics,
                      reliability_table)
from .models import REGISTRY, default_models, model_status, predict_with_context
from .walkforward import class_means, ensemble_proba, fit_stage, run_walk_forward

log = logging.getLogger(__name__)
GAP = 1
_cache: dict[str, dict[str, Any]] = {}


def _cost() -> float:
    return settings.fee_rate + (settings.slippage_bps + settings.spread_bps / 2) / 1e4


def train_bundle(symbol: str, timeframe: str, frame: Frame, btc: Frame | None = None,
                 model_names: list[str] | None = None, fast: bool = False,
                 progress: Callable[[float, str], None] | None = None, htf: Frame | None = None,
                 deriv: Any = None) -> dict[str, Any]:
    if timeframe not in WALK_FORWARD:
        raise ValueError(f"no model is trained for timeframe {timeframe}")
    ds = make_dataset(frame, btc, htf=htf, deriv=deriv)
    idx = np.where(ds.trainable)[0]
    if len(idx) < settings.min_train_samples + 60:
        raise InsufficientData(f"{len(idx)} usable training rows for {symbol} {timeframe}")
    names = model_names or default_models(fast)
    X = ds.X.to_numpy(float)[idx]
    m = ds.meta.iloc[idx]
    y, sigma, fwd = m["y"].to_numpy(float), m["sigma"].to_numpy(float), m["fwd_ret"].to_numpy(float)
    groups = np.nan_to_num(m["regime_group"].to_numpy(float), nan=1.0)
    vol_state = m["vol_state"].to_numpy(float)
    ts, close = m["ts"].to_numpy(), m["close"].to_numpy(float)
    z = fwd / sigma

    wf = run_walk_forward(X, y, sigma, fwd, groups, ds.feature_names, names, WALK_FORWARD[timeframe], GAP,
                          settings.min_train_samples, progress)
    oos = np.isfinite(wf.P_ens).all(axis=1)
    if not wf.folds or oos.sum() < 20:
        raise InsufficientData(f"not enough history for walk-forward validation of {symbol} {timeframe}")

    lo, hi = int(idx[np.argmax(oos)]), int(idx[len(oos) - 1 - np.argmax(oos[::-1])]) + 1
    bt_cfg = BacktestConfig(fee_rate=settings.fee_rate, slippage_bps=settings.slippage_bps,
                            spread_bps=settings.spread_bps, stop_atr=None)
    df_oos = frame.df.iloc[lo:hi]

    def trading(P: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
        sig = np.zeros(len(frame.df))
        sig[idx[mask]] = S.from_probabilities(P[mask])
        s = run_backtest(df_oos, sig[lo:hi], bt_cfg, timeframe)["summary"]
        return {"net_return": s["net_return"], "gross_return": s["gross_return"], "sharpe": s["sharpe"],
                "max_drawdown": s["max_drawdown"], "win_rate": s["win_rate"], "profit_factor": s["profit_factor"],
                "trades": s["trades"]}, sig

    metrics: dict[str, dict[str, Any]] = {}
    for name in names:
        mask = np.isfinite(wf.P_cal[name]).all(axis=1)
        if mask.sum() < 20:
            continue
        cm = classification_metrics(wf.P_cal[name][mask], y[mask], fwd[mask])
        cm["brier_raw"] = brier(wf.P_raw[name][mask], y[mask].astype(int))
        cm.update(trading(wf.P_cal[name], mask)[0])
        cm["baseline"] = REGISTRY[name]["baseline"]
        metrics[name] = cm
    ens = classification_metrics(wf.P_ens[oos], y[oos], fwd[oos])
    ens_trading, sig_ens = trading(wf.P_ens, oos)
    ens.update(ens_trading)
    ens.update({f"reg_{k}": v for k, v in regression_metrics(wf.exp_ret[oos], fwd[oos], close[oos]).items()})
    ens["baseline"] = False
    metrics["ensemble"] = ens

    y_true = np.full(hi - lo, np.nan)
    y_pred = np.full(hi - lo, np.nan)
    y_true[idx[oos] - lo] = y[oos]
    y_pred[idx[oos] - lo] = wf.P_ens[oos].argmax(axis=1)
    prior_acc = max(float(np.bincount(y[oos].astype(int), minlength=3).max() / oos.sum()),
                    metrics.get("prior_baseline", {}).get("accuracy", 0.0))
    edge = edge_test(frame.ind, lo, hi, sig_ens[lo:hi], timeframe, _cost(), y_true, y_pred, prior_acc,
                     settings.edge_alpha, settings.min_oos_for_edge)

    # ---- live fit: the most recent train/validation windows, same recipe as every fold ------------------
    f0 = wf.folds[0]
    train_len, val_len = f0.train[1] - f0.train[0], f0.val[1] - f0.val[0]
    n = len(idx)
    val = (n - val_len, n)
    train = (max(0, val[0] - GAP - train_len), val[0] - GAP)
    failures = dict(wf.failures)
    stage = fit_stage(X, y, groups, ds.feature_names, names, train, val, wf.test_skill, failures)
    if not stage["weights"]["global"]:
        raise InsufficientData(f"no model could be fitted for {symbol} {timeframe}: {failures}")
    mu = class_means(y[slice(*train)].astype(int), z[slice(*train)])

    pred = wf.P_ens.argmax(axis=1)
    z_res = (fwd - wf.exp_ret) / sigma
    keep = np.where(oos)[0][-6000:]
    oos_store = {
        "ts": ts[keep].astype(np.int64), "P_ens": wf.P_ens[keep].astype(np.float32),
        "y": y[keep].astype(np.int8), "pred": pred[keep].astype(np.int8),
        "p_max": wf.P_ens[keep].max(axis=1).astype(np.float32),
        "hit": (pred[keep] == y[keep]).astype(np.int8), "vol_state": vol_state[keep].astype(np.float32),
        "fwd_ret": fwd[keep].astype(np.float32), "exp_ret": wf.exp_ret[keep].astype(np.float32),
        "z_res": z_res[keep].astype(np.float32),
        "z_mfe": (m["mfe"].to_numpy(float)[keep] / sigma[keep]).astype(np.float32),
        "z_mae": (m["mae"].to_numpy(float)[keep] / sigma[keep]).astype(np.float32),
    }
    Xtr = X[slice(*train)]
    drift_ref = {
        "features": {nm: reference_bins(Xtr[:, j]) for j, nm in enumerate(ds.feature_names)},
        "p_up": reference_bins(wf.P_ens[oos][:, 2]),
        "vol_pct_median": float(np.nanmedian(Xtr[:, ds.feature_names.index("vol_pct")])),
    }
    cand = {k: v for k, v in metrics.items() if not v["baseline"] and k != "ensemble"}
    best = min(cand, key=lambda k: cand[k]["brier"]) if cand else None
    best_test = None
    if best and "prior_baseline" in metrics:   # is the best single model distinguishable from the class prior?
        bm = oos & np.isfinite(wf.P_cal[best]).all(axis=1) & np.isfinite(wf.P_cal["prior_baseline"]).all(axis=1)
        best_test = brier_skill_test(wf.P_cal[best][bm], wf.P_cal["prior_baseline"][bm], y[bm].astype(int))
    best_by_regime = {}
    for g, gname in ((0.0, "bear"), (1.0, "neutral"), (2.0, "bull"), (3.0, "unstable")):
        gm = oos & (groups == g)
        if gm.sum() >= 100:
            sc = {k: brier(wf.P_cal[k][gm], y[gm].astype(int)) for k in cand if np.isfinite(wf.P_cal[k][gm]).all()}
            if sc:
                best_by_regime[gname] = {"model": min(sc, key=sc.get), "n": int(gm.sum()), "brier": sc}

    # ---- trade filter: learn which of the model's calls actually pay under the bots' rules ------------------
    tfilter: dict[str, Any] = {"enabled": False, "reason": "not trained (fast model set)"}
    if not fast:
        try:
            from . import trade_filter
            o_rows = idx[oos]
            ind = frame.ind
            tfilter = trade_filter.train(X[oos], wf.P_ens[oos], o_rows, ind["high"].to_numpy(float), ind["low"].to_numpy(float),
                                         ind["close"].to_numpy(float), ind["atr"].to_numpy(float), _cost())
        except Exception as exc:          # the filter must never block a model release
            log.warning("trade filter failed for %s %s: %s", symbol, timeframe, exc)
            tfilter = {"enabled": False, "reason": f"{type(exc).__name__}: {exc}"[:160]}

    created = now_ms()
    digest = hashlib.sha1(f"{symbol}{timeframe}{created}{sorted(stage['models'])}".encode()).hexdigest()[:8]
    version = f"{symbol.replace('/', '')}-{timeframe}-{time.strftime('%Y%m%d%H%M%S', time.gmtime(created / 1000))}-{digest}"
    bundle: dict[str, Any] = {
        "version": version, "symbol": symbol, "timeframe": timeframe, "created_at": created,
        "feature_names": ds.feature_names, "uses_btc": btc is not None, "neutral_band": settings.neutral_band_sigma,
        "uses_htf": htf.timeframe if htf is not None else None,
        "selective": selective_threshold(wf.P_ens[oos], y[oos], fwd[oos]),
        "models": stage["models"], "calibrators": stage["calibrators"], "weights": stage["weights"],
        "calibration": {k: {kk: vv for kk, vv in v.items()} for k, v in stage["calibration"].items()},
        "prior": stage["prior"], "mu": mu, "feat_median": np.nanmedian(Xtr, axis=0),
        "oos": oos_store, "drift_ref": drift_ref, "metrics": metrics, "edge": edge,
        "interval_coverage": interval_coverage(z_res[oos]),
        "reliability": reliability_table(wf.P_ens[oos], y[oos].astype(int)),
        "best_model": {"name": best, "label": REGISTRY[best]["label"] if best else None,
                       "supported": bool(best_test and best_test["p_value"] is not None
                                         and best_test["p_value"] < settings.edge_alpha),
                       "skill_test_vs_prior": best_test,
                       "by_regime": best_by_regime},
        "folds": [{"fold": f.i,
                   "train": [int(ts[f.train[0]]), int(ts[f.train[1] - 1])],
                   "val": [int(ts[f.val[0]]), int(ts[f.val[1] - 1])],
                   "test": [int(ts[f.test[0]]), int(ts[f.test[1] - 1])]} for f in wf.folds],
        "fold_reports": wf.fold_reports,
        "live_fit": {"train": [int(ts[train[0]]), int(ts[train[1] - 1])], "val": [int(ts[val[0]]), int(ts[val[1] - 1])],
                     "train_rows": train[1] - train[0], "val_rows": val_len},
        "sizes": {"train": train_len, "val": val_len, "test": f0.test[1] - f0.test[0], "gap": GAP},
        "n_samples": int(n), "n_oos": int(oos.sum()), "data_start": int(ts[0]), "data_end": int(ts[-1]),
        "failures": failures, "model_status": model_status(), "importance": None, "fast": bool(fast),
        "trade_filter": tfilter,
    }
    if not fast:
        try:
            fn = ensemble_function(bundle)
            k = min(400, val_len)
            bundle["importance"] = explain.permutation_importance(fn, X[n - k:n], y[n - k:n].astype(int), ds.feature_names)
        except Exception as exc:  # explainability must never block a model release
            log.warning("permutation importance failed: %s", exc)
    return bundle


def ensemble_function(bundle: dict[str, Any], multipliers: dict[str, float] | None = None
                      ) -> Callable[[np.ndarray], np.ndarray]:
    """Row-wise ensemble over the non-sequence members (used for attribution on single rows)."""
    w = _apply_multipliers(bundle["weights"]["global"], multipliers)
    members = [m for m in w if m in bundle["models"] and not getattr(bundle["models"][m], "context_rows", 0)]
    tot = sum(w[m] for m in members) or 1.0

    def fn(X: np.ndarray) -> np.ndarray:
        from .models import proba3

        out = np.zeros((len(X), 3))
        for name in members:
            out += w[name] / tot * bundle["calibrators"][name].transform(proba3(bundle["models"][name], X))
        return out

    return fn


def _apply_multipliers(weights: dict[str, float], mult: dict[str, float] | None) -> dict[str, float]:
    if not mult:
        return dict(weights)
    w = {m: v * mult.get(m, 1.0) for m, v in weights.items()}
    tot = sum(w.values())
    return {m: v / tot for m, v in w.items()} if tot > 0 else dict(weights)


def predict(bundle: dict[str, Any], ds: Dataset, pos: int = -1, multipliers: dict[str, float] | None = None
            ) -> dict[str, Any]:
    """Score one bar (default: the latest closed candle). `multipliers` down-weights models whose LIVE
    performance has deteriorated (see services.tracking)."""
    missing = [f for f in bundle["feature_names"] if f not in ds.X.columns]
    if missing:
        raise InsufficientData(f"features missing for this model version: {missing[:5]}")
    X_all = ds.X[bundle["feature_names"]].to_numpy(float)
    j = len(X_all) + pos if pos < 0 else pos
    if not np.isfinite(X_all[j]).all():
        raise InsufficientData("features are incomplete for the latest closed candle")
    meta = ds.meta.iloc[j]
    weights = {"global": _apply_multipliers(bundle["weights"]["global"], multipliers),
               "by_regime": {g: _apply_multipliers(w, multipliers) for g, w in bundle["weights"]["by_regime"].items()}}
    group = np.array([1.0 if not np.isfinite(meta["regime_group"]) else meta["regime_group"]])
    per_model, cal = [], {}
    for name, model in bundle["models"].items():
        try:
            raw = predict_with_context(model, X_all, j, j + 1)
        except Exception as exc:
            per_model.append({"name": name, "label": REGISTRY[name]["label"], "error": str(exc)[:160]})
            continue
        c = bundle["calibrators"][name].transform(raw)
        cal[name] = c
        w_row = weights["by_regime"].get(int(group[0]), weights["global"]).get(name, 0.0)
        per_model.append({
            "name": name, "label": REGISTRY[name]["label"], "baseline": REGISTRY[name]["baseline"],
            "raw": raw[0].tolist(), "calibrated": c[0].tolist(), "weight": float(w_row),
            "calibration": bundle["calibrators"][name].method, "predicted": CLASSES[int(c[0].argmax())],
            "oos_accuracy": bundle["metrics"].get(name, {}).get("accuracy"),
            "oos_brier": bundle["metrics"].get(name, {}).get("brier"),
        })
    P = ensemble_proba(cal, weights, group)[0]
    if not np.isfinite(P).all():
        raise InsufficientData("no ensemble member produced a prediction")
    cls = int(P.argmax())
    members = [p for p in per_model if "calibrated" in p and not p["baseline"] and p["weight"] > 0]
    wsum = sum(p["weight"] for p in members) or 1.0
    agree_w = sum(p["weight"] for p in members if int(np.argmax(p["calibrated"])) == cls) / wsum
    raw_ens = sum(p["weight"] / wsum * np.array(p["raw"]) for p in members) if members else P
    sigma, price = float(meta["sigma"]), float(meta["close"])
    exp_ret = float(sigma * (P @ bundle["mu"]))
    oos = bundle["oos"]
    vol_state = float(meta["vol_state"]) if np.isfinite(meta["vol_state"]) else 1.0
    return {
        "model_version": bundle["version"], "bar_ts": int(meta["ts"]), "price": price, "sigma": sigma,
        "neutral_band": float(bundle["neutral_band"] * sigma),
        "probabilities": {"down": float(P[0]), "neutral": float(P[1]), "up": float(P[2])},
        "raw_probabilities": {"down": float(raw_ens[0]), "neutral": float(raw_ens[1]), "up": float(raw_ens[2])},
        "predicted_class": cls, "predicted": CLASSES[cls], "p_max": float(P[cls]),
        "model_agreement": float(agree_w), "models_agreeing": int(sum(int(np.argmax(p["calibrated"])) == cls for p in members)),
        "models_total": len(members), "per_model": per_model,
        "regime_weights_used": int(group[0]) in weights["by_regime"],
        "expected_return": exp_ret,
        "distribution": forecast_distribution(price, sigma, exp_ret, oos["z_res"].astype(float)),
        "touch": touch_probabilities(sigma, oos["z_mfe"].astype(float), oos["z_mae"].astype(float), oos["pred"], cls),
        "confidence": confidence_lookup(float(P[cls]), cls, vol_state, oos),
        "vol_state": vol_state,
        "confident_call": _confident(bundle.get("selective"), cls, float(P[cls])),
    }


def _confident(sel: dict[str, Any] | None, cls: int, p: float) -> dict[str, Any] | None:
    """Is this an UP / DOWN call at or above the model's out-of-sample confident-call threshold?"""
    if not sel or sel.get("threshold") is None:
        return None
    return {"is_confident": bool(cls != 1 and p >= sel["threshold"]), "threshold": sel["threshold"],
            "hit_rate": sel["hit_rate"], "coverage": sel["coverage"], "n": sel["n"],
            "base_hit_rate": (sel.get("base") or {}).get("hit_rate")}


def explain_prediction(bundle: dict[str, Any], ds: Dataset, pos: int = -1) -> dict[str, Any] | None:
    X_all = ds.X[bundle["feature_names"]].to_numpy(float)
    x = X_all[pos]
    if not np.isfinite(x).all():
        return None
    out = explain.occlusion_attribution(ensemble_function(bundle), x, bundle["feat_median"], bundle["feature_names"])
    for tree in ("xgboost", "lightgbm", "random_forest"):
        if tree in bundle["models"]:
            sv = explain.shap_tree(bundle["models"][tree], x, bundle["feature_names"])
            if sv:
                out["shap"] = {**sv, "model": REGISTRY[tree]["label"]}
                break
    return out


# ---- persistence -------------------------------------------------------------------------------------

def _summary(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "weights": bundle["weights"]["global"], "weights_by_regime": bundle["weights"]["by_regime"],
        "has_skill": bundle["weights"]["has_skill"], "edge": bundle["edge"], "best_model": bundle["best_model"],
        "folds": bundle["folds"], "live_fit": bundle["live_fit"], "sizes": bundle["sizes"],
        "calibration": {k: {"method": v.get("method"), "reason": v.get("reason")} for k, v in bundle["calibration"].items()},
        "interval_coverage": bundle["interval_coverage"], "reliability": bundle["reliability"],
        "failures": bundle["failures"], "importance": bundle["importance"],
        "models": sorted(bundle["models"]), "uses_btc": bundle["uses_btc"], "fast": bundle.get("fast", False),
        "uses_htf": bundle.get("uses_htf"), "selective": bundle.get("selective"),
    }


def save_bundle(bundle: dict[str, Any], db: Database) -> str:
    Path(settings.model_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(settings.model_dir) / f"{bundle['version']}.joblib")
    joblib.dump(bundle, path, compress=3)
    register(bundle_record(bundle), path, db)
    _cache[f"{bundle['symbol']}|{bundle['timeframe']}"] = bundle
    return path


def bundle_record(bundle: dict[str, Any]) -> dict[str, Any]:
    """Everything the database needs about a trained bundle (lets another machine register it without
    unpickling the models)."""
    metrics = [[model, k, float(v)] for model, mm in bundle["metrics"].items()
               for k, v in mm.items() if isinstance(v, (int, float, np.floating, np.integer)) and not isinstance(v, bool)
               and v is not None and np.isfinite(v)]
    return {"version": bundle["version"], "symbol": bundle["symbol"], "timeframe": bundle["timeframe"],
            "created_at": int(bundle["created_at"]), "data_start": bundle["data_start"], "data_end": bundle["data_end"],
            "n_samples": int(bundle["n_samples"]), "n_oos": int(bundle["n_oos"]),
            "edge_confirmed": int(bundle["edge"]["edge_confirmed"]), "summary": _summary(bundle), "metrics": metrics}


def register(rec: dict[str, Any], path: str, db: Database) -> None:
    db.execute("UPDATE model_versions SET active = 0 WHERE symbol = ? AND timeframe = ?", (rec["symbol"], rec["timeframe"]))
    db.execute(
        "INSERT INTO model_versions (id, symbol, timeframe, created_at, data_start, data_end, n_samples, n_oos, "
        "edge_confirmed, active, path, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
        (rec["version"], rec["symbol"], rec["timeframe"], rec["created_at"], rec["data_start"], rec["data_end"],
         rec["n_samples"], rec["n_oos"], rec["edge_confirmed"], path, dumps(rec["summary"])))
    db.executemany("INSERT INTO model_metrics (model_version_id, model, metric, value) VALUES (?, ?, ?, ?)",
                   [(rec["version"], m, k, v) for m, k, v in rec["metrics"]])


def import_bundle(rec: dict[str, Any], file: str, db: Database) -> bool:
    """Register a bundle trained on another machine. Skipped when a newer model is already active."""
    import shutil

    cur = active_version(rec["symbol"], rec["timeframe"], db)
    if cur is not None and (cur["created_at"] >= rec["created_at"] or cur["id"] == rec["version"]):
        return False
    Path(settings.model_dir).mkdir(parents=True, exist_ok=True)
    path = str(Path(settings.model_dir) / f"{rec['version']}.joblib")
    shutil.copyfile(file, path)
    register(rec, path, db)
    _cache.pop(f"{rec['symbol']}|{rec['timeframe']}", None)
    return True


def prune_files(db: Database, keep_days: float = 7) -> int:
    """Delete model files of versions that are no longer active and older than `keep_days` (the database rows
    stay for the history pages). Keeps the engine state - and its backup - from growing without end."""
    cutoff = int(time.time() * 1000 - keep_days * 86_400_000)
    n = 0
    for r in db.query("SELECT id, path FROM model_versions WHERE active = 0 AND created_at < ? AND path IS NOT NULL", (cutoff,)):
        try:
            p = Path(r["path"])
            if p.exists():
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def active_version(symbol: str, timeframe: str, db: Database) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM model_versions WHERE symbol = ? AND timeframe = ? AND active = 1 "
                 "ORDER BY created_at DESC LIMIT 1", (symbol, timeframe))
    if row:
        row["summary"] = loads(row["summary"], {})
    return row


def load_bundle(symbol: str, timeframe: str, db: Database) -> dict[str, Any] | None:
    key = f"{symbol}|{timeframe}"
    row = active_version(symbol, timeframe, db)
    if row is None:
        return None
    cached = _cache.get(key)
    if cached is not None and cached["version"] == row["id"]:
        return cached
    try:
        bundle = joblib.load(row["path"])
    except Exception as exc:   # model file missing/corrupt: report it instead of predicting from nothing
        log.error("cannot load model %s: %s", row["id"], exc)
        return None
    _cache[key] = bundle
    return bundle


def metrics_table(version_id: str, db: Database) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for r in db.query("SELECT model, metric, value FROM model_metrics WHERE model_version_id = ?", (version_id,)):
        out.setdefault(r["model"], {})[r["metric"]] = r["value"]
    return out


def selective_threshold(P: np.ndarray, y: np.ndarray, fwd: np.ndarray | None = None, min_calls: int = 30,
                        min_coverage: float = 0.08) -> dict[str, Any] | None:
    """Out-of-sample "confident call" threshold.

    A directional call is an UP or DOWN prediction; it is a hit when the next bar's return has that sign (the
    same definition the demo bots use), or, without returns, when the class matches. For each threshold, the walk-forward
    out-of-sample hit rate of the calls at or above it is measured; the threshold with the best lower 95%
    (Wilson) bound is chosen, so a high hit rate on a handful of calls cannot win. Requires at least
    `min_calls` calls and `min_coverage` of all bars. Everything is out-of-sample; nothing is fitted on the
    bars it is scored on beyond picking this one number (reported with its sample size).
    """
    from .metrics import wilson

    if P is None or len(P) < 100:
        return None
    pred = P.argmax(axis=1)
    pmax = P.max(axis=1)
    yy = y.astype(int)
    directional = pred != 1
    curve, best = [], None
    for t in np.round(np.arange(0.34, 0.80, 0.02), 2):
        sel = directional & (pmax >= t)
        n = int(sel.sum())
        if n == 0:
            break
        if fwd is not None:
            k = int((np.sign(fwd[sel]) == np.where(pred[sel] == 2, 1.0, -1.0)).sum())
        else:
            k = int((pred[sel] == yy[sel]).sum())
        lo, hi = wilson(k, n)
        row = {"threshold": float(t), "n": n, "coverage": n / len(P), "hit_rate": k / n, "ci95": [lo, hi]}
        curve.append(row)
        if n >= min_calls and n / len(P) >= min_coverage and (best is None or lo > best["ci95"][0]):
            best = row
    base = curve[0] if curve else None
    if best is None or base is None:
        return {"threshold": None, "curve": curve, "base": base, "reason": "too few out-of-sample calls"}
    return {"threshold": best["threshold"], "hit_rate": best["hit_rate"], "coverage": best["coverage"],
            "n": best["n"], "ci95": best["ci95"], "base": base, "curve": curve,
            "improvement": best["hit_rate"] - base["hit_rate"]}
