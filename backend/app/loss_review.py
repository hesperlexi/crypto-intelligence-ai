"""Read-only review (owner, 23 Nov 2026: "since yesterday we are losing continuously - market or our changes?").

python -m app.loss_review --out x.json. From the engine state copy: closed record calls per Dubai day (last 10 days),
and for the recent window (from --since-ms, default 22 Nov 00:00 Dubai) splits by timeframe, side, grade, coin, exit,
the payload switches that changed lately (15m filters bypassed, capital-protection shadow, runner, reserve slot), the
calls the filters blocked in the same window, and BTC's daily move (market backdrop). Counts and R only."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .db import Database
from .services import tracking

DUBAI = timezone(timedelta(hours=4))
DAY = 86_400_000


def _r(row: dict) -> float | None:
    net = tracking.net_pct(row)
    e, s = row.get("entry"), row.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return float(net) / risk if risk > 0 else None


def _stats(rows: list[dict]) -> dict:
    rs = [x for x in (_r(r) for r in rows) if x is not None]
    nets = [float(tracking.net_pct(r) or 0) for r in rows]
    return {"n": len(rows), "won": sum(1 for v in nets if v > 0), "lost": sum(1 for v in nets if v <= 0),
            "net_pct_sum": round(sum(nets), 2), "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "sum_r": round(sum(rs), 2)}


def _payload(r: dict) -> dict:
    try:
        return json.loads(r.get("payload") or "{}") or {}
    except Exception:
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--since-ms", type=int, default=int(datetime(2026, 11, 22, tzinfo=DUBAI).timestamp() * 1000))
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    from .research_verdict import frozen_copy
    db = Database(frozen_copy(a.db))          # V3.2: private copy without the forward-holdout period
    since_rec = int(db.get_setting("record_since", 0) or 0)
    closed = tuple(tracking.CLOSED_STATUSES)
    q = ",".join("?" * len(closed))
    rows = db.query(f"SELECT * FROM signals WHERE status IN ({q}) AND COALESCE(fill_status,'') != 'NOT_FILLED' "
                    "AND created_at >= ? AND closed_at IS NOT NULL ORDER BY closed_at", (*closed, since_rec))
    out: dict = {"ok": True, "record_since": since_rec, "since": a.since_ms}
    day = defaultdict(list)
    for r in rows:
        d = datetime.fromtimestamp(int(r["closed_at"]) / 1000, DUBAI).strftime("%Y-%m-%d")
        day[d].append(r)
    out["by_day"] = {d: _stats(v) for d, v in sorted(day.items())[-10:]}
    recent = [r for r in rows if int(r["closed_at"]) >= a.since_ms]
    before = [r for r in rows if int(r["closed_at"]) < a.since_ms]
    out["recent_all"], out["before_all"] = _stats(recent), _stats(before)

    def split(rs, key):
        g = defaultdict(list)
        for r in rs:
            g[key(r)].append(r)
        return {k: _stats(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}
    for name, fn in (("timeframe", lambda r: r["timeframe"]), ("side", lambda r: "LONG" if r["side"] > 0 else "SHORT"),
                     ("grade", lambda r: _payload(r).get("grade") or "?"), ("coin", lambda r: r["symbol"]),
                     ("exit", lambda r: r["status"] + ("·admin" if r.get("exit_reason") == "admin_close" else "")),
                     ("filter_bypassed", lambda r: bool(_payload(r).get("filter_bypassed"))),
                     ("risk_would_block", lambda r: bool((_payload(r).get("risk_shadow") or {}).get("would_block"))),
                     ("runner", lambda r: bool((_payload(r).get("runner") or {}).get("on") if isinstance(_payload(r).get("runner"), dict) else _payload(r).get("runner"))),
                     ("reserve_slot", lambda r: bool(_payload(r).get("reserve_slot") or _payload(r).get("same_side_reserve"))),
                     ("entry_mode", lambda r: ((_payload(r).get("entry_rule") or {}).get("mode") or "?"))):
        out[f"recent_by_{name}"] = split(recent, fn)
        out[f"before_by_{name}"] = split(before, fn)
    keys = defaultdict(int)
    for r in recent:
        for k in _payload(r):
            keys[k] += 1
    out["recent_payload_keys"] = dict(sorted(keys.items()))
    # recent list (no prices): coin, tf, side, grade, exit, net %, R, opened / closed (Dubai)
    f = lambda ms: datetime.fromtimestamp(int(ms) / 1000, DUBAI).strftime("%d %H:%M")  # noqa: E731
    out["recent_calls"] = [{"coin": r["symbol"].split("/")[0], "tf": r["timeframe"], "side": "L" if r["side"] > 0 else "S",
                            "grade": _payload(r).get("grade"), "exit": r["status"], "net": round(float(tracking.net_pct(r) or 0), 2),
                            "r": round(_r(r) or 0, 2), "open": f(r["created_at"]), "close": f(r["closed_at"]),
                            "bypass": bool(_payload(r).get("filter_bypassed")),
                            "veto_shadow": bool((_payload(r).get("risk_shadow") or {}).get("would_block"))} for r in recent]
    # what the filters blocked in the same window (followed privately)
    rej = db.query(f"SELECT * FROM rejected_signals WHERE status IN ({q}) AND COALESCE(fill_status,'') != 'NOT_FILLED' "
                   "AND closed_at >= ?", (*closed, a.since_ms))
    g = defaultdict(list)
    for r in rej:
        g[r.get("reject_flag") or "?"].append(r)
    out["recent_blocked_by_flag"] = {k: _stats(v) for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))}
    # open calls now
    op = db.query("SELECT symbol, timeframe, side, created_at FROM signals WHERE status = 'OPEN'")
    out["open_now"] = {"n": len(op), "long": sum(1 for r in op if r["side"] > 0), "short": sum(1 for r in op if r["side"] < 0)}
    # market backdrop: BTC / ETH / SOL daily move (Dubai days) from the stored 1h candles
    mk = {}
    try:
        from .services.runtime import Runtime
        rt = Runtime(db, None)
        for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
            df = rt.store.load(rt.exchange, sym, "1h")
            dd = defaultdict(list)
            for x in df[df["ts"] >= a.since_ms - 4 * DAY].itertuples():
                dd[datetime.fromtimestamp(int(x.ts) / 1000, DUBAI).strftime("%Y-%m-%d")].append(x)
            mk[sym] = {d: round((v[-1].close / v[0].open - 1) * 100, 2) for d, v in sorted(dd.items()) if v}
    except Exception as exc:
        mk = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    out["market_daily_move_pct"] = mk
    s = json.dumps(out, indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)


if __name__ == "__main__":
    main()
