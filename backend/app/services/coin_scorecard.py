"""v2.33 coin scorecard (owner, 14 Nov 2026: "let the radar categorize the coins and track the ones which can give better
results while the page should suggest the ones which are not giving any output so we can remove them - by output i
mean no good signals").

Every watchlist coin, from the real record only (wins and losses alike, net after fees, the record's own counting
window `views.record_clause`), over the last WINDOW_DAYS (or since the record start when that is shorter):
public calls published, closed / won, average and total net %, open now, and calls the filters blocked
(`rejected_signals`, the v2.24 filter check). Category:

* best    - at least MIN_CLOSED closed, average net > 0 and win rate >= 50 %
* working - at least MIN_CLOSED closed, average net > 0
* losing  - at least MIN_CLOSED_LOSING closed and average net < 0
* quiet   - no public call in the window (needs MIN_DAYS of watching): "no good signals"
* early   - anything else (too few closed calls to judge)

`suggest_remove` = quiet, or losing with win rate < 40 % over at least MIN_CLOSED_REMOVE closed calls; never a
pinned coin (BTC, gold). Suggestions only: nothing is removed automatically. Published inside `views/radar` (hourly).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..db import now_ms
from . import tracking

DAY = 86_400_000
WINDOW_DAYS = 30
MIN_DAYS = 7
MIN_CLOSED = 3
MIN_CLOSED_LOSING = 4
MIN_CLOSED_REMOVE = 6
STUDY_FILE = Path(__file__).resolve().parent.parent / "assets" / "coin_study.json"   # research-coins.yml aggregates
BAD_TEST_R, BAD_TEST_N = -0.15, 30        # past test clearly negative: also suggested (unless the live record is positive)
LABELS = {"best": "Best results", "working": "Making money", "early": "Too early to judge",
          "losing": "Losing after fees", "quiet": "No signals"}


def _category(c: dict[str, Any], watched_days: float) -> str:
    n, avg, wr = c["closed"], c["avg_net_pct"], c["win_rate"]
    if n >= MIN_CLOSED and avg is not None and avg > 0:
        return "best" if (wr or 0) >= 0.5 else "working"
    if n >= MIN_CLOSED_LOSING and avg is not None and avg < 0:
        return "losing"
    if c["calls"] == 0 and watched_days >= MIN_DAYS:
        return "quiet"
    return "early"


def build(rt: Any, watchlist: list[dict[str, Any]] | list[str], now: int | None = None) -> dict[str, Any]:
    from .. import views
    now = now_ms() if now is None else now
    items = [w if isinstance(w, dict) else {"symbol": w, "pinned": False} for w in watchlist]
    clause, params = views.record_clause(rt)
    since = max(views.record_since(rt), now - WINDOW_DAYS * DAY)
    watched_days = (now - since) / DAY
    rows = rt.db.query(f"SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND created_at >= ? AND {clause}",
                       (since, *params))
    try:
        blocked = {r["symbol"]: int(r["n"]) for r in rt.db.query(
            "SELECT symbol, COUNT(*) AS n FROM rejected_signals WHERE created_at >= ? GROUP BY symbol", (since,))}
    except Exception:
        blocked = {}
    study = load_study()
    coins = []
    for w in items:
        sym = w["symbol"]
        mine = [r for r in rows if r["symbol"] == sym]
        closed = [r for r in mine if r.get("status") in tracking.CLOSED_STATUSES and r.get("fill_status") != "NOT_FILLED"]
        nets = [x for x in (tracking.net_pct(r) for r in closed) if x is not None]
        wins = sum(1 for x in nets if x > 0)
        c = {"symbol": sym, "pinned": bool(w.get("pinned")), "calls": len(mine), "closed": len(nets), "wins": wins,
             "win_rate": round(wins / len(nets), 3) if nets else None,
             "avg_net_pct": round(sum(nets) / len(nets), 3) if nets else None,
             "total_net_pct": round(sum(nets), 2) if nets else None,
             "open": sum(1 for r in mine if r.get("status") == "OPEN"),
             "blocked": blocked.get(sym, 0),
             "last_call_at": max((int(r["created_at"]) for r in mine), default=None),
             "timeframes": sorted({r["timeframe"] for r in mine})}
        days = (now - max(since, int(w.get("added_at") or 0))) / DAY       # a newly added coin is not "quiet" yet
        c["watched_days"] = round(days, 1)
        c["category"] = _category(c, days)
        bad = (c["category"] == "losing" and c["closed"] >= MIN_CLOSED_REMOVE and (c["win_rate"] or 0) < 0.4)
        t = (study.get("watchlist") or {}).get(sym)
        c["past_test"] = {k: t[k] for k in ("avg_r", "trades", "win_rate")} if t else None
        bad_test = bool(t and t["trades"] >= BAD_TEST_N and (t["avg_r"] or 0) <= BAD_TEST_R
                        and not (c["avg_net_pct"] is not None and c["avg_net_pct"] > 0))
        c["suggest_remove"] = bool(not c["pinned"] and (c["category"] == "quiet" or bad or bad_test))
        c["why"] = ("no public signal in %d days" % round(days) if c["category"] == "quiet"
                    else f"{c['closed']} closed, win rate {round((c['win_rate'] or 0) * 100)}%, average {c['avg_net_pct']:+.2f}% after fees"
                    if bad else f"past test: {t['avg_r']:+.2f}R per trade over {t['trades']} trades (losing after fees)"
                    if bad_test else None)
        coins.append(c)
    have = {c["symbol"] for c in coins}
    cands = [dict(r, verdict=verdict(r)) for r in study.get("candidates") or [] if r["symbol"] not in have]
    order = {"best": 0, "working": 1, "early": 2, "losing": 3, "quiet": 4}
    coins.sort(key=lambda c: (order[c["category"]], -(c["total_net_pct"] or 0), -c["calls"]))
    return {"since": since, "days": round(watched_days, 1), "coins": coins, "labels": LABELS,
            "counts": {k: sum(1 for c in coins if c["category"] == k) for k in order},
            "suggest_remove": [c["symbol"] for c in coins if c["suggest_remove"]],
            "study": {"stamp": study.get("stamp"), "method": study.get("method"), "candidates": cands,
                      "baseline": study.get("baseline_overall")} if study else None,
            "method": (f"From the real record only, after fees, over the last {WINDOW_DAYS} days (or since the record "
                       f"started). Best / making money: at least {MIN_CLOSED} closed calls with a positive average. "
                       f"Losing: at least {MIN_CLOSED_LOSING} closed with a negative average. No signals: not one public "
                       f"call in the window. Suggested to remove: no signals, or losing with a win rate under 40% over "
                       f"{MIN_CLOSED_REMOVE}+ closed calls. BTC and gold are never suggested.")}


def load_study() -> dict[str, Any]:
    try:
        return json.loads(STUDY_FILE.read_text())
    except Exception:
        return {}


def verdict(r: dict[str, Any]) -> str:
    """A tested new coin: add (positive, enough trades, futures on Binance and MEXC) / promising (positive, few trades) /
    no_mexc (positive but no MEXC futures) / weak / avoid."""
    avg, n, lst = r.get("avg_r") or 0.0, int(r.get("trades") or 0), r.get("listings") or {}
    if avg >= 0.05 and not (lst.get("mexc_futures") and lst.get("binance_futures")):
        return "no_mexc"
    if avg >= 0.05:
        return "add" if n >= 30 else "promising"
    return "weak" if avg > -0.05 else "avoid"
