"""v2.19 Trade Guardian: recommend-only early warnings on open calls (deterministic synthetic candles, mocked Gemini)."""
import math
import tempfile
import time

import pandas as pd
import pytest

from app import worker
from app.db import Database, dumps, loads
from app.services import adjust as A
from app.services import guardian as G
from app.services import tracking as T
from app.sinks import LocalSink

MIN = 60_000
M15 = 15 * MIN
NOW = (int(time.time() * 1000) // M15) * M15 + 7 * MIN     # mid-candle, "now" (job freshness uses the wall clock)
CREATED = NOW - 3 * 3_600_000
SYM, TF = "ETH/USDT", "1h"


# ---- synthetic data -------------------------------------------------------------------------------------------
def m1_rows(now, path, start=100.0):
    """100 closed 1m candles ending at `now`: close(k) = path(k), k = 0..99 (99 = the newest)."""
    out, prev = [], start
    for k in range(100):
        ts = now - (100 - k) * MIN
        c = path(k)
        out.append([ts, prev, max(prev, c) + 0.02, min(prev, c) - 0.02, c, 10.0])
        prev = c
    return out


def calm(base=100.0):
    return lambda k: base + 0.03 * math.sin(k)


def drop(to, base=100.0, start_k=85):
    def f(k):
        noise = 0.03 * math.sin(k)
        if k < start_k:
            return base + noise
        return base + (to - base) * (k - start_k + 1) / (99 - start_k + 1) + noise * 0.2
    return f


def m15_frame(end=NOW, n=40, base=100.0):
    """15m candles with a 1.0 range (ATR = 1.0), closed by `end`."""
    first = (end // M15) * M15 - n * M15
    rows = [[first + i * M15, base, base + 0.5, base - 0.5, base, 1.0] for i in range(n)]
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


class RT:
    def __init__(self, db=None):
        self.db = db or Database("sqlite:///:memory:")
        self.m15 = {SYM: m15_frame(), "BTC/USDT": m15_frame(base=50_000.0)}
        self.px = {}
        self.provider = None

    def candles(self, symbol, tf, include_forming=False, **kw):
        return self.m15.get(symbol, m15_frame()) if tf == "15m" else self.m15.get(symbol, m15_frame()).iloc[0:0]

    def live_price(self, symbol):
        return self.px.get(symbol)


def add_call(db, side=1, entry=100.0, stop=98.0, tps=(102.0, 103.0, 104.0), grade="A", tp1_hit=0, peak_r=0.2,
             created=CREATED, sid="sig1", status="OPEN", **extra):
    cols = {"id": sid, "created_at": created, "symbol": SYM, "timeframe": TF, "bar_ts": created - 3_600_000,
            "signal": "BUY" if side > 0 else "SELL", "decision": "BUY" if side > 0 else "SELL", "price": entry,
            "side": side, "entry": entry, "stop": stop, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2], "rr": 1.5,
            "status": status, "tp1_hit": tp1_hit, "fill_status": "FILLED", "peak_r": peak_r, "atr": 1.0,
            "payload": dumps({"grade": grade}), **extra}
    db.execute(f"INSERT INTO signals ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
    return sid


def analyses(decision="BUY", grade="A", at=NOW - MIN):
    return {(SYM, TF): {"status": "OK", "generated_at": at, "decision": decision, "grade": grade}}


def fetcher(paths, now=NOW):
    """fetch(symbol, since, limit) for the Guardian: rows from `paths[symbol]` (callable(k)) ending at `now`."""
    calls = []

    def f(symbol, since, limit):
        calls.append((symbol, since, limit))
        p = paths[symbol]
        base = 50_000.0 if symbol == "BTC/USDT" else 100.0
        rows = m1_rows(now, p, base) if callable(p) else p
        return [r for r in rows if r[0] >= since][:limit]
    f.calls = calls
    return f


class FakeAdv:
    def __init__(self, answer=None, enabled=True):
        self.answer, self.enabled, self.model, self.daily_limit, self.n = answer, enabled, "fake-gemini", 150, 0
        self.seen = None

    def available(self, now=None):
        return self.enabled

    def _state(self):
        return {}

    def generate(self, task, data, schema, now=None):
        self.n += 1
        self.seen = data
        return self.answer


def guardian(rt, paths, sink=None, adv=None, now=NOW):
    rt.px.setdefault(SYM, None)
    g = G.Guardian(rt, sink, fetch=fetcher(paths, now), advisor=adv or FakeAdv(enabled=False), now=now)
    return g


def run(rt, paths, decision="BUY", grade="A", sink=None, adv=None, now=NOW, at=None, keep_cache=False):
    """One tick. Each synthetic scenario is its own timeline ending at `now`, so the 1m cache is cleared first
    (real candles never change; test_m1_cache_is_incremental covers the cache)."""
    if not keep_cache:
        rt.db.execute("DELETE FROM guardian_m1")
    rows = m1_rows(now, paths[SYM]) if callable(paths[SYM]) else paths[SYM]
    rt.px[SYM] = rows[-1][4]
    g = guardian(rt, paths, sink, adv, now)
    return g, g.run(analyses(decision, grade, at if at is not None else now - MIN))


BTC_CALM = calm(50_000.0)
BTC_DUMP = drop(49_000.0, base=50_000.0)


# ---- 1. detection ---------------------------------------------------------------------------------------------
def test_sharp_reversal_gives_close_now():
    rt = RT()
    add_call(rt.db)
    g, out = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL")
    recs = g.recs()
    assert out["created"] == 1 and len(recs) == 1
    r = recs[0]
    assert r["level"] == "CLOSE" and r["rules_level"] == "CLOSE" and r["severity"] >= 75 and r["status"] == "live"
    codes = {x["code"] for x in loads(r["payload"])["reasons"]}
    assert {"move", "near_stop", "btc", "flip"} <= codes
    assert loads(r["payload"])["ai"]["path"] == "rules_only"            # Gemini off -> rules + template


def test_mild_adverse_gives_tighten_with_a_valid_tighter_stop():
    rt = RT()
    add_call(rt.db)
    g, out = run(rt, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL")
    r = g.recs()[0]
    p = loads(r["payload"])
    assert r["level"] == "TIGHTEN" and 50 <= r["severity"] < 75, (r["severity"], p["reasons"])
    stop, price = p["proposed_stop"], p["price"]
    assert 98.0 < stop < price                                      # tighter than 98, below the price
    assert price - stop >= G.MIN_GAP_ATR * 1.0                      # not instantly triggered (ATR 1.0)
    # what Apply runs accepts it
    sig = rt.db.one("SELECT * FROM signals")
    assert A.validate(sig, {"stop": 98.0, "tp1": 102.0}, price, stop, None, G.NOTE_TIGHTEN)


def test_normal_noise_gives_no_alert():
    rt = RT()
    add_call(rt.db)
    g, out = run(rt, {SYM: calm(), "BTC/USDT": BTC_CALM})
    assert out["created"] == 0 and g.recs() == []
    st = rt.db.get_setting(G.STATE)
    assert st["calls"]["sig1"]["severity"] < 50


def test_short_is_mirrored():
    rt = RT()
    add_call(rt.db, side=-1, entry=100.0, stop=102.0, tps=(98.0, 97.0, 96.0))
    up = lambda k: 200 - drop(98.6)(k)                              # mirror: rises to 101.4
    g, _ = run(rt, {SYM: up, "BTC/USDT": calm(50_000.0)}, decision="BUY")
    r = g.recs()[0]
    assert r["level"] in ("TIGHTEN", "CLOSE")
    p = loads(r["payload"])
    if r["level"] == "TIGHTEN":
        assert p["price"] < p["proposed_stop"] < 102.0


def test_stale_data_gives_no_recommendation_and_is_counted():
    rt = RT()
    add_call(rt.db)
    old = m1_rows(NOW - 10 * MIN, drop(98.6))                       # newest candle 10 minutes old
    g, out = run(rt, {SYM: old, "BTC/USDT": BTC_DUMP}, decision="SELL")
    assert g.recs() == [] and out["stale"] == 1
    assert rt.db.get_setting(G.STATE)["today"]["skipped_stale"] == 1
    # fresh candles but an analysis older than its interval -> also stale
    rt2 = RT()
    add_call(rt2.db)
    g2, out2 = run(rt2, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", at=NOW - 40 * MIN)
    assert g2.recs() == [] and out2["stale"] == 1
    # BTC candles stale for an altcoin call -> stale too (no recommendation from partial data)
    rt3 = RT()
    add_call(rt3.db)
    g3, out3 = run(rt3, {SYM: drop(98.6), "BTC/USDT": m1_rows(NOW - 10 * MIN, BTC_DUMP, 50_000.0)}, decision="SELL")
    assert g3.recs() == [] and out3["stale"] == 1


def test_price_sanity_vs_the_engine_price():
    rt = RT()
    add_call(rt.db)
    g = guardian(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP})
    rt.px[SYM] = 105.0                                              # the engine's price disagrees by > 2 %
    g.run(analyses("SELL"))
    assert g.recs() == [] and rt.db.get_setting(G.STATE)["today"]["skipped_price"] == 1


def test_wrong_side_or_looser_stop_is_rejected():
    assert G.stop_problem(1, 97.5, 98.0, 99.0, 1.0) == "the proposed stop is not tighter than the stop in force"
    assert "wrong side" in G.stop_problem(1, 99.5, 98.0, 99.0, 1.0)
    assert "closer than" in G.stop_problem(1, 98.9, 98.0, 99.0, 1.0)     # 0.1 ATR from the price
    assert G.stop_problem(1, 98.5, 98.0, 99.0, 1.0) is None
    assert "wrong side" in G.stop_problem(-1, 99.0, 102.0, 100.0, 1.0)
    assert G.stop_problem(-1, 101.0, 102.0, 100.0, 1.0) is None
    # propose_stop never returns a looser / too-close level
    rows = [(i * MIN, 100, 100.1, 99.9, 100.0) for i in range(20)]
    assert G.propose_stop(1, 100.0, rows, 1.0, 99.9, 2.0) is None      # nothing tighter than 99.9 that keeps 0.3 ATR
    s = G.propose_stop(1, 100.0, rows, 1.0, 98.0, 2.0)
    assert 98.0 < s <= 100.0 - G.PROPOSE_GAP_ATR


def test_stop_in_force_follows_the_record_rules():
    sig = {"side": 1, "entry": 100.0, "stop": 98.0, "tp1": 102.0, "tp2": 103.0, "tp3": 104.0, "payload": "{}"}
    assert G.stop_in_force(sig, []) == 98.0
    assert G.stop_in_force({**sig, "tp1_hit": 1}, []) == 100.0                       # break-even
    assert G.stop_in_force({**sig, "tp1_hit": 1, "tp2_hit": 1}, []) == 102.0         # TP1 after TP2
    adj = [{"at": 1, "field": "stop", "old": 98.0, "new": 99.0, "note": ""}]
    assert G.stop_in_force(sig, adj) == 99.0                                         # admin stop before TP1
    assert G.stop_in_force({**sig, "tp1_hit": 1}, adj) == 100.0                      # never looser than BE after TP1


def test_after_tp1_giveback_counts():
    rt = RT()
    add_call(rt.db, tp1_hit=1, peak_r=1.6)
    # price back at 100.6 = 0.3R; gave back 81 % of the 1.6R peak
    g, _ = run(rt, {SYM: drop(100.6, base=103.0), "BTC/USDT": BTC_CALM}, decision="SELL")
    p = loads(g.recs()[0]["payload"]) if g.recs() else None
    st = rt.db.get_setting(G.STATE)["calls"]["sig1"]
    assert st["severity"] >= 50
    assert p is not None and any(r["code"] == "giveback" for r in p["reasons"])
    if g.recs()[0]["level"] == "TIGHTEN":
        assert p["proposed_stop"] > 100.0                           # tighter than break-even


# ---- 2. Gemini ------------------------------------------------------------------------------------------------
GOOD = "The price moved against the long trade in the last 15 minutes. Bitcoin fell over the same window."


def test_gemini_downgrade_is_honoured():
    rt = RT()
    add_call(rt.db)
    adv = FakeAdv({"verdict": "downgrade", "explanation": GOOD})
    g, _ = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", adv=adv)
    r = g.recs()[0]
    p = loads(r["payload"])
    assert r["rules_level"] == "CLOSE" and r["level"] == "TIGHTEN" and p["ai"]["path"] == "ai_downgraded"
    assert p["ai"]["text"] == GOOD and p["proposed_stop"] is not None
    assert "proposed_stop" not in adv.seen                          # a CLOSE was sent without any level to edit
    # TIGHTEN -> no action: stored (dedupe + evidence), not live, no push
    rt2 = RT()
    add_call(rt2.db)
    sink = LocalSink(tempfile.mkdtemp(), rt2.db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    g2, _ = run(rt2, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL", sink=sink,
                adv=FakeAdv({"verdict": "downgrade", "explanation": GOOD}))
    r2 = g2.recs()[0]
    assert r2["level"] == "NONE" and r2["status"] == "downgraded" and sent == []


@pytest.mark.parametrize("answer", [
    {"verdict": "upgrade", "explanation": GOOD},                                       # cannot upgrade
    {"verdict": "agree", "explanation": "The price fell hard. Move the stop to 98.37 instead."},   # invented level
    {"verdict": "agree", "explanation": "The trade is weak now. You should close it before it gets worse."},  # advice
    {"verdict": "agree", "explanation": "Ether is likely to fall further. The trend turned."},          # prediction
    {"verdict": "agree", "explanation": "Weak."},                                                       # 1 sentence
    "not a dict",
])
def test_gemini_bad_answers_are_rejected_and_the_rules_stand(answer):
    rt = RT()
    add_call(rt.db)
    g, _ = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", adv=FakeAdv(answer))
    r = g.recs()[0]
    p = loads(r["payload"])
    assert r["level"] == "CLOSE" and p["ai"]["path"] == "ai_rejected"
    assert p["ai"]["text"].startswith("Severity ")                  # the template, not the rejected text


def test_gemini_agree_and_unavailable():
    rt = RT()
    add_call(rt.db)
    g, _ = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", adv=FakeAdv({"verdict": "agree", "explanation": GOOD}))
    p = loads(g.recs()[0]["payload"])
    assert g.recs()[0]["level"] == "CLOSE" and p["ai"] == {"path": "ai_agreed", "text": GOOD, "model": "fake-gemini"}
    rt2 = RT()
    add_call(rt2.db)
    adv = FakeAdv(None)                                             # HTTP failure / over budget -> None
    g2, _ = run(rt2, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", adv=adv)
    assert adv.n == 1 and loads(g2.recs()[0]["payload"])["ai"]["path"] == "rules_only"


def test_gemini_reserve_is_respected():
    rt = RT()
    add_call(rt.db)
    adv = FakeAdv({"verdict": "agree", "explanation": GOOD})
    day = time.strftime("%Y-%m-%d", time.gmtime(NOW / 1000))
    adv._state = lambda: {"day": day, "count": 140}                  # 10 left < the 25 kept free
    g, _ = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", adv=adv)
    assert adv.n == 0 and loads(g.recs()[0]["payload"])["ai"]["path"] == "rules_only"


# ---- 6. dedupe / expiry ---------------------------------------------------------------------------------------
def test_dedupe_across_ticks_and_restarts():
    rt = RT()
    add_call(rt.db)
    paths = {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}
    for i in range(4):                                              # 4 ticks, each a fresh Guardian (= engine restart)
        run(rt, paths, decision="SELL", now=NOW + i * 5 * MIN)
    assert len(G.Guardian(rt).recs()) == 1


def test_dedupe_survives_a_lost_database_through_the_mirror():
    rt = RT()
    add_call(rt.db)
    sink = LocalSink(tempfile.mkdtemp(), rt.db)
    sink.send_push = lambda msgs: {"sent": len(msgs)}
    paths = {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}
    run(rt, paths, decision="SELL", sink=sink)
    sink.flush()
    rid = G.Guardian(rt).recs()[0]["id"]
    # the engine state is lost: new database (the call itself is still open), same Firestore
    rt2 = RT()
    add_call(rt2.db)
    sink2 = LocalSink(sink.root, rt2.db)
    sink2.send_push = lambda msgs: {"sent": len(msgs)}
    _, out = run(rt2, paths, decision="SELL", sink=sink2, now=NOW + 5 * MIN)
    recs = G.Guardian(rt2).recs()
    assert out["restored"] == 1 and len(recs) == 1 and recs[0]["id"] == rid


def test_escalation_supersedes_and_expiry_then_persistence():
    rt = RT()
    add_call(rt.db)
    run(rt, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL")
    t = G.Guardian(rt).recs()[0]
    assert t["level"] == "TIGHTEN"
    run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", now=NOW + 5 * MIN)
    recs = {r["id"]: r for r in G.Guardian(rt).recs()}
    assert recs[t["id"]]["status"] == "superseded" and len(recs) == 2
    c = next(r for r in recs.values() if r["level"] == "CLOSE")
    # nothing applied: expires 30 (+10 grace) minutes later
    later = NOW + 5 * MIN + G.EXPIRES_MS + G.APPROVE_GRACE_MS + MIN
    run(rt, {SYM: calm(98.7), "BTC/USDT": BTC_CALM}, decision="SELL", now=later)
    assert G.Guardian(rt).recs()[1]["status"] == "expired"
    # conditions come back: a new CLOSE only after PERSIST_TICKS ticks of persistence
    n0 = len(G.Guardian(rt).recs())
    for i in range(1, G.PERSIST_TICKS + 1):
        run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", now=later + i * 5 * MIN)
        n = len(G.Guardian(rt).recs())
        assert n == (n0 if i < G.PERSIST_TICKS else n0 + 1), i
    assert c["id"] != G.Guardian(rt).recs()[-1]["id"]


def test_dismissed_blocks_the_same_level():
    rt = RT()
    add_call(rt.db)
    run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL")
    rid = G.Guardian(rt).recs()[0]["id"]
    G.dismiss(rt, {"guardian_id": rid}, "boss@example.com", now=NOW + MIN)
    for i in range(1, 6):
        run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", now=NOW + i * 5 * MIN)
    recs = G.Guardian(rt).recs()
    assert len(recs) == 1 and recs[0]["status"] == "dismissed"


def test_should_create_rules():
    mk = lambda lvl, st, at=0: {"id": f"{lvl}{st}{at}", "rules_level": lvl, "status": st, "created_at": at}
    assert G.should_create([], None, 9) == (False, None)
    assert G.should_create([], "TIGHTEN", 0) == (True, None)
    assert G.should_create([mk("TIGHTEN", "live")], "TIGHTEN", 9) == (False, None)
    assert G.should_create([mk("TIGHTEN", "live")], "CLOSE", 0) == (True, "TIGHTENlive0")
    assert G.should_create([mk("CLOSE", "live")], "TIGHTEN", 9) == (False, None)
    assert G.should_create([mk("TIGHTEN", "applied")], "TIGHTEN", 9) == (False, None)
    assert G.should_create([mk("TIGHTEN", "expired")], "TIGHTEN", G.PERSIST_TICKS - 1) == (False, None)
    assert G.should_create([mk("TIGHTEN", "expired")], "TIGHTEN", G.PERSIST_TICKS) == (True, None)


# ---- 4. approval through the adjust path ------------------------------------------------------------------------
def _sink(rt):
    sink = LocalSink(tempfile.mkdtemp(), rt.db)
    sent = []
    sink.send_push = lambda msgs: (sent.extend(msgs), {"sent": len(msgs)})[1]
    sink.uid_for_email = lambda e: None
    return sink, sent


def _job(sink, jid, by, params, created=None):
    sink.set(f"jobs/{jid}", {"type": "adjust_signal", "status": "queued", "created_at": created or int(time.time() * 1000),
                             "by": by, "params": params})


def test_admin_apply_tighten_goes_through_adjust_and_notifies(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    rt = RT()
    add_call(rt.db)
    sink, sent = _sink(rt)
    g, _ = run(rt, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL", sink=sink)
    r = g.recs()[0]
    stop = loads(r["payload"])["proposed_stop"]
    assert sent and sent[0]["url"] == "/guardian" and "uid" not in sent[0] and "broadcast" not in sent[0]   # admin push
    # a member cannot approve (engine check, whatever the params say)
    _job(sink, "m", "member@example.com", {"signal_id": "sig1", "stop": stop, "note": "x" * 5, "guardian_id": r["id"]})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/m")["status"] == "failed" and "only the admin" in sink.get("jobs/m")["error"]
    assert G.Guardian(rt).recs()[0]["status"] == "live" and not rt.db.query("SELECT * FROM signal_adjustments")
    # a member cannot dismiss either
    sink.set("jobs/d", {"type": "guardian_dismiss", "status": "queued", "created_at": int(time.time() * 1000),
                        "by": "member@example.com", "params": {"guardian_id": r["id"]}})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/d")["status"] == "failed" and G.Guardian(rt).recs()[0]["status"] == "live"
    # the admin may not change the level through this path
    _job(sink, "x", "boss@example.com", {"signal_id": "sig1", "stop": stop - 0.5, "note": "tighten", "guardian_id": r["id"]})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/x")["status"] == "failed" and "recommended level" in sink.get("jobs/x")["error"]
    # the admin applies it: same adjust path (stored change, member broadcast), recommendation applied
    _job(sink, "a", "boss@example.com", {"signal_id": "sig1", "stop": stop, "note": G.NOTE_TIGHTEN, "guardian_id": r["id"]})
    n0 = len(sent)
    worker.process_jobs(rt, sink, time.time() + 60)
    job = sink.get("jobs/a")
    assert job["status"] == "done", job
    adj = rt.db.query("SELECT * FROM signal_adjustments")
    assert len(adj) == 1 and adj[0]["field"] == "stop" and adj[0]["new"] == pytest.approx(stop)
    assert sent[n0]["broadcast"] == "1" and "update" in sent[n0]["title"]       # members notified as with Adjust
    rec = G.Guardian(rt).recs()[0]
    assert rec["status"] == "applied" and loads(rec["payload"])["applied"]["field"] == "stop"


def test_apply_revalidates_at_the_engine_price(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    rt = RT()
    add_call(rt.db)
    sink, _ = _sink(rt)
    g, _ = run(rt, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL", sink=sink)
    r = g.recs()[0]
    stop = loads(r["payload"])["proposed_stop"]
    rt.px[SYM] = stop + 0.05                                        # the price fell to just above the proposed stop
    _job(sink, "a", "boss@example.com", {"signal_id": "sig1", "stop": stop, "note": G.NOTE_TIGHTEN, "guardian_id": r["id"]})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/a")["status"] == "failed" and "no longer valid" in sink.get("jobs/a")["error"]
    rec = G.Guardian(rt).recs()[0]
    assert rec["status"] == "rejected" and "closer than" in rec["status_reason"]
    assert not rt.db.query("SELECT * FROM signal_adjustments")


def test_apply_close_and_expired_and_changed_call(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    rt = RT()
    add_call(rt.db)
    sink, sent = _sink(rt)
    g, _ = run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", sink=sink)
    r = g.recs()[0]
    assert r["level"] == "CLOSE"
    # a TIGHTEN-style request for a CLOSE recommendation is refused (the recommendation stays live)
    _job(sink, "w", "boss@example.com", {"signal_id": "sig1", "stop": 99.0, "note": "nope", "guardian_id": r["id"]})
    worker.process_jobs(rt, sink, time.time() + 60)
    assert sink.get("jobs/w")["status"] == "failed"
    assert G.Guardian(rt).recs()[0]["status"] == "live"
    out = G.approve(rt, {"signal_id": "sig1", "action": "close", "guardian_id": r["id"]}, "boss@example.com", sink,
                    job_created_at=NOW + MIN, now=NOW + 2 * MIN)
    assert out["ok"] and out["guardian"]["status"] == "applied"
    adj = rt.db.query("SELECT * FROM signal_adjustments")
    assert adj[-1]["field"] == "close" and "closed" in sent[-1]["title"]
    # expired: the job was created after the recommendation expired
    rt2 = RT()
    add_call(rt2.db)
    g2, _ = run(rt2, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL")
    r2 = g2.recs()[0]
    with pytest.raises(A.AdjustError, match="expired"):
        G.approve(rt2, {"signal_id": "sig1", "action": "close", "guardian_id": r2["id"]}, "boss@example.com",
                  job_created_at=r2["expires_at"] + 1, now=r2["expires_at"] + 2)
    assert G.Guardian(rt2).recs()[0]["status"] == "expired"
    # changed after the recommendation (an admin Adjust in between) -> refused
    rt3 = RT()
    add_call(rt3.db)
    g3, _ = run(rt3, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL")
    r3 = g3.recs()[0]
    rt3.db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note, by, price_at_change) "
                   "VALUES ('x', 'sig1', ?, 'stop', 98, 98.2, 'manual', 'boss', 98.6)", (NOW + MIN,))
    with pytest.raises(A.AdjustError, match="changed after"):
        G.approve(rt3, {"signal_id": "sig1", "action": "close", "guardian_id": r3["id"]}, "boss@example.com",
                  job_created_at=NOW + 2 * MIN, now=NOW + 3 * MIN)


def test_m1_cache_is_incremental():
    rt = RT()
    f = fetcher({SYM: calm()})
    g = G.Guardian(rt, fetch=f, now=NOW)
    rows = g.m1(SYM)
    assert len(rows) == 100 and f.calls[-1][1] == NOW - 100 * MIN
    f2 = fetcher({SYM: calm()}, now=NOW + 5 * MIN)
    g2 = G.Guardian(rt, fetch=f2, now=NOW + 5 * MIN)
    rows2 = g2.m1(SYM)
    assert f2.calls[-1][1] == rows[-1][0]                           # only the tail from the newest cached candle
    assert len(rows2) == 100 and rows2[-1][0] == NOW + 4 * MIN


# ---- 7. fail-safe ---------------------------------------------------------------------------------------------
def test_errors_never_raise_and_never_touch_the_record():
    rt = RT()
    add_call(rt.db)
    before = rt.db.one("SELECT * FROM signals")

    def broken(symbol, since, limit):
        raise ConnectionError("data-api down")
    g = G.Guardian(rt, None, fetch=broken, advisor=FakeAdv(enabled=False), now=NOW)
    out = g.run(analyses("SELL"))                                   # no exception
    st = rt.db.get_setting(G.STATE)
    assert st["today"]["errors"] >= 1 and "1m candles" in st["last_error"]["where"] and g.recs() == []
    assert out["stale"] == 1
    run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL")
    assert rt.db.one("SELECT * FROM signals") == before             # the record is never changed by the Guardian
    assert not rt.db.query("SELECT * FROM signal_adjustments")
    assert not rt.db.query("SELECT * FROM decisions WHERE rule LIKE 'guardian%'")   # nothing in member-readable views


def test_switch_off(monkeypatch):
    monkeypatch.setattr(G, "ENABLED", False)
    rt = RT()
    add_call(rt.db)
    assert G.Guardian(rt, now=NOW).run(analyses()) == {"enabled": False}


# ---- 8. shadow evidence -------------------------------------------------------------------------------------------
def _closed_call(rt, status="STOPPED"):
    t0 = (CREATED // M15) * M15
    add_call(rt.db, created=t0, status=status, closed_at=t0 + 3 * M15, return_pct=-2.0)
    rt.m15[SYM] = pd.DataFrame([[t0, 100, 100.3, 99.6, 99.8, 1], [t0 + M15, 99.8, 99.9, 98.9, 99.0, 1],
                                [t0 + 2 * M15, 99.0, 99.1, 97.8, 97.9, 1]],
                               columns=["ts", "open", "high", "low", "close", "volume"])
    return t0


def _rec(rt, t0, level, status="dismissed", **pay):
    rt.db.execute("INSERT INTO guardian_recs (id, signal_id, symbol, timeframe, side, level, rules_level, severity, created_at, "
                  "expires_at, status, payload) VALUES (?, 'sig1', ?, ?, 1, ?, ?, 60, ?, ?, ?, ?)",
                  (f"r{level}{status}", SYM, TF, level, level, t0 + 10 * MIN, t0 + 40 * MIN, status, dumps(pay)))


def test_shadow_outcome_tighten_and_close_not_applied():
    rt = RT()
    t0 = _closed_call(rt)
    _rec(rt, t0, "TIGHTEN", proposed_stop=99.2, price=99.6)
    _rec(rt, t0, "CLOSE", status="expired", price=99.5)
    G.Guardian(rt, now=NOW).shadow_update()
    rows = {r["level"]: loads(r["shadow"]) for r in G.Guardian(rt).recs()}
    cost_r = T.cost_pct() / 2.0                                     # risk 2 % of the entry
    t = rows["TIGHTEN"]
    assert t["without_r"] == pytest.approx(-1.0 - cost_r, abs=1e-3)  # the real result: stopped at 98
    assert t["with_r"] == pytest.approx(-0.4 - cost_r, abs=1e-3)     # stop 99.2 from the next candle
    assert t["delta_r"] == pytest.approx(0.6, abs=1e-3) and not t["applied"]
    c = rows["CLOSE"]
    assert c["with_r"] == pytest.approx(-0.25 - cost_r, abs=1e-3) and c["delta_r"] == pytest.approx(0.75, abs=1e-3)
    sb = G.scoreboard(G.Guardian(rt).recs())
    assert sb["n"] == 2 and sb["saved_r"] == pytest.approx(1.35) and sb["cost_r"] == 0 and sb["helped"] == 2
    assert sb["by_level"]["TIGHTEN"]["n"] == 1 and sb["not_applied"]["n"] == 2


def test_shadow_outcome_applied_compares_against_without():
    rt = RT()
    t0 = _closed_call(rt)
    at = t0 + 10 * MIN
    rt.db.execute("INSERT INTO signal_adjustments (id, signal_id, at, field, old, new, note, by, price_at_change) "
                  "VALUES ('a1', 'sig1', ?, 'stop', 98, 99.2, 'g', 'boss', 99.6)", (at,))
    _rec(rt, t0, "TIGHTEN", status="applied", proposed_stop=99.2, price=99.6,
         applied={"at": at, "field": "stop", "value": 99.2})
    G.Guardian(rt, now=NOW).shadow_update()
    s = loads(G.Guardian(rt).recs()[0]["shadow"])
    assert s["applied"] and s["delta_r"] == pytest.approx(0.6, abs=1e-3)


def test_shadow_waits_while_the_call_is_open_and_skips_not_filled():
    rt = RT()
    add_call(rt.db)
    _rec(rt, CREATED, "TIGHTEN", proposed_stop=99.0, price=99.5)
    assert G.Guardian(rt, now=NOW).shadow_update() == 0
    rt.db.execute("UPDATE signals SET status = 'NOT_FILLED'")
    G.Guardian(rt, now=NOW).shadow_update()
    assert loads(G.Guardian(rt).recs()[0]["shadow"])["skipped"] == "call not_filled"


# ---- 9. the admin's document -----------------------------------------------------------------------------------
def test_view_size_and_writes(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    rt = RT()
    add_call(rt.db)
    sink, _ = _sink(rt)
    run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", sink=sink)
    assert sink.flush() == 1                                        # the new recommendation went out at once
    # a calm tick a few minutes later: only the status line changed -> held back until the next engine run (PUBLISH_EVERY_S)
    run(rt, {SYM: calm(98.7), "BTC/USDT": BTC_CALM}, decision="SELL", sink=sink, now=NOW + 5 * MIN)
    assert sink.flush() == 0
    # 300 recommendations in history: the document stays small (live + last 50)
    for i in range(300):
        rt.db.execute("INSERT INTO guardian_recs (id, signal_id, symbol, timeframe, side, level, rules_level, severity, "
                      "created_at, expires_at, status, payload) VALUES (?, 'old', ?, ?, 1, 'TIGHTEN', 'TIGHTEN', 60, ?, ?, "
                      "'expired', ?)", (f"h{i}", SYM, TF, NOW - i * MIN, NOW, dumps({"reasons": [{"code": "move", "points": 30,
                      "label": "Moved 1.40 ATR against in 15 min"}] * 5, "facts": {"x": list(range(20))}, "ai": {"path": "rules_only",
                      "text": "x" * 400}})))
    v = G.Guardian(rt, now=NOW).view()
    size = len(dumps(v).encode())
    assert len(v["history"]) == G.HISTORY_IN_VIEW and size < 150_000, size
    doc = sink.get("views/guardian")
    data = loads(doc["json"])
    assert data["live"] and data["live"][0]["level"] == "CLOSE" and "status" in data and "scoreboard" in data


def test_lean_mode_only_publishes_a_new_close(monkeypatch):
    rt = RT()
    add_call(rt.db)
    sink, _ = _sink(rt)
    monkeypatch.setattr(type(sink), "lean", property(lambda self: True))
    run(rt, {SYM: drop(99.1), "BTC/USDT": BTC_CALM}, decision="SELL", sink=sink)       # TIGHTEN: not essential
    assert sink.flush() == 0
    run(rt, {SYM: drop(98.6), "BTC/USDT": BTC_DUMP}, decision="SELL", sink=sink, now=NOW + 5 * MIN)   # new CLOSE
    assert sink.flush() == 1


def test_rules_template_keeps_guardian_admin_only():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "firestore.rules.template").read_text()
    assert "(id == 'guardian' && isAdmin())" in src and "id != 'guardian'" in src
    # members may only queue backtest / replay / test_push jobs (never adjust_signal / guardian_dismiss)
    assert "request.resource.data.type in ['backtest', 'replay', 'test_push']" in src


def test_telegram_dm_never_goes_to_the_public_channel(monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "config", lambda sink: {"token": "t", "channel": "@public"})
    sent = []
    monkeypatch.setattr(telegram, "send", lambda cfg, text, session=None: (sent.append(cfg["channel"]), {"ok": True})[1])
    assert G.telegram_dm(None, "@public", "x")["ok"] is False and sent == []
    assert G.telegram_dm(None, "12345", "x")["ok"] and sent == ["12345"]
