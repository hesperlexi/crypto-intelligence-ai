"""V3.4 Stage 4C: each filter judged on its own; enforcement only suggested on strong, stable evidence; never automatic."""
from app.services import ml_shadow as MS


def _rows(n, blocked_r, allowed_r, f="trade_filter"):
    out = []
    for i in range(n):
        out.append((i, {f} if i % 2 == 0 else set(), blocked_r if i % 2 == 0 else allowed_r))
    return out


def test_too_few_stays_in_shadow():
    r = MS.recommend(_rows(60, -0.5, 0.3))
    assert r["trade_filter"]["recommendation"] == "keep in shadow"
    assert any("needs" in x for x in r["trade_filter"]["reasons"])


def test_strong_stable_evidence_is_suggested_not_enforced():
    rows = [(i, {"trade_filter"} if i % 2 == 0 else set(), (-0.6 if i % 2 == 0 else 0.4) + (i % 7) * 0.01) for i in range(400)]
    kept = {"trade_filter|15m": {"kept_share": 0.62, "keep_fraction": 0.6}}
    r = MS.recommend(rows, kept)
    assert r["trade_filter"]["recommendation"].startswith("evidence supports"), r["trade_filter"]["reasons"]
    assert r["trade_filter2"]["recommendation"] == "keep in shadow"           # judged on its own: no blocked calls
    assert "nothing is enforced" in r["note"]


def test_blocked_better_or_unstable_is_not_suggested():
    rows = [(i, {"trade_filter"} if i % 2 == 0 else set(), 0.5 if i % 2 == 0 else 0.1) for i in range(400)]
    assert MS.recommend(rows, {"trade_filter|1h": {"kept_share": 0.6, "keep_fraction": 0.6}})["trade_filter"]["recommendation"] == "keep in shadow"
    flip = [(i, {"trade_filter"} if i % 2 == 0 else set(), (-0.6 if i < 200 else 0.9) if i % 2 == 0 else 0.2) for i in range(400)]
    r = MS.recommend(flip, {"trade_filter|1h": {"kept_share": 0.6, "keep_fraction": 0.6}})["trade_filter"]
    assert r["recommendation"] == "keep in shadow" and any("both halves" in x for x in r["reasons"])
