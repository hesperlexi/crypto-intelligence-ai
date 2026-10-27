"""Batch engine for the Firebase deployment (always-on GitHub Actions job, one cycle every 5 minutes).

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
from .data import derivs
from .services import alerts, analysis, autopaper, backtests, health, market, membership, news, radar, telegram, replay, scanner, tracking, training
from .services.bots import DEFAULT_BOTS, BotEngine
from .services.runtime import USER, Runtime
from .sinks import BaseSink, FirestoreSink, LocalSink
from . import views

log = logging.getLogger("engine")
SCHEDULE_MIN = 5
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

def cleanup_bots(bots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """v2.2 tidy-up of the demo bots: identical copies are removed, a bot whose id names another timeframe gets
    that timeframe (and restarts), and prediction trackers only take the model's confident calls (fewer trades,
    less fee drag)."""
    import re

    out, seen, removed, retimed, confident = [], {}, [], [], []
    for b in bots:
        b = dict(b)
        m = re.search(r"-(15m|1h|4h|12h|1d|3d)(?:$|-)", str(b.get("id", "")))
        if m and b.get("timeframe") != m.group(1):
            b["timeframe"] = m.group(1)
            b["reset_token"] = f"tf-{b.get('reset_token', '1')}"
            retimed.append(b["id"])
        if b.get("mode") == "prediction" and not b.get("confident_only"):
            b["confident_only"] = True
            confident.append(b["id"])
        sig = dumps({k: v for k, v in sorted(b.items()) if k not in ("id", "name", "reset_token")})
        if sig in seen:
            removed.append(b["id"])
            continue
        seen[sig] = b["id"]
        out.append(b)
    return out, {"removed_duplicates": removed, "timeframe_fixed": retimed, "confident_only": confident}

MAJOR_COINS = ["BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT", "DOGE/USDT", "TRX/USDT", "ADA/USDT",
               "LINK/USDT", "AVAX/USDT", "SUI/USDT", "XLM/USDT", "GRAM/USDT", "HBAR/USDT", "BCH/USDT", "LTC/USDT",
               "DOT/USDT", "UNI/USDT", "NEAR/USDT", "APT/USDT", "AAVE/USDT"]
# coins the exchange renamed: the old pair stops trading, the new one continues the same asset
# (Binance: Toncoin TON -> Gram GRAM, trading as GRAM/USDT from 2026-07-02)
RENAMED = {"TON/USDT": "GRAM/USDT"}
GOLD = "PAXG/USDT"           # gold (tracks XAU/USD); added to the watchlist once in v2.1
MEMBER_COIN_LIMIT = 5        # default: coins one member can add for themselves (admin can change: config/limits)
MEMBER_COINS_MAX = 25        # default: all members together, on top of the admin's list (keeps the engine within its time)


def member_limits(sink: BaseSink) -> tuple[int, int]:
    d = sink.get("config/limits") or {}
    try:
        per = max(0, min(50, int(d.get("member_coin_limit", MEMBER_COIN_LIMIT))))
        total = max(0, min(200, int(d.get("member_coins_max", MEMBER_COINS_MAX))))
    except (TypeError, ValueError):
        per, total = MEMBER_COIN_LIMIT, MEMBER_COINS_MAX
    return per, total


def sync_config(rt: Runtime, sink: BaseSink) -> dict[str, Any]:
    notes: dict[str, Any] = {}
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
    # coins members added for themselves (active members only, a few each, capped overall)
    member_coins: list[str] = []
    per_member, all_members = member_limits(sink)
    for uid, d in sink.list("user_coins"):
        if uid in users and uid not in inactive:
            for x in (d.get("symbols") or [])[:per_member]:
                sym = norm_symbol(x)
                sym = RENAMED.get(sym, sym)
                if sym not in member_coins:
                    member_coins.append(sym)
    # watchlist
    doc = sink.get("config/watchlist")
    if doc is None or not isinstance(doc.get("symbols"), list):
        sink.set("config/watchlist", {"symbols": [{"symbol": w["symbol"], "pinned": bool(w["pinned"])}
                                                  for w in rt.watchlist()], "updated_at": now_ms()})
    else:
        if not rt.db.get_setting("watchlist_majors_v2", False):
            # v2.0: one-time expansion to the major coins (the admin can remove any of them afterwards;
            # coins without a proven edge get no AI-led signals, so quality is protected)
            have = {norm_symbol(i["symbol"] if isinstance(i, dict) else i) for i in doc["symbols"]}
            add = []
            for m in MAJOR_COINS:
                if m in have:
                    continue
                try:      # only coins the exchange really lists
                    if m in asyncio.run(rt.provider.search_markets(m.split("/")[0], 50)):
                        add.append(m)
                except Exception:
                    pass
            if add:
                doc = {**doc, "symbols": list(doc["symbols"]) + [{"symbol": m, "pinned": False} for m in add],
                       "updated_at": now_ms()}
                sink.set("config/watchlist", doc)
                notes["majors_added"] = add
            rt.db.set_setting("watchlist_majors_v2", True)
        if not rt.db.get_setting("gold_paxg_v21", False):
            # v2.1: gold signals. Forex.com has no free data feed; PAXG (one token = one troy ounce of gold, Binance
            # spot) tracks XAU/USD closely, so the models train on it and the website labels it as gold.
            have = {norm_symbol(i["symbol"] if isinstance(i, dict) else i) for i in doc["symbols"]}
            if GOLD not in have:
                try:
                    listed = GOLD in asyncio.run(rt.provider.search_markets("PAXG", 50))
                except Exception:
                    listed = False
                if listed:
                    doc = {**doc, "symbols": list(doc["symbols"]) + [{"symbol": GOLD, "pinned": True}], "updated_at": now_ms()}
                    sink.set("config/watchlist", doc)
                    notes["gold_added"] = GOLD
            rt.db.set_setting("gold_paxg_v21", True)
        # renamed coins: rewrite the watchlist once so the website shows the new name too
        names = [norm_symbol(i["symbol"] if isinstance(i, dict) else i) for i in doc["symbols"]]
        if any(n in RENAMED for n in names):
            items, seen_syms = [], set()
            for i, n in zip(doc["symbols"], names):
                new = RENAMED.get(n, n)
                if new in seen_syms:
                    continue
                seen_syms.add(new)
                items.append({"symbol": new, "pinned": bool(i.get("pinned")) if isinstance(i, dict) else False})
            doc = {**doc, "symbols": items, "updated_at": now_ms()}
            sink.set("config/watchlist", doc)
            notes["renamed"] = {o: n for o, n in RENAMED.items() if o in names}
        wanted = {}
        for item in doc["symbols"]:
            sym = norm_symbol(item["symbol"] if isinstance(item, dict) else item)
            wanted[sym] = bool(item.get("pinned")) if isinstance(item, dict) else False
        extra = [c for c in member_coins if c not in wanted][:all_members]
        for sym in extra:
            wanted[sym] = False
        if extra:
            notes["member_coins"] = extra
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
    if not rt.db.get_setting("bots_cleanup_v22", False):
        bots_cfg, cleaned = cleanup_bots(bots_cfg)
        sink.set("config/bots", {**(sink.get("config/bots") or {}), "bots": bots_cfg, "updated_at": now_ms()})
        rt.db.set_setting("bots_cleanup_v22", True)
        notes["bots_cleanup"] = cleaned
    if not rt.db.get_setting("fresh_start_v2", False):
        # v2.0 fresh start: every bot restarts with its starting balance and the counted track record begins now.
        # Older signals stay in the database (Signal log); they are just not counted in the v2.0 record.
        bots_cfg = [{**b, "reset_token": f"v2-{b.get('reset_token', '1')}"} for b in bots_cfg]
        sink.set("config/bots", {**(sink.get("config/bots") or {}), "bots": bots_cfg, "updated_at": now_ms()})
        rt.db.set_setting("record_since", now_ms())
        rt.db.set_setting("fresh_start_v2", True)
        notes["fresh_start_v2"] = True
    BotEngine(rt).sync_configs(bots_cfg)
    return notes


# ---- jobs queued by the website ---------------------------------------------------------------------------

def run_job(rt: Runtime, job: dict[str, Any], deadline: float, sink: BaseSink | None = None) -> dict[str, Any]:
    kind, p = job.get("type"), job.get("params") or {}
    if kind == "test_telegram":
        return telegram.test_post(sink)
    if kind == "telegram_post":
        return telegram.post_draft(sink, str(p.get("id") or ""))
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
    bot_report = BotEngine(rt).report()
    sink.view("bots", bot_report)
    sink.view("track_record", views.track_record(rt, bot_report))
    sink.view("weekly_report", views.weekly_reports(rt, bot_report))
    sink.view("wins_today", views.wins_today(rt))
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
    try:
        from .services import safety
        h["safety"] = safety.overview(rt.db)
    except Exception:
        h["safety"] = []
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

    def beat(name: str, extra: dict | None = None) -> None:
        # tiny progress note (admin/engine_heartbeat) so a stuck or failing cycle can be seen from outside
        try:
            sink.set("admin/engine_heartbeat", {"step": name, "at": now_ms(), "tick_started": started,
                                                "steps": {k: v.get("seconds", v.get("error")) for k, v in detail["steps"].items()},
                                                **(extra or {})})
        except Exception:
            pass

    def step(name: str, fn):
        s0 = time.time()
        beat(name)
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
        detail["news"] = step("news", lambda: sync_news(rt))
        detail["derivs"] = step("derivs", lambda: derivs.sync(rt.db, rt.symbols(), max_calls=40))
        detail["crowd"] = step("crowd", lambda: derivs.sync_crowd(rt.db, rt.symbols(), max_files=25))
    if not rt.db.get_setting("tracking_be_v23", False):     # one-time: re-follow TP1/TP2 signals with break-even stops
        detail["tracking_be_v23"] = tracking.reopen_for_break_even(rt.db)
        rt.db.set_setting("tracking_be_v23", True)
    step("outcomes", lambda: (tracking.resolve_outcomes(rt), tracking.update_signal_outcomes(rt),
                                  tracking.update_signal_outcomes(rt, table="shadow_signals")))
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
    if analyses:
        res = step("auto_paper", lambda: _auto_paper(rt, sink, analyses))
        detail["auto_paper"] = res
    if fetch_context and hasattr(rt.provider, "_get_sync") and now_ms() - int(rt.db.get_setting("radar_at", 0) or 0) > 55 * 60_000:
        def run_radar():
            r = radar.scan(rt.db, rt.provider, rt.symbols())
            rt.db.set_setting("radar_at", now_ms())
            sink.view("radar", r)
            return {"screened": r["screened"], "picks": [p["symbol"] for p in r["picks"][:5]]}
        detail["radar"] = step("radar", run_radar)
    if fetch_context:
        step("news_publish", lambda: sink.view("news", news.news_view(rt.db, getattr(rt, "headlines", None),
                                                                        getattr(rt, "calendar_status", None))))
        due = news.due_notifications(rt.db)
        if due:
            detail["news_push"] = step("news_push", lambda: sink.send_push(due))
    last_week = views.week_start(now_ms()) - views.WEEK
    if int(rt.db.get_setting("weekly_report_notified", 0) or 0) < last_week and now_ms() - views.week_start(now_ms()) > 4 * 3_600_000:
        def weekly_push():
            r = views.weekly_report(rt, last_week)
            rt.db.set_setting("weekly_report_notified", last_week)
            body = (f"{r['closed']} signals closed, win rate {r['win_rate']:.0%}, total {r['total_return_pct']:+.1f}%. "
                    "Open Report to download the post image.") if r["closed"] else "No signals closed last week. The report is ready to view."
            return sink.send_push([{"title": "Your weekly report is ready", "body": body, "url": "/report", "tag": "weekly-report"}])
        detail["weekly_push"] = step("weekly_push", weekly_push)
    if fetch_context:
        detail["telegram"] = step("telegram", lambda: telegram.run(rt, sink, views.wins_today(rt), views.weekly_reports(rt, None, weeks=2)))
    if fired_events:
        owners = {r["id"]: r["user_id"] for r in rt.db.query("SELECT id, user_id FROM alerts")}
        detail["push"] = step("push", lambda: sink.send_push(
            [push_message(e, owners.get(e.get("alert_id"))) for e in fired_events]))
    beat("publish", {"pending_docs": len(sink.pending),
                     "pending_mb": round(sum(len(v.get("json") or "") for v in sink.pending.values()) / 1e6, 2)})
    detail["written"] = step("publish", sink.flush) or 0
    beat("done", {"written": detail["written"]})
    detail["skipped_unchanged"] = sink.skipped
    status = "ok" if all(v["ok"] for v in detail["steps"].values()) else "partial"
    _record(rt, "tick", started, status, detail)
    detail["status"], detail["seconds"] = status, round(time.time() - t0, 1)
    return detail


def _auto_paper(rt: Runtime, sink: BaseSink, analyses: dict[tuple[str, str], dict]) -> dict[str, Any]:
    """New futures signals into the paper accounts of members who switched auto-trading on."""
    rows = {tf: views.futures(rt, tf, analyses)["rows"] for tf in views.FUTURES_TIMEFRAMES if any(k[1] == tf for k in analyses)}
    r = autopaper.run(sink, rows)
    msgs = r.pop("push")
    if msgs:
        r["push"] = sink.send_push(msgs)
    return r


def sync_news(rt: Runtime) -> dict[str, Any]:
    """Calendar at most hourly (it changes slowly), headlines every cycle."""
    last = int(rt.db.get_setting("calendar_synced_at", 0) or 0)
    if now_ms() - last > 3_600_000:
        rt.calendar_status = news.sync_calendar(rt.db)
        if not rt.calendar_status.get("errors") or rt.calendar_status.get("events"):
            rt.db.set_setting("calendar_synced_at", now_ms())
    rt.headlines = news.headlines()
    return {"calendar": getattr(rt, "calendar_status", None) or "fresh", "headlines": len(rt.headlines.get("items", [])),
            "errors": rt.headlines.get("errors")}


def train(rt: Runtime, sink: BaseSink, budget_s: float = 2700) -> dict[str, Any]:
    t0 = time.time()
    started = now_ms()
    asyncio.run(market.sync_all(rt))
    try:                       # futures history for the models: plenty of requests allowed here (backfill)
        log.info("derivs: %s", derivs.sync(rt.db, rt.symbols(), max_calls=600))
    except Exception as exc:
        log.warning("derivs sync failed: %s", exc)
    pairs = pairs_needing_full(rt)
    done = train_until(rt, pairs, False, t0 + budget_s)
    detail = {"trained": done, "remaining": max(0, len(pairs) - len(done)), "libraries": model_status()}
    _record(rt, "train", started, "ok", detail)
    publish_models(rt, sink)
    publish_status(rt, sink, engine_info(rt, {"last_train_seconds": round(time.time() - t0, 1)}))
    sink.flush()
    return detail


# ---- parallel nightly training (train.yml: 15 slices on separate machines, then one merge) -------------------

TF_COST = {"15m": 6, "1h": 5, "4h": 3, "12h": 2, "1d": 2, "3d": 1}


def shard_pairs(rt: Runtime, shard: int, of: int, max_age_h: float = 12) -> list[tuple[str, str]]:
    """Every model that is missing, fast-only, missing a model family, or older than `max_age_h`, spread over
    `of` slices so each gets a similar amount of work (heavy timeframes dealt out first)."""
    pairs = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            if not rt.store.is_current(rt.exchange, s, tf):
                continue
            v = trainer.active_version(s, tf, rt.db)
            if v is None or (v.get("summary") or {}).get("fast") or now_ms() - v["created_at"] > max_age_h * 3.6e6 \
                    or _missing_models(v.get("summary") or {}):
                pairs.append((s, tf))
    pairs.sort(key=lambda p: (-TF_COST.get(p[1], 1), p[0]))
    return [p for i, p in enumerate(pairs) if i % of == shard]


def train_shard(rt: Runtime, shard: int, of: int, budget_s: float, out_dir: str) -> dict[str, Any]:
    """Train one slice on a copy of the engine state and write the new models + their records to `out_dir`.
    Nothing is published from here; the merge job registers the results in the real state."""
    import shutil
    from pathlib import Path

    t0 = time.time()
    pairs = shard_pairs(rt, shard, of)
    done = train_until(rt, pairs, False, t0 + budget_s)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for d in done:
        s, tf = d["pair"].rsplit(" ", 1)
        st = rt.training.get(f"{s}|{tf}", {})
        if st.get("state") != "done" or not st.get("version"):
            continue
        bundle = trainer.load_bundle(s, tf, rt.db)
        if bundle is None or bundle["version"] != st["version"]:
            continue
        rec = trainer.bundle_record(bundle)
        src = trainer.active_version(s, tf, rt.db)["path"]
        shutil.copyfile(src, out / f"{rec['version']}.joblib")
        records.append(rec)
    (out / "manifest.json").write_text(dumps({"shard": shard, "of": of, "records": records, "trained": done,
                                              "seconds": round(time.time() - t0, 1)}))
    return {"shard": shard, "pairs": len(pairs), "trained": len(done), "exported": len(records),
            "remaining": max(0, len(pairs) - len(done))}


def train_merge(rt: Runtime, sink: BaseSink, in_dir: str) -> dict[str, Any]:
    """Register the models the slices trained (a newer model already active wins), tidy old model files,
    refresh the futures history for the next night, and publish."""
    from pathlib import Path

    t0 = time.time()
    started = now_ms()
    imported, skipped, shards, failed = 0, 0, 0, []
    for m in sorted(Path(in_dir).glob("**/manifest.json")):
        shards += 1
        data = loads(m.read_text(), {}) or {}
        for rec in data.get("records", []):
            f = m.parent / f"{rec['version']}.joblib"
            if f.exists() and trainer.import_bundle(rec, str(f), rt.db):
                imported += 1
            else:
                skipped += 1
        failed += [t for t in data.get("trained", []) if t.get("state") == "failed"]
    pruned = trainer.prune_files(rt.db)
    try:
        asyncio.run(market.sync_all(rt))
        derivs_note = {"funding": derivs.sync(rt.db, rt.symbols(), max_calls=600),
                       "crowd": derivs.sync_crowd(rt.db, rt.symbols(), max_files=2500)}
    except Exception as exc:
        derivs_note = f"failed: {exc}"
    detail = {"shards": shards, "imported": imported, "skipped": skipped, "pruned_files": pruned,
              "failed": failed[:20], "derivs": derivs_note}
    _record(rt, "train", started, "ok", detail)
    publish_models(rt, sink)          # health/status stays with the 5-minute engine (it has the live price feed)
    sink.flush()
    return detail


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app.worker")
    ap.add_argument("command", choices=["tick", "train", "train-shard", "train-merge"])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--out", default="shard-out", help="train-shard: folder for the trained models")
    ap.add_argument("--in", dest="inp", default="shards", help="train-merge: folder with the slices' output")
    ap.add_argument("--budget", type=float, default=None, help="seconds")
    ap.add_argument("--local", default=None, help="write to this folder instead of Firestore (dry run)")
    a = ap.parse_args()
    settings.ensure_dirs()
    db = get_db()
    rt = Runtime(db, market.make_provider())
    sink: BaseSink = LocalSink(a.local, db) if a.local else FirestoreSink(db, settings_project())
    if a.command == "tick":
        out = tick(rt, sink, a.budget or 600)
    elif a.command == "train-shard":
        out = train_shard(rt, a.shard, a.of, a.budget or 3000, a.out)
    elif a.command == "train-merge":
        out = train_merge(rt, sink, a.inp)
    else:
        out = train(rt, sink, a.budget or 2700)
    if a.command == "tick":                       # read by scripts/engine_loop.py (the summary below is cut at 2000 chars)
        print(f'tick written: {{"written": {int(out.get("written") or 0)}}}', flush=True)
    log.info("finished: %s", dumps({k: v for k, v in out.items() if k != "trained"})[:2000])
    asyncio.run(rt.provider.close())


def settings_project() -> str | None:
    import os

    return os.environ.get("FIREBASE_PROJECT_ID") or None


if __name__ == "__main__":
    main()
