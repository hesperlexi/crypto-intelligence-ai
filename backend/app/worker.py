"""Batch engine for the Firebase deployment (runs on a schedule, e.g. GitHub Actions every 15 minutes).

  python -m app.worker tick  [--budget 600] [--local DIR]     one engine cycle
  python -m app.worker train [--budget 2700] [--local DIR]    upgrade / refresh models (full model set)

One cycle:
  1. read the website's configuration from Firestore (watchlist, settings, alert rules, demo bots)
  2. update candles incrementally, take a ticker + order-book snapshot, fetch market context
  3. score outcomes of earlier predictions and signals
  4. train any missing model with the fast model set (bootstrap)
  5. run every analysis, evaluate alerts, run the demo bots, process queued jobs (backtests, replays ...)
  6. publish the results as Firestore documents (unchanged documents are skipped)
State (candles, models, predictions, bot books) lives in a local SQLite file that the scheduler caches
between runs; Firestore holds only what the website shows.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

from .config import MODEL_TIMEFRAMES, settings
from .db import Database, dumps, get_db, loads, new_id, now_ms
from .engine.signal import optimise_weights
from .features.dataset import InsufficientData
from .ml import trainer
from .ml.models import default_models, model_status
from .services import alerts, analysis, backtests, health, market, membership, replay, scanner, tracking, training
from .services.bots import DEFAULT_BOTS, BotEngine
from .services.runtime import USER, Runtime
from .sinks import BaseSink, FirestoreSink, LocalSink
from . import views

log = logging.getLogger("engine")
SCHEDULE_MIN = 15
HOURLY_TFS = {"12h", "1d", "3d", "1w"}


class StaticFeed:
    """Ticker snapshot taken once per cycle (the website streams live prices itself)."""

    def __init__(self, tickers: dict[str, dict[str, Any]], error: str | None = None):
        self.tickers = tickers
        self.taken_ms = now_ms()
        self.error = error

    def set_symbols(self, symbols: list[str]) -> None:
        return None

    def publish(self, message: dict[str, Any]) -> None:
        return None

    def health(self) -> dict[str, Any]:
        ok = bool(self.tickers)
        return {"status": "OK" if ok else "DOWN", "transport": "engine snapshot (website streams live prices)",
                "last_update_ms": self.taken_ms, "age_s": (now_ms() - self.taken_ms) / 1000, "reconnects": 0,
                "symbols": len(self.tickers), "last_error": self.error}


def norm_symbol(raw: str) -> str:
    s = str(raw).upper().replace("-", "/").replace("_", "/")
    if "/" not in s:
        s = f"{s[:-4]}/USDT" if s.endswith("USDT") and len(s) > 4 else f"{s}/USDT"
    return s


# ---- configuration from the website --------------------------------------------------------------------

def sync_config(rt: Runtime, sink: BaseSink) -> dict[str, Any]:
    notes: dict[str, Any] = {}
    # watchlist
    doc = sink.get("config/watchlist")
    if doc is None or not isinstance(doc.get("symbols"), list):
        sink.set("config/watchlist", {"symbols": [{"symbol": w["symbol"], "pinned": bool(w["pinned"])}
                                                  for w in rt.watchlist()], "updated_at": now_ms()})
    else:
        wanted = {}
        for item in doc["symbols"]:
            sym = norm_symbol(item["symbol"] if isinstance(item, dict) else item)
            wanted[sym] = bool(item.get("pinned")) if isinstance(item, dict) else False
        current = set(rt.symbols())
        rejected = []
        for sym in set(wanted) - current:
            try:
                ok = sym in asyncio.run(rt.provider.search_markets(sym.split("/")[0], 50))
            except Exception:
                ok = True            # lookup failed: accept, candle sync will report a bad symbol
            if ok:
                rt.add_symbol(sym)
            else:
                rejected.append(sym)
        for sym in current - set(wanted):
            rt.remove_symbol(sym)
        for sym, pinned in wanted.items():
            rt.pin_symbol(sym, pinned)
        if rejected:
            notes["rejected_symbols"] = rejected
    # settings
    doc = sink.get("config/settings") or {}
    if isinstance(doc.get("risk_profile"), dict):
        from .engine.risk import RiskProfile

        rt.db.set_setting("risk_profile", RiskProfile.from_dict(doc["risk_profile"]).__dict__)
    if isinstance(doc.get("signal_weights"), dict):
        w = {k: max(0.0, float(v)) for k, v in doc["signal_weights"].items() if k in rt.signal_weights()}
        if sum(w.values()) > 0:
            rt.db.set_setting("signal_weights", w)
    # memberships: pause the alerts of people who are no longer active; payment / renewal notifications
    users = dict(sink.list("users"))
    now = now_ms()
    inactive = membership.inactive_uids(users, now)
    msgs, seen = membership.notifications(users, rt.db.get_setting("membership_notified", {}), now)
    if msgs:
        notes["membership_push"] = sink.send_push(msgs)
    rt.db.set_setting("membership_notified", seen)
    if inactive:
        notes["inactive_members"] = len(inactive)
    # alert rules (website) -> local table, keeping the debounce state
    remote = dict(sink.list("alerts"))
    local = {a["id"]: a for a in rt.db.query("SELECT * FROM alerts")}
    for aid in set(local) - set(remote):
        rt.db.execute("DELETE FROM alerts WHERE id = ?", (aid,))
    for aid, a in remote.items():
        if a.get("type") not in alerts.ALERT_TYPES or not a.get("symbol"):
            continue
        row = (a["type"], norm_symbol(a["symbol"]), a.get("timeframe", "4h"), dumps(a.get("params") or {}),
               int(a.get("cooldown_s", 3600)), int(bool(a.get("enabled", True)) and a.get("owner_uid") not in inactive))
        if aid in local:
            rt.db.execute("UPDATE alerts SET type = ?, symbol = ?, timeframe = ?, params = ?, cooldown_s = ?, enabled = ?, "
                          "user_id = ? WHERE id = ?", (*row, a.get("owner_uid") or USER, aid))
        else:
            rt.db.execute("INSERT INTO alerts (id, user_id, type, symbol, timeframe, params, cooldown_s, enabled, created_at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (aid, a.get("owner_uid") or USER, *row, int(a.get("created_at") or now_ms())))
    # demo bots
    doc = sink.get("config/bots")
    if doc is None or not isinstance(doc.get("bots"), list):
        sink.set("config/bots", {"bots": DEFAULT_BOTS, "updated_at": now_ms(),
                                 "defaults_added": [b["id"] for b in DEFAULT_BOTS]})
        bots_cfg = DEFAULT_BOTS
    else:
        bots_cfg = doc["bots"]
        # one-time additions: default bots introduced in a later version are added once (deleting them later sticks)
        seen = set(doc.get("defaults_added") or [b.get("id") for b in bots_cfg])
        new = [b for b in DEFAULT_BOTS if b["id"] not in seen and b["id"] not in {x.get("id") for x in bots_cfg}]
        if new or not doc.get("defaults_added"):
            bots_cfg = bots_cfg + new
            sink.set("config/bots", {**doc, "bots": bots_cfg, "updated_at": now_ms(),
                                     "defaults_added": sorted(seen | {b["id"] for b in DEFAULT_BOTS})})
    BotEngine(rt).sync_configs(bots_cfg)
    return notes


# ---- jobs queued by the website ---------------------------------------------------------------------------

def run_job(rt: Runtime, job: dict[str, Any], deadline: float, sink: BaseSink | None = None) -> dict[str, Any]:
    kind, p = job.get("type"), job.get("params") or {}
    if kind == "test_push":
        if sink is None:
            return {"ok": False, "reason": "no publisher"}
        m = {"title": "Test notification", "body": "Notifications from Crypto Intelligence AI work on this device.",
             "url": "/settings", "tag": "test"}
        if p.get("uid"):
            m["uid"] = str(p["uid"])
        res = sink.send_push([m])
        return {"ok": res.get("sent", 0) > 0, **res}
    if kind == "backtest":
        p = {**p, "symbol": norm_symbol(p["symbol"])}
        return backtests.run(rt, p)
    if kind == "replay":
        return replay.replay(rt, norm_symbol(p["symbol"]), p.get("timeframe", "4h"), int(p["as_of"]),
                             int(p.get("bars_after", 30)), bool(p.get("with_model", True)))
    if kind == "optimise_weights":
        try:
            fr = rt.frame(norm_symbol(p["symbol"]), p.get("timeframe", "4h"))
        except InsufficientData as exc:
            return {"ok": False, "reason": str(exc)}
        return optimise_weights(fr.ind, fr.ind["close"].shift(-1) / fr.ind["close"] - 1)
    if kind == "train":
        syms = [norm_symbol(p["symbol"])] if p.get("symbol") else rt.symbols()
        tfs = [p["timeframe"]] if p.get("timeframe") else MODEL_TIMEFRAMES
        done, left = [], []
        for s in syms:
            for tf in tfs:
                if time.time() > deadline:
                    left.append(f"{s} {tf}")
                    continue
                st = training.train_one(rt, s, tf, fast=bool(p.get("fast", True)))
                done.append({"pair": f"{s} {tf}", "state": st["state"], "message": st.get("error") or st.get("message")})
        return {"trained": done, "not_reached": left,
                "note": "Pairs not reached in this cycle are trained by the daily training run." if left else None}
    raise ValueError(f"unknown job type {kind!r}")


def process_jobs(rt: Runtime, sink: BaseSink, deadline: float) -> int:
    n = 0
    for jid, job in sink.queued_jobs():
        if time.time() > deadline:
            break
        sink.set(f"jobs/{jid}", {"status": "running", "started_at": now_ms()}, merge=True)
        try:
            result = run_job(rt, job, deadline, sink)
            sink.set(f"jobs/{jid}", {"status": "done", "json": dumps(result), "finished_at": now_ms()}, merge=True)
        except Exception as exc:
            log.exception("job %s failed", jid)
            sink.set(f"jobs/{jid}", {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300],
                                     "finished_at": now_ms()}, merge=True)
        n += 1
    cutoff = now_ms() - 3 * 86_400_000
    for jid, job in sink.list("jobs"):
        if (job.get("finished_at") or job.get("created_at") or now_ms()) < cutoff:
            sink.delete(f"jobs/{jid}")
    return n


# ---- training ---------------------------------------------------------------------------------------------

def pairs_needing_full(rt: Runtime) -> list[tuple[str, str]]:
    """Models missing, trained with the fast set only, missing a now-available model family, or older than
    RETRAIN_INTERVAL_H - oldest first."""
    out = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            if not rt.store.is_current(rt.exchange, s, tf):
                continue
            v = trainer.active_version(s, tf, rt.db)
            if v is None:
                out.append((0, s, tf))
            elif (v.get("summary") or {}).get("fast") or now_ms() - v["created_at"] > settings.retrain_interval_h * 3.6e6 \
                    or _missing_models(v.get("summary") or {}):
                # also retrain when a model family became available after this bundle was trained (e.g. torch)
                out.append((v["created_at"], s, tf))
    return [(s, tf) for _, s, tf in sorted(out)]


def _missing_models(summary: dict[str, Any]) -> bool:
    """A model family is installed now but this bundle has neither trained nor tried it."""
    tried = set(summary.get("models") or []) | set((summary.get("failures") or {}).keys())
    return bool(set(default_models()) - tried)


def train_until(rt: Runtime, pairs: list[tuple[str, str]], fast: bool, deadline: float) -> list[dict[str, Any]]:
    out = []
    for s, tf in pairs:
        if time.time() > deadline:
            break
        st = training.train_one(rt, s, tf, fast=fast)
        out.append({"pair": f"{s} {tf}", "state": st["state"], "seconds": st.get("seconds"),
                    "message": st.get("error") or st.get("message")})
        log.info("trained %s %s: %s", s, tf, st["state"])
    return out


# ---- publishing -------------------------------------------------------------------------------------------

def push_message(ev: dict[str, Any], owner: str | None = None) -> dict[str, str]:
    title = {"TRADE_SETUP": "Trade signal", "BUY_SIGNAL": "Buy signal", "SELL_SIGNAL": "Sell signal"}.get(
        ev.get("type"), (ev.get("type") or "Alert").replace("_", " ").title())
    msg = {"title": f"{title} · {ev.get('symbol', '')}", "body": ev.get("message", ""), "url": "/alerts",
           "tag": ev.get("id", "")}
    if owner and owner != USER:
        msg["uid"] = owner            # only this member's devices; without it, the admins' devices
    return msg


def publish(rt: Runtime, sink: BaseSink, engine: dict[str, Any], now: int, analyses: dict[tuple[str, str], dict]) -> None:
    for (s, tf), a in analyses.items():
        sink.view(f"analysis_{views.slug(s)}_{tf}", a)
    for tf in MODEL_TIMEFRAMES:
        sink.view(f"dashboard_{tf}", scanner.dashboard(rt, tf))
    publish_models(rt, sink)
    sink.view("performance", views.performance_all(rt))
    sink.view("signals", views.signals(rt))
    sink.view("alerts", views.alerts_view(rt, USER))
    for uid in {r["user_id"] for r in rt.db.query("SELECT DISTINCT user_id FROM alerts")} - {USER}:
        sink.view(f"alerts_u_{uid}", views.alerts_view(rt, uid))    # each member reads only their own
    sink.view("backtests", views.backtest_history(rt))
    sink.view("replay_ranges", views.replay_ranges(rt))
    sink.view("cross_asset_1d", scanner.cross_asset(rt, "1d"))
    sink.view("bots", BotEngine(rt).report())
    for tf in views.FUTURES_TIMEFRAMES:
        if all((s, tf) in analyses for s in rt.symbols()):
            sink.view(f"futures_{tf}", views.futures(rt, tf, analyses))
    sink.view("settings", views.settings_view(rt))
    ctx = rt.context_cache[1] if rt.context_cache else {"enabled": False, "reason": "not fetched"}
    sink.view("context", ctx, volatile=("fetched_at",))
    publish_status(rt, sink, engine)


def publish_models(rt: Runtime, sink: BaseSink) -> None:
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            sink.view(f"models_{views.slug(s)}_{tf}", views.models(rt, s, tf))
            sink.view(f"perf_{views.slug(s)}_{tf}", views.performance(rt, s, tf))
    sink.view("models_status", views.models_status(rt))


def publish_status(rt: Runtime, sink: BaseSink, engine: dict[str, Any]) -> None:
    h = health.report(rt)
    h["engine"] = engine
    sink.view("health", h, volatile=())
    sink.view("meta", views.meta(rt, engine), volatile=())


def engine_info(rt: Runtime, current: dict[str, Any]) -> dict[str, Any]:
    last_train = rt.db.one("SELECT * FROM engine_runs WHERE kind = 'train' ORDER BY started_at DESC LIMIT 1")
    ticks = rt.db.one("SELECT COUNT(*) AS n FROM engine_runs WHERE kind = 'tick'")["n"]
    return {**current, "schedule_minutes": SCHEDULE_MIN, "ticks": ticks,
            "last_train": None if not last_train else {"started_at": last_train["started_at"],
                                                       "finished_at": last_train["finished_at"],
                                                       "detail": loads(last_train["detail"], {})}}


def _record(rt: Runtime, kind: str, started: int, status: str, detail: dict[str, Any]) -> None:
    rt.db.execute("INSERT INTO engine_runs (id, kind, started_at, finished_at, status, detail) VALUES (?, ?, ?, ?, ?, ?)",
                  (new_id(), kind, started, now_ms(), status, dumps(detail)))
    rt.db.execute("DELETE FROM engine_runs WHERE started_at < ?", (now_ms() - 30 * 86_400_000,))


# ---- entry points -----------------------------------------------------------------------------------------

def tick(rt: Runtime, sink: BaseSink, budget_s: float = 600, now: int | None = None, fetch_context: bool = True) -> dict[str, Any]:
    t0 = time.time()
    started = now_ms() if now is None else now
    deadline = t0 + budget_s
    detail: dict[str, Any] = {"steps": {}}

    def step(name: str, fn):
        s0 = time.time()
        try:
            out = fn()
            detail["steps"][name] = {"ok": True, "seconds": round(time.time() - s0, 1)}
            return out
        except Exception as exc:   # one failing step must not stop the cycle
            log.exception("step %s failed", name)
            rt.record_error(f"engine {name}", exc)
            detail["steps"][name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            return None

    detail["config"] = step("config", lambda: sync_config(rt, sink))
    step("candles", lambda: asyncio.run(market.sync_all(rt)))

    def snapshot():
        try:
            rt.feed = StaticFeed(asyncio.run(rt.provider.fetch_tickers(rt.symbols())))
        except Exception as exc:
            rt.feed = StaticFeed({}, f"{type(exc).__name__}: {exc}"[:200])
        for s in rt.symbols():
            asyncio.run(market.refresh_order_book(rt, s))
        asyncio.run(market.clock_skew(rt))
        rt.funding_rates = market.funding_rates(rt.symbols())
    step("snapshot", snapshot)
    if fetch_context:
        step("context", lambda: asyncio.run(market.external_context(rt)))
    step("outcomes", lambda: (tracking.resolve_outcomes(rt), tracking.update_signal_outcomes(rt)))
    missing = [(s, tf) for s in rt.symbols() for tf in MODEL_TIMEFRAMES
               if trainer.active_version(s, tf, rt.db) is None and rt.store.is_current(rt.exchange, s, tf)]
    detail["bootstrap"] = step("bootstrap", lambda: train_until(rt, missing, True, t0 + budget_s * 0.5))

    analyses: dict[tuple[str, str], dict] = {}
    fired_events: list[dict[str, Any]] = []

    def analyse():
        hourly = (started // 900_000) % 4 == 0
        fired = 0
        for s in rt.symbols():
            for tf in views.ASSET_TIMEFRAMES:
                if tf in HOURLY_TFS and not hourly and rt.db.one("SELECT 1 FROM published WHERE doc_id = ?",
                                                                 (f"analysis_{views.slug(s)}_{tf}",)):
                    continue
                a = analysis.analyze(rt, s, tf, detail=True, use_cache=False)
                analyses[(s, tf)] = a
                evs = alerts.evaluate(rt.db, a)
                fired += len(evs)
                fired_events.extend(evs)
        return fired
    detail["alerts_fired"] = step("analyses", analyse)
    detail["bot_events"] = len(step("bots", lambda: BotEngine(rt).run(started)) or [])
    detail["jobs"] = step("jobs", lambda: process_jobs(rt, sink, deadline))
    engine = engine_info(rt, {"last_tick_started": started, "last_tick_finished": now_ms(),
                              "last_tick_seconds": round(time.time() - t0, 1),
                              "data_host": getattr(rt.provider, "host_used", None),
                              "failed_steps": [k for k, v in detail["steps"].items() if not v["ok"]]})
    engine["ticks"] += 1                     # include this cycle (it is recorded after publishing)
    step("publish", lambda: publish(rt, sink, engine, started, analyses))
    if fired_events:
        owners = {r["id"]: r["user_id"] for r in rt.db.query("SELECT id, user_id FROM alerts")}
        detail["push"] = step("push", lambda: sink.send_push(
            [push_message(e, owners.get(e.get("alert_id"))) for e in fired_events]))
    detail["written"] = sink.flush()
    detail["skipped_unchanged"] = sink.skipped
    status = "ok" if all(v["ok"] for v in detail["steps"].values()) else "partial"
    _record(rt, "tick", started, status, detail)
    detail["status"], detail["seconds"] = status, round(time.time() - t0, 1)
    return detail


def train(rt: Runtime, sink: BaseSink, budget_s: float = 2700) -> dict[str, Any]:
    t0 = time.time()
    started = now_ms()
    asyncio.run(market.sync_all(rt))
    pairs = pairs_needing_full(rt)
    done = train_until(rt, pairs, False, t0 + budget_s)
    detail = {"trained": done, "remaining": max(0, len(pairs) - len(done)), "libraries": model_status()}
    _record(rt, "train", started, "ok", detail)
    publish_models(rt, sink)
    publish_status(rt, sink, engine_info(rt, {"last_train_seconds": round(time.time() - t0, 1)}))
    sink.flush()
    return detail


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.worker")
    ap.add_argument("command", choices=["tick", "train"])
    ap.add_argument("--budget", type=float, default=None, help="seconds")
    ap.add_argument("--local", default=None, help="write to this folder instead of Firestore (dry run)")
    a = ap.parse_args()
    settings.ensure_dirs()
    db = get_db()
    rt = Runtime(db, market.make_provider())
    sink: BaseSink = LocalSink(a.local, db) if a.local else FirestoreSink(db, settings_project())
    if a.command == "tick":
        out = tick(rt, sink, a.budget or 600)
    else:
        out = train(rt, sink, a.budget or 2700)
    log.info("finished: %s", dumps({k: v for k, v in out.items() if k != "trained"})[:2000])
    asyncio.run(rt.provider.close())


def settings_project() -> str | None:
    import os

    return os.environ.get("FIREBASE_PROJECT_ID") or None


if __name__ == "__main__":
    main()
