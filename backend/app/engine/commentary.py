"""Market commentary assembled from calculated values only.

This is template-driven on purpose: every clause is conditional on a number the engines produced, so the
text cannot describe a market condition that was not measured. (No language model is called.)
"""
from __future__ import annotations

from typing import Any


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def build_commentary(a: dict[str, Any]) -> str:
    """`a` is the structured analysis produced by services.analysis.analyze()."""
    sym = a["symbol"].split("/")[0]
    tf = a["timeframe"].upper()
    reg, sig = a.get("regime") or {}, a.get("signal") or {}
    parts: list[str] = []
    if reg.get("regime") in (None, "INSUFFICIENT DATA"):
        return f"There is not enough closed-candle history to classify {sym} on the {tf} timeframe."
    stance = reg["regime"].lower()
    parts.append(f"{sym} is classified as {stance} on the {tf} timeframe"
                 + (f" with {reg['trend_strength'].lower()} trend strength (ADX {reg['adx']:.0f})"
                    if reg.get("trend_strength") and reg.get("adx") is not None else "") + ".")
    comps = {c["key"]: c for c in sig.get("components", []) if c.get("available")}
    drivers = sorted(comps.values(), key=lambda c: -abs(c["contribution"]))[:3]
    if drivers and sig.get("composite") is not None:
        lean = "bullish" if sig["composite"] > 0 else "bearish"
        same = [c["label"].lower() for c in drivers if c["contribution"] * sig["composite"] > 0]
        opp = [c["label"].lower() for c in drivers if c["contribution"] * sig["composite"] < 0]
        if same:
            parts.append(f"The composite reading is {lean} ({sig['score']:.0f}/100), driven mainly by "
                         + ", ".join(same) + (f"; {', '.join(opp)} point{'s' if len(opp) == 1 else ''} the other way."
                                              if opp else "."))
    ml = a.get("forecast") or {}
    if ml.get("available"):
        p = ml["probabilities"]
        parts.append(f"The calibrated ensemble puts the next {tf} bar at {p['up']:.0%} up / {p['neutral']:.0%} neutral / "
                     f"{p['down']:.0%} down, with {ml['model_agreement']:.0%} of model weight agreeing.")
        if not ml.get("edge_confirmed"):
            parts.append("That model has no statistically confirmed out-of-sample edge after costs, so it is shown "
                         "for information and does not drive the signal.")
    elif ml.get("reason"):
        parts.append(f"No model forecast is shown: {ml['reason']}.")
    mtf = a.get("mtf") or {}
    if mtf.get("alignment") is not None:
        parts.append(f"Multi-timeframe alignment is {mtf['alignment']:.0%}"
                     + (", and short and long timeframes disagree." if mtf.get("conflict") else "."))
    warns = sig.get("warnings") or []
    if warns:
        parts.append("Caveats: " + "; ".join((w[0].lower() + w[1:]) if w[1:2].islower() else w for w in warns[:3]) + ".")
    setup = a.get("setup") or {}
    decision = a.get("decision")
    if decision in ("BUY", "BUY ON PULLBACK", "SELL") and setup.get("valid"):
        z = setup["entry_zone"]
        how = "only inside the entry zone rather than at the current price" if decision == "BUY ON PULLBACK" \
            else "from the entry zone"
        parts.append(f"The plan therefore favours a {setup['side'].lower()} setup {how} ({z[0]:,.6g}-{z[1]:,.6g}), "
                     f"invalidated at {setup['stop']:,.6g}, with risk/reward 1:{setup['risk_reward']:.1f}.")
    elif decision == "NO TRADE":
        parts.append("Decision: no trade - " + (a.get("decision_reason") or "the evidence is insufficient") + ".")
    elif decision == "HOLD":
        parts.append("Decision: hold - the directional evidence is not strong enough for a new position.")
    return " ".join(parts)
