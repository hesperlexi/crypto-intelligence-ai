// FUTURES PAPER TRADING (manual, virtual USDT-margined perpetuals) stored in Firestore.
// Virtual money only; nothing is ever sent to an exchange.
//
// Isolated margin per position. Liquidation, stop-loss and take-profit are checked against every closed
// 15-minute candle since the last check (so they also trigger while the app was closed) and against the live
// price while it is open. When one candle touches both the stop and the target, the stop counts first.
// Funding is charged every 8 hours (00:00, 08:00, 16:00 UTC) at Binance's current rate for the coin.
import { addDoc, collection, doc, getDoc, onSnapshot, query, runTransaction, setDoc, where } from "firebase/firestore";
import { derivatives, klines, tickers } from "./binance";
import { db } from "./firebase";
import { latestPrices } from "./live";

const ACC = doc(db, "paper", "futures");
const TRADES = "paper_futures_trades";
export const FEE = 0.0005;             // 0.05% taker
export const MMR = 0.005;              // maintenance margin (conservative tier-1)
const ADVERSE = (2 + 0.5) / 1e4;       // slippage + half spread
const SLIP = 2 / 1e4;
const STEP = 900_000;
const FUNDING_MS = 8 * 3_600_000;
export const MAX_LEV = 50;

export const liqPrice = (entry: number, side: number, lev: number) =>
  side > 0 ? Math.max(0, entry * (1 - 1 / Math.max(1, lev) + MMR)) : entry * (1 + 1 / Math.max(1, lev) - MMR);

const keyOf = (s: string) => s.replace("/", "");
/** Position key: one position per coin in one-way mode, one per coin AND side in hedge mode. */
export const posKey = (symbol: string, side: number, hedge: boolean) => (hedge ? `${keyOf(symbol)}_${side > 0 ? "LONG" : "SHORT"}` : keyOf(symbol));
export type PositionMode = "oneway" | "hedge";

async function price(symbol: string): Promise<number> {
  if (latestPrices[symbol]) return latestPrices[symbol];
  const t = await tickers([symbol]);
  if (!t[symbol]?.last) throw new Error(`no market price available for ${symbol}`);
  latestPrices[symbol] = t[symbol].last;
  return t[symbol].last;
}

export async function reset(startingBalance = 10000) {
  if (!(startingBalance > 0)) throw new Error("starting balance must be positive");
  const acc = { id: Math.random().toString(36).slice(2, 12), starting_balance: startingBalance, wallet: startingBalance, created_at: Date.now(),
    positions: {}, position_mode: "oneway", totals: { realized: 0, fees: 0, funding: 0, count: 0, wins: 0, liquidations: 0 } };
  await setDoc(ACC, acc);
  return acc;
}

async function log(trade: any) {
  await addDoc(collection(db, TRADES), { ...trade, created_at: trade.created_at ?? Date.now(), mode: "PAPER FUTURES" });
}

export interface OpenOrder { symbol: string; side: 1 | -1; margin: number; leverage: number; stop?: number | null; take?: number | null }

/** One-way: a coin holds either a long or a short. Hedge: a long and a short can be open on the same coin at once. */
export async function setMode(mode: PositionMode) {
  if (!(await getDoc(ACC)).exists()) await reset();
  await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC)).data();
    if (mode === "oneway") {
      const sides: Record<string, Set<number>> = {};
      for (const p of Object.values<any>(acc.positions ?? {})) (sides[p.symbol] ??= new Set()).add(p.side);
      const both = Object.entries(sides).filter(([, v]) => v.size > 1).map(([k]) => k);
      if (both.length) throw new Error(`close one side of ${both.join(", ")} first: one-way mode allows only one direction per coin`);
    }
    tx.update(ACC, { position_mode: mode });
  });
}

export async function open(o: OpenOrder) {
  const lev = Math.round(Number(o.leverage));
  if (!(lev >= 1 && lev <= MAX_LEV)) throw new Error(`leverage must be between 1x and ${MAX_LEV}x`);
  if (!(o.margin > 0)) throw new Error("enter a positive margin amount");
  if (!(await getDoc(ACC)).exists()) await reset();
  const mark = await price(o.symbol);
  const fill = mark * (1 + o.side * ADVERSE);
  const qty = (o.margin * lev) / fill;
  const fee = qty * fill * FEE;
  const stop = o.stop || null, take = o.take || null;
  if (stop && o.side * (fill - stop) <= 0) throw new Error(`the stop-loss must be ${o.side > 0 ? "below" : "above"} the entry price`);
  if (take && o.side * (take - fill) <= 0) throw new Error(`the take-profit must be ${o.side > 0 ? "above" : "below"} the entry price`);
  const res = await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC)).data();
    if (o.margin + fee > acc.wallet + 1e-9) throw new Error(`not enough virtual balance: need $${(o.margin + fee).toFixed(2)}, have $${acc.wallet.toFixed(2)}`);
    const positions = { ...(acc.positions ?? {}) };
    const hedge = acc.position_mode === "hedge";
    const now = Date.now();
    if (!hedge) {
      const opposite = Object.values<any>(positions).find((p) => p.symbol === o.symbol && p.side !== o.side);
      if (opposite) throw new Error(`you have a ${opposite.side > 0 ? "LONG" : "SHORT"} ${o.symbol} position. Close it first, or switch to Hedge mode to hold both sides.`);
    }
    // same coin and side: add to the existing position (it may sit under the other mode's key)
    const key = Object.keys(positions).find((k) => positions[k].symbol === o.symbol && positions[k].side === o.side) ?? posKey(o.symbol, o.side, hedge);
    const cur = positions[key];
    let pos: any;
    if (cur) {   // add to the position: average entry, combined margin, effective leverage
      const q = cur.qty + qty;
      const entry = (cur.entry * cur.qty + fill * qty) / q;
      const margin = cur.margin + o.margin;
      const effLev = (q * entry) / margin;
      pos = { ...cur, qty: q, entry, margin, leverage: effLev, liq: liqPrice(entry, o.side, effLev), fees: cur.fees + fee,
        stop: stop ?? cur.stop ?? null, take: take ?? cur.take ?? null };
    } else {
      pos = { key, symbol: o.symbol, side: o.side, qty, entry: fill, margin: o.margin, leverage: lev, liq: liqPrice(fill, o.side, lev),
        stop, take, opened_at: now, checked_at: now, funded_until: now, funding: 0, fees: fee };
    }
    positions[key] = { ...pos, key };
    const t = acc.totals;
    tx.update(ACC, { wallet: acc.wallet - o.margin - fee, positions, totals: { ...t, fees: t.fees + fee } });
    return { account_id: acc.id, pos, hedge };
  });
  await log({ account_id: res.account_id, type: "OPEN", symbol: o.symbol, side: o.side, qty, price: fill, mark_price: mark,
    leverage: lev, margin: o.margin, fee, liquidation_price: res.pos.liq, stop, take, hedge: res.hedge });
  return res.pos;
}

/** Close all or part of a position. `at` is a trigger level (stop / target / liquidation); otherwise the live price. */
export async function close(key: string, fraction = 1, reason = "manual", at?: number, when?: number) {
  const snap: any = (await getDoc(ACC)).data();
  const symbol: string | undefined = snap?.positions?.[key]?.symbol;
  if (!symbol) return null;
  const mark = at ?? (await price(symbol));
  const res = await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC)).data();
    const pos = acc?.positions?.[key];
    if (!pos) return null;                                    // already closed (e.g. by another check)
    const f = Math.min(1, Math.max(0, fraction));
    const q = pos.qty * f;
    const marginPart = pos.margin * f;
    let fill: number, fee: number, pnl: number, back: number;
    if (reason === "liquidated") {
      fill = pos.liq; fee = 0; pnl = -marginPart; back = 0;   // isolated margin: the margin is lost
    } else {
      fill = at != null ? mark * (1 - pos.side * SLIP) : mark * (1 - pos.side * ADVERSE);
      fee = q * fill * FEE;
      const gross = pos.side * q * (fill - pos.entry);
      back = Math.max(0, marginPart + gross) - fee;
      pnl = back - marginPart;
    }
    const openFee = (pos.fees ?? 0) * f;                       // the opening fee belongs to this trade's result
    pnl -= openFee;
    const positions = { ...acc.positions };
    if (f >= 1 - 1e-9) delete positions[key];
    else positions[key] = { ...pos, qty: pos.qty - q, margin: pos.margin - marginPart, fees: (pos.fees ?? 0) - openFee };
    const t = acc.totals;
    const closingPnl = pnl;
    tx.update(ACC, { wallet: acc.wallet + back, positions, totals: { ...t, realized: t.realized + closingPnl, fees: t.fees + fee,
      count: t.count + 1, wins: t.wins + (closingPnl > 0 ? 1 : 0), liquidations: t.liquidations + (reason === "liquidated" ? 1 : 0) } });
    return { account_id: acc.id, pos, q, fill, fee, pnl: closingPnl, marginPart };
  });
  if (!res) return null;
  await log({ account_id: res.account_id, type: "CLOSE", reason, symbol, side: res.pos.side, qty: res.q, price: res.fill, entry: res.pos.entry,
    leverage: res.pos.leverage, margin: res.marginPart, fee: res.fee, realized_pnl: res.pnl, roe_pct: (res.pnl / res.marginPart) * 100,
    funding: res.pos.funding * fraction, opened_at: res.pos.opened_at, created_at: when ?? Date.now() });
  return res;
}

export async function setOrders(key: string, stop: number | null, take: number | null) {
  await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC)).data();
    const pos = acc?.positions?.[key];
    if (!pos) throw new Error("no open position");
    if (stop && pos.side * (pos.entry - stop) <= 0 && pos.side * ((latestPrices[pos.symbol] ?? pos.entry) - stop) <= 0) throw new Error("the stop would trigger immediately");
    tx.update(ACC, { positions: { ...acc.positions, [key]: { ...pos, stop: stop || null, take: take || null } } });
  });
}

/** Trigger check for one candle (or the live price as a zero-range candle). Order: liquidation, stop, target. */
function trigger(pos: any, op: number, hi: number, lo: number): { reason: string; at: number } | null {
  const s = pos.side;
  const liqHit = s > 0 ? lo <= pos.liq : hi >= pos.liq;
  const stopHit = pos.stop != null && (s > 0 ? lo <= pos.stop : hi >= pos.stop);
  const stopProtects = pos.stop != null && s * (pos.stop - pos.liq) > 0 && s * (op - pos.stop) > 0;
  if (liqHit && !stopProtects) return { reason: "liquidated", at: pos.liq };
  if (stopHit) return { reason: "stop-loss", at: s > 0 ? Math.min(op, pos.stop) : Math.max(op, pos.stop) };
  if (pos.take != null && (s > 0 ? hi >= pos.take : lo <= pos.take)) return { reason: "take-profit", at: s > 0 ? Math.max(op, pos.take) : Math.min(op, pos.take) };
  return null;
}

let settling = false;
/** Funding + liquidation / stop / target checks for every open position. Safe to call often. */
export async function settle() {
  if (settling) return;
  settling = true;
  try {
    const acc: any = (await getDoc(ACC)).data();
    if (!acc) return;
    const now = Date.now();
    for (const [posK, pos] of Object.entries<any>(acc.positions ?? {})) {
      // 1) funding payments since the last one
      const first = Math.floor(pos.funded_until / FUNDING_MS) * FUNDING_MS + FUNDING_MS;
      const n = first <= now ? Math.floor((now - first) / FUNDING_MS) + 1 : 0;
      if (n > 0) {
        let rate = 0.0001;
        try { const d = await derivatives(pos.symbol); if (d.available && Number.isFinite(d.funding?.rate)) rate = d.funding.rate; } catch { /* default */ }
        const px = latestPrices[pos.symbol] ?? pos.entry;
        const amount = n * pos.side * pos.qty * px * rate;
        const key = posK;
        await runTransaction(db, async (tx) => {
          const a: any = (await tx.get(ACC)).data();
          const p = a?.positions?.[key];
          if (!p || p.opened_at !== pos.opened_at || p.funded_until !== pos.funded_until) return;
          // funding comes out of the position's margin (isolated), which moves the liquidation price
          const margin = p.margin - amount;
          const lev = (p.qty * p.entry) / Math.max(margin, 1e-9);
          tx.update(ACC, { positions: { ...a.positions, [key]: { ...p, margin, leverage: lev, liq: liqPrice(p.entry, p.side, lev),
            funding: (p.funding ?? 0) + amount, funded_until: first + (n - 1) * FUNDING_MS } },
            totals: { ...a.totals, funding: (a.totals.funding ?? 0) + amount, realized: a.totals.realized - amount } });
        });
      }
      // 2) closed 15m candles since the last check, then the live price
      let hit: { reason: string; at: number; ts: number } | null = null;
      if (now - pos.checked_at > STEP) {
        try {
          const need = Math.min(1000, Math.ceil((now - pos.checked_at) / STEP) + 2);
          for (const c of await klines(pos.symbol, "15m", need)) {
            if (c[0] < pos.checked_at - (pos.checked_at % STEP) || c[0] + STEP > now) continue;
            const t = trigger(pos, c[1], c[2], c[3]);
            if (t) { hit = { ...t, ts: c[0] + STEP }; break; }
          }
        } catch { /* try again next time */ }
      }
      if (!hit) {
        const px = latestPrices[pos.symbol];
        const t = px ? trigger(pos, px, px, px) : null;
        if (t) hit = { ...t, at: t.reason === "liquidated" ? pos.liq : px, ts: now };
      }
      if (hit) await close(posK, 1, hit.reason, hit.at, hit.ts);
      else if (now - pos.checked_at > STEP) {
        const key = posK;
        await runTransaction(db, async (tx) => {
          const a: any = (await tx.get(ACC)).data();
          const p = a?.positions?.[key];
          if (p && p.opened_at === pos.opened_at) tx.update(ACC, { positions: { ...a.positions, [key]: { ...p, checked_at: now - (now % STEP) } } });
        });
      }
    }
  } finally {
    settling = false;
  }
}

/** Live account view: wallet, margin in use, unrealized P&L at the live price, history. */
export function subscribe(cb: (s: any) => void, err: (e: Error) => void) {
  let trades: any[] = [];
  let unsubTrades = () => {};
  let currentId = "";
  let lastAcc: any = null;
  const build = (acc: any) => {
    if (!acc) { reset().catch(err); return; }
    const positions = Object.entries<any>(acc.positions ?? {}).map(([key, p0]) => {
      const p = { ...p0, key };
      const mark = latestPrices[p.symbol] ?? null;
      const upnl = mark != null ? p.side * p.qty * (mark - p.entry) : null;
      return { ...p, mark, upnl, roe_pct: upnl != null ? (upnl / p.margin) * 100 : null, notional: mark != null ? p.qty * mark : p.qty * p.entry };
    });
    const bySym: Record<string, any[]> = {};
    for (const p of positions) (bySym[p.symbol] ??= []).push(p);
    const hedges = Object.entries(bySym).filter(([, ps]) => ps.length > 1).map(([symbol, ps]) => {
      const long = ps.filter((p) => p.side > 0).reduce((a, p) => a + p.notional, 0);
      const short = ps.filter((p) => p.side < 0).reduce((a, p) => a + p.notional, 0);
      const pnl = ps.reduce((a, p) => a + (p.upnl ?? 0), 0);
      return { symbol, long, short, net: long - short, pnl, margin: ps.reduce((a, p) => a + p.margin, 0) };
    });
    const marginUsed = positions.reduce((s, p) => s + p.margin, 0);
    const upnl = positions.reduce((s, p) => s + (p.upnl ?? 0), 0);
    const equity = acc.wallet + positions.reduce((s, p) => s + Math.max(0, p.margin + (p.upnl ?? 0)), 0);
    const closes = trades.filter((t) => t.type === "CLOSE");
    cb({
      account: acc, mode: acc.position_mode === "hedge" ? "hedge" : "oneway", hedges, wallet: acc.wallet, margin_used: marginUsed, unrealized_pnl: upnl, equity,
      return_pct: (equity / acc.starting_balance - 1) * 100, positions, trades,
      realized_pnl: acc.totals?.realized ?? 0, fees: acc.totals?.fees ?? 0, funding: acc.totals?.funding ?? 0,
      liquidations: acc.totals?.liquidations ?? 0, closed: closes.length,
      win_rate: closes.length ? closes.filter((t) => t.realized_pnl > 0).length / closes.length : null,
      exposure: positions.reduce((s, p) => s + p.notional, 0),
    });
  };
  const unsubAcc = onSnapshot(ACC, (s) => {
    lastAcc = s.data() ?? null;
    if (lastAcc && lastAcc.id !== currentId) {
      currentId = lastAcc.id;
      unsubTrades();
      unsubTrades = onSnapshot(query(collection(db, TRADES), where("account_id", "==", currentId)), (q) => {
        trades = q.docs.map((d) => ({ id: d.id, ...d.data() })).sort((a: any, b: any) => b.created_at - a.created_at).slice(0, 300);
        build(lastAcc);
      }, err);
    }
    build(lastAcc);
  }, err);
  settle().catch(() => {});
  const timer = window.setInterval(() => { if (!document.hidden) { settle().catch(() => {}); if (lastAcc) build(lastAcc); } }, 15_000);
  return () => { unsubAcc(); unsubTrades(); window.clearInterval(timer); };
}
