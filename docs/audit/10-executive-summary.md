# 10 · Executive summary

Crypto Intelligence AI audit, 24 Nov 2026, read-only. Code `96fc3f9`.

## Overall health: **good, with a thin edge**

The platform works. Every page loaded for every role at desktop, tablet and phone size with **no errors**, the engine trains
every night, tests and Firestore rules pass on every push, the backup restores, costs are counted the same way everywhere,
and **no bug that loses money or bends the record was found**. The weak points are (1) the engine was offline for 7 hours on
23 Nov and almost 3 hours on 24 Nov, (2) one risk check fails open for members' auto-trade, (3) a tablet layout bug, and
(4) the trading edge itself: strong live results so far, but from one falling market and mostly shorts; on unseen history the
edge is small.

## Answers to the 20 questions

1. **Is the whole application working?** Yes, with the exceptions below. 156 page loads, 0 errors.
2. **Fully functional pages:** all of them on desktop and phone.
3. **Need improvement:** every page on tablets (sideways scroll, F-01); Risk (disclosure route clash F-07, false "Data late" F-08); Health (no uptime / backup age); README is outdated.
4. **Buttons, filters, integrations:** tabs, filters, search, redirects and share buttons work in the preview. Firebase writes and Telegram posts were not pressed in this audit; the last 5 Telegram post jobs all succeeded.
5. **Are all ML models used as intended?** Yes: every add-on is on only where its own out-of-sample test passed. But only Random Forest clearly beats the base rate; weaker models still hold ~60 % of the ensemble weight (F-12).
6. **Trained and evaluated correctly?** Yes: nightly, walk-forward, calibrated, champion / challenger on (7 of 383 retrains refused). 15m models can be up to 4.4 days old (F-11). No bundle passes the strict "edge confirmed" test (F-13).
7. **Market data accurate and fresh?** Yes when the engine runs (views 5 min old for 15m-4h). Fail-closed on stale data and calendar.
8. **Decisions follow the intended pipeline?** Yes. One implementation of the exit rules; same costs and liquidation formula on the site and in the engine.
9. **Filters blocking profitable trades?** In the last 10 days the same-side cap (+38R), the AI trade filter (+30R) and the volume wall (+9R) blocked mostly winners; grade A only, the fee filter and the bigger-trend check saved −25R. The sample is all shorts in a falling market — needs a replay before any change (F-14).
10. **Bugs or thresholds hurting results?** No bug found. The thresholds above are the candidates.
11. **Unnecessary work slowing things down?** The engine round (201 s of a 240 s cycle) is getting tight (F-29); PyTorch is installed every run for 13 bundles (F-20); Firebase is the heaviest part of the first page load.
12. **Missing market intelligence?** ETF and exchange flows (no free, honest source); order-flow features are being recorded and can be tested in December.
13. **Pages missing helpful information?** Long / short exposure, "has the move already gone?", what the filters held back, a confidence range on the live record, a side split on Results.
14. **Infrastructure used efficiently?** Yes: 2.5 k of 20 k Firestore writes, 1.5 k of 50 k reads by 12:30 UTC; edge views on free Cloudflare.
15. **Top 10 improvements:** (1) fix auto-trade on stale risk (F-02) · (2) prove engine uptime and show it (F-03) · (3) tablet layout (F-01) · (4) replay the three filters that blocked winners (F-14) · (5) 15m models fresher (F-11) · (6) disclosure route (F-07) · (7) "Data late" label (F-08) · (8) engine round time (F-29) · (9) long / short exposure meter · (10) "move already gone?" on the card.
16. **Free improvements:** all of the above; nothing in this plan needs a paid service.
17. **Fix immediately:** F-02, F-01, F-08, F-07 (Stage 1 in 09).
18. **Develop next:** the filter replays (Stage 3), then the member information items (Stage 4).
19. **Do not change:** the record rules (honest entry, net of costs, nothing hidden), the time limits (re-tested today: keep), the exit rules (no alternative passed), the costs rule, grade-A-only, the fee filter, the bigger-trend check, the BTC shock guard, the edge-only add-on switches, the Firestore pacing.
20. **Overall health:** **7.5 / 10.** Solid, honest and well tested; the main risk is market-regime concentration and a small proven edge, not code.

Reports: `01`-`09` in this folder. Every figure comes from a file named in the report; anything not checked is marked
"unverified".
