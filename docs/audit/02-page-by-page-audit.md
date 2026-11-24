# 02 · Page-by-page audit

## How it was tested

Automated browser sweep (Playwright, Chromium) of the UI preview (`frontend/dev`, sample data, no Firebase) — **156 page
loads**: every member route (incl. old redirect routes and a 404), every admin route, and the public pages, each as
**member, admin and signed-out visitor** at **1440 px (desktop), 820 px (tablet) and 390 px (phone)**. For each load: page
errors, console errors, horizontal overflow of the document, elements sticking out of the screen, and error-like text
("Something went wrong", "NaN", "undefined", "[object Object]"). Screenshots of desktop and phone kept for review.

Limits: the preview uses sample data, so the *numbers* are not checked here (live data is checked in reports 04-06). Live
WebSocket prices are mocked. Buttons that write to Firebase (save, post, trade) were not pressed.

## Result in one line

**No page crashed, no JavaScript error, no broken text on any page or role.** One layout bug on tablets, one route
conflict, one misleading "Data late" label; the rest are small.

## Findings

| ID | Page | What | Evidence |
|---|---|---|---|
| F-01 (P1) | every page, **tablet 768-1023 px** (iPad portrait, Galaxy Fold open) | The top navigation row is wider than the screen, so **the whole page scrolls sideways** by ~157 px (member) / ~327 px (admin). | Sweep: document `scrollWidth` 1147 px at 820 px width on all 32 member routes and 13 admin routes; screenshot of the nav row cut after "News". |
| F-07 (P2) | `/risk` | Two routes share `/risk`: the V3 **Risk page** and the **Risk disclosure** (Trust page). Signed-in members always get the Risk page; the footer link "Risk disclosure", the sign-in screen link and the WinsToday note open the Risk *page* instead of the legal disclosure. Members cannot reach the disclosure. | `App.tsx` lines 74 (TRUST map) and 412 (Risk route). |
| F-08 (P2) | Overview mood card, Risk page | **"Data late" shown while data is fine.** The risk state is re-published at most every 30 min when nothing changes (`risk_state.PUBLISH_EVERY_S` 1800), but the card calls it late after 20 min (`V3Home.tsx`). Owner saw "Data late · checked 26 min ago" today with the engine running normally. | Code + owner's screenshot (24 Nov 16:07). |
| F-09 (P3) | Results → Signal log (phone) | "Outcomes TP1 8 · TP2 4 · TP3 4 ·…" is cut off at 390 px. | Phone screenshot. |
| F-10 (P3) | Signals (phone) | Timeframe tabs: "3D" sits off-screen in the scroll row with no hint that the row scrolls. | Phone screenshot. |

## Page by page

| Page | Works | Information | Notes / recommendations |
|---|---|---|---|
| Overview | ✓ all roles, all widths (tablet: F-01) | Market mood + risk + breadth + coin spectrum, capital, positions, AI decisions, market today, board | Good hierarchy after V3. Missing: **engine/data freshness for members** in one place (only "Data fresh/late" of the risk state), and **open exposure by side** (how many longs vs shorts are running) — the record is almost all shorts (see 05). |
| AI Intelligence | ✓ | Galaxy, readout, signals in flight, universe, mission control, market heat, deep scan | Heavy page (34 KB + globe 33 KB + land map 65 KB, lazy). Fine. |
| Risk | ✓ | 12 checks, level, policy | F-07, F-08. Add "what changed since the last level" (history exists in `risk_state_log`). |
| Signals | ✓ | Card, why-this-signal, levels, grade, progress | Missing on the card: **"is the move already gone?"** (distance of price from the entry in R) is shown only as "inside / outside entry zone"; **which filters it passed** is not shown (exists in `analysis.flags`). |
| Trade | ✓ | Chart, book, order form, auto-trade, journal | Journal notes removed today on request. |
| Portfolio | ✓ | Capital, positions, protection, closed trades | Aligned today. |
| Results | ✓ | Record, bots, log, leaderboard | Sample-size note exists (< 30). **No confidence interval on the live record** (only the "tested on unseen data" table shows one); no split by **side** (long vs short) although the record is 96 % shorts. |
| Coins | ✓ | Board (table / heatmap) | Good. |
| Money flow | ✓ (browser streams) | River, whales, liquidation map, funding | Independent of the engine; works when Binance is reachable from the member's network. |
| Radar | ✓ | Scope, picks, scorecard | Good. |
| News | ✓ | Stream, mood, calendar, impact after release | Good. |
| Coin page | ✓ | Chart + tools, report, call, derivatives, passport | Missing: **BTC correlation** (exists on Command "Coin vs coin"), **model calibration for this coin** (exists in proof checks, admin only). |
| Community / Alerts / Settings | ✓ | — | Fine. |
| Health (admin) | ✓ | Engine, writes, reads, services, models, bots, safeguards | Missing: **engine uptime / gaps** (7 h gap on 23 Nov not visible on the page), **backup age**, **workflow failures**, **Gemini calls**. |
| Guardian, Lab, Hesper, Share kit, Users, Backtest, Replay (admin) | ✓ | — | Users loads member photos from Google (fails in the sandbox only). |
| Public: landing, record, about, terms, contact, risk | ✓ | — | Decorative glow shapes stick out of the screen but are clipped (no sideways scroll). |

## Visual consistency

V3 graphite + gold + cyan, IBM Plex Sans everywhere (canvases too), logo B+D with blinking neurons. No leftover
space visuals found on member pages except the AI Intelligence "galaxy / universe" naming (owner approved names in V3;
the visuals still use orbits — a design choice, not a bug).
