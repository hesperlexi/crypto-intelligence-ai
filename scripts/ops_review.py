"""Read-only operations review (owner, 27 Nov 2026: "performance dropped after the updates - updates or market?").
Runs on a COPY of the engine state; nothing is published or saved back. Prints COUNTS only (no coin + side, no levels):
  1. record calls per timeframe before vs after the 26 Nov update (published, closed, won / lost, avg net %),
  2. calls the filters held back (rejected_signals) per timeframe x flag, before vs after,
  3. engine decisions (skip reasons) per timeframe, before vs after,
  4. guard / portfolio / regime state now,
  5. a fresh analysis of every coin now on 15m / 1h / 4h / 12h: final decision and every flag that was raised.
Run from backend/: python ../scripts/ops_review.py > out.json"""
import collections
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.getcwd())
from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services import analysis, market, tracking  # noqa: E402
from app.services.runtime import Runtime  # noqa: E402

H = 3600_000
NOW = int(time.time() * 1000)
DEPLOY = 1795668300000            # 26 Nov 2026 04:45 UTC: V3.2-V3.4 stages live
BEFORE = DEPLOY - 7 * 24 * H      # the 7 days before it
CLOSED = tuple(tracking.CLOSED_STATUSES)
TFS = ("15m", "1h", "4h", "12h", "1d", "3d")


def win(ts):
    return "before" if BEFORE <= ts < DEPLOY else ("after" if ts >= DEPLOY else None)


def main():
    settings.ensure_dirs()
    db = get_db()
    out = {"now": NOW, "deploy": DEPLOY, "before_from": BEFORE, "hours_after": round((NOW - DEPLOY) / H, 1)}

    # 1. record
    rec = {w: {tf: collections.Counter() for tf in TFS} for w in ("before", "after")}
    net = {w: {tf: [] for tf in TFS} for w in ("before", "after")}
    for r in db.query("SELECT timeframe, side, status, fill_status, created_at, return_net_pct, payload FROM signals "
                      "WHERE created_at >= ?", (BEFORE,)):
        w = win(int(r["created_at"] or 0))
        tf = r["timeframe"]
        if not w or tf not in TFS or not r["side"]:
            continue
        c = rec[w][tf]
        c["published"] += 1
        c["long" if r["side"] > 0 else "short"] += 1
        if r["fill_status"] == "NOT_FILLED":
            c["not_filled"] += 1
        elif r["status"] in CLOSED:
            n = float(r["return_net_pct"] or 0)
            c["closed"] += 1
            c["won" if n > 0 else "lost"] += 1
            net[w][tf].append(n)
        else:
            c["open_or_pending"] += 1
    for w in rec:
        for tf in TFS:
            xs = net[w][tf]
            if xs:
                rec[w][tf]["avg_net_pct_x100"] = round(sum(xs) / len(xs) * 100)
    out["record"] = {w: {tf: dict(c) for tf, c in v.items() if c} for w, v in rec.items()}

    # also count the archived pre-reset record (V3.0 fresh start 24 Nov moved older calls to archive_v3_signals)
    try:
        arch = collections.Counter()
        for r in db.query("SELECT timeframe, created_at FROM archive_v3_signals WHERE created_at >= ? AND side != 0", (BEFORE,)):
            arch[r["timeframe"]] += 1
        out["record_archived_before_reset"] = dict(arch)
    except Exception as exc:
        out["record_archived_before_reset"] = f"n/a {type(exc).__name__}"

    # 2. held back by filters
    rj = {w: collections.Counter() for w in ("before", "after")}
    for tbl in ("rejected_signals", "archive_v3_rejected_signals"):
        try:
            for r in db.query(f"SELECT timeframe, reject_flag, created_at FROM {tbl} WHERE created_at >= ?", (BEFORE,)):
                w = win(int(r["created_at"] or 0))
                if w:
                    rj[w][f"{r['timeframe']}|{r['reject_flag'] or '?'}"] += 1
        except Exception:
            pass
    out["held_back"] = {w: dict(sorted(c.items())) for w, c in rj.items()}

    # 3. engine decisions
    dc = {w: collections.Counter() for w in ("before", "after")}
    for tbl in ("decisions", "archive_v3_decisions"):
        try:
            for r in db.query(f"SELECT ts, timeframe, rule, inputs FROM {tbl} WHERE ts >= ?", (BEFORE,)):
                w = win(int(r["ts"] or 0))
                if not w:
                    continue
                rule = r["rule"] or "?"
                if rule == "skip_entry":
                    try:
                        why = str((json.loads(r["inputs"] or "{}") or {}).get("reason") or "")[:40]
                    except Exception:
                        why = "?"
                    rule = f"skip_entry:{why}"
                dc[w][f"{r['timeframe']}|{rule}"] += 1
        except Exception:
            pass
    out["decisions"] = {w: dict(sorted(c.items())) for w, c in dc.items()}

    # 4. state
    st = {}
    for k in ("gate_failures", "portfolio_state", "filter_off_revoked|15m", "safety:state"):
        v = db.get_setting(k, None)
        if k == "gate_failures" and isinstance(v, dict):
            v = {g: {"count": x.get("count"), "age_min": round((NOW - int(x.get("at") or 0)) / 60000),
                     "timeframe": x.get("timeframe"), "detail": str(x.get("detail") or "")[:100]} for g, x in v.items()}
        st[k] = v
    for k in ("market_regime", "risk_state"):
        v = db.get_setting(k, None) or {}
        st[k] = {kk: v.get(kk) for kk in ("label", "state", "level", "confidence", "agreement", "at", "points")} if isinstance(v, dict) else v
    try:
        from app.services import portfolio_risk
        st["portfolio_mode"] = getattr(portfolio_risk, "MODE", None) or os.environ.get("PORTFOLIO_GATE")
    except Exception:
        pass
    out["state"] = st

    # 5. fresh analysis now
    rt = Runtime(db, market.make_provider())
    syms = rt.symbols()
    live = {}
    for tf in ("15m", "1h", "4h", "12h"):
        dec, flags, grades, recst = collections.Counter(), collections.Counter(), collections.Counter(), collections.Counter()
        errors = 0
        for s in syms:
            try:
                a = analysis.analyze(rt, s, tf, detail=True, use_cache=False)
            except Exception:
                errors += 1
                if errors <= 2:
                    out.setdefault("errors", []).append(traceback.format_exc()[-600:])
                continue
            dec[a.get("decision") or "?"] += 1
            grades[str(a.get("grade"))] += 1
            recst[str(a.get("record_status"))] += 1
            for f in a.get("flags") or []:
                flags[str(f)[:40]] += 1
        live[tf] = {"coins": len(syms), "errors": errors, "decisions": dict(dec), "grades": dict(grades),
                    "record_status": dict(recst), "flags": dict(flags.most_common(30))}
    out["live_now"] = live
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
