"""Grade research: per-timeframe live horizons and the A-only vs A+B bootstrap."""
from app import research_grades as G


def test_live_horizons():
    assert G.horizons("1h") == [200] and G.horizons("4h") == [100] and G.horizons("1d") == [30]
    assert G.horizons("3d") == [30] and G.horizons("12h") == [30] and G.horizons("15m") == [250, 30]


def test_boot_a_vs_ab():
    t = lambda r: {"return_pct": r, "risk_pct": 1.0}  # noqa: E731
    res = {"A_only": {"s1": [t(1.15), t(1.15)], "s2": [t(0.65)]},
           "A_plus_B": {"s1": [t(1.15), t(-0.85), t(-0.85)], "s2": [t(0.65), t(-0.85)]}}
    b = G.boot(res, 0.15, n_boot=200)
    assert b["A_only"]["share_expectancy_above_0"] == 1.0
    assert b["A_only_vs_A_plus_B"]["share_better_expectancy"] == 1.0
