import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SymbolSelect, TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note } from "../components/ui";
import { del, post, put, useApi } from "../lib/api";
import { fmtTime } from "../lib/format";
import * as push from "../lib/push";

const NEEDS: Record<string, { key: string; label: string; placeholder: string }> = {
  CONFIDENCE_ABOVE: { key: "threshold", label: "Confidence threshold (0–1)", placeholder: "0.6" },
  PRICE_ABOVE: { key: "level", label: "Price level", placeholder: "e.g. 70000" },
  PRICE_BELOW: { key: "level", label: "Price level", placeholder: "e.g. 60000" },
};
const LABEL: Record<string, string> = { TRADE_SETUP: "Trade signal — entry, stop-loss & take-profits" };
const TRADE_TFS = ["15m", "1h", "4h"] as const;

function describe(a: any): string {
  const p = a.params ?? {};
  if (a.type === "TRADE_SETUP") {
    const parts = [p.side && p.side !== "any" ? `${p.side} only` : "long or short", p.market === "futures" ? "futures" : "spot"];
    if (p.min_confidence) parts.push(`confidence ≥ ${Math.round(p.min_confidence * 100)}%`);
    if (p.confident_only) parts.push("confident calls only");
    if (String(p.grade ?? "").toUpperCase() === "A") parts.push("strong (grade A) only");
    return `Trade signal (${parts.join(", ")})`;
  }
  const v = Object.values(p);
  return `${a.type.replace(/_/g, " ").toLowerCase()}${v.length ? ` (${v.join(", ")})` : ""}`;
}

export default function Alerts() {
  const symbols = useSymbols();
  const [params] = useSearchParams();
  const data = useApi<any>("/alerts", 20000);
  const [type, setType] = useState("TRADE_SETUP");
  const [symbol, setSymbol] = useState(params.get("symbol") ?? "BTC/USDT");
  const [tf, setTf] = useState(params.get("timeframe") ?? "4h");
  const [param, setParam] = useState("");
  const [side, setSide] = useState("any");
  const [market, setMarket] = useState(params.get("market") === "futures" ? "futures" : "spot");
  const [minConf, setMinConf] = useState("");
  const [confidentOnly, setConfidentOnly] = useState(false);
  const [strongOnly, setStrongOnly] = useState(false);
  const [cooldown, setCooldown] = useState("60");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [perm, setPerm] = useState(push.permission());
  const types: Record<string, string> = { TRADE_SETUP: LABEL.TRADE_SETUP, ...(data.data?.types ?? {}) };
  const need = NEEDS[type];
  const isTrade = type === "TRADE_SETUP";

  useEffect(() => { if (isTrade && !TRADE_TFS.includes(tf as any)) setTf("4h"); }, [isTrade]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<any>, done?: string) => {
    try { await fn(); setErr(null); setOk(done ?? null); data.reload(); } catch (e: any) { setErr(e.message); setOk(null); }
  };
  const create = () => {
    if (need && !param) return setErr(`${need.label} is required`);
    const p = isTrade ? { side, market, min_confidence: minConf ? Number(minConf) / 100 : 0, confident_only: confidentOnly, grade: strongOnly ? "A" : "any" }
      : need ? { [need.key]: Number(param) } : {};
    run(() => post("/alerts", { type, symbol, timeframe: tf, cooldown_s: Math.max(1, Number(cooldown)) * 60, params: p }),
      `Alert created for ${symbol} ${tf.toUpperCase()}. It fires when the condition next turns true (checked every engine run, about every 5–10 minutes).`);
  };
  const turnOn = () => run(async () => { const msg = await push.enable(); setPerm(push.permission()); setOk(msg); }, undefined);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Alerts</h1>

      <div className={`panel flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm ${perm === "granted" ? "" : "border-warn/40"}`}>
        <span>
          <span className="font-medium">Phone notifications: </span>
          {perm === "granted" ? (push.savedToken() ? <span className="text-bull">on, also when the app is closed</span> : <span className="text-warn">on while the app is open</span>)
            : perm === "denied" ? <span className="text-bear">blocked in your browser settings</span>
            : perm === "unsupported" ? <span className="text-mute">not supported here{/iphone|ipad/i.test(navigator.userAgent) ? " — add the app to your Home Screen first" : ""}</span>
            : <span className="text-mute">off</span>}
        </span>
        <span className="flex gap-2">
          {perm !== "granted" && perm !== "unsupported" && <button className="btn btn-primary px-3 py-1 text-xs" onClick={turnOn}>{perm === "denied" ? "Try again" : "Turn on"}</button>}
          <Link className="btn px-3 py-1 text-xs" to="/settings#notifications">Notification settings</Link>
        </span>
      </div>

      <Card title="New alert">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs text-mute sm:col-span-2">Condition
            <select className="input mt-1" value={type} onChange={(e) => { setType(e.target.value); setParam(""); }}>
              {Object.entries(types).sort(([a], [b]) => (a === "TRADE_SETUP" ? -1 : b === "TRADE_SETUP" ? 1 : 0)).map(([k, v]) => <option key={k} value={k}>{LABEL[k] ?? v}</option>)}
            </select>
          </label>
          <SymbolSelect stacked value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
          <div className="text-xs text-mute">Timeframe<div className="mt-1"><TfTabs value={tf} onChange={setTf} options={isTrade ? TRADE_TFS : undefined} /></div></div>
          {isTrade && (<>
            <label className="text-xs text-mute">Direction
              <select className="input mt-1" value={side} onChange={(e) => setSide(e.target.value)}>
                <option value="any">Long or short</option><option value="long">Long only</option><option value="short">Short only</option>
              </select>
            </label>
            <label className="text-xs text-mute">Market
              <select className="input mt-1" value={market} onChange={(e) => setMarket(e.target.value)}>
                <option value="spot">Spot</option><option value="futures">Futures (adds leverage & liquidation)</option>
              </select>
            </label>
            <label className="text-xs text-mute">Minimum confidence (%, optional)<input className="input mt-1" inputMode="numeric" placeholder="e.g. 55" value={minConf} onChange={(e) => setMinConf(e.target.value)} /></label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={confidentOnly} onChange={(e) => setConfidentOnly(e.target.checked)} />Confident calls only</label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm" title="Grade A: trend, AI models and their track record all agree. Leave off to also get grade B (moderate) signals."><input type="checkbox" checked={strongOnly} onChange={(e) => setStrongOnly(e.target.checked)} />Strong signals only (grade A)</label>
          </>)}
          {need && <label className="text-xs text-mute">{need.label}<input className="input mt-1" inputMode="decimal" placeholder={need.placeholder} value={param} onChange={(e) => setParam(e.target.value)} /></label>}
          <label className="text-xs text-mute">Cooldown (minutes)<input className="input mt-1" inputMode="numeric" value={cooldown} onChange={(e) => setCooldown(e.target.value)} /></label>
        </div>
        <button className="btn btn-primary mt-3 w-full sm:w-auto" onClick={create}>Create alert</button>
        {err && <div className="mt-3"><ErrorBox error={err} /></div>}
        {ok && <p className="mt-3 text-sm text-accent">{ok}</p>}
        <Note>{isTrade ? "A trade-signal alert fires when the engine issues a valid BUY / SELL plan for the coin, and the message contains the entry zone, stop-loss, the three take-profit levels, risk/reward, confidence and — for futures — a suggested leverage with its liquidation price. “Confident calls only” keeps just the calls above the model's out-of-sample confident-call threshold. " : ""}An alert fires once when its condition turns from false to true, then stays quiet until the condition has reset and the cooldown has passed. Conditions are checked at every engine run (about every 5–10 minutes).</Note>
      </Card>

      {data.error && <ErrorBox error={data.error} retry={data.reload} />}
      {!data.data && data.loading && <Loading />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`Active rules${data.data?.alerts?.length ? ` (${data.data.alerts.length})` : ""}`}>
          {data.data?.alerts?.length ? (
            <ul className="divide-y divide-glass/[0.06]">
              {data.data.alerts.map((a: any) => (
                <li key={a.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm"><span className="font-medium">{a.symbol}</span> <span className="text-xs uppercase text-mute">{a.timeframe}</span></div>
                    <div className="truncate text-xs text-mute" title={types[a.type]}>{describe(a)} · cooldown {Math.round(a.cooldown_s / 60)} min · last fired {a.last_fired_at ? fmtTime(a.last_fired_at) : "never"}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button onClick={() => run(() => put(`/alerts/${a.id}`, { enabled: !a.enabled }))} aria-pressed={!!a.enabled}><Badge tone={a.enabled ? "bull" : "mute"}>{a.enabled ? "On" : "Off"}</Badge></button>
                    <button className="text-xs text-mute hover:text-bear" onClick={() => run(() => del(`/alerts/${a.id}`))}>Delete</button>
                  </div>
                </li>
              ))}
            </ul>
          ) : <Empty>No alert rules yet</Empty>}
        </Card>
        <Card title="Fired alerts" right={data.data?.events?.some((e: any) => !e.is_read) ? <button className="btn px-2 py-0.5 text-xs" onClick={() => run(() => post("/alerts/read"))}>Mark all read</button> : undefined}>
          {data.data?.events?.length ? data.data.events.map((e: any) => (
            <div key={e.id} className={`border-b border-line/50 py-2.5 text-sm last:border-0 ${e.is_read ? "text-mute" : ""}`}>
              <div className="mb-0.5 flex items-center justify-between gap-2 text-xs text-mute">
                <span>{(e.type ?? "").replace(/_/g, " ").toLowerCase()}</span><span className="whitespace-nowrap">{fmtTime(e.created_at)}</span>
              </div>
              <span>{e.message}</span>
            </div>
          )) : <Empty>Nothing has fired yet</Empty>}
        </Card>
      </div>
    </div>
  );
}
