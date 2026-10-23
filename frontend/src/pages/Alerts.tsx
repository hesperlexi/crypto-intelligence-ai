import { useState } from "react";
import { SymbolSelect, TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Empty, ErrorBox, Loading, Note } from "../components/ui";
import { del, post, put, useApi } from "../lib/api";
import { fmtTime } from "../lib/format";

const NEEDS: Record<string, { key: string; label: string; placeholder: string }> = {
  CONFIDENCE_ABOVE: { key: "threshold", label: "Confidence threshold (0–1)", placeholder: "0.6" },
  PRICE_ABOVE: { key: "level", label: "Price level", placeholder: "e.g. 70000" },
  PRICE_BELOW: { key: "level", label: "Price level", placeholder: "e.g. 60000" },
};

export default function Alerts() {
  const symbols = useSymbols();
  const data = useApi<any>("/alerts", 20000);
  const [type, setType] = useState("BUY_SIGNAL");
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [tf, setTf] = useState("4h");
  const [param, setParam] = useState("");
  const [cooldown, setCooldown] = useState("60");
  const [err, setErr] = useState<string | null>(null);
  const types: Record<string, string> = data.data?.types ?? {};
  const need = NEEDS[type];

  const run = async (fn: () => Promise<any>) => {
    try {
      await fn();
      setErr(null);
      data.reload();
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const create = () => {
    if (need && !param) return setErr(`${need.label} is required`);
    run(() => post("/alerts", { type, symbol, timeframe: tf, cooldown_s: Math.max(1, Number(cooldown)) * 60, params: need ? { [need.key]: Number(param) } : {} }));
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Alerts</h1>
      <Card title="New alert">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-mute">Condition<select className="input mt-1 w-72" value={type} onChange={(e) => { setType(e.target.value); setParam(""); }}>{Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <SymbolSelect value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
          <TfTabs value={tf} onChange={setTf} />
          {need && <label className="text-xs text-mute">{need.label}<input className="input mt-1 w-36" inputMode="decimal" placeholder={need.placeholder} value={param} onChange={(e) => setParam(e.target.value)} /></label>}
          <label className="text-xs text-mute">Cooldown (minutes)<input className="input mt-1 w-28" inputMode="numeric" value={cooldown} onChange={(e) => setCooldown(e.target.value)} /></label>
          <button className="btn btn-primary" onClick={create}>Create alert</button>
        </div>
        {err && <div className="mt-3"><ErrorBox error={err} /></div>}
        <Note>An alert fires once when its condition turns from false to true, then stays quiet until the condition has reset and the cooldown has passed. Conditions are checked at every forecast refresh. Alerts appear here and as in-app notifications.</Note>
      </Card>
      {data.error && <ErrorBox error={data.error} retry={data.reload} />}
      {!data.data && data.loading && <Loading />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Active rules">
          {data.data?.alerts?.length ? (
            <div className="overflow-x-auto"><table className="grid-table">
              <thead><tr><th>Condition</th><th>Asset</th><th>TF</th><th>Cooldown</th><th>Last fired</th><th>State</th><th /></tr></thead>
              <tbody>{data.data.alerts.map((a: any) => (
                <tr key={a.id}>
                  <td title={types[a.type]}>{a.type.replace(/_/g, " ")}{Object.keys(a.params ?? {}).length ? ` (${Object.values(a.params).join(", ")})` : ""}</td>
                  <td>{a.symbol}</td><td className="uppercase text-mute">{a.timeframe}</td><td className="num text-mute">{Math.round(a.cooldown_s / 60)} min</td>
                  <td className="text-mute">{a.last_fired_at ? fmtTime(a.last_fired_at) : "never"}</td>
                  <td><button onClick={() => run(() => put(`/alerts/${a.id}`, { enabled: !a.enabled }))} aria-pressed={!!a.enabled}><Badge tone={a.enabled ? "bull" : "mute"}>{a.enabled ? "On" : "Off"}</Badge></button></td>
                  <td><button className="text-xs text-mute hover:text-bear" onClick={() => run(() => del(`/alerts/${a.id}`))}>Delete</button></td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <Empty>No alert rules yet</Empty>}
        </Card>
        <Card title="Fired alerts" right={data.data?.events?.some((e: any) => !e.is_read) ? <button className="btn px-2 py-0.5 text-xs" onClick={() => run(() => post("/alerts/read"))}>Mark all read</button> : undefined}>
          {data.data?.events?.length ? data.data.events.map((e: any) => (
            <div key={e.id} className={`flex items-start justify-between gap-3 border-b border-line/50 py-2 text-sm last:border-0 ${e.is_read ? "text-mute" : ""}`}>
              <span>{e.message}</span><span className="whitespace-nowrap text-xs text-mute">{fmtTime(e.created_at)}</span>
            </div>
          )) : <Empty>Nothing has fired yet</Empty>}
        </Card>
      </div>
    </div>
  );
}
