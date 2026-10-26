"""Payload builders shared by the batch engine (published to Firestore) and the local HTTP API.

Every function returns plain data in exactly the shape the website expects.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .backtest.strategies import STRATEGIES
from .config import HORIZONS, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, TIMEFRAMES, settings
from .db import loads, now_ms
from .ml import trainer
from .ml.drift import drift_report
from .ml.models import REGISTRY, model_status
from .services import alerts, backtests, replay, tracking
from .services.runtime import Runtime

ASSET_TIMEFRAMES = ["15m", "1h", "4h", "12h", "1d", "3d", "1w"]


def slug(symbol: str) -> str:
    return symbol.replace("/", "")


def meta(rt: Runtime, engine: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "app": "Crypto Intelligence AI", "mode": "ANALYSIS ONLY", "exchange": rt.exchange,
        "watchlist": rt.watchlist(), "timeframes": TIMEFRAMES, "asset_timeframes": ASSET_TIMEFRAMES,
        "model_timeframes": MODEL_TIMEFRAMES, "mtf_timeframes": MTF_TIMEFRAMES, "horizons": HORIZONS,
        "strategies": {k: {"label": v["label"], "params": v["params"]} for k, v in STRATEGIES.items()},
        "alert_types": alerts.ALERT_TYPES, "models": model_status(),
        "policy": {"min_confidence": settings.min_confidence, "min_model_agreement": settings.min_model_agreement,
                   "min_risk_reward": settings.min_risk_reward, "require_edge_for_ml": settings.require_edge_for_ml,
                   "require_edge_for_trade": settings.require_edge_for_trade, "edge_alpha": settings.edge_alpha,
                   "neutral_band_sigma": settings.neutral_band_sigma},
        "costs": {"fee_rate": settings.fee_rate, "slippage_bps": settings.slippage_bps, "spread_bps": settings.spread_bps},
        "engine": engine or {},
    }


def models(rt: Runtime, symbol: str, tf: str) -> dict[str, Any]:
    b = trainer.load_bundle(symbol, tf, rt.db)
    if b is None:
        return {"symbol": symbol, "timeframe": tf, "available": False, "training": rt.training.get(f"{symbol}|{tf}"),
                "reason": "no trained model for this symbol/timeframe yet", "libraries": model_status()}
    rows = [{"name": k, "label": "Ensemble" if k == "ensemble" else REGISTRY[k]["label"],
             "weight": b["weights"]["global"].get(k), "calibration_method": (b["calibration"].get(k) or {}).get("method"),
             "calibration_reason": (b["calibration"].get(k) or {}).get("reason"), **v} for k, v in b["metrics"].items()]
    return {
        "symbol": symbol, "timeframe": tf, "available": True, "version": b["version"], "trained_at": b["created_at"],
        "fast": b.get("fast", False),
        "n_samples": b["n_samples"], "n_oos": b["n_oos"], "data_start": b["data_start"], "data_end": b["data_end"],
        "models": rows, "weights": b["weights"]["global"], "weights_by_regime": b["weights"]["by_regime"],
        "has_skill": b["weights"]["has_skill"], "edge": b["edge"], "best_model": b["best_model"],
        "folds": b["folds"], "live_fit": b["live_fit"], "sizes": b["sizes"], "fold_reports": b["fold_reports"][-20:],
        "interval_coverage": b["interval_coverage"], "reliability": b["reliability"], "importance": b["importance"],
        "failures": b["failures"], "libraries": b["model_status"], "features": len(b["feature_names"]),
        "selective": b.get("selective"), "uses_htf": b.get("uses_htf"),
        "selection_note": "The best single model is only named as 'supported' if its out-of-sample Brier score is "
                          "significantly better than the class-prior baseline. Model choice never uses RMSE alone.",
    }


def performance_all(rt: Runtime) -> dict[str, Any]:
    rows = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            v = trainer.active_version(s, tf, rt.db)
            if not v:
                continue
            m = trainer.metrics_table(v["id"], rt.db).get("ensemble", {})
            live = tracking.live_stats(rt.db, s, tf, last=100)
            rows.append({"symbol": s, "timeframe": tf, "version": v["id"], "trained_at": v["created_at"],
                         "edge_confirmed": bool(v["edge_confirmed"]), "n_oos": v["n_oos"],
                         "oos_accuracy": m.get("accuracy"), "oos_directional_accuracy": m.get("directional_accuracy"),
                         "oos_brier": m.get("brier"), "oos_sharpe": m.get("sharpe"), "oos_net_return": m.get("net_return"),
                         "oos_max_drawdown": m.get("max_drawdown"), "oos_profit_factor": m.get("profit_factor"),
                         "live_n": live["resolved"], "live_accuracy": live["overall"]["accuracy"],
                         "live_30d": live["rolling"]["30d"]["accuracy"]})
    live = tracking.live_stats(rt.db)
    live.pop("recent", None)
    return {"rows": rows, "live": live, "signals": tracking.signal_summary(rt.db)}


def performance(rt: Runtime, symbol: str, tf: str) -> dict[str, Any]:
    live = tracking.live_stats(rt.db, symbol, tf)
    b = trainer.load_bundle(symbol, tf, rt.db)
    out: dict[str, Any] = {"symbol": symbol, "timeframe": tf, "live": live, "model": None, "drift": None}
    if b is None:
        out["reason"] = "no trained model for this symbol/timeframe yet"
        return out
    out["model"] = {"version": b["version"], "trained_at": b["created_at"], "n_oos": b["n_oos"],
                    "ensemble": b["metrics"]["ensemble"], "edge": b["edge"], "reliability": b["reliability"],
                    "interval_coverage": b["interval_coverage"],
                    "source": "walk-forward out-of-sample predictions (never seen during fitting)"}
    try:
        ds = rt.dataset(symbol, tf, b["uses_btc"])
        X = ds.X[b["feature_names"]].to_numpy(float)
        recent = X[np.isfinite(X).all(axis=1)][-200:]
        preds = rt.db.query("SELECT p_up FROM predictions WHERE symbol = ? AND timeframe = ? ORDER BY bar_ts DESC LIMIT 200",
                            (symbol, tf))
        p_up = np.array([p["p_up"] for p in preds], float) if len(preds) >= 30 else None
        out["drift"] = drift_report(b, recent, p_up, float(ds.X["vol_pct"].iloc[-1]), tracking.performance_windows(rt.db, b))
    except Exception as exc:
        out["drift"] = {"drift_detected": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


def models_status(rt: Runtime) -> dict[str, Any]:
    rows = list(rt.training.values())
    for s in rt.symbols():          # the engine is short-lived: fill in active versions from the database
        for tf in MODEL_TIMEFRAMES:
            key = f"{s}|{tf}"
            if key in rt.training:
                continue
            v = trainer.active_version(s, tf, rt.db)
            if v:
                rows.append({"symbol": s, "timeframe": tf, "state": "done", "progress": 1.0, "version": v["id"],
                             "message": "NO STATISTICALLY CONFIRMED EDGE" if not v["edge_confirmed"] else "edge confirmed",
                             "finished_at": v["created_at"], "fast": (v.get("summary") or {}).get("fast")})
    return {"training": rows, "libraries": model_status()}


def signals(rt: Runtime) -> dict[str, Any]:
    return {"signals": tracking.signal_history(rt.db, None, 300), "summary": tracking.signal_summary(rt.db)}


def alerts_view(rt: Runtime, user_id: str | None = None) -> dict[str, Any]:
    """Alert state and fired events. With `user_id`, only that user's rules (members never see each other's)."""
    rows = rt.db.query("SELECT * FROM alerts" + (" WHERE user_id = ?" if user_id else ""), (user_id,) if user_id else ())
    state = {a["id"]: {"last_fired_at": a["last_fired_at"], "last_state": a["last_state"]} for a in rows}
    if user_id:
        # this member's own events, however many other members there are
        ids = list(state)
        evs = rt.db.query(f"SELECT * FROM alert_events WHERE alert_id IN ({','.join('?' * len(ids))}) "
                          "ORDER BY created_at DESC LIMIT 100", tuple(ids)) if ids else []
    else:
        evs = alerts.events(rt.db, 100)
    return {"events": evs[:100], "state": state, "types": alerts.ALERT_TYPES}


def backtest_history(rt: Runtime) -> list[dict[str, Any]]:
    return backtests.history(rt)


def replay_ranges(rt: Runtime) -> dict[str, Any]:
    return {f"{slug(s)}_{tf}": replay.replay_range(rt, s, tf) for s in rt.symbols() for tf in FUTURES_TIMEFRAMES}


def settings_view(rt: Runtime) -> dict[str, Any]:
    return {"risk_profile": rt.risk_profile().__dict__, "signal_weights": rt.signal_weights(), "generated_at": now_ms()}


# ---- futures -----------------------------------------------------------------------------------------------
FUTURES_TIMEFRAMES = ("15m", "1h", "4h", "12h", "1d", "3d")


def futures(rt: Runtime, timeframe: str, analyses: dict[tuple[str, str], dict]) -> dict[str, Any]:
    from .engine import futures as F

    funding = getattr(rt, "funding_rates", None) or {}
    rows = [F.futures_view(analyses[(s, timeframe)], funding.get(s)) for s in rt.symbols() if (s, timeframe) in analyses]
    order = {"LONG": 0, "LONG ON PULLBACK": 0, "SHORT": 0, "NO TRADE": 1}
    rows.sort(key=lambda r: (order.get(r.get("action"), 2), -(r.get("confidence") or 0)))
    return {
        "timeframe": timeframe, "rows": rows,
        "funding_source": f"{next(iter(funding.values())).get('source') or 'Binance futures'} (live)" if funding else
            f"assumed {F.DEFAULT_FUNDING_RATE * 100:.2f}% per 8h: Binance's futures API is not reachable from the engine's "
            "server, your browser shows the live rate",
        "assumptions": {"maintenance_margin": F.MAINTENANCE_MARGIN, "fee_rate": F.FUTURES_FEE_RATE,
                        "max_suggested_leverage": 10, "liquidation_buffer": 1.5},
    }


# ---- public track record ---------------------------------------------------------------------------------------

def record_since(rt: Runtime) -> int:
    """Start of the counted record: the v2.0 launch (older signals stay in the database, labelled as the old engine)."""
    return int(rt.db.get_setting("record_since", 0) or 0)


def track_record(rt: Runtime, bot_report: dict[str, Any] | None = None, limit: int = 150) -> dict[str, Any]:
    """Everything a visitor needs to judge the app honestly, readable without an account (views/track_record):
    every trade signal since launch with its real outcome, the models' results on past data they never trained on
    (clearly a simulation), and the demo bots' results. Nothing is filtered for looks."""
    import numpy as np

    from .ml import direction as dirview, trainer

    since0 = record_since(rt)
    rows = rt.db.query("SELECT * FROM signals WHERE status != 'INFO' AND created_at >= ? ORDER BY created_at DESC", (since0,))
    sigs = []
    for r in rows:
        p = loads(r.get("payload"), {}) if isinstance(r.get("payload"), str) else (r.get("payload") or {})
        sigs.append({"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
                     "decision": r["decision"], "grade": p.get("grade"), "created_at": r["created_at"], "entry": r["entry"],
                     "stop": r["stop"], "tp1": r["tp1"], "tp2": r["tp2"], "tp3": r["tp3"], "status": r["status"],
                     "closed_at": r["closed_at"], "return_pct": r["return_pct"]})
    closed = [x for x in sigs if x["status"] not in ("OPEN",) and x["return_pct"] is not None]

    def summ(xs: list[dict[str, Any]]) -> dict[str, Any]:
        r = np.array([x["return_pct"] for x in xs], float)
        if not len(r):
            return {"closed": 0}
        wins = r[r > 0]
        losses = r[r <= 0]
        return {"closed": int(len(r)), "win_rate": float((r > 0).mean()), "avg_return_pct": float(r.mean()),
                "total_return_pct": float(r.sum()), "best_pct": float(r.max()), "worst_pct": float(r.min()),
                "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else None}

    by_tf = {tf: summ([x for x in closed if x["timeframe"] == tf]) for tf in sorted({x["timeframe"] for x in closed})}
    by_grade = {g: summ([x for x in closed if (x["grade"] or "-") == g]) for g in sorted({x["grade"] or "-" for x in closed})}
    curve, acc = [], 0.0
    for x in sorted(closed, key=lambda x: x["closed_at"] or x["created_at"]):
        acc += x["return_pct"]
        curve.append({"ts": x["closed_at"] or x["created_at"], "cum_return_pct": acc})

    tested = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            try:
                b = trainer.load_bundle(s, tf, rt.db)
            except Exception:
                b = None
            if not b:
                continue
            pol = dirview.direction_policy(b.get("oos") or {}, b.get("version"))
            if not pol:
                continue
            best = pol.get("best") or {}
            o = b.get("oos") or {}
            ts = o.get("ts")
            days = (int(ts[-1]) - int(ts[0])) / 86_400_000 if ts is not None and len(ts) > 1 else None
            tested.append({"symbol": s, "timeframe": tf, "edge": pol.get("edge"), "all_calls_hit_rate": pol.get("base_hit_rate"),
                           "selective_hit_rate": best.get("hit_rate"), "selective_ci95": best.get("ci95"),
                           "selective_calls": best.get("n"), "coverage": best.get("coverage"), "tested_days": days,
                           "calls_per_day": (best.get("n") / days) if best.get("n") and days else None})
    bots = []
    for bt in (bot_report or {}).get("bots", []):
        st, cfg = bt.get("stats") or {}, bt.get("config") or {}
        if not cfg.get("enabled", True):
            continue
        from .services.bots import SCORECARD_IDS
        bots.append({"scorecard": cfg.get("id") in SCORECARD_IDS, "name": cfg.get("name") or cfg.get("id"), "mode": cfg.get("mode"), "market": cfg.get("market", "spot"), "timeframe": cfg.get("timeframe"),
                     "grades": cfg.get("grades"), "trades": st.get("trades"), "return_pct": st.get("return_pct"),
                     "benchmark_return_pct": st.get("benchmark_return_pct"), "win_rate": st.get("win_rate"),
                     "max_drawdown_pct": st.get("max_drawdown_pct"), "started_at": (bt.get("state") or {}).get("started_at")})
    first = min((x["created_at"] for x in sigs), default=None)
    out = {"generated_at": now_ms(), "since": first, "record_since": since0 or None, "live": {"summary": summ(closed), "by_timeframe": by_tf,
            "by_grade": by_grade, "open": sum(x["status"] == "OPEN" for x in sigs), "curve": curve[-500:],
            "signals": sigs[:limit]},
            "tested": sorted(tested, key=lambda t: (not t["edge"], -(t["selective_hit_rate"] or 0))),
            "bots": sorted(bots, key=lambda b: not b["scorecard"]),
            "method": {"live": "Every trade signal the engine published, followed candle by candle: a third of the position "
                               "exits at each take-profit, the rest at the stop or after 30 candles. Fees not included.",
                       "tested": "Walk-forward test: the models are trained only on data before each test period and then "
                                 "scored on the following period, which they never saw. A simulation, not live results."}}
    out["achievements"] = achievements(rt, out, bot_report)
    return out


# ---- weekly report (marketing, built on the full record) ------------------------------------------------------

WEEK = 7 * 86_400_000


def week_start(ts: int) -> int:
    """Monday 00:00 UTC of the week containing ts (1970-01-01 was a Thursday)."""
    return ts - ((ts - 4 * 86_400_000) % WEEK)


def weekly_report(rt: Runtime, start: int, bot_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Signals that CLOSED in [start, start + 1 week): best trades first, but with the complete totals (wins and
    losses), so the report can be posted as it is without misleading anyone."""
    import numpy as np

    from .services.bots import SCORECARD_IDS

    end = start + WEEK
    rows = rt.db.query("SELECT * FROM signals WHERE status NOT IN ('OPEN', 'INFO') AND return_pct IS NOT NULL "
                       "AND closed_at >= ? AND closed_at < ? AND created_at >= ? ORDER BY return_pct DESC", (start, end, record_since(rt)))
    issued = rt.db.one("SELECT COUNT(*) AS n FROM signals WHERE status != 'INFO' AND created_at >= ? AND created_at < ?",
                       (max(start, record_since(rt)), end))["n"]
    trades = []
    for r in rows:
        p = loads(r.get("payload"), {}) if isinstance(r.get("payload"), str) else (r.get("payload") or {})
        trades.append({"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
                       "grade": p.get("grade"), "entry": r["entry"], "status": r["status"], "return_pct": r["return_pct"],
                       "created_at": r["created_at"], "closed_at": r["closed_at"]})
    rets = np.array([t["return_pct"] for t in trades], float)
    wins = [t for t in trades if t["return_pct"] > 0]
    by_coin: dict[str, float] = {}
    for t in trades:
        by_coin[t["symbol"]] = by_coin.get(t["symbol"], 0.0) + t["return_pct"]
    bots = []
    for bt in (bot_report or {}).get("bots", []):
        cfg = bt.get("config") or {}
        if cfg.get("id") not in SCORECARD_IDS:
            continue
        eq = rt.db.query("SELECT ts, equity FROM bot_equity WHERE bot_id = ? AND ts < ? ORDER BY ts", (cfg["id"], end))
        before = [e for e in eq if e["ts"] < start]
        e0 = before[-1]["equity"] if before else (eq[0]["equity"] if eq else None)
        e1 = eq[-1]["equity"] if eq else None
        bots.append({"name": cfg.get("name"), "week_return_pct": (e1 / e0 - 1) * 100 if e0 and e1 else None,
                     "total_return_pct": (bt.get("stats") or {}).get("return_pct")})
    radar_best = None
    try:
        r = rt.db.one("SELECT symbol, ret_7d, btc_ret_7d FROM radar_picks WHERE evaluated_at >= ? AND evaluated_at < ? "
                      "ORDER BY ret_7d - btc_ret_7d DESC LIMIT 1", (start, end))
        if r:
            radar_best = {"symbol": r["symbol"], "ret_7d_pct": r["ret_7d"] * 100, "vs_btc_pct": (r["ret_7d"] - r["btc_ret_7d"]) * 100}
    except Exception:
        pass
    return {"week_start": start, "week_end": end, "generated_at": now_ms(), "complete": now_ms() >= end,
            "issued": issued, "closed": len(trades), "wins": len(wins), "losses": len(trades) - len(wins),
            "win_rate": float(len(wins) / len(trades)) if trades else None,
            "total_return_pct": float(rets.sum()) if len(rets) else None,
            "avg_return_pct": float(rets.mean()) if len(rets) else None,
            "best": trades[:5], "worst": trades[-1] if trades else None,
            "best_coin": max(by_coin.items(), key=lambda kv: kv[1])[0] if by_coin else None,
            "scorecard_bots": bots, "radar_best": radar_best,
            "basis": "Signals that closed this week; each return assumes equal size, a third closed at each target, before fees."}


def weekly_reports(rt: Runtime, bot_report: dict[str, Any] | None = None, weeks: int = 12) -> dict[str, Any]:
    """This week so far, last week, and the archive (newest first)."""
    now = now_ms()
    cur = week_start(now)
    first = rt.db.one("SELECT MIN(created_at) AS t FROM signals WHERE status != 'INFO' AND created_at >= ?", (record_since(rt),))
    first_ts = int(first["t"]) if first and first["t"] else cur
    out = []
    for i in range(weeks):
        st = cur - i * WEEK
        if st + WEEK <= first_ts:
            break
        out.append(weekly_report(rt, st, bot_report))
    return {"generated_at": now, "reports": out}


# ---- achievements (marketing badges, computed from the real record only) ----------------------------------------

def achievements(rt: Runtime, track: dict[str, Any], bot_report: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Milestones the app has really reached. Locked ones show progress; nothing is unlocked by hand."""
    import numpy as np

    rows = rt.db.query("SELECT symbol, side, status, return_pct, closed_at FROM signals "
                       "WHERE status NOT IN ('OPEN', 'INFO') AND return_pct IS NOT NULL AND created_at >= ? ORDER BY closed_at",
                       (record_since(rt),))
    out: list[dict[str, Any]] = []

    def add(aid, title, unlocked, value, detail, at=None, progress=None):
        out.append({"id": aid, "title": title, "unlocked": bool(unlocked), "value": value, "detail": detail,
                    "achieved_at": at if unlocked else None, "progress": None if unlocked else progress})

    n = len(rows)
    for goal in (10, 50, 100, 250, 500, 1000):
        hit = rows[goal - 1]["closed_at"] if n >= goal else None
        add(f"signals_{goal}", f"{goal} signals delivered", n >= goal, f"{goal}", f"{goal} trade signals published and followed to the end", hit,
            min(1.0, n / goal))
        if n < goal:
            break
    if rows:
        best = max(rows, key=lambda r: r["return_pct"])
        add("best_trade", "Best signal", best["return_pct"] > 0, f"+{best['return_pct']:.1f}%",
            f"{best['symbol'].split('/')[0]} {'long' if best['side'] > 0 else 'short'}", best["closed_at"])
    streak = best_streak = 0
    streak_end = None
    for r in rows:
        streak = streak + 1 if r["return_pct"] > 0 else 0
        if streak > best_streak:
            best_streak, streak_end = streak, r["closed_at"]
    add("win_streak", "Winning streak", best_streak >= 3, f"{best_streak} in a row", "consecutive winning signals",
        streak_end, min(1.0, best_streak / 3))
    tp3 = [r for r in rows if r["status"] == "TP3"]
    add("all_targets", "All targets hit", len(tp3) >= 1, f"{len(tp3)}x", "signals that reached take-profit 3",
        tp3[-1]["closed_at"] if tp3 else None, 0.0)
    weeks: dict[int, float] = {}
    for r in rows:
        weeks[week_start(int(r["closed_at"]))] = weeks.get(week_start(int(r["closed_at"])), 0.0) + r["return_pct"]
    green = sorted(w for w, v in weeks.items() if v > 0)
    if weeks:
        bw = max(weeks.items(), key=lambda kv: kv[1])
        add("best_week", "Best week", bw[1] > 0, f"+{bw[1]:.1f}%", "total of all signals closed that week", bw[0] + WEEK - 1)
    add("green_weeks", "Profitable weeks", len(green) >= 2, f"{len(green)} of {len(weeks)}", "weeks that closed in profit",
        green[-1] + WEEK - 1 if green else None, min(1.0, len(green) / 2))
    recent = [r for r in rows if r["closed_at"] >= now_ms() - 30 * 86_400_000]
    wr = float(np.mean([r["return_pct"] > 0 for r in recent])) if recent else 0.0
    add("win_rate_30d", "55%+ win rate this month", len(recent) >= 20 and wr >= 0.55, f"{wr:.0%}",
        f"over {len(recent)} signals in the last 30 days", now_ms(), min(1.0, len(recent) / 20) if len(recent) < 20 else wr / 0.55)
    for b in (bot_report or {}).get("bots", []):
        from .services.bots import SCORECARD_IDS
        cfg, st = b.get("config") or {}, b.get("stats") or {}
        if cfg.get("id") in SCORECARD_IDS and st.get("trades"):
            beat = (st.get("return_pct") or 0) > (st.get("benchmark_return_pct") or 0) and (st.get("return_pct") or 0) > 0
            add(f"bot_{cfg['id']}", f"Beat buy & hold · {cfg.get('timeframe', '').upper()}", beat and st["trades"] >= 10,
                f"{st.get('return_pct', 0):+.1f}%", f"scorecard bot vs {st.get('benchmark_return_pct') or 0:+.1f}% for holding",
                now_ms(), min(1.0, st["trades"] / 10))
    try:
        r = rt.db.one("SELECT symbol, ret_7d, btc_ret_7d, evaluated_at FROM radar_picks WHERE evaluated_at IS NOT NULL "
                      "ORDER BY ret_7d - btc_ret_7d DESC LIMIT 1")
        if r:
            ex = (r["ret_7d"] - r["btc_ret_7d"]) * 100
            add("radar_star", "Radar star pick", ex >= 10, f"+{r['ret_7d'] * 100:.0f}%",
                f"{r['symbol'].split('/')[0]} in 7 days ({ex:+.0f}% vs BTC)", r["evaluated_at"], max(0.0, min(1.0, ex / 10)))
    except Exception:
        pass
    edge = [t for t in track.get("tested", []) if t.get("edge")]
    add("proven_edges", "Proven AI edges", len(edge) >= 5, f"{len(edge)}", "coin/timeframes where the AI beat a coin flip on unseen data",
        now_ms(), min(1.0, len(edge) / 5))
    if track.get("since"):
        days = (now_ms() - track["since"]) / 86_400_000
        for goal in (30, 90, 180, 365):
            add(f"live_{goal}", f"{goal} days of public results", days >= goal, f"{int(days)} days", "every signal public since launch",
                track["since"] + goal * 86_400_000, min(1.0, days / goal))
            if days < goal:
                break
    return sorted(out, key=lambda a: (not a["unlocked"], -(a["achieved_at"] or 0)))


def wins_today(rt: Runtime, limit: int = 6) -> dict[str, Any]:
    """Public highlights for the sign-in page: winning signals closed in the last 24 h (else the last 7 days)."""
    now = now_ms()
    for hours, label in ((24, "today"), (24 * 7, "this week")):
        rows = rt.db.query("SELECT * FROM signals WHERE status NOT IN ('OPEN', 'INFO') AND return_pct > 0 AND closed_at >= ? "
                           "AND created_at >= ? ORDER BY return_pct DESC LIMIT ?", (now - hours * 3_600_000, record_since(rt), limit))
        if rows:
            break
    wins = [{"symbol": r["symbol"], "timeframe": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
             "entry": r["entry"], "status": r["status"], "return_pct": r["return_pct"], "closed_at": r["closed_at"],
             "target": {"TP1": r["tp1"], "TP2": r["tp2"], "TP3": r["tp3"]}.get(r["status"])} for r in rows]
    return {"generated_at": now, "period": label if wins else None, "wins": wins}
