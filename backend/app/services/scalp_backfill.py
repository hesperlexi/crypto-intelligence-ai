"""Scalping scorecard, 1-2 Nov 2026 rebuild (owner request 2 Nov 2026: "results from November 1 on").

The live scalping log (`tracking.log_scalp`) started when it shipped (setting `scalping_since`, 2 Nov ~14:30 Dubai). The
15m grade-A calls between 1 Nov 00:00 Dubai (2026-10-31T20:00Z) and that moment are rebuilt here by replaying the
engine's own decision for every closed 15m candle of the window, as the live engine would have made it then:

* the call's time = when the live engine first analysed that candle: `predictions.created_at` of the live forecast
  logged for it (no live forecast logged for a candle = the engine did not analyse it = no call);
* the model = the 15m model version the live engine used for that candle (`predictions.model_version_id`); its file
  must still be stored (`prune_keep_versions` keeps the files from the nightly clean-up until the rebuild is done); a
  model trained after the call time is never used (checked);
* candles and features only up to the candle's close (`analysis.analyze(..., as_of=close)`), the ensemble weights as
  they stood then (`tracking.live_multipliers(until=call time)`);
* the live-only gates replayed as they stood at the call time: the AI lean threshold (from the live forecast itself),
  the news pause, the safety switch (read-only), the 15m trade filter (only when trained before the call; a newer one
  skips the candle), one call at a time against the public record (read-only), then the scalping log's own rules:
  grade A only, one open call per coin, re-entry cooldown / cap (judged on what had closed by the call time), the
  record's entry / fill / target rules and the 250-candle limit;
* every rebuilt call is followed at once with the same exit engine to today (`update_signal_outcomes(ids=...)`), so
  the next candle knows whether the coin still had a call running.

Rows are marked (payload `backfilled: true`, `rebuilt_at`, `replay` {...}) and listed with a "rebuilt" tag. It never
writes `signals`, `shadow_signals`, `decisions`, `signal_proofs`, bots or any public view. Incremental: a cursor per
coin in settings `scalp_backfill_state`; each engine tick does at most `max_analyses` replays within `budget_s`;
idempotent (one row per coin/candle, UNIQUE (symbol, timeframe, bar_ts)); done flag `scalp_backfill_v1`.
CLI: `python -m app.worker scalp-backfill`.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from ..config import settings
from ..data.base import tf_ms
from ..db import dumps, loads, now_ms
from . import tracking

log = logging.getLogger("scalp_backfill")

WINDOW_START = 1_793_476_800_000         # 2026-11-01 00:00 Dubai = 2026-10-31T20:00:00Z
TF = "15m"
STEP = tf_ms(TF)
STATE_KEY = "scalp_backfill_state"
DONE_FLAG = "scalp_backfill_v1"
SINCE_FLAG = "scalping_since_nov1"       # one-time: scalping_since moved to WINDOW_START
LIVE_SINCE_KEY = "scalping_live_since"   # when the live log started (the old scalping_since)
KEEP_KEY = "prune_keep_versions"         # trainer.prune_files skips these model files
MARGIN_TOL = 0.01                        # replay vs live probabilities may differ slightly: only clear misses are skipped
NOTE = ("1-2 Nov rebuilt by replaying the engine's decisions on the candles of the time (the 15m model it used then, "
        "candles up to each call); from {live} logged live.")

_bundles: dict[str, Any] = {}


def status(db: Any) -> dict[str, Any] | None:
    """For views.scalping: None when there is no rebuild; else its state (progress, counts, live start)."""
    st = db.get_setting(STATE_KEY, None)
    if not st:
        return None
    total = max(1, len(st["symbols"]) * max(0, (st["end"] - st["start"]) // STEP))
    done = sum(max(0, min(c, st["end"]) - st["start"]) // STEP for c in st["cursor"].values())
    return {"state": "done" if db.get_setting(DONE_FLAG, False) else "running", "window_start": st["start"],
            "live_since": st["end"], "progress": min(1.0, done / total), "rebuilt": st.get("rebuilt", 0),
            "replayed": st.get("analyses", 0), "skipped": st.get("skipped", {}), "finished_at": st.get("finished_at"),
            "note": NOTE.format(live=time.strftime("%d %b %H:%M UTC", time.gmtime(st["end"] / 1000)))}


def init(rt: Any, now: int | None = None) -> dict[str, Any] | None:
    """Create the rebuild state once and move `scalping_since` to 1 Nov 00:00 Dubai (flag-guarded). None when done."""
    db = rt.db
    if db.get_setting(DONE_FLAG, False):
        return None
    now = now or now_ms()
    st = db.get_setting(STATE_KEY, None)
    if not st:
        live = int(tracking.scalp_since(db) or now)
        end = max(WINDOW_START, live)
        symbols = list(rt.symbols())
        marks = ",".join("?" * len(symbols)) or "''"
        versions = [r["model_version_id"] for r in db.query(
            f"SELECT DISTINCT model_version_id FROM predictions WHERE timeframe = ? AND symbol IN ({marks}) "
            "AND bar_ts >= ? AND bar_ts < ?", (TF, *symbols, WINDOW_START - STEP, end))] if symbols else []
        st = {"start": WINDOW_START, "end": end, "symbols": symbols, "cursor": {s: WINDOW_START for s in symbols},
              "versions": versions, "rebuilt": 0, "analyses": 0, "skipped": {}, "started_at": now}
        db.set_setting(STATE_KEY, st)
        db.set_setting(LIVE_SINCE_KEY, live)
        keep = set(db.get_setting(KEEP_KEY, []) or []) | set(versions)
        db.set_setting(KEEP_KEY, sorted(keep))
    if not db.get_setting(SINCE_FLAG, False):
        db.set_setting("scalping_since", min(WINDOW_START, int(tracking.scalp_since(db) or WINDOW_START)))
        db.set_setting("scalping_v1", True)      # sync_config must not set it again
        db.set_setting(SINCE_FLAG, True)
    return st


def _load_version(db: Any, vid: str) -> dict[str, Any] | None:
    if vid in _bundles:
        return _bundles[vid]
    row = db.one("SELECT path FROM model_versions WHERE id = ?", (vid,))
    b = None
    if row and row.get("path"):
        try:
            import joblib
            b = joblib.load(row["path"])
        except Exception:
            b = None
    _bundles[vid] = b
    return b


def _live_forecasts(db: Any, symbol: str, start: int, end: int) -> dict[int, dict[str, Any]]:
    """The live engine's first 15m forecast per candle (bar_ts -> row): its time and model."""
    out: dict[int, dict[str, Any]] = {}
    for r in db.query("SELECT bar_ts, created_at, model_version_id, p_up, p_down FROM predictions WHERE symbol = ? "
                      "AND timeframe = ? AND bar_ts >= ? AND bar_ts < ? ORDER BY created_at", (symbol, TF, start, end)):
        out.setdefault(int(r["bar_ts"]), r)
    return out


def _known_closed(r: dict[str, Any], t: int) -> bool:
    """Whether the live engine knew at `t` that row `r` had closed (its closing 15m candle had finished)."""
    return r["status"] != "OPEN" and r.get("closed_at") is not None and int(r["closed_at"]) + STEP <= t


def gate_as_of(db: Any, call: dict[str, Any], t: int) -> tuple[str, str | None, dict[str, Any]]:
    """tracking.entry_gate on `scalp_signals` as it stood at time `t` (only calls made before `t`, closes known by `t`).
    `call` may have no decision yet (side 0): then the re-entry part is skipped."""
    sym = call["symbol"]
    rows = db.query(f"SELECT * FROM {tracking.SCALP_TABLE} WHERE symbol = ? AND timeframe = ? AND side != 0 "
                    "AND created_at < ? ORDER BY created_at", (sym, TF, t))
    running = [r for r in rows if not _known_closed(r, t)]
    if running:
        cur = running[-1]
        return ("already_open", f"a {TF} {'long' if cur['side'] > 0 else 'short'} call on this coin was still running",
                {"open_id": cur["id"]})
    closed = [r for r in rows if r["status"] != "VOID"]
    if closed:
        last = max(closed, key=lambda r: int(r["closed_at"]))
        ends = int(last["closed_at"]) + STEP
        if t < ends + settings.reentry_cooldown_bars * STEP:
            return ("cooldown", f"the last {TF} call on this coin had just closed", {"last_id": last["id"]})
    side = tracking._side_of(call.get("decision") or "")
    if side:
        window = settings.reentry_window_bars * STEP
        exits = sorted([r for r in rows if r["side"] == side and int(r["closed_at"]) >= t - window
                        and r.get("exit_reason") in ("giveback", "stop")], key=lambda r: int(r["closed_at"]))
        if exits:
            first = exits[0]
            regime = (call.get("regime") or {}).get("regime")
            vol = (call.get("volatility") or {}).get("state")
            if regime in tracking.UNSTABLE_REGIMES or vol == "EXTREME":
                return ("reentry_regime", "no re-entry while volatility is extreme", {"after_id": first["id"]})
            n = sum(1 for r in rows if r["side"] == side and int(r["created_at"]) > int(first["closed_at"]))
            if n >= settings.reentry_max:
                return ("reentry_cap", f"already {n} re-entries in this direction", {"after_id": first["id"]})
    return ("ok", None, {})


def _record_call_running(db: Any, symbol: str, side: int, t: int) -> bool:
    """analysis.ONE_CALL_TFS as it stood at `t`: an opposite 15m call of the public record still running (read only)."""
    for r in db.query("SELECT status, closed_at FROM signals WHERE symbol = ? AND timeframe = ? AND side = ? "
                      "AND created_at < ?", (symbol, TF, -side, t)):
        if not _known_closed(r, t):
            return True
    return False


def _safety_paused(db: Any, symbol: str, t: int) -> bool:
    """The safety switch's stored state at `t` (read only; safety.check would move the switch)."""
    from .safety import _key
    st = db.get_setting(_key(symbol, TF), {}) or {}
    if st.get("paused_at") and int(st["paused_at"]) <= t:
        return True
    return bool(st.get("last_pause") and int(st["last_pause"]) <= t < int(st.get("resumed_at") or 0))


def _filter2(db: Any, t: int) -> tuple[str, Any]:
    """('off', None) | ('newer', None) | ('on', filter): the 15m pooled trade filter usable at `t`."""
    if not settings.trade_filter2:
        return "off", None
    from ..ml import trade_filter2 as TF2
    f2 = TF2.load(db, TF)
    if f2 is None:
        return "off", None
    at = int((db.get_setting(f"trade_filter2|{TF}", None) or {}).get("at") or 0)
    return ("on", f2) if at and at <= t else ("newer", None)


def _skip(st: dict[str, Any], why: str) -> str:
    st["skipped"][why] = st["skipped"].get(why, 0) + 1
    return why


def _one_bar(rt: Any, st: dict[str, Any], symbol: str, close: int, live: dict[int, dict[str, Any]], now: int) -> str:
    """Replay one closed 15m candle (closing at `close`). Returns what happened ('rebuilt' or a skip reason)."""
    from ..ml import direction as dirview
    from . import analysis
    from .news import event_risk

    db = rt.db
    bar_ts = close - STEP
    pr = live.get(bar_ts)
    if pr is None:
        return _skip(st, "no_live_analysis")
    t = int(pr["created_at"])                         # when the live engine first analysed this candle
    if t >= st["end"]:
        return _skip(st, "live_log")                  # the live scalping log had started
    if db.one(f"SELECT 1 FROM {tracking.SCALP_TABLE} WHERE symbol = ? AND timeframe = ? AND bar_ts = ?",
              (symbol, TF, bar_ts)):
        return _skip(st, "already_logged")
    g, _, _ = gate_as_of(db, {"symbol": symbol}, t)
    if g != "ok":
        return _skip(st, g)
    bundle = _load_version(db, pr["model_version_id"])
    if bundle is None:
        return _skip(st, "model_file_missing")
    # trained before the call, on candles (and their next-candle labels) that had closed by this candle's close
    if int(bundle["created_at"]) >= t or int(bundle.get("data_end") or 0) + 2 * STEP > close:
        return _skip(st, "model_newer_than_call")     # never a model that saw the call's candles
    if settings.require_edge_for_trade and not bundle["edge"]["edge_confirmed"]:
        return _skip(st, "no_edge")
    dv = dirview.view({"available": True, "probabilities": {"up": float(pr["p_up"]), "down": float(pr["p_down"])}}, bundle)
    if dv is not None and (dv.get("policy_margin") is None or dv["margin"] < dv["policy_margin"] - MARGIN_TOL):
        return _skip(st, "ai_below_threshold")        # grade A needs the AI lean above its threshold (live forecast)
    if event_risk(db, t):
        return _skip(st, "news_pause")
    if _safety_paused(db, symbol, t):
        return _skip(st, "safety_paused")
    f2_state, f2 = _filter2(db, t)
    if f2_state == "newer":
        return _skip(st, "trade_filter_newer_than_call")
    mult = tracking.live_multipliers(db, bundle, until=t)
    st["analyses"] = st.get("analyses", 0) + 1
    a = analysis.analyze(rt, symbol, TF, as_of=close, bundle=bundle, detail=False, use_cache=False, multipliers=mult)
    if a.get("status") != "OK" or a.get("bar_ts") != bar_ts:
        return _skip(st, "candle_missing")
    setup = a.get("setup") or {}
    if a["decision"] not in tracking.TRADE_DECISIONS or a.get("grade") != "A" or not setup.get("valid"):
        return _skip(st, "no_grade_a_call")
    side = 1 if a["decision"] in ("BUY", "BUY ON PULLBACK") else -1
    if f2 is not None:                                # analysis.analyze applies it only to live calls
        from ..ml import trade_filter2 as TF2
        last = rt.frame(symbol, TF, close).ind.iloc[-1]
        row = TF2.live_features(a["forecast"], a.get("confidence"), a.get("grade"), side, last, a["mtf"],
                                analysis._btc_last(rt, symbol, TF, close, last), setup, close)
        sc = TF2.score(f2, row)
        if sc is not None and sc < f2["threshold"]:
            return _skip(st, "trade_filter")
    if _record_call_running(db, symbol, side, t):
        return _skip(st, "record_call_running")
    fc = a.get("forecast") or {}
    pv = fc.get("probabilities") or {}
    call = {**a, "decision": "NO TRADE", "grade": None, "demo": {"decision": a["decision"], "grade": "A"},
            "price": a.get("last_close") or a.get("price")}
    extra = {"backfilled": True, "rebuilt_at": now,
             "replay": {"as_of": close, "live_analysed_at": t, "model_version": pr["model_version_id"],
                        "model_trained_at": int(bundle["created_at"]), "model_data_end": bundle.get("data_end"),
                        "live_p_up": pr["p_up"], "live_p_down": pr["p_down"],
                        "replay_p_up": pv.get("up"), "replay_p_down": pv.get("down"),
                        "entry_rule_now": True}}
    res = tracking.log_scalp(db, call, now=t, extra=extra, gate=lambda d, c, tt: gate_as_of(d, c, tt))
    if res["status"] != "logged":
        return _skip(st, res.get("gate") or "not_logged")
    tracking.update_signal_outcomes(rt, table=tracking.SCALP_TABLE, now=now, ids=[res["id"]])
    st["rebuilt"] = st.get("rebuilt", 0) + 1
    return "rebuilt"


def _finish(rt: Any, st: dict[str, Any], now: int) -> None:
    """Mark rebuilt calls that were still running when live calls on the same coin were logged (both kept), release
    the model files and set the done flag."""
    db = rt.db
    rows = db.query(f"SELECT * FROM {tracking.SCALP_TABLE} WHERE created_at < ? AND side != 0", (st["end"],))
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        if not p.get("backfilled"):
            continue
        until = int(r["closed_at"]) + STEP if r["status"] != "OPEN" and r.get("closed_at") else now + 1
        hits = [x["id"] for x in db.query(f"SELECT id FROM {tracking.SCALP_TABLE} WHERE symbol = ? AND timeframe = ? "
                                          "AND side != 0 AND created_at >= ? AND created_at < ? AND id != ?",
                                          (r["symbol"], TF, st["end"], until, r["id"]))]
        if hits:
            db.execute(f"UPDATE {tracking.SCALP_TABLE} SET payload = ? WHERE id = ?",
                       (dumps({**p, "overlaps_live": hits}), r["id"]))
    keep = set(db.get_setting(KEEP_KEY, []) or []) - set(st.get("versions") or [])
    db.set_setting(KEEP_KEY, sorted(keep))
    st["finished_at"] = now
    db.set_setting(STATE_KEY, st)
    db.set_setting(DONE_FLAG, True)
    _bundles.clear()


def run(rt: Any, budget_s: float = 120, max_analyses: int = 150, now: int | None = None) -> dict[str, Any]:
    """One slice of the rebuild (engine tick step / CLI). Returns progress."""
    st = init(rt, now)
    if st is None:
        return {"done": True}
    now = now or now_ms()
    t0, n0 = time.time(), st.get("analyses", 0)
    out: dict[str, int] = {}
    for sym in st["symbols"]:
        cur = int(st["cursor"].get(sym, st["start"]))
        if cur >= st["end"]:
            continue
        live = _live_forecasts(rt.db, sym, st["start"] - STEP, st["end"])
        while cur < st["end"]:
            if time.time() - t0 > budget_s or st.get("analyses", 0) - n0 >= max_analyses:
                rt.db.set_setting(STATE_KEY, st)
                return {"done": False, "progress": (status(rt.db) or {}).get("progress"), "this_run": out}
            try:
                what = _one_bar(rt, st, sym, cur, live, now)     # cursor = close of the next candle
            except Exception as exc:                 # one bad candle never stops the rebuild
                what = _skip(st, f"error {type(exc).__name__}")
                log.warning("scalp backfill %s %s: %s", sym, cur, exc)
            out[what] = out.get(what, 0) + 1
            cur += STEP
            st["cursor"][sym] = cur
            rt.db.set_setting(STATE_KEY, st)
        _bundles.clear()                              # one coin's models in memory at a time
    _finish(rt, st, now)
    return {"done": True, "rebuilt": st.get("rebuilt", 0), "skipped": st.get("skipped"), "this_run": out}
