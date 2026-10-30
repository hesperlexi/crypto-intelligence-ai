"""v2.6 nightly evidence (train-merge): per coin / timeframe policy, entry rule per timeframe and the pooled trade filter.

Everything is computed from the active models' walk-forward out-of-sample calls (ml/series_policy.py) plus the live
record and the hidden practice (shadow) trades, and cached in app_settings:
  series_policy1|SYMBOL|TF   series gate + grade-B confidence threshold (used when SERIES_GATE / SERIES_CONF are on)
  entry_policy1|TF           entry rule chosen on the older 70 % and kept only if it also wins on the newer 30 %
  trade_filter2|TF           pooled filter summary (+ model file next to the models; used when TRADE_FILTER2 is on)
Budgeted; a failure in one series never stops the others or the merge.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from ..config import MODEL_TIMEFRAMES, settings
from ..db import loads
from ..ml import series_policy as SP, series_sim as S, trade_filter2 as TF2
from .runtime import Runtime

log = logging.getLogger(__name__)
ENTRY_OPTIONS = [("old", 0.0), ("market", 0.0), ("confirm", 0.0), ("confirm", 0.1), ("confirm", 0.25),
                 ("pullback", 0.25), ("pullback", 0.5)]


def record_rows(db: Any, symbol: str, tf: str, cost: float) -> list[dict[str, Any]]:
    """Closed live calls (record and shadow) of a series: R after costs plus what the filter needs."""
    out = []
    for table in ("signals", "shadow_signals"):
        try:
            rows = db.query(f"SELECT * FROM {table} WHERE symbol = ? AND timeframe = ? AND side != 0 AND return_pct IS NOT NULL "
                            "AND status IN ('STOPPED','TP1','TP2','TP3','EXPIRED') ORDER BY created_at", (symbol, tf))
        except Exception:
            continue
        for r in rows:
            if not r.get("entry") or not r.get("stop"):
                continue
            rp = abs(r["entry"] - r["stop"]) / r["entry"] * 100
            if rp:
                out.append({**dict(r), "table": table, "r": (r["return_pct"] - cost) / rp})
    return out


def _record_features(rt: Runtime, symbol: str, tf: str, frames: dict, btc: Any, recs: list[dict[str, Any]]) -> list[tuple]:
    """(features, R, ts) of live calls, rebuilt from the stored forecast of their bar and the frames at that time."""
    if not recs:
        return []
    preds = {}
    for p in rt.db.query("SELECT bar_ts, p_down, p_neutral, p_up FROM predictions WHERE symbol = ? AND timeframe = ?", (symbol, tf)):
        preds[int(p["bar_ts"])] = (p["p_down"], p["p_neutral"], p["p_up"])
    keep = [r for r in recs if int(r["bar_ts"]) in preds]
    if not keep:
        return []
    fake = {"oos": {"ts": np.array([int(r["bar_ts"]) for r in keep], np.int64),
                    "P_ens": np.array([preds[int(r["bar_ts"])] for r in keep], float), "fwd_ret": np.zeros(len(keep))},
            "edge": {"edge_confirmed": True}}
    ctx = SP.build_context(symbol, tf, fake, frames, btc)
    if ctx is None:
        return []
    by_ts = {int(r["bar_ts"]): r for r in keep}
    out = []
    for j in range(ctx.n):
        r = by_ts.get(int(ctx.ts[j]))
        if r is None:
            continue
        pay = loads(r.get("payload"), {}) or {}
        atr = float(ctx.atr[j])
        d = {"side": np.array([int(r["side"])]), "confidence": np.array([r.get("confidence") if r.get("confidence") is not None else np.nan]),
             "grade": np.array([pay.get("grade") or ""]),
             "plan": [{"dist": abs(r["entry"] - r["stop"]), "extended": r["decision"] == "BUY ON PULLBACK"}]}

        class _One:                                         # a one-row view of the context
            pass
        one = _One()
        for name in ("P", "regime_score", "tech", "btc_regime", "btc_tech", "vol_state", "atr", "close"):
            setattr(one, name, getattr(ctx, name)[j:j + 1])
        one.mtf_dir = {t: v[j:j + 1] for t, v in ctx.mtf_dir.items()}
        one.decision_ts = ctx.decision_ts[j:j + 1]
        if atr > 0:
            out.append((TF2.features(one, d, 0), r["r"], int(r["created_at"])))
    return out


def run(rt: Runtime, budget_s: float = 900, symbols: list[str] | None = None) -> dict[str, Any]:
    from ..ml import trainer
    from ..research_engine import _news_fn

    t0 = time.time()
    cost = settings.research_cost_pct
    news = _news_fn(rt.db)
    syms = symbols or rt.symbols()
    done, errors, skipped = 0, [], []
    pool: dict[str, dict[str, list]] = {}
    entry_tbl: dict[str, dict[str, list]] = {}
    for tf in ["3d", "1d", "12h", "4h", "1h", "15m"]:
        for s in syms:
            if time.time() - t0 > budget_s:
                skipped.append(f"{s} {tf}")
                continue
            try:
                bundle = trainer.load_bundle(s, tf, rt.db)
                if bundle is None:
                    continue
                from ..research_engine import _series_frames
                frames = _series_frames(rt, s, tf)
                btc = frames.get(tf) if s.startswith("BTC/") else _frame(rt, "BTC/USDT", tf)
                ctx = SP.build_context(s, tf, bundle, frames, btc)
                if ctx is None or ctx.n < 200:
                    continue
                paths = SP.Paths(rt.candles(s, "15m"), rt.candles(s, tf))
                recs = record_rows(rt.db, s, tf, cost)
                pol = SP.compute(ctx, paths, [r["r"] for r in recs], news=news)
                rt.db.set_setting(SP.key(s, tf), pol)
                allrows = np.ones(ctx.n, bool)
                d = SP.decide(ctx, allrows)
                cut = int(ctx.ts[0]) + int((int(ctx.ts[-1]) - int(ctx.ts[0])) * 0.7)
                for mode, k in ENTRY_OPTIONS:
                    cands = SP.candidates(ctx, paths, allrows, d, entry_mode=mode, k=k, news=news)
                    for part, sel in (("early", lambda c: c["ts"] < cut), ("late", lambda c: c["ts"] >= cut)):
                        tr = SP.taken(ctx, [c for c in cands if sel(c)])
                        entry_tbl.setdefault(tf, {}).setdefault(f"{mode}:{k}|{part}", []).extend(t["r"] for t in tr)
                    if (mode, k) == ("old", 0.0):
                        P = pool.setdefault(tf, {"F": [], "R": [], "ts": []})
                        for c in cands:
                            if c["filled"]:
                                P["F"].append(TF2.features(ctx, d, c["j"]))
                                P["R"].append(c["r"])
                                P["ts"].append(c["ts"])
                for f, r, ts in _record_features(rt, s, tf, frames, btc, recs):
                    P = pool.setdefault(tf, {"F": [], "R": [], "ts": []})
                    P["F"].append(f)
                    P["R"].append(r)
                    P["ts"].append(ts)
                done += 1
            except Exception as exc:              # one series must never stop the others
                log.warning("series policy %s %s failed: %s", s, tf, exc)
                errors.append(f"{s} {tf}: {type(exc).__name__}: {exc}"[:160])
    entry = {}
    for tf, tbl in entry_tbl.items():
        rows = {}
        for mode, k in ENTRY_OPTIONS:
            e, l_ = tbl.get(f"{mode}:{k}|early", []), tbl.get(f"{mode}:{k}|late", [])
            rows[f"{mode}:{k}"] = {"n_early": len(e), "mean_early": float(np.mean(e)) if e else None,
                                   "lb80_early": S.bootstrap_lb(e, 0.8) if len(e) >= 30 else None,
                                   "n_late": len(l_), "mean_late": float(np.mean(l_)) if l_ else None}
        old = rows["old:0.0"]
        cands = [(k, v) for k, v in rows.items() if v["lb80_early"] is not None and v["n_early"] >= 0.3 * max(old["n_early"], 1)]
        best = max(cands, key=lambda kv: kv[1]["lb80_early"])[0] if cands else "old:0.0"
        b = rows[best]
        confirmed = bool(best != "old:0.0" and b["mean_late"] is not None and old["mean_late"] is not None
                         and b["mean_late"] > old["mean_late"])
        entry[tf] = {"at": int(time.time() * 1000), "chosen": best if confirmed else "old:0.0", "best_early": best,
                     "confirmed_late": confirmed, "table": rows}
        rt.db.set_setting(f"entry_policy1|{tf}", entry[tf])
    filters = {}
    for tf, P in pool.items():
        try:
            f = TF2.train(np.array(P["F"]), np.array(P["R"]), np.array(P["ts"]))
            TF2.save(rt.db, tf, f)
            filters[tf] = {k: v for k, v in f.items() if k not in ("model", "features")}
        except Exception as exc:
            errors.append(f"filter2 {tf}: {type(exc).__name__}: {exc}"[:160])
    return {"series": done, "skipped": skipped[:20], "errors": errors[:20], "entry": {k: v["chosen"] for k, v in entry.items()},
            "filters": filters, "seconds": round(time.time() - t0, 1)}


def _frame(rt: Runtime, symbol: str, tf: str) -> Any:
    try:
        return rt.frame(symbol, tf)
    except Exception:
        return None


def entry_rule(db: Any, tf: str) -> tuple[str, float]:
    """The proven entry rule of a timeframe ('old', 0.0 when ENTRY_RULES is off or nothing beat the v2.5 rule)."""
    if not settings.entry_rules:
        return "old", 0.0
    try:
        e = db.get_setting(f"entry_policy1|{tf}", None) or {}
        if time.time() * 1000 - int(e.get("at") or 0) > 3 * 86_400_000:
            return "old", 0.0
        mode, k = (e.get("chosen") or "old:0.0").split(":")
        return mode, float(k)
    except Exception:
        return "old", 0.0


def summary(db: Any) -> dict[str, Any]:
    """Health view: per series whether the gate / threshold / market-data inputs are on."""
    out = {}
    for s in [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1")]:
        for tf in MODEL_TIMEFRAMES:
            p = db.get_setting(SP.key(s, tf), None)
            if not p:
                continue
            out[f"{s} {tf}"] = {"gate": (p.get("gate") or {}).get("verdict"), "mean_r": (p.get("gate") or {}).get("mean_r"),
                                "n": (p.get("gate") or {}).get("n"), "conf_b": p.get("conf_b")}
    return out
