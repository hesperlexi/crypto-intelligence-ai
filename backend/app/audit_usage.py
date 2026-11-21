"""v2.65 deep audit (read-only): which built capabilities are ACTUALLY switched on in the live engine state.
Loads each active model bundle and counts its add-ons; reads the nightly policy settings and the record's payloads.
python -m app.audit_usage --out x.json  (aggregates only, no coin + side / levels)."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from .db import Database, loads


def run(db_url: str) -> dict[str, Any]:
    import joblib
    db = Database(db_url)
    rows = db.query("SELECT id, symbol, timeframe, created_at, edge_confirmed, path, summary FROM model_versions WHERE active = 1")
    per_tf: dict[str, Counter] = defaultdict(Counter)
    errors = Counter()
    ages = defaultdict(list)
    import time
    now = time.time() * 1000
    for r in rows:
        tf = r["timeframe"]
        c = per_tf[tf]
        c["bundles"] += 1
        c["edge_confirmed"] += int(r["edge_confirmed"] or 0)
        ages[tf].append((now - int(r["created_at"])) / 86_400_000)
        s = loads(r.get("summary"), {}) or {}
        if s.get("has_skill"):
            c["has_skill"] += 1
        if s.get("weights_by_regime"):
            c["regime_weights"] += 1
        for m in s.get("models") or []:
            c[f"model:{m}"] += 1
        if s.get("uses_btc"):
            c["uses_btc"] += 1
        if s.get("uses_htf"):
            c["uses_htf"] += 1
        try:
            b = joblib.load(r["path"])
        except Exception as exc:
            errors[type(exc).__name__] += 1
            continue
        for key in ("trade_filter", "target_model", "runner_model"):
            x = b.get(key) or {}
            c[f"{key}:{'on' if x.get('enabled') else 'off'}"] += 1
        ex = b.get("extras") or {}
        for key in ("deriv_gate", "htf_gate"):
            g = ex.get(key)
            on = bool(g.get("on")) if isinstance(g, dict) else bool(g)
            c[f"{key}:{'on' if on else 'off'}"] += 1
        c["deep_members"] += int(any(m in (b.get("models") or {}) for m in ("lstm", "gru", "transformer")))
    out_tf = {tf: {**dict(sorted(c.items())), "median_age_days": round(sorted(ages[tf])[len(ages[tf]) // 2], 1) if ages[tf] else None}
              for tf, c in sorted(per_tf.items())}
    settings = {}
    for r in db.query("SELECT key, value FROM app_settings WHERE key LIKE 'trade_filter2|%' OR key LIKE 'entry_policy1|%' "
                      "OR key LIKE 'filter_off_%' OR key LIKE 'safety%'"):
        v = loads(r["value"], r["value"])
        if isinstance(v, dict):
            v = {k: v.get(k) for k in ("enabled", "mode", "rule", "at", "exam", "n", "reason", "closed", "avg_r", "paused") if k in v}
        settings[r["key"]] = v
    sp = Counter()
    for r in db.query("SELECT value FROM app_settings WHERE key LIKE 'series_policy1|%'"):
        v = loads(r["value"], {}) or {}
        sp["series"] += 1
        sp["gate_blocks"] += int(bool(v.get("blocked")))
    pay = Counter()
    for r in db.query("SELECT payload, timeframe FROM signals WHERE side != 0 AND created_at >= ?",
                      (int(now - 30 * 86_400_000),)):
        p = loads(r.get("payload"), {}) or {}
        pay["calls_30d"] += 1
        pay["with_expect"] += int(bool(p.get("expect")))
        pay["runner_on"] += int(bool((p.get("runner") or {}).get("on")))
        pay["risk_shadow"] += int(bool(p.get("risk_shadow")))
        pay["filter_bypassed"] += int(bool(p.get("filter_bypassed")))
    preds = db.one("SELECT COUNT(*) AS n FROM predictions WHERE created_at >= ?", (int(now - 86_400_000),))
    return {"ok": True, "active_bundles": len(rows), "load_errors": dict(errors), "by_timeframe": out_tf,
            "nightly_settings": settings, "series_policy": dict(sp), "record_payloads_30d": dict(pay),
            "predictions_last_24h": (preds or {}).get("n")}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
