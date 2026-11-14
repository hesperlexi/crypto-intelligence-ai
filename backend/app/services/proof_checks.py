"""v2.24 proof checks (admin, owner-approved 14 Nov 2026). Two questions, answered from the live engine's own data:

1. Do the filters save money?  A call that had a valid setup and a trade decision but was turned into NO TRADE by a
   filter is logged in `rejected_signals` (entry / stop / targets / fill rules of the record, the call's own time limit)
   and followed to the end with the record's exit engine (`tracking.update_signal_outcomes(table=...)`). The scoreboard
   shows, per filter, what the blocked calls would have made after fees. Never shown as a signal; nothing that builds the
   record, the bots, Telegram, training or the safety switch reads this table.
2. Is the AI still as good live as it was in training?  Live next-candle forecasts (`predictions` + `prediction_outcomes`)
   are scored per timeframe: Brier score vs the base-rate forecast (skill), last 7 days vs the 30 days before (drift), and
   a reliability table (stated probability vs what happened). Calls made since v2.24 also store the TP1 base rate, so TP1
   expected vs actual can be compared.

Published inside `views/guardian` (admin only, already written), refreshed at most hourly (setting `proof_checks`):
no new Firestore documents, no reads.
"""
from __future__ import annotations

import math
import time
from typing import Any

from ..db import Database, dumps, loads, new_id, now_ms

TABLE = "rejected_signals"
EVERY_S = 3600
DAY = 86_400_000
# filters whose effect is measured (checks that failed, admin holds, the safety switch's own shadow log, stale data and
# demo-only routing are not filters of the call itself and are left out)
FLAGS = ("AGAINST BIGGER TREND", "NO PROVEN EDGE", "FILTERED", "TARGET TOO SMALL FOR COSTS", "STOP TOO WIDE",
         "VOLUME WALL AHEAD", "STOP TOO TIGHT FOR FEES", "TOO MANY SAME-SIDE CALLS", "TIMEFRAME PAUSED", "GRADE A ONLY",
         "CALL STILL RUNNING", "NEWS RISK")
SKIP_FLAGS = ("CHECK UNAVAILABLE", "WITHDRAWN BY ADMIN", "COIN BEING REMOVED", "PAUSED", "STALE DATA", "DEMO BOTS ONLY")
MIN_JUDGE = 10            # closed rejected calls before a filter gets a verdict
DRIFT_MIN_N = 150         # resolved forecasts in the last 7 days before drift is judged
BUCKETS = ((0.33, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 1.01))


def blocking_flag(new_flags: list[str]) -> str | None:
    """The filter that turned the call into NO TRADE: the first measured flag added after the decision was formed.
    None when the first one is a check failure / hold / safety pause / stale data (not measured)."""
    for f in new_flags:
        if f in SKIP_FLAGS:
            return None
        if f in FLAGS:
            return f
    return None


def expect_of(setup: dict[str, Any] | None) -> dict[str, Any] | None:
    """The setup's own expectation (historical first-passage base rates, AI-lifted where proven), stored with a call."""
    if not setup:
        return None
    t = setup.get("targets") or []
    p = [x.get("probability") for x in t[:3]]
    if not any(v is not None for v in p):
        return None
    return {"p_tp": p, "expectancy_r": setup.get("expectancy_r")}


def log_rejected(db: Database, a: dict[str, Any], decision: str, setup: dict[str, Any], grade: str | None, flag: str,
                 reason: str | None, now: int | None = None) -> bool:
    """Log a would-be call that a filter blocked. One OPEN one per coin / timeframe, one per candle; skipped while the
    record itself has a call running there (it would not have been recorded either)."""
    from . import tracking as T
    sym, tf = a["symbol"], a["timeframe"]
    if T.open_call(db, sym, tf, "signals") or T.open_call(db, sym, tf, TABLE):
        return False
    pl = T._plan({**a, "decision": decision, "setup": setup}, db)
    if pl.get("entry") is None:
        return False
    fc = a.get("forecast") or {}
    app_v, eng_v = T.versions()
    now = now or now_ms()
    payload = {"rejected": True, "flag": flag, "reason": reason, "grade": grade, "decision": decision,
               "runner": T._runner_for(setup.get("runner"), pl), "manage": T.manage_params(db),
               "horizon_bars": T.horizon_for(tf), "entry_rule": pl.get("entry_rule"), "expect": expect_of(setup)}
    n = db.execute(
        f"INSERT INTO {TABLE} (id, created_at, symbol, timeframe, bar_ts, signal, decision, score, confidence, regime, "
        "price, side, entry, stop, tp1, tp2, tp3, rr, status, model_version_id, payload, fill_status, filled_at, peak_r, "
        "peak_pct, managed, atr, app_version, engine_version, reject_flag, reject_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 0, 0, 0, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, timeframe, bar_ts) DO NOTHING",
        (new_id(), now, sym, tf, a["bar_ts"], (a.get("signal") or {}).get("signal", ""), decision,
         (a.get("signal") or {}).get("score"), a.get("confidence"), (a.get("regime") or {}).get("regime"), a["price"],
         pl["side"], pl["entry"], pl["stop"], *pl["tps"], pl["rr"], fc.get("model_version"), dumps(payload),
         pl["fill_status"], now if pl["fill_status"] == "FILLED" else None, pl["atr"], app_v, eng_v, flag,
         (reason or "")[:300]))
    return n > 0


def _net_r(r: dict[str, Any]) -> float | None:
    from . import tracking as T
    if r.get("status") not in T.CLOSED_STATUSES or r.get("return_pct") is None or not r.get("entry") or not r.get("stop"):
        return None
    risk = abs(float(r["entry"]) - float(r["stop"])) / float(r["entry"]) * 100
    net = T.net_pct(r)
    return net / risk if net is not None and risk > 0 else None


def _summary(rs: list[float]) -> dict[str, Any]:
    n = len(rs)
    return {"closed": n, "would_have_won": sum(1 for x in rs if x > 0), "would_have_lost": sum(1 for x in rs if x <= 0),
            "total_r": round(sum(rs), 2) if n else 0.0, "avg_r": round(sum(rs) / n, 3) if n else None,
            # the filter blocked calls that would have LOST in total: it saved money
            "verdict": None if n < MIN_JUDGE else ("saving money" if sum(rs) < 0 else "costing money")}


def rejected_board(db: Database, since: int = 0, limit: int = 30) -> dict[str, Any]:
    try:
        rows = db.query(f"SELECT * FROM {TABLE} WHERE created_at >= ? ORDER BY created_at DESC", (int(since),))
    except Exception:
        return {"n": 0, "by_flag": [], "items": []}
    by: dict[str, dict[str, Any]] = {}
    allr: list[float] = []
    items = []
    for r in rows:
        f = r.get("reject_flag") or "?"
        b = by.setdefault(f, {"flag": f, "n": 0, "open": 0, "missed": 0, "rs": []})
        b["n"] += 1
        if r["status"] == "OPEN":
            b["open"] += 1
        elif r["status"] in ("NOT_FILLED", "VOID"):
            b["missed"] += 1
        nr = _net_r(r)
        if nr is not None:
            b["rs"].append(nr)
            allr.append(nr)
        if len(items) < limit:
            items.append({"id": r["id"], "symbol": r["symbol"], "timeframe": r["timeframe"],
                          "side": "LONG" if r["side"] > 0 else "SHORT", "flag": f, "created_at": r["created_at"],
                          "status": r["status"], "tp1_hit": r.get("tp1_hit"), "net_r": None if nr is None else round(nr, 3)})
    flags = sorted(({**{k: v for k, v in b.items() if k != "rs"}, **_summary(b["rs"])} for b in by.values()),
                   key=lambda x: -x["n"])
    return {"n": len(rows), "open": sum(1 for r in rows if r["status"] == "OPEN"), "since": since,
            "min_judge": MIN_JUDGE, **_summary(allr), "by_flag": flags, "items": items}


def _brier(rows: list[dict[str, Any]], base: tuple[float, float, float]) -> tuple[float, float]:
    """(model Brier, base-rate Brier) of the 3-class forecasts."""
    bm = bb = 0.0
    for r in rows:
        y = [1.0 if int(r["actual_class"]) == k else 0.0 for k in (0, 1, 2)]
        p = (float(r["p_down"]), float(r["p_neutral"]), float(r["p_up"]))
        bm += sum((p[k] - y[k]) ** 2 for k in range(3))
        bb += sum((base[k] - y[k]) ** 2 for k in range(3))
    n = max(1, len(rows))
    return bm / n, bb / n


def _skill(rows: list[dict[str, Any]], base: tuple[float, float, float]) -> dict[str, Any] | None:
    if not rows:
        return None
    bm, bb = _brier(rows, base)
    hit = sum(1 for r in rows if int(r["predicted_class"]) == int(r["actual_class"])) / len(rows)
    return {"n": len(rows), "brier": round(bm, 4), "base_brier": round(bb, 4),
            "skill": round(1 - bm / bb, 4) if bb > 0 else None, "hit_rate": round(hit, 4)}


def calibration(db: Database, now: int | None = None, days: int = 37) -> dict[str, Any]:
    """Live forecast quality per timeframe: last 7 days vs the 30 days before. Skill > 0 = better than always saying
    the base rates; drift = the last week clearly worse than the month before."""
    now = now or now_ms()
    since = now - days * DAY
    try:
        rows = db.query(
            "SELECT p.timeframe, p.created_at, p.p_down, p.p_neutral, p.p_up, p.predicted_class, o.actual_class "
            "FROM predictions p JOIN prediction_outcomes o ON o.prediction_id = p.id WHERE p.created_at >= ?", (since,))
    except Exception:
        return {"timeframes": [], "warnings": []}
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["timeframe"], []).append(r)
    out, warns = [], []
    order = {"15m": 0, "1h": 1, "4h": 2, "12h": 3, "1d": 4, "3d": 5}
    for tf in sorted(by, key=lambda t: order.get(t, 9)):
        rs = by[tf]
        cut = now - 7 * DAY
        recent = [r for r in rs if r["created_at"] >= cut]
        before = [r for r in rs if r["created_at"] < cut]
        ref = before or rs          # base rates from the earlier month (no peeking at the week judged)
        cnt = [sum(1 for r in ref if int(r["actual_class"]) == k) for k in (0, 1, 2)]
        tot = max(1, sum(cnt))
        base = (cnt[0] / tot, cnt[1] / tot, cnt[2] / tot)
        s7, s30 = _skill(recent, base), _skill(before, base)
        # reliability: the stated probability of the predicted class vs how often that class happened
        rel = []
        for lo, hi in BUCKETS:
            b = [r for r in rs if lo <= max(float(r["p_down"]), float(r["p_neutral"]), float(r["p_up"])) < hi]
            if len(b) >= 20:
                said = sum(max(float(r["p_down"]), float(r["p_neutral"]), float(r["p_up"])) for r in b) / len(b)
                got = sum(1 for r in b if int(r["predicted_class"]) == int(r["actual_class"])) / len(b)
                rel.append({"lo": lo, "hi": min(hi, 1.0), "n": len(b), "said": round(said, 4), "happened": round(got, 4)})
        gap = (sum(x["n"] * (x["said"] - x["happened"]) for x in rel) / sum(x["n"] for x in rel)) if rel else None
        state = "ok"
        if s7 and s7["n"] >= DRIFT_MIN_N and s7["skill"] is not None:
            if s7["skill"] < 0 and (s30 is None or s30["skill"] is None or s7["skill"] < s30["skill"] - 0.01):
                state = "drift"
            elif s7["skill"] < 0:
                state = "no skill"
        elif not s7 or s7["n"] < DRIFT_MIN_N:
            state = "too few"
        if gap is not None and gap > 0.08 and state == "ok":
            state = "overconfident"
        row = {"timeframe": tf, "last7": s7, "prior30": s30, "reliability": rel,
               "overconfidence": None if gap is None else round(gap, 4), "state": state}
        out.append(row)
        if state == "drift":
            warns.append(f"{tf}: the AI did worse than plain base rates this week (skill {s7['skill']:+.1%}) "
                         "and worse than the month before")
        elif state == "overconfident":
            warns.append(f"{tf}: the AI's stated chances are {gap:.0%} higher than what happened")
    return {"timeframes": out, "warnings": warns, "since": since}


def tp1_check(db: Database, since: int = 0) -> dict[str, Any]:
    """Record calls (v2.24 on, payload `expect`): TP1 base rate stated at the call vs TP1 reached, per timeframe."""
    from . import tracking as T
    try:
        rows = db.query("SELECT timeframe, status, tp1_hit, payload FROM signals WHERE created_at >= ? AND side != 0 "
                        f"AND status IN ({','.join('?' * len(T.CLOSED_STATUSES))})", (int(since), *T.CLOSED_STATUSES))
    except Exception:
        return {"timeframes": []}
    by: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        ex = (loads(r.get("payload"), {}) or {}).get("expect") or {}
        p = (ex.get("p_tp") or [None])[0]
        if p is None:
            continue
        by.setdefault(r["timeframe"], []).append((float(p), int(r.get("tp1_hit") or 0)))
    out = []
    for tf, xs in by.items():
        n = len(xs)
        out.append({"timeframe": tf, "n": n, "expected": round(sum(p for p, _ in xs) / n, 4),
                    "actual": round(sum(h for _, h in xs) / n, 4),
                    # 95 % band of the actual rate if the expectation were right
                    "band": round(1.96 * math.sqrt(max(1e-9, (sum(p for p, _ in xs) / n) * (1 - sum(p for p, _ in xs) / n) / n)), 4)})
    return {"timeframes": sorted(out, key=lambda x: x["timeframe"])}


def checks(db: Database, now: int | None = None, force: bool = False) -> dict[str, Any]:
    """The block published in views/guardian (`checks`); recomputed at most every EVERY_S."""
    now = now or now_ms()
    cached = db.get_setting("proof_checks", None)
    if not force and isinstance(cached, dict) and now - int(cached.get("at") or 0) < EVERY_S * 1000:
        return cached
    since = int(db.get_setting("record_since", 0) or 0)
    t0 = time.time()
    v = {"at": now, "rejected": rejected_board(db),
         "calibration": calibration(db, now), "tp1": tp1_check(db, since), "took_s": round(time.time() - t0, 2)}
    db.set_setting("proof_checks", v)
    return v
