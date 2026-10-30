"""v2.6 stub: should the Gemini news-sentiment score (services/sentiment.py) be used as a trade-filter feature?

There is no history to back-test it yet, so it is OFF. Once at least MIN_DAYS of hourly scores exist, `decide` will test
it the same way as the other gates: add the score known at each call's decision time (sentiment.as_of, by known_at -
no look-ahead) as a feature of the pooled trade filter (ml/trade_filter2.py) and keep it only if the filter's exam on the
newest 25 % of calls improves average R by at least MIN_GAIN_R. Until that test exists and passes, nothing uses it.
"""
from __future__ import annotations

from typing import Any

MIN_DAYS = 60
MIN_GAIN_R = 0.03


def coverage_days(db: Any, grp: str = "market") -> float:
    try:
        r = db.one("SELECT MIN(ts) AS a, MAX(ts) AS b, COUNT(*) AS n FROM news_sentiment WHERE grp = ?", (grp,))
    except Exception:
        return 0.0
    if not r or r["a"] is None:
        return 0.0
    return (int(r["b"]) - int(r["a"])) / 86_400_000


def decide(db: Any) -> dict[str, Any]:
    days = coverage_days(db)
    if days < MIN_DAYS:
        return {"on": False, "days": round(days, 1), "reason": f"collecting news sentiment ({days:.0f} of {MIN_DAYS} days)"}
    # deliberately not implemented yet: the evaluation is written and proven when the history exists
    return {"on": False, "days": round(days, 1),
            "reason": "enough history collected; the evaluation still has to be run before it can be used"}
