"""v2.1 check: watchlist (gold), signal views and record, as AGGREGATE COUNTS only (no personal data).

The output goes to the public `reports` branch and public job logs, so it never contains a call's coin, side, grade or
levels (members pay for those), nor any record row - only counts and statuses (v2.13)."""
import json, os, time
import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()


def _edge_only(reason: str) -> None:
    """Firestore refused (daily quota): report what the Cloudflare side knows, then stop."""
    import hashlib, urllib.request
    o = {"firestore": reason[:200]}
    base = "https://cia-chat.cryptointelai.workers.dev"
    try:
        o["edge_health"] = json.load(urllib.request.urlopen(urllib.request.Request(base + "/edge-health", headers={"User-Agent": "cia-status"}), timeout=20))
    except Exception as exc:
        o["edge_health"] = {"error": str(exc)[:200]}
    try:
        key = hashlib.sha256(("cia-edge-v1|" + os.environ["FIREBASE_SERVICE_ACCOUNT"]).encode()).hexdigest()
        st = json.load(urllib.request.urlopen(urllib.request.Request(base + "/watch/status?since=0", headers={"X-Edge-Key": key, "User-Agent": "cia-status"}), timeout=20))
        o["cloud_watcher"] = {k: st.get(k) for k in ("at", "armed", "priced", "sent_total", "error", "idle", "price_tries")}
    except Exception as exc:
        o["cloud_watcher"] = {"error": str(exc)[:200]}
    try:   # the record and the bots as members see them (edge copy), compared without coin / side / levels
        q = "https://cia-chat.cryptointelai.workers.dev/v?n=track_record,bots,futures_15m,futures_1h,futures_4h,futures_12h&e=,,,,,"
        vv = json.load(urllib.request.urlopen(urllib.request.Request(q, headers={"X-Edge-Key": key, "User-Agent": "cia-status"}), timeout=30))["views"]
        trj = (vv.get("track_record") or {}).get("data") or {}
        bj = (vv.get("bots") or {}).get("data") or {}
        sigs = (trj.get("live") or {}).get("signals") or trj.get("signals") or []
        o["record_at"] = (vv.get("track_record") or {}).get("at")
        o["record_open"] = [{"tf": x.get("timeframe"), "status": x.get("status"), "fill": x.get("fill_status"), "created_at": x.get("created_at")}
                            for x in sigs if x.get("status") in ("OPEN", "PENDING")]
        o["record_newest"] = [{"tf": x.get("timeframe"), "status": x.get("status"), "created_at": x.get("created_at")}
                              for x in sorted(sigs, key=lambda x: -(x.get("created_at") or 0))[:5]]
        rows = []
        for b in bj.get("bots") or []:
            cfg = b.get("config") or {}
            for pz in b.get("positions") or []:
                inf = pz.get("info") or {}
                tf = inf.get("timeframe") or cfg.get("timeframe")
                same = [x for x in sigs if x.get("timeframe") == tf and x.get("symbol") == pz.get("symbol")
                        and (x.get("side") == "LONG") == (int(pz.get("side") or 0) > 0)]
                rows.append({"bot": cfg.get("id"), "tf": tf, "opened_at": pz.get("opened_at"), "info_keys": sorted(inf.keys())[:16],
                             "grade": inf.get("grade"), "demo": inf.get("demo"),
                             "pending_bars": cfg.get("pending_bars"), "exit_at": pz.get("exit_at"),
                             "record_same_coin_tf_side": [{k: x.get(k) for k in ("status", "created_at", "fill_status", "filled_at", "closed_at",
                                                           "exit_reason", "horizon_bars", "expires_at", "tp1_hit", "stop_hit")} for x in same][:3]})
        o["bots_open"] = rows
        for tf in ("15m", "1h", "4h", "12h"):
            fr = ((vv.get(f"futures_{tf}") or {}).get("data") or {}).get("rows") or []
            o[f"calls_{tf}"] = {"at": (vv.get(f"futures_{tf}") or {}).get("at"),
                                "with_plan": sum(1 for r in fr if r.get("plan")), "record_status": sorted({str(r.get("record_status")) for r in fr})}
    except Exception as exc:
        o["record_error"] = str(exc)[:300]
    print(json.dumps(o, indent=1, default=str))
    raise SystemExit(0)


try:
    _probe = fs.document("config/watchlist").get()
except Exception as _exc:
    _edge_only(str(_exc))
wl = [x.get("symbol") for x in (_probe.to_dict() or {}).get("symbols", [])]
out = {"watchlist": wl, "views": {}}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    d = fs.document(f"views/futures_{tf}").get().to_dict()
    v = json.loads(d["json"]) if d and d.get("json") else {}
    rows = v.get("rows") or []
    out["views"][tf] = {
        "rows": len(rows), "updated": (d or {}).get("updated_at"),
        "with_plan": sum(1 for r in rows if r.get("plan")),
        "grades": {g: sum(1 for r in rows if r.get("plan") and str(r.get("grade")) == g) for g in sorted({str(r.get("grade")) for r in rows if r.get("plan")})},
        "statuses": sorted({str(r.get("status")) for r in rows}),
        "gold_row": any(str(r.get("symbol", "")).startswith("PAXG") for r in rows),
    }
# (v3.1: the size listing of every view was removed - it read ~800 documents per run of this check)
h = fs.document("views/health_admin").get().to_dict() or fs.document("views/health").get().to_dict()
hj = json.loads(h["json"]) if h else {}
out["health"] = {"status": hj.get("status"), "engine": {k: v for k, v in (hj.get("engine") or {}).items()
                                                         if not isinstance(v, (list, dict)) or k in ("failed_steps",)},
                 "quota": {k: v for k, v in hj.items() if any(w in k for w in ("firestore", "reads", "writes", "lean", "budget"))},
                 "models_15m": [{"symbol": m["symbol"], "state": m["state"], "message": (m.get("message") or "")[:120]} for m in hj.get("models", []) if m["timeframe"] == "15m"][:30],
                 "series_15m": [{"symbol": s["symbol"], "candles": s["candles"], "status": s["status"]} for s in hj.get("series", []) if s["timeframe"] == "15m"]}
ages = {}
for m in hj.get("models", []):
    ages.setdefault(m["timeframe"], []).append(m.get("age_h"))
out["model_age_h"] = {tf: {"n": len(v), "fresh_12h": sum(1 for a in v if a is not None and a <= 12),
                           "max": max((a for a in v if a is not None), default=None), "missing": sum(1 for a in v if a is None)}
                      for tf, v in ages.items()}
out["last_train"] = (hj.get("engine") or {}).get("last_train")
out["safety"] = hj.get("safety")
# v2.1 fresh start check: release marker, record views, practice data counts (no personal data)
out["release"] = fs.document("config/release").get().to_dict()
tr = fs.document("views/track_record").get().to_dict()
trj = json.loads(tr["json"]) if tr and tr.get("json") else {}
out["track_record"] = {"record_since": trj.get("record_since"), "live_signals": len((trj.get("live") or {}).get("signals") or trj.get("signals") or []),
                       "updated": (tr or {}).get("updated_at")}
sigs = (trj.get("live") or {}).get("signals") or trj.get("signals") or []
out["record_live"] = {"summary": (trj.get("live") or {}).get("summary") or trj.get("summary"),
                      "by_timeframe": (trj.get("live") or {}).get("by_timeframe") or trj.get("by_timeframe"),
                      # counts only: no coin / side / levels / single results
                      "signals_by_status": {s: sum(1 for x in sigs if x.get("status") == s) for s in sorted({str(x.get("status")) for x in sigs})},
                      "signals_by_timeframe": {t: sum(1 for x in sigs if x.get("timeframe") == t) for t in sorted({str(x.get("timeframe")) for x in sigs})}}
_count = lambda c: int(fs.collection(c).count().get()[0][0].value)     # aggregation: 1 read per 1000 documents
out["counts"] = {c: _count(c) for c in ("paper", "paper_trades", "paper_futures_trades", "auto_paper_state", "jobs")}
bots = fs.document("config/bots").get().to_dict() or {}
out["bots"] = [{"id": b.get("id"), "reset_token": b.get("reset_token")} for b in bots.get("bots", [])]
# notifications check (no secrets: booleans, kinds and counts only)
tg = fs.document("owner/telegram").get().to_dict() or {}
out["telegram"] = {"has_token": bool(tg.get("token")), "has_channel": bool(tg.get("channel")),
                   **{k: v for k, v in tg.items() if k.startswith(("enabled", "approve_first", "post_"))}}
st = fs.document("owner/telegram_status").get().to_dict() or {}
out["telegram_status"] = {k: st.get(k) for k in ("ok", "checked_at", "last_sent", "last_post_at", "updated_at")}
out["telegram_status"]["errors"] = len(st.get("errors") or [])
dr = fs.document("owner/telegram_drafts").get().to_dict() or {}
out["telegram_drafts"] = {"n": len(dr.get("items") or []), "items": [{k: i.get(k) for k in ("kind", "created_at", "at")} for i in (dr.get("items") or [])][:10]}
out["telegram"]["keys"] = sorted(k for k in tg.keys() if k != "token")
out["push_tokens"] = _count("push_tokens")
import re as _re
_jobs = [d.to_dict() or {} for d in fs.collection("jobs").where("type", "==", "telegram_post").stream()]
out["telegram_post_jobs"] = [{"status": j.get("status"), "created_at": j.get("created_at"),
                              "error": _re.sub(r"bot\d+:[\w-]+", "bot***", str(j.get("error") or (j.get("result") or {}).get("reason") or ""))[:200]}
                             for j in sorted(_jobs, key=lambda j: -(j.get("created_at") or 0))[:5]]
# every job type: how many done / failed / waiting, and the newest failure reasons (no user data)
try:
    js = {}
    for d in fs.collection("jobs").stream():
        j = d.to_dict() or {}
        t = js.setdefault(str(j.get("type")), {"n": 0, "status": {}, "errors": [], "oldest_queued_min": None})
        t["n"] += 1
        st = str(j.get("status")); t["status"][st] = t["status"].get(st, 0) + 1
        if j.get("error") and len(t["errors"]) < 3:
            t["errors"].append(_re.sub(r"bot\d+:[\w-]+", "bot***", str(j.get("error")))[:160])
        if st in ("queued", "pending", "running") and j.get("created_at"):
            age = round((time.time() * 1000 - int(j["created_at"])) / 60000)
            t["oldest_queued_min"] = max(t["oldest_queued_min"] or 0, age)
    out["jobs_summary"] = js
except Exception as exc:
    out["jobs_summary"] = {"error": str(exc)[:200]}
# v3.1 open trades vs the public record (counts / ids hashed only; no coin, side or levels)
try:
    import hashlib as _h
    hid = lambda x: _h.sha256(("cia|" + str(x)).encode()).hexdigest()[:8]
    rec = {x.get("id"): x for x in sigs}
    rec_open = {i for i, x in rec.items() if x.get("status") in ("OPEN", "PENDING")}
    bv = fs.document("views/bots").get().to_dict() or {}
    bj = json.loads(bv["json"]) if bv.get("json") else {}
    rows = []
    for b in bj.get("bots") or []:
        cfg = b.get("config") or {}
        for pz in (b.get("positions") or []) + [dict(x, _pending=True) for x in (b.get("pending") or [])]:
            inf = pz.get("info") or {}
            sid = inf.get("signal_id") or inf.get("call_id") or (inf.get("call") or {}).get("id")
            tf = inf.get("timeframe") or cfg.get("timeframe")
            same = [x for x in sigs if x.get("timeframe") == tf and x.get("symbol") == pz.get("symbol")
                    and (x.get("side") == "LONG") == (int(pz.get("side") or 0) > 0)]
            rows.append({"bot": cfg.get("id"), "tf": tf, "pending": bool(pz.get("_pending")), "opened_at": pz.get("opened_at") or pz.get("placed_at"),
                         "info_keys": sorted(inf.keys())[:14], "sid": hid(sid) if sid else None,
                         "sid_in_record": sid in rec if sid else None, "sid_open_in_record": sid in rec_open if sid else None,
                         "same_coin_tf_side_statuses": [x.get("status") for x in same][:4]})
    aut = []
    for d in fs.collection("paper").stream():
        if not d.id.endswith("_futures"):
            continue
        a = d.to_dict() or {}
        for pz in list((a.get("positions") or {}).values()) + list((a.get("orders") or {}).values()):
            sg = pz.get("signal") or {}
            if not sg:
                continue
            same = [x for x in sigs if x.get("timeframe") == sg.get("timeframe") and x.get("symbol") == sg.get("symbol")]
            aut.append({"tf": sg.get("timeframe"), "grade": sg.get("grade"), "at": sg.get("at"), "sid": hid(sg.get("id")),
                        "sid_in_record": sg.get("id") in rec, "sid_open_in_record": sg.get("id") in rec_open,
                        "same_coin_tf_statuses": [x.get("status") for x in same][:4]})
    out["open_vs_record"] = {"record_rows": len(sigs), "record_open": len(rec_open),
                             "record_open_tfs": sorted(str(rec[i].get("timeframe")) for i in rec_open),
                             "record_since_tf": trj.get("record_since_tf"), "bots": rows, "auto": aut}
except Exception as exc:
    out["open_vs_record"] = {"error": str(exc)[:300]}
# v3.1: closed trades of the 15m bots (time, reason, win/loss only; no coin, side or prices)
try:
    _bv = fs.document("views/bots").get().to_dict() or {}
    _bj = json.loads(_bv["json"]) if _bv.get("json") else {}
    _rec = {x.get("id"): x for x in sigs}
    out["bot15_trades"] = {}
    for _b in _bj.get("bots") or []:
        _c = _b.get("config") or {}
        if _c.get("timeframe") != "15m":
            continue
        out["bot15_trades"][_c.get("id")] = [{"opened": t.get("opened_at"), "closed": t.get("closed_at"), "reason": t.get("reason") or t.get("exit_reason"),
                                               "win": (t.get("pnl") or 0) > 0, "keys": sorted(t.keys())[:12],
                                               "record_same": [(x.get("status"), x.get("created_at")) for x in sigs if x.get("timeframe") == "15m"
                                                               and x.get("symbol") == t.get("symbol")][:3]}
                                              for t in (_b.get("trades") or [])[:10]]
except Exception as exc:
    out["bot15_trades"] = {"error": str(exc)[:200]}
# v3.1: closed trades of the 15m bots vs the record (hashed, no coin / side / levels)
try:
    _bv = fs.document("views/bots").get().to_dict() or {}
    _bj = json.loads(_bv["json"]) if _bv.get("json") else {}
    _sig_all = sigs
    _bt = []
    for b in _bj.get("bots") or []:
        cfg = b.get("config") or {}
        if cfg.get("timeframe") != "15m":
            continue
        for t in (b.get("trades") or [])[:20]:
            sym, side = t.get("symbol"), t.get("side")
            oa = int(t.get("opened_at") or t.get("entry_ts") or 0)
            match = [x for x in _sig_all if x.get("symbol") == sym and x.get("timeframe") == "15m"
                     and (x.get("side") == "LONG") == (str(side).upper() in ("1", "LONG", "BUY"))
                     and int(x.get("created_at") or 0) <= oa + 20 * 60_000 and (x.get("closed_at") is None or int(x.get("closed_at")) >= oa - 60_000)]
            _bt.append({"bot": cfg.get("id"), "opened_at": oa, "closed_at": t.get("closed_at") or t.get("exit_ts"),
                        "reason": t.get("reason") or t.get("exit_reason"), "pnl_sign": (1 if (t.get("pnl") or 0) > 0 else -1),
                        "pnl_pct_of_equity": round(100 * float(t.get("pnl") or 0) / 30000, 3),
                        "record_match": [(x.get("status"), x.get("exit_reason"), x.get("created_at")) for x in match][:2],
                        "keys": sorted(t.keys())[:20]})
    out["bot15_trades"] = _bt
except Exception as exc:
    out["bot15_trades"] = {"error": str(exc)[:200]}
# v2.75 check: views/derivs summary + silver (XAG/USDT) models (counts / names only)
try:
    dv = fs.document("views/derivs").get().to_dict()
    dj = json.loads(dv["json"]) if dv else {}
    out2 = {"exists": bool(dv), "generated_at": dj.get("generated_at"), "coins": len(dj.get("coins") or {}),
            "liq_maps": len(dj.get("liq_maps") or {}), "volatility": sorted((dj.get("volatility") or {}).keys()),
            "macro": sorted((dj.get("macro") or {}).keys()), "unlocks": len(dj.get("unlocks") or [])}
except Exception as exc:
    out2 = {"error": type(exc).__name__}
xag = {}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    m = fs.document(f"views/models_XAGUSDT_{tf}").get().to_dict()
    mj = json.loads(m["json"]) if m else {}
    xag[tf] = {"exists": bool(m), "active": bool(mj.get("active") or mj.get("bundle") or mj.get("models")), "keys": sorted(mj.keys())[:8]}
out["derivs"], out["xag_models"] = out2, xag
# V3.0 market risk state (state, score, factor levels only)
try:
    r = fs.document("views/risk_state").get().to_dict()
    rj = json.loads(r["json"]) if r and "json" in r else (r or {})
    out["risk_state"] = {"state": rj.get("state"), "score": rj.get("score"), "at": rj.get("generated_at"),
                         "factors": {f["key"]: f["status"] for f in rj.get("factors") or []}} if rj else None
except Exception as e:  # noqa: BLE001
    out["risk_state"] = {"error": type(e).__name__}
# Hesper challenge (main + Last Stand): counts only - no coin, side or levels in this public report
for vid in ("hesper", "laststand"):
    try:
        r = fs.document(f"views/{vid}").get().to_dict()
        hj = json.loads(r["json"]) if r and "json" in r else (r or {})
        def _n(o, k):
            v = o.get(k) if isinstance(o, dict) else None
            return len(v) if isinstance(v, list) else v
        out[f"challenge_{vid}"] = {"keys": sorted(hj.keys())[:30], "runs": _n(hj, "runs"), "trades": _n(hj, "trades"),
                                   "at": hj.get("generated_at"), "since": hj.get("since"),
                                   "current_run": (hj.get("current") or {}).get("run") if isinstance(hj.get("current"), dict) else None,
                                   "run_numbers": [x.get("run") for x in (hj.get("runs") or []) if isinstance(x, dict)][:40],
                                   "run_trades": [x.get("trades") for x in (hj.get("runs") or []) if isinstance(x, dict)][:40],
                                   "laststand": {k: (len(v) if isinstance(v, list) else v if isinstance(v, (int, float, str)) else None)
                                                 for k, v in (hj.get("laststand") or {}).items()} if isinstance(hj.get("laststand"), dict) else None}
    except Exception as e:  # noqa: BLE001
        out[f"challenge_{vid}"] = {"error": type(e).__name__}
# news / calendar (public facts only): is the calendar arriving, which high-impact US events were due
try:
    import time as _t
    nd = fs.document("views/news").get().to_dict() or {}
    nv = json.loads(nd["json"]) if nd.get("json") else {}
    now_ms_ = int(_t.time() * 1000)
    cal = nv.get("calendar") or []
    hi = [e for e in cal if e.get("impact") == "High" and e.get("country") == "USD"]
    out["news"] = {"updated": nd.get("updated_at"), "generated_at": nv.get("generated_at"), "calendar_n": len(cal),
                   "high_usd": [{"title": e.get("title"), "ts": e.get("ts"), "past": e.get("ts", 0) < now_ms_} for e in hi][:20],
                   "next_high": (nv.get("next_high") or {}).get("title"), "headlines_n": len(nv.get("headlines") or []),
                   "errors": nv.get("errors")}
except Exception as exc:
    out["news"] = {"error": str(exc)[:200]}
try:
    _h = fs.document("views/health_admin").get().to_dict() or {}
    hj = json.loads(_h["json"]) if _h.get("json") else {}
    out["alert_watcher"] = (hj.get("engine") or {}).get("alert_watcher")
except Exception:
    pass
# health tiles the owner sees as warnings: market data, exchange errors, AI check (counts / labels only)
try:
    _h = fs.document("views/health_admin").get().to_dict() or {}
    hj = json.loads(_h["json"]) if _h.get("json") else {}
    out["hj_keys"] = sorted(hj.keys())
    out["md"] = {k: v for k, v in (hj.get("market_data") or {}).items() if not isinstance(v, list)}
    out["md_stale"] = [{k: v for k, v in x.items() if k in ("symbol", "timeframe", "status", "candles", "last_ts", "age_s", "gaps", "quality_pct", "missing")} for x in (hj.get("series") or []) if x.get("status") not in ("OK", "ok", "LIVE", None)][:40]
    out["series_status"] = {st_: sum(1 for x in (hj.get("series") or []) if x.get("status") == st_) for st_ in {x.get("status") for x in (hj.get("series") or [])}}
    out["series_sample"] = (hj.get("series") or [None])[0]
    _e = hj.get("engine") or {}
    out["step_avg"] = dict(sorted((_e.get("step_seconds_avg") or {}).items(), key=lambda kv: -(kv[1] or 0))[:15])
    out["step_max"] = dict(sorted((_e.get("step_seconds_max") or {}).items(), key=lambda kv: -(kv[1] or 0))[:10])
    out["step_last"] = dict(sorted((_e.get("step_seconds") or {}).items(), key=lambda kv: -(kv[1] or 0))[:12])
    out["eng_watch"] = {k: v for k, v in (hj.get("engine") or {}).items() if k.startswith(("watch", "alert", "flow", "round", "last_tick"))}
    out["exchange"] = {k: (v if not isinstance(v, (list, dict)) else str(v)[:300]) for k, v in (hj.get("exchange") or {}).items()}
    g = fs.document("views/guardian").get().to_dict() or {}
    gj = json.loads(g["json"]) if g.get("json") else {}
    cal = (gj.get("checks") or {}).get("calibration") or {}
    out["ai_check"] = {"warnings": cal.get("warnings"), "by_tf": {tf: {k: v for k, v in (x or {}).items() if not isinstance(v, (list, dict))} for tf, x in (cal.get("by_tf") or cal.get("timeframes") or {}).items()} if isinstance(cal.get("by_tf") or cal.get("timeframes"), dict) else None,
                       "keys": sorted(cal.keys())}
except Exception as exc:
    out["md_probe_error"] = str(exc)[:200]
# auto-trade: per member (anonymous index) the settings that decide what is taken, and recent outcomes (no coin / side / levels)
try:
    import time as _t2
    cut = int(_t2.time() * 1000) - 2 * 86_400_000
    ap = []
    for i, d in enumerate(fs.collection("auto_paper").stream()):
        a = d.to_dict() or {}
        st_ = fs.document(f"auto_paper_state/{d.id}").get().to_dict() or {}
        log = [x for x in (st_.get("log") or []) if int(x.get("ts") or 0) >= cut]
        reasons, last2h = {}, {}
        for x in log:
            k = f"{x.get('timeframe')}|{x.get('grade')}|{x.get('action')}|{x.get('reason') or ''}"
            reasons[k] = reasons.get(k, 0) + 1
            if int(x.get("ts") or 0) >= int(time.time() * 1000) - 2 * 3_600_000:
                last2h[k] = last2h.get(k, 0) + 1
        ap.append({"n": i, "enabled": a.get("enabled"), "timeframes": a.get("timeframes"), "grades": a.get("grades"),
                   "coins": a.get("coins"), "max_open": a.get("max_open"), "max_same_side": a.get("max_same_side"),
                   "max_new_per_day": a.get("max_new_per_day"), "last2h": last2h, "margin": {k: a.get(k) for k in a if "margin" in k or "size" in k or "risk" in k},
                   "state_updated": st_.get("updated_at"), "recent": reasons})
    out["auto_trade"] = ap
except Exception as exc:
    out["auto_trade"] = {"error": str(exc)[:200]}
# the Cloudflare price-alert watcher itself (counts only; no tokens, no keys)
try:
    import hashlib, urllib.request
    key = hashlib.sha256(("cia-edge-v1|" + os.environ["FIREBASE_SERVICE_ACCOUNT"]).encode()).hexdigest()
    req = urllib.request.Request("https://cia-chat.cryptointelai.workers.dev/watch/status?since=0", headers={"X-Edge-Key": key, "User-Agent": "cia-status"})
    st = json.load(urllib.request.urlopen(req, timeout=20))
    out["cloud_watcher"] = {**{k: st.get(k) for k in ("at", "armed", "armed_at", "sent", "sent_total", "due", "priced", "error", "idle")},
                            "sent_keys_n": len(st.get("sent_keys") or []), "bad_tokens_n": len(st.get("bad_tokens") or []),
                            "engine_diag": st.get("engine_diag"), "fcm_check": st.get("fcm_check"), "price_tries": st.get("price_tries")}
except Exception as exc:
    out["cloud_watcher"] = {"probe_error": str(exc)[:200]}
# the Cloudflare copy (what members see) vs the Firestore copy
try:
    import hashlib as _hl, urllib.request as _ur
    _k = _hl.sha256(("cia-edge-v1|" + os.environ["FIREBASE_SERVICE_ACCOUNT"]).encode()).hexdigest()
    _b = "https://cia-chat.cryptointelai.workers.dev"
    _eh = json.load(_ur.urlopen(_ur.Request(_b + "/edge-health", headers={"User-Agent": "cia-status"}), timeout=20))
    _vv = json.load(_ur.urlopen(_ur.Request(_b + "/v?n=health,track_record&e=,", headers={"X-Edge-Key": _k, "User-Agent": "cia-status"}), timeout=30))["views"]
    out["edge_side"] = {"edge_health": _eh, "health_at": (_vv.get("health") or {}).get("at"),
                        "health_tick": (((_vv.get("health") or {}).get("data") or {}).get("engine") or {}).get("last_tick_finished"),
                        "track_record_at": (_vv.get("track_record") or {}).get("at"),
                        "mexc_px": json.load(_ur.urlopen(_ur.Request(_b + "/px?s=ANTHROPIC", headers={"User-Agent": "cia-status", "Origin": "https://cryptointelai.com"}), timeout=20)),
                        "mexc_kl_1h": (lambda r: {"n": len(r), "last_ts": r[-1][0] if r else None, "last_close": r[-1][4] if r else None})(
                            json.load(_ur.urlopen(_ur.Request(_b + "/kl?s=ANTHROPIC&tf=1h&limit=50", headers={"User-Agent": "cia-status", "Origin": "https://cryptointelai.com"}), timeout=20)))}
except Exception as exc:
    out["edge_side"] = {"error": str(exc)[:200]}
print(json.dumps(out, indent=1, default=str))
