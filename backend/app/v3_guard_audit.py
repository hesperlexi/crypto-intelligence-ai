"""Read-only audit for the "adaptive BTC volatility & capital flow" brief (24 Nov 2026).

python -m app.v3_guard_audit --out x.json
1. Blocked opportunities: every call a filter held back (archive_v3_rejected_signals + rejected_signals), followed to its
   outcome with the record's exits and costs: per filter, per side, per BTC condition at the time.
2. Published calls (archive_v3_signals + signals, trade calls only) by timeframe, side, grade, BTC condition.
3. BTC condition at a call = BTC 24 h return before the call (bucket) and BTC 4h trend (EMA50 slope) - closed candles only.
4. Data coverage for capital-flow / leverage inputs (days of history, newest point).
Counts and R only; no coins with levels."""
from __future__ import annotations

import argparse
import bisect
import json
from collections import defaultdict
from typing import Any

import numpy as np

from .db import Database, loads
from .services import tracking

H = 3_600_000


def _r(row: dict) -> float | None:
    net = tracking.net_pct(row)
    e, s = row.get("entry"), row.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return float(net) / risk if risk > 0 else None


class BTC:
    def __init__(self, db):
        r1 = db.query("SELECT ts, close FROM market_data WHERE symbol='BTC/USDT' AND timeframe='1h' ORDER BY ts")
        self.t1 = [int(x["ts"]) for x in r1]
        self.c1 = [float(x["close"]) for x in r1]
        r4 = db.query("SELECT ts, close FROM market_data WHERE symbol='BTC/USDT' AND timeframe='4h' ORDER BY ts")
        self.t4 = [int(x["ts"]) for x in r4]
        c4 = np.array([float(x["close"]) for x in r4])
        a = 2 / 51
        e = np.empty_like(c4)
        if len(c4):
            e[0] = c4[0]
            for i in range(1, len(c4)):
                e[i] = a * c4[i] + (1 - a) * e[i - 1]
        self.e4, self.c4 = e, c4

    def at(self, t: int) -> dict[str, Any]:
        i = bisect.bisect_right(self.t1, t - H) - 1            # last 1h candle CLOSED by t
        out = {"ret24": None, "trend4h": None}
        if i >= 24:
            out["ret24"] = (self.c1[i] / self.c1[i - 24] - 1) * 100
        j = bisect.bisect_right(self.t4, t - 4 * H) - 1
        if j >= 6:
            slope = (self.e4[j] / self.e4[j - 6] - 1) * 100
            above = self.c4[j] > self.e4[j]
            out["trend4h"] = "up" if slope > 0.3 and above else "down" if slope < -0.3 and not above else "range"
        return out


def bucket(x):
    if x is None:
        return "unknown"
    return "<-3%" if x < -3 else "-3..-1%" if x < -1 else "-1..+1%" if x <= 1 else "+1..+3%" if x <= 3 else ">+3%"


def stats(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"n": 0}
    a = np.array(rs)
    pos, neg = a[a > 0].sum(), -a[a < 0].sum()
    return {"n": len(a), "won": int((a > 0).sum()), "lost": int((a <= 0).sum()), "sum_r": round(float(a.sum()), 2),
            "avg_r": round(float(a.mean()), 3), "pf": round(float(pos / neg), 2) if neg > 0 else None}


def _rows(db, tables, where):
    have = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    out = []
    for t in tables:
        if t in have:
            out += db.query(f"SELECT * FROM {t} WHERE {where}")
    return out


def blocked(db, btc) -> dict[str, Any]:
    rows = _rows(db, ("archive_v3_rejected_signals", "rejected_signals"), "side != 0")
    by = defaultdict(list)
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED" or not r.get("closed_at"):
            continue
        x = _r(r)
        if x is None:
            continue
        b = btc.at(int(r["created_at"]))
        side = "LONG" if r["side"] > 0 else "SHORT"
        f = r.get("reject_flag") or "?"
        for k in (("flag", f), ("flag_side", f"{f}|{side}"), ("btc24", bucket(b["ret24"])),
                  ("flag_btc24", f"{f}|{bucket(b['ret24'])}"), ("btc_trend", f"{side}|btc {b['trend4h']}"),
                  ("tf", r["timeframe"]), ("all", "all")):
            by[k[0] + ":" + k[1]].append(x)
    first = min((int(r["created_at"]) for r in rows), default=None)
    return {"rows": len(rows), "since": first, "groups": {k: stats(v) for k, v in sorted(by.items())}}


def published(db, btc) -> dict[str, Any]:
    rows = _rows(db, ("archive_v3_signals", "signals"), "side != 0 AND status != 'INFO'")
    by = defaultdict(list)
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED" or not r.get("closed_at"):
            continue
        x = _r(r)
        if x is None:
            continue
        p = loads(r.get("payload"), {}) or {}
        b = btc.at(int(r["created_at"]))
        side = "LONG" if r["side"] > 0 else "SHORT"
        for k in (("all", "all"), ("tf", r["timeframe"]), ("side", side), ("grade", str(p.get("grade"))),
                  ("btc24", bucket(b["ret24"])), ("btc_trend", f"{side}|btc {b['trend4h']}"),
                  ("regime", str(r.get("regime"))), ("tf_side", f"{r['timeframe']}|{side}")):
            by[k[0] + ":" + k[1]].append(x)
    first = min((int(r["created_at"]) for r in rows), default=None)
    return {"rows": len(rows), "since": first, "groups": {k: stats(v) for k, v in sorted(by.items())}}


def coverage(db) -> dict[str, Any]:
    out = {}
    q = [("derivs", "kind", "SELECT kind AS k, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM derivs WHERE symbol='BTC/USDT' GROUP BY kind"),
         ("mkt_okx", "kind", "SELECT kind AS k, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM mkt_okx WHERE coin='BTC' GROUP BY kind"),
         ("mkt_daily", "kind", "SELECT kind AS k, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM mkt_daily GROUP BY kind"),
         ("mkt_liq", "coin", "SELECT coin AS k, COUNT(*) n, MIN(ts) a, MAX(ts) b FROM mkt_liq WHERE coin='BTC' GROUP BY coin")]
    for t, _, sql in q:
        try:
            out[t] = {r["k"]: {"n": r["n"], "days": round((r["b"] - r["a"]) / 86_400_000, 1), "newest": r["b"]} for r in db.query(sql)}
        except Exception as e:  # noqa: BLE001
            out[t] = {"error": type(e).__name__}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    a = ap.parse_args()
    from .research_verdict import frozen_copy
    db = Database(frozen_copy(a.db))          # V3.2: private copy without the forward-holdout period
    btc = BTC(db)
    out: dict[str, Any] = {"ok": True}
    for k, fn in (("blocked", lambda: blocked(db, btc)), ("published", lambda: published(db, btc)), ("coverage", lambda: coverage(db))):
        try:
            out[k] = fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            out[k] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1200:]}
    with open(a.out, "w") as f:
        json.dump(out, f, default=str)


if __name__ == "__main__":
    main()
