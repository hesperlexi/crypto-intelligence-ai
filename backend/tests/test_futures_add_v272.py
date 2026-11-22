"""v2.72: a coin with no Binance spot market can be added from the website; the engine follows it on MEXC futures."""
from app import views, worker
from app.data import futures_only as F
from app.db import Database
from app.services.runtime import Runtime


class _P:
    name = "test"


def test_add_futures_only_remembers_the_contract(monkeypatch):
    rt = Runtime(Database("sqlite:///:memory:"), _P())
    monkeypatch.setattr(F, "mexc_contract_for", lambda s, **k: "HYPE_USDT" if s == "HYPE/USDT" else None)
    monkeypatch.setitem(F.FUT_ONLY, "__dummy__", "x")          # keep the dict restorable by monkeypatch
    try:
        assert worker.add_futures_only(rt, "HYPE/USDT") is True
        assert F.FUT_ONLY["HYPE/USDT"] == "HYPE_USDT" and rt.db.get_setting(F.EXTRA_KEY) == {"HYPE/USDT": "HYPE_USDT"}
        assert worker.add_futures_only(rt, "NOPE/USDT") is False and "NOPE/USDT" not in F.FUT_ONLY
        del F.FUT_ONLY["HYPE/USDT"]
        F.load_extra(rt.db.get_setting)                          # another process (fast watch) learns it from the setting
        assert F.is_fut_only("HYPE/USDT")
        assert views._with_fut([{"symbol": "HYPE/USDT"}, {"symbol": "BTC/USDT"}]) == [{"symbol": "HYPE/USDT", "fut": True}, {"symbol": "BTC/USDT"}]
    finally:
        F.FUT_ONLY.pop("HYPE/USDT", None)
