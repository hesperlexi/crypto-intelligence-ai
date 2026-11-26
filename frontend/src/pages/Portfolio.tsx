import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { doc, setDoc } from "firebase/firestore";
import { Card } from "../components/ui";
import { MyCapital, MyPositions } from "../components/V3Home";
import { NumField } from "../components/AutoTrade";
import { useApi } from "../lib/api";
import { db } from "../lib/firebase";
import { myUid } from "../lib/session";
import { DASH, base, fmtPrice, isNum } from "../lib/format";
import { useKlines } from "../lib/klines";
import { useTickerThrottled } from "../lib/live";

/* V3.0 Portfolio (owner brief, 24 Nov 2026): the member's practice capital in one place - account, open positions,
   the auto-trade protection limits (engine services/autopaper.protection) and the latest closed trades. Practice only. */

function Protection() {
  const cur = useApi<any>("/auto-paper").data;
  const [s, setS] = useState({ daily_loss_pct: 5, max_exposure_pct: 50, follow_risk: true });
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (cur) setS({ daily_loss_pct: Number(cur.daily_loss_pct ?? 5), max_exposure_pct: Number(cur.max_exposure_pct ?? 50), follow_risk: cur.follow_risk !== false });
  }, [cur]);
  const save = async () => {
    try { await setDoc(doc(db, "auto_paper", myUid()), { ...s, updated_at: Date.now() }, { merge: true }); setMsg("Saved. The engine uses it from its next round."); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <Card title="Auto-trade protection" right={<span className="v3-pill v3-muted">Practice</span>}>
      <p className="mb-3 text-sm text-mute">Limits the engine applies before every auto-trade in your practice account. Manual trades are never touched.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">Daily loss limit (% of the account)
          <NumField value={s.daily_loss_pct} min={0.5} max={100} onChange={(n) => setS({ ...s, daily_loss_pct: n })} /></label>
        <label className="text-sm">Most of the account in use (%)
          <NumField value={s.max_exposure_pct} min={5} max={100} onChange={(n) => setS({ ...s, max_exposure_pct: n })} /></label>
      </div>
      <label className="mt-4 flex items-center gap-3 text-sm">
        <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--accent))]" checked={s.follow_risk} onChange={(e) => setS({ ...s, follow_risk: e.target.checked })} />
        Follow the market risk level (High risk: half size · Severe: no new auto-trades)
      </label>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary" onClick={save}>Save protection</button>
        <Link to="/paper" className="btn">Auto-trade settings</Link>
        {msg && <span className="text-sm text-mute">{msg}</span>}
      </div>
    </Card>
  );
}

function Closed() {
  const acc = useApi<any>("/paper/futures").data;
  const rows: any[] = ((acc?.trades ?? []) as any[]).filter((t) => t.type === "CLOSE").sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)).slice(0, 10);
  return (
    <Card title="Latest closed trades" right={<Link to="/paper" className="text-xs text-accent hover:underline">Trade ›</Link>}>
      {rows.length === 0 ? <p className="text-sm text-mute">No closed practice trades yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-mute"><th className="pb-2 font-normal">Coin</th><th className="pb-2 font-normal">Exit</th>
            <th className="hidden pb-2 font-normal sm:table-cell">Why</th><th className="pb-2 text-right font-normal">P&amp;L</th></tr></thead>
          <tbody className="[&_td]:border-t [&_td]:py-2 [&_td]:[border-color:var(--hair)]">
            {rows.map((t, i) => (
              <tr key={i}>
                <td>{base(t.symbol)} <span className={t.side > 0 ? "text-bull" : "text-bear"}>{t.side > 0 ? "long" : "short"}</span>{t.auto && <span className="ml-1 text-xs text-mute">auto</span>}</td>
                <td className="num">{fmtPrice(t.price)}</td>
                <td className="hidden text-mute sm:table-cell">{t.reason ?? DASH}</td>
                <td className={`num text-right ${(t.realized_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{(t.realized_pnl ?? 0) >= 0 ? "+" : "−"}${Math.abs(t.realized_pnl ?? 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

/* V3.4 Stage 5: exposure, correlation and risk of the open practice positions (browser only: the practice account plus
   public Binance 1h candles for each coin's correlation with BTC; nothing is stored). */
const CORR_MIN = 0.7;
const rets = (k: any[] | null) => (k && k.length > 2 ? k.slice(1).map((x, i) => Math.log(x[4] / k[i][4])) : null);
function corrOf(a: number[] | null, b: number[] | null) {
  if (!a || !b) return null;
  const n = Math.min(a.length, b.length);
  if (n < 48) return null;
  const x = a.slice(-n), y = b.slice(-n);
  const mx = x.reduce((s, v) => s + v, 0) / n, my = y.reduce((s, v) => s + v, 0) / n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) { sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2; }
  return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : null;
}

type Expo = { notional: number; risk: number; corr: number | null; side: number };
function ExposureRow({ p, eq, onValue }: { p: any; eq: number | null; onValue: (k: string, v: Expo) => void }) {
  const t = useTickerThrottled(p.symbol, 3000);
  const px = (t?.last ?? p.mark ?? p.entry) as number;
  const coin = useKlines(p.symbol, "1h", 73, 900_000).data;
  const btc = useKlines("BTC/USDT", "1h", 73, 900_000).data;
  const corr = base(p.symbol) === "BTC" ? 1 : corrOf(rets(coin), rets(btc));
  const notional = Math.abs(p.qty * px);
  const stop = Number(p.stop) || null;
  const risk = stop ? Math.max(0, p.side * (px - stop)) * Math.abs(p.qty) : null;
  const key = `${p.symbol}|${p.side}|${p.entry}`;
  useEffect(() => { onValue(key, { notional, risk: risk ?? notional, corr, side: p.side }); }, [key, notional, risk, corr, p.side, onValue]);
  const share = (v: number | null) => (isNum(v) && isNum(eq) && eq > 0 ? `${((v / eq) * 100).toFixed(1)}%` : DASH);
  return (
    <tr>
      <td>{base(p.symbol)} <span className={p.side > 0 ? "text-bull" : "text-bear"}>{p.side > 0 ? "long" : "short"}</span></td>
      <td className="num">${notional.toLocaleString(undefined, { maximumFractionDigits: 0 })}<span className="ml-1 text-xs text-mute">{share(notional)}</span></td>
      <td className="num">{risk == null ? <span className="text-bear">no stop</span> : <>${risk.toFixed(2)}<span className="ml-1 text-xs text-mute">{share(risk)}</span></>}</td>
      <td className="num text-right">{isNum(corr) ? `${Math.round(corr * 100)}%` : DASH}</td>
    </tr>
  );
}

function Exposure() {
  const acc = useApi<any>("/paper/futures").data;
  const pos: any[] = acc?.positions ?? [];
  const eq = isNum(acc?.equity) ? acc.equity : null;
  const [vals, setVals] = useState<Record<string, Expo>>({});
  const onValue = useCallback((k: string, v: Expo) => setVals((m) => (m[k] && m[k].notional === v.notional && m[k].risk === v.risk && m[k].corr === v.corr ? m : { ...m, [k]: v })), []);
  const keys = new Set(pos.map((p) => `${p.symbol}|${p.side}|${p.entry}`));
  const live = Object.entries(vals).filter(([k]) => keys.has(k)).map(([, v]) => v);
  const sum = useMemo(() => {
    const tot = (f: (v: Expo) => boolean, g: (v: Expo) => number) => live.filter(f).reduce((a, v) => a + g(v), 0);
    return { notional: tot(() => true, (v) => v.notional), risk: tot(() => true, (v) => v.risk),
      corrLong: tot((v) => v.side > 0 && (v.corr == null || v.corr >= CORR_MIN), (v) => v.notional),
      corrShort: tot((v) => v.side < 0 && (v.corr == null || v.corr >= CORR_MIN), (v) => v.notional) };
  }, [live]);
  const pc = (v: number) => (isNum(eq) && eq > 0 ? `${((v / eq) * 100).toFixed(0)}%` : DASH);
  return (
    <Card title="Exposure and risk" right={<span className="v3-pill v3-muted">Practice</span>}>
      {!pos.length ? <p className="text-sm text-mute">No open practice positions.</p> : (
        <>
          <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div><div className="v3-k">Open exposure</div><div className="num mt-0.5 text-lg">{pc(sum.notional)}</div><div className="text-xs text-mute">of the account</div></div>
            <div><div className="v3-k">Lost if every stop hits</div><div className="num mt-0.5 text-lg text-bear">{pc(sum.risk)}</div><div className="text-xs text-mute">from the price now</div></div>
            <div><div className="v3-k">Long, moving with BTC</div><div className="num mt-0.5 text-lg">{pc(sum.corrLong)}</div><div className="text-xs text-mute">correlation ≥ 70 %</div></div>
            <div><div className="v3-k">Short, moving with BTC</div><div className="num mt-0.5 text-lg">{pc(sum.corrShort)}</div><div className="text-xs text-mute">correlation ≥ 70 %</div></div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-mute"><th className="pb-2 font-normal">Position</th><th className="pb-2 font-normal">Size</th><th className="pb-2 font-normal">At risk to stop</th><th className="pb-2 text-right font-normal">Moves with BTC</th></tr></thead>
              <tbody className="[&_td]:border-t [&_td]:py-2 [&_td]:[border-color:var(--hair)]">
                {pos.map((p) => <ExposureRow key={`${p.symbol}|${p.side}|${p.entry}`} p={p} eq={eq} onValue={onValue} />)}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-mute">Positions that move with Bitcoin add up: several longs in such coins behave like one bigger bet. Correlation = 72 hours of 1h returns; a coin without enough history counts as moving with BTC.</p>
        </>
      )}
    </Card>
  );
}

export default function Portfolio() {
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">Portfolio</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">Your practice capital, open positions and protection. Virtual money only.</p>
      </header>
      {/* owner 24 Nov: one grid, two equal columns, so both rows line up edge to edge and each pair has one height */}
      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <MyCapital />
        <MyPositions />
        <Protection />
        <Closed />
      </div>
      <Exposure />
    </div>
  );
}
