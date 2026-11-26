import { Link } from "react-router-dom";
import DataStatus from "../components/DataStatus";
import { Card, ErrorBox } from "../components/ui";
import { useApi } from "../lib/api";
import { useIsAdmin } from "../lib/session";
import { ago } from "../lib/format";

/* V3.4 Stage 5 · Settings & System → System status (members). Only what the member view of the engine status carries
   (views/health: engine age, market data, models ready) plus the market regime's data quality. Plan / write budgets and
   raw errors stay admin only (Control room). */

const MIN = 60_000;

export default function SystemStatus() {
  const h = useApi<any>("/system", 60_000);
  const reg = useApi<any>("/market-regime", 300_000).data;
  const admin = useIsAdmin();
  const d = h.data;
  const last = d?.engine?.last_tick_finished ?? d?.generated_at;
  const age = last ? (Date.now() - last) / MIN : null;
  const engineSt = age == null ? "unavailable" : age <= 15 ? "confirmed" : age <= 60 ? "delayed" : "unavailable";
  const md = d?.market_data ?? {};
  const mdSt = String(md.status ?? "").toLowerCase();
  const models = d?.models_summary ?? {};
  const rows: [string, string, string, string?][] = [
    ["Engine", engineSt, last ? `last cycle ${ago(last)}` : "no reading", "Runs about every 4 minutes"],
    ["Market data", mdSt === "ok" || mdSt === "live" ? "confirmed" : mdSt ? "delayed" : "unavailable", md.quality ? `quality ${md.quality}` : md.status ?? "no reading"],
    ["AI models", models.active ? "confirmed" : "unavailable", models.active ? `${models.active} active${models.newest ? ` · newest ${ago(models.newest)}` : ""}` : "none ready"],
    ["Market regime inputs", reg ? (reg.data_quality === "good" ? "confirmed" : reg.data_quality === "partial" ? "delayed" : "unavailable") : "unavailable",
      reg?.inputs ? `${reg.inputs.total - reg.inputs.unavailable} of ${reg.inputs.total} inputs measured` : "no reading"],
  ];
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">System status</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">Is the engine running and is its data fresh? Analysis and demo trading only: no real orders, ever.</p>
      </header>
      {h.error && <ErrorBox error={h.error} retry={h.reload} />}
      <Card title="Services" right={<span className="text-xs text-mute">{d?.generated_at ? `checked ${ago(d.generated_at)}` : ""}</span>}>
        <ul className="divide-y" style={{ borderColor: "var(--hair)" }}>
          {rows.map(([name, st, detail, note]) => (
            <li key={name} className="flex items-start gap-3 py-2.5" style={{ borderColor: "var(--hair)" }}>
              <div className="min-w-0 flex-1"><div className="text-sm font-medium">{name}</div><div className="text-xs text-mute">{detail}{note ? ` · ${note}` : ""}</div></div>
              <DataStatus status={st} />
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Safety checks that always apply">
        <ul className="space-y-1.5 text-sm text-mute">
          <li>· A check that cannot read its data blocks new signals ("check unavailable") instead of letting them through.</li>
          <li>· Open signals keep their stop and targets during a data outage; nothing is assumed while prices are missing.</li>
          <li>· A trained model goes live only after its file loads and its own tests exist; otherwise the previous model stays.</li>
        </ul>
        {admin && <p className="mt-3 text-sm"><Link to="/health" className="text-accent hover:underline">Open the Control room for the full engine status →</Link></p>}
      </Card>
    </div>
  );
}
