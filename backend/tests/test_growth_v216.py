"""v2.16 growth: five more coins (one-time migration), AI market briefing, AI coin reports, Telegram funnel (daily free
call with its result, briefing, last-7-days card), smarter alerts (call events + market mood), Results 7-day card, and
the Firestore write savings that pay for them."""
import asyncio
import json
from datetime import datetime, timezone

from app import views, worker
from app.db import Database, dumps, loads
from app.services import alerts, briefing, cards, coin_reports, telegram as T
from app.services.runtime import USER, Runtime
from app.sinks import LocalSink

H = 3_600_000
D = 86_400_000


def ms(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


class _P:
    name = "test"

    def __init__(self, listed=("LINK", "ADA", "SUI", "DOT", "NEAR")):
        self.listed = set(listed)

    async def search_markets(self, q, limit=20):
        return [f"{q}/USDT"] if q in self.listed else []


def _rt(provider=None):
    return Runtime(Database("sqlite:///:memory:"), provider or _P())


def _sig(rt, sid, created, symbol="BTC/USDT", tf="4h", side=1, status="OPEN", grade="A", fill="FILLED", filled=None,
         closed=None, ret=None, tp=(0, 0, 0), stop_hit=0, exit_reason=None, entry=100.0, stop=98.0, net=None):
    rt.db.execute(
        "INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, price, side, entry, stop, tp1, tp2, "
        "tp3, status, payload, fill_status, filled_at, closed_at, return_pct, return_net_pct, tp1_hit, tp2_hit, tp3_hit, "
        "stop_hit, exit_reason) VALUES (?, ?, ?, ?, ?, 'BUY', 'BUY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sid, created, symbol, tf, created, entry, side, entry, stop, entry + side * 2, entry + side * 3.5, entry + side * 5,
         status, dumps({"grade": grade}), fill, filled if filled is not None else (created if fill == "FILLED" else None),
         closed, ret, net, *tp, stop_hit, exit_reason))


# ---- 1. coins ------------------------------------------------------------------------------------------------------
def test_growth_coins_are_appended_once_and_only_listed_ones(tmp_path):
    rt = _rt(_P(listed=("LINK", "ADA", "DOT", "NEAR")))          # SUI not listed by this (fake) exchange
    for f in worker.MIGRATION_FLAGS:                             # a real, running installation
        if f != "coins_growth_v216":
            rt.db.set_setting(f, True)
    sink = LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}, {"symbol": "DOT/USDT", "pinned": False}]})
    sink.set("config/bots", {"bots": [], "defaults_added": [b["id"] for b in worker.DEFAULT_BOTS]})
    notes = worker.sync_config(rt, sink)
    assert notes["coins_growth_v216"] == ["LINK/USDT", "ADA/USDT", "NEAR/USDT"]
    syms = [s["symbol"] for s in sink.get("config/watchlist")["symbols"]]
    assert syms == ["BTC/USDT", "DOT/USDT", "LINK/USDT", "ADA/USDT", "NEAR/USDT"]
    assert set(rt.symbols()) == set(syms)
    # the admin removes one later: it is never added back
    sink.set("config/watchlist", {"symbols": [{"symbol": s, "pinned": False} for s in syms if s != "ADA/USDT"]})
    worker.sync_config(rt, sink)
    assert "ADA/USDT" not in [s["symbol"] for s in sink.get("config/watchlist")["symbols"]]


def test_growth_flag_is_a_guarded_migration_and_never_runs_on_a_fresh_database(tmp_path):
    assert "coins_growth_v216" in worker.MIGRATION_FLAGS
    rt, sink = _rt(), LocalSink(tmp_path)
    sink.set("config/watchlist", {"symbols": [{"symbol": "BTC/USDT", "pinned": True}]})
    notes = worker.sync_config(rt, sink)
    assert "coins_growth_v216" not in notes
    assert [s["symbol"] for s in sink.get("config/watchlist")["symbols"]] == ["BTC/USDT"]


def test_new_models_train_first_within_their_cost_tier():
    import inspect
    src = inspect.getsource(worker.shard_pairs)
    assert "age[p]" in src                                   # missing (age 0) and oldest models first in each tier


def test_perf_pages_are_held_to_hourly(tmp_path):
    rt, sink = _rt(), LocalSink(tmp_path, None)
    rt.add_symbol("BTC/USDT")
    calls = []
    sink.view = lambda name, payload, **kw: calls.append((name, kw.get("min_interval_s", 0)))
    worker.publish_models(rt, sink)
    perf = [m for n, m in calls if n.startswith("perf_")]
    assert perf and all(m == worker.PERF_EVERY_S == 3600 for m in perf)
    assert worker.ANALYSIS_EVERY_S["15m"] == 1800          # 15m coin pages every 30 min (a changed call still at once)


# ---- 5. smarter alerts -------------------------------------------------------------------------------------------
def _alert(rt, aid, type_, symbol="ALL/USDT", tf="all", params=None, user="m1", cooldown=60):
    rt.db.execute("INSERT INTO alerts (id, user_id, type, symbol, timeframe, params, cooldown_s, enabled, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)", (aid, user, type_, symbol, tf, dumps(params or {}), cooldown))


def test_call_events_fire_once_per_call_and_new_rules_are_primed():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _sig(rt, "old", now - 5 * H, tp=(1, 1, 0))                  # TP2 already reached before the rule existed
    _alert(rt, "a1", "SIGNAL_UPDATES")
    assert alerts.lifecycle(rt.db, now) == []                     # primed: what already happened is not sent
    _sig(rt, "p", now - H, symbol="ETH/USDT", fill="PENDING", filled=None)
    assert alerts.lifecycle(rt.db, now + 1) == []
    rt.db.execute("UPDATE signals SET fill_status = 'FILLED', filled_at = ? WHERE id = 'p'", (now,))
    evs = alerts.lifecycle(rt.db, now + 2)
    assert [e["type"] for e in evs] == ["ENTRY_REACHED"] and "ETH 4H LONG: entry reached" in evs[0]["message"]
    assert alerts.lifecycle(rt.db, now + 3) == []                 # deduplicated
    rt.db.execute("UPDATE signals SET tp1_hit = 1, tp2_hit = 1, tp3_hit = 1 WHERE id = 'old'")
    evs = alerts.lifecycle(rt.db, now + 4)
    assert [e["type"] for e in evs] == ["TP3_REACHED"]            # TP1 / TP2 of 'old' were seen at priming
    rt.db.execute("UPDATE signals SET status = 'STOPPED', closed_at = ?, return_pct = -2.0, return_net_pct = -2.2, "
                  "stop_hit = 1 WHERE id = 'p'", (now + 5,))
    evs = alerts.lifecycle(rt.db, now + 6)
    assert [e["type"] for e in evs] == ["SIGNAL_CLOSED"] and "stopped out" in evs[0]["message"] and "-2.20% after fees" in evs[0]["message"]


def test_single_event_types_symbol_and_timeframe_filters_and_daily_cap(monkeypatch):
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _alert(rt, "btc", "TP2_REACHED", symbol="BTC/USDT", tf="4h")
    _alert(rt, "any1h", "SIGNAL_CLOSED", tf="1h", user="m2")
    alerts.lifecycle(rt.db, now)                                 # prime both
    _sig(rt, "b", now, tp=(1, 1, 0))
    _sig(rt, "e", now, symbol="ETH/USDT", tp=(1, 1, 0))
    _sig(rt, "x", now, symbol="SOL/USDT", tf="1h", status="EXPIRED", closed=now, ret=0.4, net=0.2)
    evs = alerts.lifecycle(rt.db, now + 1)
    got = sorted((e["alert_id"], e["symbol"], e["type"]) for e in evs)
    assert got == [("any1h", "SOL/USDT", "SIGNAL_CLOSED"), ("btc", "BTC/USDT", "TP2_REACHED")]
    # cap: a member gets at most MAX_EVENTS_PER_DAY of these a day
    monkeypatch.setattr(alerts, "MAX_EVENTS_PER_DAY", 1)
    for i in range(3):
        _sig(rt, f"s{i}", now + 10 + i, symbol="ADA/USDT", tf="1h", status="STOPPED", closed=now + 10, ret=-1.0)
    assert alerts.lifecycle(rt.db, now + 20) == []                # m2 already had one today


def test_trade_setup_rules_skip_event_types():
    rt = _rt()
    _alert(rt, "a", "TP2_REACHED", symbol="BTC/USDT", tf="4h")
    a = {"status": "OK", "symbol": "BTC/USDT", "timeframe": "4h", "price": 1.0}
    assert alerts.evaluate(rt.db, a) == []
    assert rt.db.one("SELECT last_state FROM alerts WHERE id = 'a'")["last_state"] is None


def _an(groups, tf="4h"):
    return {(f"C{i}/USDT", tf): {"status": "OK", "regime": {"group": g}} for i, g in enumerate(groups)}


def test_market_mood_flip_fires_only_between_bull_and_bear():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _alert(rt, "m", "MOOD_CHANGE", tf="4h", cooldown=3600)
    assert alerts.mood(rt.db, _an(["Bull"] * 7 + ["Bear"] * 3), now) == []           # first reading: remembered
    assert alerts.mood(rt.db, _an(["Bull"] * 4 + ["Neutral"] * 6), now + 1) == []    # neutral never fires
    evs = alerts.mood(rt.db, _an(["Bear"] * 8 + ["Bull"] * 2), now + 2)
    assert len(evs) == 1 and "turned bearish (was bullish)" in evs[0]["message"] and evs[0]["symbol"] == "ALL/USDT"
    assert alerts.mood(rt.db, _an(["Bull"] * 8 + ["Bear"] * 2), now + 3) == []        # flip back inside the cooldown
    assert alerts.mood(rt.db, _an(["Bear"] * 8 + ["Bull"] * 2), now + 2 * H) != []


def test_alert_row_accepts_the_new_types_and_push_titles():
    row = worker.alert_row({"type": "SIGNAL_UPDATES", "symbol": "ALL/USDT", "timeframe": "all",
                            "params": {"events": ["entry", "tp2"]}, "cooldown_s": 60, "owner_uid": "m1"})
    assert row and row[0] == "SIGNAL_UPDATES" and row[1] == "ALL/USDT" and row[2] == "all"
    m = worker.push_message({"type": "MOOD_CHANGE", "symbol": "ALL/USDT", "message": "x", "id": "1"}, "m1")
    assert m["title"] == "Market mood changed" and m["uid"] == "m1"
    assert worker.push_message({"type": "TP2_REACHED", "symbol": "BTC/USDT", "message": "x", "id": "2"})["title"] == "TP2 hit · BTC/USDT"


def test_signal_updates_respects_chosen_events():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _alert(rt, "a", "SIGNAL_UPDATES", params={"events": ["tp3"]})
    alerts.lifecycle(rt.db, now)
    _sig(rt, "s", now, tp=(1, 1, 1), status="TP3", closed=now, ret=5.0)
    assert [e["type"] for e in alerts.lifecycle(rt.db, now + 1)] == ["TP3_REACHED"]


# ---- 6. last 7 days ------------------------------------------------------------------------------------------------
def test_recent_summary_is_net_counts_wins_and_losses_and_has_no_timestamps():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    rt.db.set_setting("record_since", now - 30 * D)
    _sig(rt, "w", now - 3 * D, status="TP2", closed=now - 2 * D, ret=3.0, net=2.8)
    _sig(rt, "l", now - 3 * D, symbol="ETH/USDT", status="STOPPED", closed=now - D, ret=-2.0, net=-2.2)
    _sig(rt, "o", now - 9 * D, symbol="SOL/USDT", status="STOPPED", closed=now - 8 * D, ret=-1.0, net=-1.2)   # outside
    _sig(rt, "n", now - 2 * D, symbol="ADA/USDT", status="NOT_FILLED", fill="NOT_FILLED", closed=now - D)    # no result
    r = views.recent_summary(rt, 7, now)
    assert r["closed"] == 2 and r["wins"] == 1 and r["losses"] == 1 and r["win_rate"] == 0.5
    assert abs(r["avg_return_pct"] - 0.3) < 1e-9 and r["best"]["symbol"] == "BTC/USDT" and r["worst"]["return_pct"] == -2.2
    assert "Only 2 closed signals" in r["sample_note"]
    assert not any(k in json.dumps(r) for k in ('"ts"', '"since"', '"until"', '"generated_at"'))
    assert views.recent_summary(rt, 7, now + 60_000) == r        # the window sliding a minute changes nothing


def test_track_record_carries_the_7_day_block():
    rt = _rt()
    tr = views.track_record(rt, None)
    assert tr["last_7d"]["closed"] == 0 and tr["last_7d"]["sample_note"] == "No signal closed in these 7 days."


# ---- 2. briefing -----------------------------------------------------------------------------------------------------
def _analysis(sym, tf, group="Bull", regime="BULL", ch=1.5, side=1, conf=0.58, clears=True, close=110.0, ema=100.0):
    return {"status": "OK", "symbol": sym, "timeframe": tf, "price": close, "last_close": close, "change_24h_pct": ch,
            "regime": {"regime": regime, "group": group}, "indicators": {"ema_50": ema, "rsi": 55.0},
            "forecast": {"available": True}, "direction_view": {"side": side, "clears_policy": clears, "policy_edge": True},
            "confidence": conf, "bar_ts": 1, "volatility": {"state": "NORMAL"},
            "levels": {"zones": {"support": [{"mid": close * 0.95}, {"mid": close * 0.9}],
                                 "resistance": [{"mid": close * 1.05}]}}}


def _analyses():
    out = {}
    for i, (s, g, ch) in enumerate([("BTC/USDT", "Bull", 2.0), ("ETH/USDT", "Bull", -1.0), ("SOL/USDT", "Bull", 5.0),
                                    ("XRP/USDT", "Bear", -3.0), ("ADA/USDT", "Neutral", 0.5)]):
        for tf in ("4h", "12h", "1d"):
            out[(s, tf)] = _analysis(s, tf, g, {"Bull": "BULL", "Bear": "BEAR", "Neutral": "NEUTRAL"}[g], ch, ema=100.0 if g != "Bear" else 120.0)
    return out


CTX = {"sentiment": {"value": 34, "label": "Fear", "change_7d": -6}, "market": {"btc_dominance": 57.23, "market_cap_change_24h_pct": 1.1}}


def test_briefing_facts_and_template_use_only_engine_numbers():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _sig(rt, "o1", now - H)
    _sig(rt, "o2", now - H, symbol="ETH/USDT", side=-1, entry=100, stop=102, fill="PENDING", filled=None)
    f = briefing.facts(rt.db, _analyses(), CTX, now)
    assert f["mood"]["status"] == "BULL" and f["mood"]["bull"] == 3 and f["breadth"] == {"above_ema50_4h": 4, "of": 5, "up_24h": 3}
    assert f["open_calls"] == {"long": 1, "short": 0, "waiting_entry": 1}
    assert f["movers"]["up"][0] == {"coin": "SOL", "change_24h_pct": 5.0} and f["movers"]["down"][0]["coin"] == "XRP"
    t = briefing.template(f)
    assert 3 <= t.count(". ") + 1 <= 6 and briefing.numbers_ok(t, f) and "leaning bullish" in t
    assert briefing.bullets(f)[0].startswith("Mood (4H): 3 bullish")


def test_briefing_ai_text_is_checked_and_falls_back_to_the_template():
    f = briefing.facts(_rt().db, _analyses(), CTX, ms(2026, 11, 3, 12))
    good = ("The market leans bullish, with 3 of 5 coins in a bullish 4H regime. Bitcoin is up 2.0% over 24 hours. "
            "Fear & Greed sits at 34, showing fear.")
    assert briefing.acceptable(good, f) == good
    assert briefing.acceptable(good.replace("34", "71"), f) is None                       # invented number
    assert briefing.acceptable(good + " Bitcoin will rise to new highs.", f) is None       # prediction
    assert briefing.acceptable("Guaranteed gains ahead. Buy now. Really.", f) is None      # promise / advice
    assert briefing.acceptable("One sentence only.", f) is None


class _Adv:
    def __init__(self, text, enabled=True):
        self.text, self.enabled, self.model, self.daily_limit, self.calls = text, enabled, "gemini-test", 150, 0

    def available(self, now=None):
        return self.enabled

    def _state(self):
        return {}

    def generate(self, task, data, schema, now=None):
        self.calls += 1
        assert "Do NOT" in task or "do NOT" in task
        return {"text": self.text}


def test_briefing_run_due_rules_ai_and_template():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    good = "The market leans bullish, with 3 of 5 coins in a bullish 4H regime. Bitcoin is up 2.0% over 24 hours."
    out = briefing.run(rt.db, _analyses(), CTX, now, advisor=_Adv(good))
    assert out["source"] == "ai" and briefing.current(rt.db)["text"] == good and "core" not in briefing.current(rt.db)
    assert briefing.run(rt.db, _analyses(), CTX, now + H, advisor=_Adv(good))["skipped"] == "not due"
    # a big regime change refreshes it after an hour; a bad AI answer falls back to the template
    an = _analyses()
    for s in ("BTC/USDT", "ETH/USDT", "SOL/USDT"):
        an[(s, "4h")] = _analysis(s, "4h", "Bear", "BEAR", -2.0)
    assert briefing.run(rt.db, an, CTX, now + 30 * 60_000, advisor=_Adv(good))["skipped"] == "not due"
    out = briefing.run(rt.db, an, CTX, now + H + 1, advisor=_Adv("Bitcoin will rise 40%. Trust us. Now."))
    assert out == {"refreshed": "regime change", "source": "template", "chars": out["chars"]}
    assert briefing.current(rt.db)["mood"] == "BEAR"
    # without the hourly analyses (no 1D) nothing is done
    four = {k: v for k, v in an.items() if k[1] == "4h"}
    assert "skipped" in briefing.run(rt.db, four, CTX, now + 9 * H, advisor=_Adv(good))


def test_market_context_view_carries_the_briefing(tmp_path, monkeypatch):
    rt = _rt()
    rt.db.set_setting("briefing", {"text": "A. B. C.", "at": 5, "core": [1], "bullets": []})
    sink = LocalSink(tmp_path, rt.db)
    seen = {}
    real = sink.view

    def view(name, payload, **kw):
        if name in ("market_context", "coin_reports"):
            seen[name] = (payload, kw)
        return real(name, payload, **kw)
    sink.view = view
    worker.publish(rt, sink, {}, 0, {})
    p, kw = seen["market_context"]
    assert p["briefing"]["text"] == "A. B. C." and kw["core"] == 5 and kw["min_interval_s"] == 3600
    assert seen["coin_reports"][1]["min_interval_s"] == 3600


# ---- 3. coin reports -------------------------------------------------------------------------------------------------
def test_coin_report_is_built_from_the_analysis_and_open_call():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    an = _analyses()
    r = coin_reports.report(rt.db, "BTC/USDT", an)
    assert r["trend"]["label"] == "Uptrend" and r["expects"][0] == {"timeframe": "4h", "lean": "up", "confidence": 0.58,
                                                                    "above_threshold": True, "proven_edge": True}
    assert r["levels"]["support"][0] == 104.5 and r["invalidation"]["price"] == 104.5 and r["call"] is None
    assert "price" not in r                                         # no live price: unchanged markets write nothing
    _sig(rt, "c", now - H, tf="12h", entry=110, stop=106, tp=(1, 0, 0))
    r = coin_reports.report(rt.db, "BTC/USDT", an)
    assert r["call"]["timeframe"] == "12h" and r["call"]["stop"] == 110.0          # break-even after TP1
    assert "ends if price trades below 110.00" in r["invalidation"]["text"]
    an[("BTC/USDT", "4h")]["volatility"] = {"state": "HIGH"}
    assert coin_reports.report(rt.db, "BTC/USDT", an)["risk"].startswith("Volatility is high")


def test_coin_reports_run_uses_gemini_within_budget_and_view_has_one_entry_per_coin():
    rt = _rt()
    now = ms(2026, 11, 3, 12)
    _sig(rt, "c", now - H, symbol="XRP/USDT", side=-1, entry=110, stop=114)
    syms = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT"]
    adv = _Adv("XRP is in a downtrend on 4H. Its short call stops at 114.")
    out = coin_reports.run(rt.db, _analyses(), syms, now, advisor=adv)
    assert out == {"coins": 5, "ai_written": coin_reports.COIN_AI_PER_TICK}
    v = coin_reports.view(rt.db, syms)["reports"]
    assert set(v) == set(syms) and v["XRP/USDT"]["ai"]["text"].startswith("XRP")   # the coin with a call goes first
    # unchanged reports keep their sentence (no new Gemini call for them)
    n = adv.calls
    coin_reports.run(rt.db, _analyses(), syms, now + H, advisor=adv)
    assert v["XRP/USDT"]["ai"] == coin_reports.view(rt.db, syms)["reports"]["XRP/USDT"]["ai"]
    assert adv.calls - n <= coin_reports.COIN_AI_PER_TICK
    # a 4H-only cycle does nothing
    assert "skipped" in coin_reports.run(rt.db, {k: x for k, x in _analyses().items() if k[1] == "4h"}, syms, now)


# ---- 4. Telegram funnel ----------------------------------------------------------------------------------------------
class Fake:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, data=None, files=None, timeout=None):
        m = dict(json or data or {})
        m["text"] = m.get("text") or m.get("caption")
        m["photo"] = bool(files)
        self.sent.append(m)

        class R:
            status_code = 200

            def json(self_inner):
                return {"ok": True}
        return R()


def _tg(tmp_path, **opts):
    sink = LocalSink(tmp_path)
    sink.set("owner/telegram", {"enabled": True, "token": "x", "channel": "@c", "post_wins": False, "post_weekly": False,
                                "post_each_win": False, "approve_first": True, **opts})
    return sink


def test_daily_call_is_the_first_filled_grade_a_call_and_its_result_always_follows(tmp_path):
    rt = _rt()
    rt.db.set_setting("tg_win_last", 0)
    sink, fake = _tg(tmp_path, post_briefing=False, post_week7=False), Fake()
    day = ms(2026, 11, 3, 0)
    T.run(rt, sink, None, None, day + 60_000, fake)                     # first run: the feature starts today
    _sig(rt, "b", day + 1 * H, grade="B")                                 # grade B: never the free call
    _sig(rt, "p", day + 2 * H, fill="PENDING", filled=None)               # first grade A, still waiting for entry
    _sig(rt, "f", day + 3 * H, symbol="ETH/USDT")                         # second grade A, filled at once
    T.run(rt, sink, None, None, day + 6 * H, fake)
    assert fake.sent == []                                                # the earlier call holds the choice back
    rt.db.execute("UPDATE signals SET status = 'NOT_FILLED', fill_status = 'NOT_FILLED', closed_at = ? WHERE id = 'p'", (day + 7 * H,))
    T.run(rt, sink, None, None, day + 7 * H, fake)
    assert len(fake.sent) == 1 and "Free signal of the day" in fake.sent[0]["text"] and "ETH/USDT LONG" in fake.sent[0]["text"]
    assert fake.sent[0]["photo"] and sink.get(T.DRAFTS) is None           # sent directly although approve_first is on
    assert rt.db.get_setting("tg_daily_calls", {})["2026-11-03"]["signal_id"] == "f"
    T.run(rt, sink, None, None, day + 8 * H, fake)
    assert len(fake.sent) == 1                                            # once
    rt.db.execute("UPDATE signals SET status = 'STOPPED', closed_at = ?, return_pct = -2.0, return_net_pct = -2.21 WHERE id = 'f'",
                  (day + 9 * H,))
    T.run(rt, sink, None, None, day + 10 * H, fake)
    assert len(fake.sent) == 2 and "Result · free signal of the day" in fake.sent[1]["text"] and "-2.21%" in fake.sent[1]["text"]
    assert "❌" in fake.sent[1]["text"] and "Stopped out" in fake.sent[1]["text"]
    T.run(rt, sink, None, None, day + 11 * H, fake)
    assert len(fake.sent) == 2


def test_daily_call_waits_two_hours_after_the_fill_and_teaser_is_replaced(tmp_path):
    rt = _rt()
    sink, fake = _tg(tmp_path, post_briefing=False, post_week7=False, approve_first=False), Fake()
    day = ms(2026, 11, 3, 0)
    T.run(rt, sink, None, None, day, fake)
    _sig(rt, "a", day + 5 * H, symbol="SOL/USDT", tf="1h")
    T.run(rt, sink, None, None, day + 6 * H, fake)
    assert fake.sent == []                                                # 1 h after the fill: not yet, and no teaser
    T.run(rt, sink, None, None, day + 7 * H + 1, fake)
    assert len(fake.sent) == 1 and "SOL/USDT LONG" in fake.sent[0]["text"]


def test_briefing_posts_twice_a_day_and_week7_replaces_the_weekly(tmp_path):
    rt = _rt()
    sink, fake = _tg(tmp_path, post_daily_call=False, approve_first=False, post_weekly=True), Fake()
    mon = ms(2026, 11, 2, 5, 30)                                          # Monday 05:30 UTC
    rt.db.set_setting("briefing", {"text": "The market is mixed. Bitcoin is flat.", "bullets": ["Open calls: 1 long · 0 short"],
                                   "source": "template", "at": mon - H, "mood": "NEUTRAL"})
    out = T.run(rt, sink, None, {"reports": [{}, {"complete": True, "closed": 2}]}, mon, fake)
    assert out["sent"] == ["briefing"]                                    # weekly cards wait for 06:00 UTC
    out = T.run(rt, sink, None, {"reports": [{}, {"complete": True, "closed": 2}]}, mon + H, fake)
    assert out["sent"] == ["week7"] and "Last 7 days" in fake.sent[-1]["text"] and "No signal closed" in fake.sent[-1]["text"]
    T.run(rt, sink, None, None, mon + 2 * H, fake)
    assert len(fake.sent) == 2                                            # no second briefing before 13:00, no old weekly
    rt.db.set_setting("briefing", {**rt.db.get_setting("briefing", {}), "at": mon + 7 * H})
    assert T.run(rt, sink, None, None, mon + 8 * H, fake)["sent"] == ["briefing"]
    # a stale briefing (older than 5 h) is not posted
    rt.db.set_setting("briefing", {**rt.db.get_setting("briefing", {}), "at": mon})
    assert T.run(rt, sink, None, None, mon + D, fake)["sent"] == []


def test_week7_text_has_net_figures_and_sample_note():
    r = {"closed": 3, "wins": 2, "losses": 1, "win_rate": 2 / 3, "avg_return_pct": 0.5, "total_return_pct": 1.5,
         "best": {"symbol": "PAXG/USDT", "side": "LONG", "timeframe": "4h", "return_pct": 2.0},
         "worst": {"symbol": "BTC/USDT", "side": "SHORT", "timeframe": "1h", "return_pct": -1.4}, "sample_note": views.sample_note(3)}
    t = T.week7_text(r, ms(2026, 11, 2, 6))
    assert "67%" in t and "+0.50%" in t and "GOLD LONG" in t and "-1.40%" in t and "Only 3 closed signals" in t


def test_status_document_is_not_rewritten_every_cycle(tmp_path):
    rt = _rt()
    sink, fake = _tg(tmp_path, post_daily_call=False, post_briefing=False, post_week7=False), Fake()
    writes = []
    real = sink.set
    sink.set = lambda path, data, merge=False: (writes.append(path), real(path, data, merge))
    t = ms(2026, 11, 3, 1)
    for i in range(6):
        T.run(rt, sink, None, None, t + i * 300_000, fake)
    assert writes.count("owner/telegram_status") == 1
    T.run(rt, sink, None, None, t + H + 1, fake)
    assert writes.count("owner/telegram_status") == 2


def test_funnel_cards_draw():
    r = views.recent_summary(_rt(), 7, ms(2026, 11, 3, 12))
    assert cards.week7_card(r, ms(2026, 11, 3, 12))[:4] == b"\x89PNG"
    b = {"text": "The market is mixed. " * 12, "bullets": ["Mood (4H): 3 bullish", "Open calls: 1 long · 0 short"],
         "at": ms(2026, 11, 3, 12), "mood": "BULL", "source": "ai"}
    assert cards.briefing_card(b)[:4] == b"\x89PNG"
