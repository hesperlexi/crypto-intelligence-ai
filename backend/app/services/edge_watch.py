"""Cloudflare price-alert watcher, engine side (owner, 24 Nov 2026).

The watcher (chat-worker/src/watch.ts) runs every minute on Cloudflare, also while the engine is down. The engine tells it
WHAT to watch: every level of every open call (pending entry, TP1-3 not hit yet, the stop in force) and of the Hesper /
Last Stand trades, each with the finished notification and the phones of the people who asked for that event. The texts,
audiences and tags are exactly those of `watch.py` (the engine's own 30-second watch), so nothing changes for members:
the early "price touched" push simply keeps coming when the engine is between runs.

* Phone tokens come from Firestore `push_tokens`, read at most every `TOKENS_EVERY_S` (cached in setting
  `edge_watch_tokens`), so this costs about (devices × 24) reads a day.
* Sent only when the armed list changed or every `REARM_S` (so the watcher knows the engine is alive).
* `sync_sent` pulls what the watcher already sent into `watch_sent.json`, so the engine's own watch never repeats it,
  and removes phones Firebase refused.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from ..db import now_ms

log = logging.getLogger("edge_watch")

TOKENS_EVERY_S = 3600
REARM_S = 30 * 60
TITLES = {"entry": "Entry reached", "tp1": "TP1 hit", "tp2": "TP2 hit", "tp3": "TP3 hit", "closed": "Stop hit"}


def _src(symbol: str) -> tuple[str, str]:
    from ..data.futures_only import FUT_ONLY
    s = symbol.upper()
    if s in FUT_ONLY:
        return "mexc", FUT_ONLY[s]
    return "spot", s.replace("/", "").replace("-", "")


def call_levels(db: Any) -> list[tuple[dict[str, Any], str, float, int, bool, str]]:
    """(call, event, level, side, toward_profit, body) for every level of every open call not reached yet."""
    from .. import watch as W
    out = []
    for r in db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0"):
        side = 1 if int(r["side"]) > 0 else -1
        adj = {a["field"]: float(a["new"]) for a in db.query(
            "SELECT field, new FROM signal_adjustments WHERE signal_id = ? ORDER BY at", (r["id"],))}
        head = f"{W._coin(r['symbol'])} {str(r['timeframe']).upper()} {'LONG' if side > 0 else 'SHORT'}"
        if r.get("fill_status") == "PENDING":
            if r.get("entry") is not None:
                out.append((r, "entry", float(r["entry"]), side, False,
                            f"{head}: price reached the entry {W._px(r['entry'])}. {W.CONFIRM}"))
            continue
        tps = [adj.get("tp1", r.get("tp1")), r.get("tp2"), r.get("tp3")]
        for i, lvl in enumerate(tps, 1):
            if lvl is not None and not r.get(f"tp{i}_hit"):
                out.append((r, f"tp{i}", float(lvl), side, True, f"{head}: price touched TP{i} {W._px(lvl)}. {W.CONFIRM}"))
        stop, what = adj.get("stop", r.get("stop")), "the stop"
        if stop is None:
            continue
        stop = float(stop)
        if r.get("tp1_hit") and r.get("entry") is not None:
            stop, what = W._tighter(side, stop, float(r["entry"])), "the break-even stop"
        if r.get("tp2_hit") and tps[0] is not None:
            stop, what = W._tighter(side, stop, float(tps[0])), "the stop at TP1 (profit kept)"
        out.append((r, "closed", stop, side, False, f"{head}: price touched {what} {W._px(stop)}. {W.CONFIRM}"))
    return out


def armed(db: Any, devices: list[tuple], admins: set[str]) -> list[dict[str, Any]]:
    """The watcher's list: one item per (alert rule owner group, call level), with phone tokens."""
    from .. import watch as W
    from . import alerts
    levels = call_levels(db)
    out: dict[str, dict[str, Any]] = {}

    def tokens_for(uid: str | None) -> list[str]:
        if uid:
            return [d[0] for d in devices if d[1] == uid]
        return [d[0] for d in devices if (not admins or d[2] in admins or d[1] is None)]

    if levels:
        rules = db.query(f"SELECT * FROM alerts WHERE enabled = 1 AND type IN ({','.join('?' * len(W.CALL_RULES))})", W.CALL_RULES)
        for rule in rules:
            rule["params"] = W._loads(rule.get("params"), {}) or {}
            if rule.get("last_state") != "primed":
                continue
            want = alerts._wants(rule)
            uid = rule["user_id"] if rule.get("user_id") and rule["user_id"] != W.LOCAL_USER else None
            for r, ev, lvl, side, profit, body in levels:
                if ev not in want or not alerts._matches(rule, r):
                    continue
                if db.one("SELECT 1 AS x FROM alert_marks WHERE alert_id = ? AND mark = ?", (rule["id"], f"{r['id']}:{ev}")):
                    continue
                toks = tokens_for(uid)
                if not toks:
                    continue
                # one item per call level; people who want it are merged (the watch key stays per rule for watch.py)
                k = f"{r['id']}:{ev}"
                src, pair = _src(r["symbol"])
                it = out.setdefault(k, {"key": k, "symbol": r["symbol"], "src": src, "pair": pair, "side": side, "level": lvl,
                                        "profit": profit, "rules": [], "tokens": [],
                                        "msg": {"title": f"{TITLES[ev]} · {r['symbol']}", "body": body, "url": "/alerts",
                                                "tag": f"{r['id']}-{ev}"}})
                it["rules"].append(rule["id"])
                it["tokens"] = sorted(set(it["tokens"]) | set(toks))
    items = list(out.values())
    items += _challenge_items(db, tokens_for)
    return items


def _challenge_items(db: Any, tokens_for) -> list[dict[str, Any]]:
    from .. import watch as W
    from . import hesper as H
    items = []
    members = [u for u in (db.get_setting("hesper_push_members", None) or []) if isinstance(u, str)]
    for cls in H.CHALLENGES:
        st = db.get_setting(cls.STATE_KEY, None) or {}
        if not st or st.get("idle"):
            continue
        run = st.get("run")
        head = f"{cls.TITLE} · run #{run}" if run else cls.TITLE
        pre = "h" if cls.BOT_ID == H.BOT_ID else cls.BOT_ID
        tagp = "hesper" if cls.BOT_ID == H.BOT_ID else cls.BOT_ID
        url, murl = (H.PUSH_URL, H.MEMBER_URL) if pre == "h" else (f"{H.PUSH_URL}?c={pre}", f"{H.MEMBER_URL}&c={pre}")
        admin_toks = sorted(set(tokens_for(None)))
        member_toks = sorted({t for u in members for t in tokens_for(u)} - set(admin_toks))
        if not admin_toks and not member_toks:
            continue
        found = []
        for q in st.get("positions") or []:
            side = 1 if (q.get("side") or 0) > 0 else -1
            coin, name = W._coin(q["symbol"]), f"{W._coin(q['symbol'])} {'LONG' if side > 0 else 'SHORT'}"
            hit = int(q.get("tp_hit") or 0)
            for n, lvl in enumerate(q.get("targets") or [], 1):
                if n > hit and lvl is not None:
                    found.append((q["symbol"], f"{pre}:{q['id']}:tp{n}", f"{tagp}-{run}-tp-{coin}-{n}", side, float(lvl), True,
                                  f"{name}: price touched TP{n} {W._px(lvl)}. {W.CONFIRM}"))
            if q.get("stop") is not None:
                what = "the stop" if not hit else "the break-even stop" if hit == 1 else "the stop at TP1 (profit kept)"
                found.append((q["symbol"], f"{pre}:{q['id']}:stop", f"{tagp}-{run}-close-{coin}-", side, float(q["stop"]), False,
                              f"{name}: price touched {what} {W._px(q['stop'])}. The trade closes at the candle close."))
        for o in st.get("pending") or []:
            if o.get("limit") is None:
                continue
            side = 1 if (o.get("side") or 0) > 0 else -1
            coin = W._coin(o["symbol"])
            found.append((o["symbol"], f"{pre}:{o['id']}:fill", f"{tagp}-{run}-fill-{coin}-", side, float(o["limit"]), False,
                          f"{coin}: price reached the entry order {W._px(o['limit'])}. {W.CONFIRM}"))
        for sym, key, tag, side, lvl, profit, body in found:
            src, pair = _src(sym)
            for k, toks, u in ((key, admin_toks, url), (f"{key}|m", member_toks, murl)):   # admin page vs members' tab
                if toks:
                    items.append({"key": k, "symbol": sym, "src": src, "pair": pair, "side": side, "level": lvl, "profit": profit,
                                  "tokens": toks, "msg": {"title": head, "body": body, "url": u, "tag": tag}})
    return items


def _devices(rt, sink) -> list[tuple]:
    """(token, uid, email, document id) of every phone that turned notifications on."""
    cache = rt.db.get_setting("edge_watch_tokens", None) or {}
    if cache.get("devices") is not None and now_ms() - int(cache.get("at") or 0) < TOKENS_EVERY_S * 1000:
        return [tuple(d) for d in cache["devices"]]
    try:
        devs = [((d.get("token") or i), d.get("uid"), (d.get("email") or "").lower(), i) for i, d in sink.list("push_tokens")]
    except Exception:
        # v3.1 (25 Nov 2026): Firestore over its read quota - keep arming with the last known phones (the watcher went
        # idle for 8 h because this read failed); tried again next tick
        if cache.get("devices") is not None:
            return [tuple(d) for d in cache["devices"]]
        raise
    rt.db.set_setting("edge_watch_tokens", {"at": now_ms(), "devices": devs})
    return devs


def run(rt, sink, session: Any = None) -> dict[str, Any]:
    """Worker step: send the armed list to the watcher when it changed (or every REARM_S); pull back what it sent."""
    from ..sinks import EDGE_URL, edge_key
    import requests
    key = edge_key()
    if not key or os.environ.get("EDGE_WATCH", "1") == "0":
        return {"skipped": "off"}
    sess = session or requests
    out: dict[str, Any] = {}
    try:
        out.update(sync_sent(rt, sink, sess))
    except Exception as exc:
        out["status_error"] = str(exc)[:160]
    admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    devs = _devices(rt, sink)
    items = armed(rt.db, devs, admins)
    from .. import watch as W
    diag = {"devices": len(devs), "with_uid": sum(1 for d in devs if d[1]), "admins_set": len(admins),
            "levels": len(call_levels(rt.db)),
            "rules_primed": len([1 for r in rt.db.query(f"SELECT last_state FROM alerts WHERE enabled = 1 AND type IN ({','.join('?' * len(W.CALL_RULES))})", W.CALL_RULES) if r.get("last_state") == "primed"])}
    for it in items:                                   # the watcher needs no rule ids
        it.pop("rules", None)
    members = _members(rt)
    digest = hashlib.sha256(json.dumps([items, members], sort_keys=True).encode()).hexdigest()[:20]
    last = rt.db.get_setting("edge_watch_armed", None) or {}
    if last.get("hash") == digest and now_ms() - int(last.get("at") or 0) < REARM_S * 1000 and last.get("diag") == diag:
        return {**out, "armed": len(items), "sent": False}
    r = sess.post(f"{EDGE_URL}/watch/arm", data=json.dumps({"armed": items, "diag": diag, "members": members,
                                   "probe_token": next((d[0] for d in devs if (not admins or d[2] in admins)), devs[0][0] if devs else None)}, separators=(",", ":")),
                  headers={"X-Edge-Key": key, "Content-Type": "application/json"}, timeout=20)
    ok = getattr(r, "status_code", 0) == 200
    if ok:
        rt.db.set_setting("edge_watch_armed", {"hash": digest, "at": now_ms(), "n": len(items), "diag": diag})
    return {**out, "armed": len(items), "sent": ok, "status": getattr(r, "status_code", None), "diag": diag}


def _members(rt) -> dict[str, int]:
    """v3.1: approved members {uid: membership end ms, 0 = no end} from the engine's users cache (no extra reads), so the
    Cloudflare Worker can check membership without reading Firestore (and while Firestore is over its quota)."""
    users = ((rt.db.get_setting("users_cache", None) or {}).get("users")) or {}
    out = {}
    for uid, u in users.items():
        if str(u.get("status")) == "approved":
            try:
                exp = int(float(u.get("expires_at") or 0))
            except (TypeError, ValueError):
                exp = 0
            if not exp or exp > now_ms():
                out[str(uid)] = exp
    return out


def sync_sent(rt, sink, sess) -> dict[str, Any]:
    """Merge the watcher's recent sends into watch_sent.json (so watch.py skips them) and drop refused phones."""
    from ..sinks import EDGE_URL, edge_key
    from .. import watch as W
    since = now_ms() - 2 * 86_400_000
    r = sess.get(f"{EDGE_URL}/watch/status", params={"since": since}, headers={"X-Edge-Key": edge_key()}, timeout=15)
    if getattr(r, "status_code", 0) != 200:
        return {"status_http": getattr(r, "status_code", None)}
    st = r.json()
    rt.db.set_setting("edge_watch_status", {k: st.get(k) for k in ("at", "armed", "armed_at", "sent", "sent_total", "due", "error", "priced", "idle")})
    sent_keys = {k for k, _ in (st.get("sent_keys") or [])}
    from ..config import settings
    path = settings.database_url.replace("sqlite:///", "") if settings.database_url.startswith("sqlite:///") else ""
    if path and sent_keys:
        p = Path(path).parent / W.SENT_FILE
        try:
            sent = json.loads(p.read_text()) if p.exists() else {}
        except Exception:
            sent = {}
        now = now_ms()
        rules = [x["id"] for x in rt.db.query("SELECT id FROM alerts")]
        for k in {x.split("|")[0] for x in sent_keys}:
            if k.count(":") == 1:                     # a call level "<call>:<event>"; watch.py keys are per rule
                for rid in rules:
                    sent.setdefault(f"{rid}:{k}", now)
            else:                                     # challenge keys are the same in both ("h:<id>:tp1")
                sent.setdefault(k, now)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(sent))
        tmp.replace(p)
    bad = [t for t in (st.get("bad_tokens") or []) if isinstance(t, str)]
    removed = 0
    if bad and hasattr(sink, "fs"):
        cache = rt.db.get_setting("edge_watch_tokens", None) or {}
        doc = {d[0]: (d[3] if len(d) > 3 else d[0]) for d in cache.get("devices") or []}
        for t in bad:
            if t in doc:
                try:
                    sink.fs.document(f"push_tokens/{doc[t]}").delete()
                    removed += 1
                except Exception:
                    pass
        if removed:
            cache["devices"] = [d for d in cache.get("devices") or [] if d[0] not in set(bad)]
            rt.db.set_setting("edge_watch_tokens", cache)
    return {"watcher_at": st.get("at"), "watcher_sent_total": st.get("sent_total"), "bad_removed": removed}
