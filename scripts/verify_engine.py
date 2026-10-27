"""Engine self-check on a COPY of the engine state (nothing is published, nothing is saved).

1. Record: every closed signal since the record start is re-followed from the stored candles with the current rules
   and compared with what the record says (status and result).
2. Models: every coin/timeframe is analysed with its active model; errors, statuses and decisions are counted, and
   every trade plan is re-checked (targets, stop side, R multiples).
3. Model freshness and the per-model extras (trade filter, AI targets, runner, higher-timeframe test).
Run from backend/ with DATABASE_URL pointing at the copy. Prints JSON (aggregates and coin names only).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.getcwd())

from app.config import MODEL_TIMEFRAMES  # noqa: E402
from app.db import get_db, loads  # noqa: E402
from app.services import analysis, market, tracking  # noqa: E402
from app.services.runtime import Runtime  # noqa: E402
from app.ml import trainer  # noqa: E402

out = {"problems": []}
P = out["problems"].append
db = get_db()
rt = Runtime(db, market.make_provider())
since = int(db.get_setting("record_since", 0) or 0)

# 1. record re-follow
rows = db.query("SELECT id, symbol, timeframe, status, return_pct FROM signals WHERE status IN "
                "('TP1','TP2','TP3','STOPPED','EXPIRED') AND created_at >= ?", (since,))
before = {r["id"]: (r["status"], r["return_pct"]) for r in rows}
db.execute("UPDATE signals SET status = 'OPEN', closed_at = NULL WHERE status IN ('TP1','TP2','TP3','STOPPED','EXPIRED') "
           "AND created_at >= ?", (since,))
t0 = time.time()
tracking.update_signal_outcomes(rt)
after = {r["id"]: (r["status"], r["return_pct"], r["symbol"], r["timeframe"])
         for r in db.query("SELECT id, symbol, timeframe, status, return_pct FROM signals WHERE id IN (%s)"
                           % ",".join("?" * len(before)), tuple(before))} if before else {}
diff = [(k, before[k], after[k]) for k in before if k in after and
        (before[k][0] != after[k][0] or abs((before[k][1] or 0) - (after[k][1] or 0)) > 1e-6)]
out["record"] = {"closed_checked": len(before), "seconds": round(time.time() - t0, 1), "different": len(diff),
                 "examples": [{"coin": a[2], "tf": a[3], "record": b, "recomputed": a[:2]} for _, b, a in diff[:8]],
                 "still_open_after_refollow": sum(1 for v in after.values() if v[0] == "OPEN")}
if diff:
    P(f"{len(diff)} closed signals differ when re-followed from the candles")

# 2. every coin / timeframe through its model
stat, dec, errs, plans, bad_plans = {}, {}, [], 0, []
ages = []
for s in rt.symbols():
    for tf in MODEL_TIMEFRAMES:
        try:
            a = analysis.analyze(rt, s, tf, detail=False, use_cache=False)
        except Exception as exc:
            errs.append(f"{s} {tf}: {type(exc).__name__}: {exc}"[:160]); continue
        stat[a.get("status")] = stat.get(a.get("status"), 0) + 1
        dec[a.get("decision")] = dec.get(a.get("decision"), 0) + 1
        fc = a.get("forecast") or {}
        if fc.get("status") == "MODEL ERROR":
            errs.append(f"{s} {tf}: {fc.get('reason')}"[:160])
        if fc.get("available"):
            ages.append(fc.get("model_age_h") or 0)
        st = a.get("setup") or {}
        if st.get("valid") and a.get("decision") in analysis.TRADE_DECISIONS:
            plans += 1
            side, e, stp = st["side_int"], st["ideal_entry"], st["stop"]
            R = abs(e - stp)
            rr = [t["rr"] for t in st["targets"]]
            if side * (e - stp) <= 0 or abs(rr[0] - 1) > 0.01 or not (1.24 <= rr[1] <= 2.01 and 1.99 <= rr[2] <= 3.01) \
                    or any(abs(side * (t["price"] - e) / R - t["rr"]) > 0.02 for t in st["targets"]):
                bad_plans.append(f"{s} {tf}")
out["analyses"] = {"statuses": stat, "decisions": dec, "errors": errs[:10], "trade_plans": plans, "bad_plans": bad_plans[:10],
                   "model_age_h_max": round(max(ages), 1) if ages else None, "models_used": len(ages)}
if errs:
    P(f"{len(errs)} analyses raised errors")
if bad_plans:
    P(f"{len(bad_plans)} trade plans break the target rules")

# 3. model extras
ext = {"trade_filter_on": 0, "target_model_on": 0, "runner_on": 0, "htf_on": 0, "htf_tested": 0, "deep_members": 0, "n": 0}
for r in db.query("SELECT symbol, timeframe FROM model_versions WHERE active = 1"):
    b = trainer.load_bundle(r["symbol"], r["timeframe"], db)
    if not b:
        continue
    ext["n"] += 1
    ext["trade_filter_on"] += bool((b.get("trade_filter") or {}).get("enabled"))
    ext["target_model_on"] += bool((b.get("target_model") or {}).get("enabled"))
    ext["runner_on"] += bool((b.get("runner_model") or {}).get("enabled"))
    ext["htf_on"] += bool(b.get("uses_htf"))
    ext["htf_tested"] += bool((b.get("extras") or {}).get("htf_gate"))
    ext["deep_members"] += sum(1 for k in b["models"] if k in ("lstm", "gru", "transformer"))
out["model_extras"] = ext
print(json.dumps(out, indent=1, default=str))
