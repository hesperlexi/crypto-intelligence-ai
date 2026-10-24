// PAPER TRADING (manual virtual orders) stored in Firestore. Virtual money only; no order ever reaches an exchange.
import { addDoc, collection, doc, getDoc, getDocs, onSnapshot, query, runTransaction, setDoc, where } from "firebase/firestore";
import { tickers } from "./binance";
import { db } from "./firebase";
import { latestPrices } from "./live";
import { isAdmin, myUid } from "./session";

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
    if (side === "SELL") q = Math.min(q, held);
    const fee = q * fill * costs.fee_rate;
    const slip = q * Math.abs(fill - mark);
    let realized = 0;
    const positions = { ...(acc.positions ?? {}) };
    if (side === "BUY") {
      const cost = q * fill + fee;
      if (cost > acc.cash + 1e-9) throw new Error(`insufficient virtual cash: need ${cost.toFixed(2)}, have ${acc.cash.toFixed(2)}`);
      const nq = held + q;
      positions[key] = { symbol, qty: nq, avg_price: ((pos ? pos.avg_price * held : 0) + q * fill) / nq };
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
    const equity = acc.cash + mv;
    const ret = equity / acc.starting_balance - 1;
    const bnow = latestPrices[acc.benchmark_symbol];
    const bret = bnow && acc.benchmark_price ? bnow / acc.benchmark_price - 1 : null;
    const dayAgo = Date.now() - 86_400_000;
    cb({
      mode: "PAPER TRADING", account: acc, cash: acc.cash, market_value: mv, equity, return_pct: ret * 100,
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
  return () => { cancelled = true; unsubAcc(); unsubTrades(); };
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
