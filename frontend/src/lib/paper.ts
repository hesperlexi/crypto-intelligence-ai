// PAPER TRADING (manual virtual orders) stored in Firestore. Virtual money only; no order ever reaches an exchange.
import { addDoc, collection, doc, getDoc, getDocs, onSnapshot, query, runTransaction, setDoc, where } from "firebase/firestore";
import { klines, tickers } from "./binance";
import { visibleInterval } from "./visibleInterval";
import { db } from "./firebase";
import { latestPrices } from "./live";
import { isAdmin, myUid } from "./session";
import { byNewest } from "./format";

const ACC_REF = () => doc(db, "paper", `${myUid()}_spot`);   // one account per user
let migrated = false;
/** Accounts made before member accounts existed (paper/current) move to the owner's own document once. */
async function adoptLegacy() {
  if (migrated || !isAdmin()) return;
  migrated = true;
  try {
    if ((await getDoc(ACC_REF())).exists()) return;
    const old = await getDoc(doc(db, "paper", "current"));
    if (old.exists()) await setDoc(ACC_REF(), old.data()!);
  } catch { /* ignore */ }
}
export interface Costs { fee_rate: number; slippage_bps: number; spread_bps: number }
const DEFAULT_COSTS: Costs = { fee_rate: 0.001, slippage_bps: 2, spread_bps: 1 };

async function price(symbol: string): Promise<number> {
  if (latestPrices[symbol]) return latestPrices[symbol];
  const t = await tickers([symbol]);
  if (!t[symbol]?.last) throw new Error(`no market price available for ${symbol}`);
  latestPrices[symbol] = t[symbol].last;
  return t[symbol].last;
}

export async function reset(startingBalance = 10000) {
  if (!(startingBalance > 0)) throw new Error("starting balance must be positive");
  let bench: number | null = null;
  try { bench = await price("BTC/USDT"); } catch { bench = null; }
  const acc = { id: Math.random().toString(36).slice(2, 12), starting_balance: startingBalance, cash: startingBalance, created_at: Date.now(),
    benchmark_symbol: "BTC/USDT", benchmark_price: bench, positions: {}, totals: { realized: 0, fees: 0, slippage: 0, count: 0 } };
  await setDoc(ACC_REF(), acc);
  return acc;
}

export async function order(symbol: string, side: string, qty: number | null | undefined, notional: number | null | undefined, costs: Costs = DEFAULT_COSTS) {
  side = side.toUpperCase();
  if (side !== "BUY" && side !== "SELL") throw new Error("side must be BUY or SELL");
  await adoptLegacy();
  if (!(await getDoc(ACC_REF())).exists()) await reset();
  const mark = await price(symbol);
  const adverse = (costs.slippage_bps + costs.spread_bps / 2) / 1e4;
  const fill = side === "BUY" ? mark * (1 + adverse) : mark * (1 - adverse);
  const key = symbol.replace("/", "");
  const trade = await runTransaction(db, async (tx) => {
    const snap = await tx.get(ACC_REF());
    const acc: any = snap.data();
    const pos = acc.positions?.[key];
    const held = pos?.qty ?? 0;
    let q = qty ?? (notional != null ? notional / fill : NaN);
    if (!(q > 0)) throw new Error("give a positive quantity or amount");
    if (side === "SELL" && q > held * (1 + 1e-9)) throw new Error(`cannot sell ${q.toPrecision(6)}; position is ${held.toPrecision(6)}`);
    // testing period (v2.4): at most 5 coins held at a time in the spot practice account
    if (side === "BUY" && !held && Object.values<any>(acc.positions ?? {}).filter((p) => (p?.qty ?? 0) > 0).length >= 5)
      throw new Error("during the testing period you can hold up to 5 coins at a time; sell one first");
    if (side === "SELL") q = Math.min(q, held);
    const fee = q * fill * costs.fee_rate;
    const slip = q * Math.abs(fill - mark);
    let realized = 0;
    const positions = { ...(acc.positions ?? {}) };
    if (side === "BUY") {
      const cost = q * fill + fee;
      if (cost > acc.cash + 1e-9) throw new Error(`insufficient virtual cash: need ${cost.toFixed(2)}, have ${acc.cash.toFixed(2)}`);
      const nq = held + q;
      positions[key] = { ...(pos ?? {}), symbol, qty: nq, avg_price: ((pos ? pos.avg_price * held : 0) + q * fill) / nq, opened_at: pos?.opened_at ?? Date.now(), fees: (pos?.fees ?? 0) + fee };
      acc.cash -= cost;
    } else {
      realized = q * (fill - pos.avg_price) - fee;
      const nq = held - q;
      if (nq <= 1e-12) delete positions[key]; else positions[key] = { ...pos, qty: nq };
      acc.cash += q * fill - fee;
    }
    const totals = acc.totals ?? { realized: 0, fees: 0, slippage: 0, count: 0 };
    tx.update(ACC_REF(), { cash: acc.cash, positions, totals: { realized: totals.realized + realized, fees: totals.fees + fee, slippage: totals.slippage + slip, count: totals.count + 1 } });
    return { account_id: acc.id, created_at: Date.now(), mode: "PAPER", symbol, side, qty: q, price: fill, mark_price: mark, fee, slippage_cost: slip, realized_pnl: realized };
  });
  await addDoc(collection(db, "paper_trades"), { ...trade, uid: myUid() });
  return { id: "", ...trade };
}

const STEP = 900_000;

/** Spot limit order. BUY sets the cash aside now; SELL needs coins not already promised to other sell orders. */
export async function placeLimit(symbol: string, side: "BUY" | "SELL", limit: number, qty: number, costs: Costs = DEFAULT_COSTS) {
  if (!(limit > 0)) throw new Error("enter a limit price");
  if (!(qty > 0)) throw new Error("enter a positive amount");
  await adoptLegacy();
  if (!(await getDoc(ACC_REF())).exists()) await reset();
  const mark = await price(symbol);
  if (side === "BUY" ? limit >= mark : limit <= mark) throw new Error(`a ${side.toLowerCase()} limit must be ${side === "BUY" ? "below" : "above"} the current price (${mark}); use Market to trade now`);
  const key = symbol.replace("/", "");
  await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC_REF())).data();
    const orders = { ...(acc.orders ?? {}) };
    let reserve = 0;
    if (side === "BUY") {
      reserve = qty * limit * (1 + costs.fee_rate);
      if (reserve > acc.cash + 1e-9) throw new Error(`insufficient virtual cash: need ${reserve.toFixed(2)}, have ${acc.cash.toFixed(2)}`);
    } else {
      const held = acc.positions?.[key]?.qty ?? 0;
      const promised = Object.values<any>(orders).filter((o) => o.symbol === symbol && o.side === "SELL").reduce((a, o) => a + o.qty, 0);
      if (qty > held - promised + 1e-12) throw new Error(`you can sell at most ${(held - promised).toPrecision(6)} ${symbol.split("/")[0]}`);
    }
    const now = Date.now();
    const id = Math.random().toString(36).slice(2, 10);
    orders[id] = { id, symbol, side, price: limit, qty, reserve, created_at: now, checked_at: now };
    tx.update(ACC_REF(), { cash: acc.cash - reserve, orders });
  });
}

export async function cancelOrder(id: string) {
  await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC_REF())).data();
    const od = acc?.orders?.[id];
    if (!od) return;
    const orders = { ...acc.orders }; delete orders[id];
    tx.update(ACC_REF(), { cash: acc.cash + (od.reserve ?? 0), orders });
  });
}

async function fillOrder(id: string, at: number, when: number, costs: Costs = DEFAULT_COSTS) {
  const trade = await runTransaction(db, async (tx) => {
    const acc: any = (await tx.get(ACC_REF())).data();
    const od = acc?.orders?.[id];
    if (!od) return null;
    const orders = { ...acc.orders }; delete orders[id];
    const key = od.symbol.replace("/", "");
    const positions = { ...(acc.positions ?? {}) };
    const pos = positions[key];
    const held = pos?.qty ?? 0;
    const fee = od.qty * at * costs.fee_rate;
    let realized = 0, cash = acc.cash + (od.reserve ?? 0);
    if (od.side === "BUY") {
      const nq = held + od.qty;
      positions[key] = { ...(pos ?? {}), symbol: od.symbol, qty: nq, avg_price: ((pos ? pos.avg_price * held : 0) + od.qty * at) / nq, opened_at: pos?.opened_at ?? when, fees: (pos?.fees ?? 0) + fee };
      cash -= od.qty * at + fee;
    } else {
      const q = Math.min(od.qty, held);
      if (!(q > 0)) { tx.update(ACC_REF(), { orders }); return null; }
      realized = q * (at - pos.avg_price) - fee;
      if (held - q <= 1e-12) delete positions[key]; else positions[key] = { ...pos, qty: held - q };
      cash += q * at - fee;
    }
    const t = acc.totals ?? { realized: 0, fees: 0, slippage: 0, count: 0 };
    tx.update(ACC_REF(), { cash, positions, orders, totals: { ...t, realized: t.realized + realized, fees: t.fees + fee, count: t.count + 1 } });
    return { account_id: acc.id, created_at: when, mode: "PAPER", order_type: "LIMIT", symbol: od.symbol, side: od.side, qty: od.qty, price: at, mark_price: at, fee, slippage_cost: 0, realized_pnl: realized };
  });
  if (trade) await addDoc(collection(db, "paper_trades"), { ...trade, uid: myUid() });
}

let settlingSpot = false;
/** Fills spot limit orders reached by a closed 15m candle or the live price (also after the app was closed). */
export async function settle() {
  if (settlingSpot) return;
  settlingSpot = true;
  try {
    const acc: any = (await getDoc(ACC_REF())).data();
    const now = Date.now();
    for (const od of Object.values<any>(acc?.orders ?? {})) {
      let hit: { at: number; ts: number } | null = null;
      if (now - od.checked_at > STEP) {
        try {
          const need = Math.min(1000, Math.ceil((now - od.checked_at) / STEP) + 2);
          for (const c of await klines(od.symbol, "15m", need)) {
            if (c[0] + STEP <= od.created_at || c[0] + STEP > now) continue;
            if (od.side === "BUY" ? c[3] <= od.price : c[2] >= od.price) { hit = { at: od.side === "BUY" ? Math.min(c[1], od.price) : Math.max(c[1], od.price), ts: c[0] + STEP }; break; }
          }
        } catch { /* next time */ }
      }
      const px = latestPrices[od.symbol];
      if (!hit && px && (od.side === "BUY" ? px <= od.price : px >= od.price)) hit = { at: od.price, ts: now };
      if (hit) await fillOrder(od.id, hit.at, hit.ts);
      else if (now - od.checked_at > STEP) {
        await runTransaction(db, async (tx) => {
          const a: any = (await tx.get(ACC_REF())).data();
          const o2 = a?.orders?.[od.id];
          if (o2) tx.update(ACC_REF(), { orders: { ...a.orders, [od.id]: { ...o2, checked_at: now - (now % STEP) } } });
        });
      }
    }
  } finally { settlingSpot = false; }
}

/** Same shape as the local API's /paper response. Prices: live stream, else a REST ticker. */
export function subscribe(cb: (s: any) => void, err: (e: Error) => void) {
  let trades: any[] = [];
  let unsubTrades = () => {};
  let currentId = "";
  const build = async (acc: any) => {
    if (!acc) { await reset(); return; }
    const positions = Object.values(acc.positions ?? {}) as any[];
    const need = [...positions.map((p) => p.symbol), acc.benchmark_symbol].filter((s) => s && !latestPrices[s]);
    if (need.length) {
      try { const t = await tickers(need); for (const [s, v] of Object.entries<any>(t)) latestPrices[s] = v.last; } catch { /* shown as missing */ }
    }
    let mv = 0, upnl = 0;
    const pos = positions.map((p) => {
      const mark = latestPrices[p.symbol] ?? null;
      if (mark != null) { mv += p.qty * mark; upnl += p.qty * (mark - p.avg_price); }
      return { ...p, mark, market_value: mark != null ? p.qty * mark : null, unrealized_pnl: mark != null ? p.qty * (mark - p.avg_price) : null };
    });
    pos.sort(byNewest);
    const orders = Object.values<any>(acc.orders ?? {}).sort(byNewest);
    const reserved = orders.reduce((a, o) => a + (o.reserve ?? 0), 0);
    const equity = acc.cash + reserved + mv;
    const ret = equity / acc.starting_balance - 1;
    const bnow = latestPrices[acc.benchmark_symbol];
    const bret = bnow && acc.benchmark_price ? bnow / acc.benchmark_price - 1 : null;
    const dayAgo = Date.now() - 86_400_000;
    cb({
      mode: "PAPER TRADING", account: acc, cash: acc.cash, orders, reserved, market_value: mv, equity, return_pct: ret * 100,
      realized_pnl: acc.totals?.realized ?? 0, unrealized_pnl: upnl, fees: acc.totals?.fees ?? 0, slippage: acc.totals?.slippage ?? 0,
      trade_count: acc.totals?.count ?? 0, positions: pos, trades,
      benchmark: { label: `Buy & hold ${acc.benchmark_symbol} since account start`, return_pct: bret == null ? null : bret * 100, excess_pct: bret == null ? null : (ret - bret) * 100 },
      day_realized_pnl: trades.filter((t) => t.created_at >= dayAgo).reduce((s, t) => s + (t.realized_pnl ?? 0), 0),
    });
  };
  let lastAcc: any = null;
  let unsubAcc = () => {};
  let cancelled = false;
  adoptLegacy().finally(() => {
    if (cancelled) return;
    unsubAcc = onSnapshot(ACC_REF(), (s) => {
    lastAcc = s.data() ?? null;
    if (lastAcc && lastAcc.id !== currentId) {
      currentId = lastAcc.id;
      unsubTrades();
      unsubTrades = onSnapshot(query(collection(db, "paper_trades"), where("account_id", "==", currentId), ...(isAdmin() ? [] : [where("uid", "==", myUid())])), (q) => {
        trades = q.docs.map((d) => ({ id: d.id, ...d.data() })).sort((a: any, b: any) => b.created_at - a.created_at).slice(0, 200);
        build(lastAcc).catch(err);
      }, err);
    }
    build(lastAcc).catch(err);
    }, err);
  });
  settle().catch(() => {});
  const timer = window.setInterval(() => { if (!document.hidden) settle().catch(() => {}); }, 15_000);
  // P&L follows the live price every second while the tab is visible; nothing is re-sent when no price moved
  let lastKey = "";
  const priceKey = (acc: any) => [...Object.values<any>(acc.positions ?? {}).map((p) => latestPrices[p.symbol]), latestPrices[acc.benchmark_symbol]].join("|");
  const stopPnl = visibleInterval(() => {
    if (!lastAcc) return;
    const k = priceKey(lastAcc);
    if (k === lastKey) return;
    lastKey = k;
    build(lastAcc).catch(() => {});
  }, 1000);
  return () => { cancelled = true; unsubAcc(); unsubTrades(); window.clearInterval(timer); stopPnl(); };
}

export async function openExposure(): Promise<{ exposure: number; today: number }> {
  const snap = await getDoc(ACC_REF());
  const acc: any = snap.data();
  if (!acc) return { exposure: 0, today: 0 };
  let exposure = 0;
  for (const p of Object.values<any>(acc.positions ?? {})) exposure += p.qty * (latestPrices[p.symbol] ?? p.avg_price);
  const q = await getDocs(query(collection(db, "paper_trades"), where("account_id", "==", acc.id), ...(isAdmin() ? [] : [where("uid", "==", myUid())])));
  const dayAgo = Date.now() - 86_400_000;
  const today = q.docs.map((d) => d.data()).filter((t: any) => t.created_at >= dayAgo).reduce((s: number, t: any) => s + (t.realized_pnl ?? 0), 0);
  return { exposure, today };
}
