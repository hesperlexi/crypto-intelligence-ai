Use the app as a second opinion and a practice ground: let it find setups, check them yourself, test them with virtual money, and trust only what its own track record proves. It never places real orders.

## 1. Getting started

**Open the app.** Go to **crypapp-6a9b9.web.app** and press **Sign in with Google**.

**Install it** so it opens like a normal app and can send notifications:

1. **Android, as an APK:** open **Settings → Android app** and tap **Download APK**. Open the file and allow "Install unknown apps" for your browser when Android asks.
2. **Android or desktop, from Chrome:** open the site, then menu → **Install app** (or **Add to Home screen**).
3. **iPhone or iPad:** open the site in **Safari**, tap **Share → Add to Home Screen**, and always open it from that icon. On iOS, notifications only work this way.

**Access.** New accounts see a "waiting for approval" screen until the app owner approves them on the **Users** page. After approval you are in immediately.

**Members vs. admin.** Members see every prediction, Futures, Accuracy and the demo bots, can run backtests and replays, and get their own paper accounts, alerts and notifications. Only the app owner (admin) can change the coin list, bots, engine settings and users.

## 2. Your first 10 minutes: setup checklist

Do these once and the app works for you in the background.

- ☐ **Install the app** on your phone (section 1).
- ☐ **Look at your coins:** the **My coins** card on the Dashboard shows the coins the engine follows. The admin can search any coin there (e.g. PEPE), add it and pin favourites; a new coin gets full predictions after the next engine run (about 15 minutes).
- ☐ **Turn on notifications:** **Settings → Notifications → Turn on notifications**, then press **Send a test notification**. The test comes on the engine's next run (within about 15 minutes).
- ☐ **Choose a look:** **Settings → Appearance**. Gold is the default; there are other themes and layouts, and a compact density for small screens.
- ☐ **Set up a paper account:** open **Paper**, type a **Starting balance** close to what you would really trade (e.g. 1,000 USDT) and press **Reset account**.
- ☐ **Create one alert** for your favourite coin (section 6), so the app tells you when a setup appears.
- ☐ **Open Accuracy** and note today's hit rates. This is your baseline for deciding how much to trust the models (section 9).

## 3. How to read a coin's prediction

Tap any coin to open its page. Read it top to bottom in this order:

1. **Decision: BUY, BUY ON PULLBACK, SELL or HOLD.** BUY ON PULLBACK means the direction is up but the price is stretched, so wait for the entry in the trade plan instead of chasing. HOLD means no edge worth trading. Most of the time HOLD is the right answer, and doing nothing is fine.
2. **Confidence / probability up.** The chance the models give that the price is higher at the end of the horizon. 50% is a coin flip. Around 55–60% is a real lean for crypto; anything that claims 80%+ should make you more careful, not less.
3. **Confident calls.** The Accuracy page shows the confidence level above which the model has historically been right more often (the *Confident calls* card). Above it is a confident call, worth acting on; below it, treat the call as a lean only.
4. **Expected move / edge.** How big the move is expected to be. A 55% call with a tiny expected move is often not worth fees and slippage.
5. **Trade setup: entry, stop loss, targets.** Built from recent volatility (ATR) and support/resistance; tap **Trade plan** above the chart to draw it. Always use the stop loss. "No valid setup" means the reward is too small for the risk.
6. **Multi-timeframe card.** Shows each timeframe's view and an *alignment* score. The strongest setups are when timeframes agree. The 1H and 4H models have the better track record; give the daily call less weight.
7. **Model consensus and "Why this signal?".** Each model (gradient boosting, LSTM, GRU, Transformer) votes, and the explanation card lists the reasons. Agreement between very different models is a better sign than one model being very sure.

> **Rule of thumb:** act only when the decision is a confident call, at least two timeframes agree, and the reward to the take profit is at least 1.5× the risk to the stop loss.

## 4. A daily routine that gets the most out of it

About 10 minutes a day is enough. Prices update every few seconds and predictions refresh regularly, so you do not need to watch constantly.

| When | Where | What to do |
| --- | --- | --- |
| Morning (5 min) | **Dashboard** | Scan your coins for BUY/SELL calls. Ignore HOLDs. |
| Morning | **Coin page** | For each candidate, check timeframe agreement and the trade plan (section 3). |
| Morning | **Futures** | Check funding and the long/short ratio before going against the crowd (section 5). |
| When notified | **Alerts** | Open the alert, re-check the coin page, then place the trade on paper first. |
| Evening (3 min) | **Paper** | Review open positions; move stops only in your favour. |
| Weekly (10 min) | **Accuracy**, **Bots** | Compare models and bots over the last week and month. Keep what works. |

> **Golden rule:** a new strategy runs on paper for at least 2–4 weeks and 30+ trades before you even think about real money.

## 5. Futures: long, short and leverage

The **Futures** page turns the same predictions into perpetual-futures calls for every coin. Each coin card shows:

- **Action:** LONG, LONG ON PULLBACK, SHORT or NO TRADE. *Lean* shows which way the models tilt even when there is no trade.
- **Suggested leverage and liquidation price** for the setup's stop. The liquidation price must always be further away than your stop.
- **Funding 8h:** positive funding means longs pay shorts every 8 hours. High positive funding plus a crowded long ratio often comes before a drop; the opposite before a squeeze up.
- **OI 24h (open interest)** and **longs/shorts:** rising OI with rising price confirms a move; rising OI with falling price means new shorts are piling in.

Use the filter buttons to show only longs or shorts, and tap a card's paper button to open the setup straight in futures paper trading.

**Leverage & liquidation calculator** (bottom of the page). Enter entry, stop, leverage, balance and risk per trade. It gives the position size, margin, loss at the stop and the **max safe leverage**. If it says *liquidation BEFORE your stop*, lower the leverage.

**Futures rules that keep you alive:**

1. Size the position from the stop and your risk (1–2% of the account per trade), never from the leverage.
2. Stay at or below the suggested leverage; 2–5× is plenty for crypto.
3. Skip trades where funding is strongly against you, unless you will hold only a few hours.

## 6. Alerts and phone notifications

Alerts let the app watch the market for you. Open **Alerts → New alert**:

1. **Condition:** choose **Trade setup** (the most useful), or a price or indicator condition.
2. **Coin** and **Timeframe** (1H or 4H are the best balance of speed and accuracy).
3. **Direction:** long or short, long only, or short only.
4. **Market:** Spot, or Futures (adds suggested leverage and liquidation to the message).
5. **Minimum confidence** (optional, e.g. 55) and tick **Confident calls only** for fewer, better alerts.
6. **Cooldown:** minutes before the same alert can fire again (e.g. 240 for 4H).
7. Press **Create alert**.

When it fires, you get a notification with the side, entry, stop loss, take profit and confidence, and it is listed under **Fired alerts**. The engine checks every 15 minutes, so allow a few minutes of delay and check the price before entering.

**Notifications on your phone:** **Settings → Notifications → Turn on notifications**, allow them when asked, then **Send a test notification**. On iPhone, open the app from the Home Screen icon first. *(App owner, one time only: Firebase console → Project settings → Cloud Messaging → Web Push certificates → Generate key pair, then paste the key in Settings → Notifications. Without it, notifications arrive only while the app is open in the background.)*

## 7. Paper trading: practise with virtual money

Open **Paper** and choose the **Spot** or **Futures** tab. Every account is yours alone; nothing touches a real exchange.

**Spot:** pick a coin, enter an amount in USDT and press **Virtual BUY** or **Virtual SELL**. Positions show live profit and loss; **Sell all** closes one. Fees and slippage are included so results are realistic.

**Futures:**

1. Choose the coin, **Long** or **Short**, the **Margin (USDT)** and the **leverage**.
2. Fill in **Stop-loss** and **Take-profit**. They are optional, but always set them; the app warns you if your stop is beyond the liquidation price.
3. Open the position. Stop loss, take profit, liquidation and funding are applied automatically.
4. Manage it from the position card: **Close ½** to bank half the profit, or **Close**.

**Hedge mode.** At the top of the futures account, switch **One-way** to **Hedge** to hold a long and a short on the same coin at once, e.g. to protect a long during an expected dip without closing it. In one-way mode, opening the opposite side is blocked until you close the first.

**How to practise properly:** take only trades you would really take, at the real size; write down why you took each one and compare after 30 trades; reset the account only when you change strategy.

## 8. Demo bots: proof of whether the predictions work

The **Bots** page runs automatic demo traders with virtual money around the clock, so you can see what following the app would really have earned.

- **Signal bots** trade only the final decisions (BUY, BUY ON PULLBACK, SELL) using the trade plan's entry, stop and three targets, taking a third off at each target.
- **Prediction trackers** take every raw model call for one bar, showing how good the raw predictions are.
- **Futures bots** trade the same calls as perpetual futures with leverage, liquidation and funding.

**How to judge a bot:**

1. Wait for **at least 30 closed trades**. Fewer than that is mostly luck.
2. Compare the **Bot equity** line with the dashed **Buy & hold** line. A bot that loses to simply holding adds no value.
3. Look at the **win rate after costs**, **profit factor** (above 1.2 is good) and **max drawdown** (could you live with that drop on real money?).
4. Compare spot vs futures and confident-only vs all calls; follow the style that wins over months, not days.

## 9. When to trust the models: the Accuracy page

The **Accuracy** page is the app's honest report card. Every number on it is *out-of-sample*: measured on data the model had never seen, using walk-forward testing. Look at, in order:

1. **The verdict** for the coin and timeframe: does the model beat a naive guess, and is the p-value below 0.05 (edge unlikely to be luck)?
2. **Directional accuracy:** for crypto, **51–56% is realistic and useful**; nobody gets 70% consistently.
3. **Confident calls:** accuracy on the calls above the confidence threshold, usually a couple of points better.
4. **Calibration:** when the model says 60%, is it right about 60% of the time?
5. **Model comparison:** which model is best for this coin.
6. **Live predictions:** calls made in real time and scored after the outcome — the most honest check of all.
7. **Model drift:** "Drift detected" means the market changed and recent accuracy fell. Be more careful.

> **Practical rule:** trade a coin and timeframe only when its out-of-sample accuracy is above 52%, its confident calls are better still, and live predictions agree.

## 10. Backtest and Replay: test ideas on the past

**Backtest** runs a strategy over past data with fees and slippage. Choose the coin, timeframe, period and strategy under **Inputs** and run it. Read the verdict (*Beats buy & hold* or not), net return, win rate, profit factor, Sharpe and max drawdown. A strategy that only wins before costs does not win.

**Replay** is the best way to build trust. Under **Choose a moment**, pick a coin and a past date and time. The app shows exactly what it knew and forecast then, without future data (the **Look-ahead audit** proves it). Decide what you would have done, then press **Reveal what happened next**. Do 10–20 replays across calm, rising and falling markets.

## 11. For the app owner (admin)

| Task | Where | How often |
| --- | --- | --- |
| Approve or remove people | **Users** | When someone asks |
| Add, remove or pin coins | Dashboard **My coins**, or **Scanner → Watchlist** | When interests change |
| Create, edit, pause or reset bots | **Bots** | Monthly review |
| Retrain models | **Accuracy → Train all**, or **Retrain** on a coin page | After drift or big market changes |
| Risk profile | **Settings → Risk profile** | Once |
| Signal scoring weights | **Settings → Signal scoring weights → Fit weights** | Every few months |
| Check the engine | **Health** | If data looks stale |

## 12. Rules for getting the most out of it

1. **Let the app find setups; you make the decision.** A second opinion, not an autopilot.
2. **Prefer confident calls with timeframe agreement.** Fewer trades, better trades.
3. **Always use the stop loss** from the trade setup, and never move it further away.
4. **Risk 1–2% of your account per trade.** Size from the stop, not from leverage.
5. **Respect HOLD and NO TRADE.** Not trading is a position.
6. **Prove it on paper first:** 30+ trades and 2–4 weeks before risking real money.
7. **Check the bots and Accuracy weekly** and follow what the numbers say, not what you hope.
8. **Watch funding and the long/short ratio on futures;** avoid joining a crowded side.
9. **Be extra careful around big news:** models trained on normal markets can be wrong in sudden shocks.
10. **Expect losing streaks.** At 55% accuracy, five losses in a row will happen regularly.

## 13. Troubleshooting

| Problem | Fix |
| --- | --- |
| "Waiting for approval" after sign-in | The app owner must press **Approve** on the Users page. |
| Header shows **RECONNECTING** instead of **LIVE** | It reconnects on its own within seconds. If it stays, check your internet, then reload. |
| "Insufficient data" or no forecast | New coins need the next engine run (about 15 minutes) and enough history. |
| The app looks old after an update | Close and reopen the app, or **Settings → About → Check for updates**. The version is shown at the bottom. |
| The home-screen icon did not change | Phones cache icons; remove and re-add the app, or reinstall the newest APK. |
| APK says "App not installed" | Uninstall the older copy first, then install the new APK. |
| No notifications when the app is closed | Allow notifications for the app in phone settings and make sure battery saver is not blocking it. On iPhone, open the app from the Home Screen icon. |
| Alerts arrive late | The engine runs every 15 minutes; this is expected. |
| Futures order refused: "opposite position" | Switch to **Hedge** mode, or close the other side first. |

> **Important:** the app is for analysis and practice. It is not financial advice, all trading in it uses virtual money, and past accuracy does not guarantee future results.
