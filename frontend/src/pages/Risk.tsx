import { Card, ErrorBox } from "../components/ui";
import { MarketStatus } from "../components/V3Home";
import { useApi } from "../lib/api";
import { ago } from "../lib/format";

/* V3.0 Risk Intelligence (owner brief, 24 Nov 2026). Everything comes from the engine's central risk state
   (services/risk_state.py -> views/risk_state): one deterministic state from measured inputs, never set by the AI. */

const ST: Record<string, [string, string]> = { ok: ["OK", "v3-ok"], warn: ["Raised", "v3-watch"], high: ["High", "v3-act"], unknown: ["No data", "v3-muted"] };
const COLOR: Record<string, string> = { NORMAL: "--bull", CAUTION: "--warn", RECOVERY: "--ai", HIGH: "--bear", SEVERE: "--bear" };

function Series({ s }: { s: [number, number, string][] }) {
  if (!s?.length) return <p className="text-sm text-mute">The history fills in hour by hour.</p>;
  const W = 720, Hh = 120, max = Math.max(6, ...s.map((x) => x[1]));
  const bw = W / s.length;
  return (
    <svg viewBox={`0 0 ${W} ${Hh + 18}`} className="w-full" role="img" aria-label="Risk score by hour, last 7 days">
      {[2, 4, 6].map((y) => <line key={y} x1={0} x2={W} y1={Hh - (y / max) * Hh} y2={Hh - (y / max) * Hh} stroke="rgb(var(--glass) / 0.07)" />)}
      {s.map(([t, v, st], i) => (
        <rect key={t} x={i * bw + 0.5} width={Math.max(1, bw - 1)} y={Hh - (Math.max(v, 0.15) / max) * Hh} height={(Math.max(v, 0.15) / max) * Hh}
          rx={1} fill={`rgb(var(${COLOR[st] ?? "--mute"}) / 0.75)`}><title>{`${new Date(t).toLocaleString()} · ${st} · score ${v}`}</title></rect>
      ))}
      <text x={0} y={Hh + 14} fontSize="11" fill="rgb(var(--mute))">{new Date(s[0][0]).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</text>
      <text x={W} y={Hh + 14} fontSize="11" textAnchor="end" fill="rgb(var(--mute))">now</text>
    </svg>
  );
}

const LEVELS = [
  { state: "NORMAL", label: "Normal", policy: "Normal conditions. Every check still applies to each signal." },
  { state: "CAUTION", label: "Caution", policy: "Be selective: prefer grade A calls and smaller size." },
  { state: "HIGH", label: "High risk", policy: "Conditions are unsafe for many setups: practice auto-trade uses half size." },
  { state: "SEVERE", label: "Severe risk", policy: "Stand aside: practice auto-trade opens nothing new until risk falls." },
  { state: "RECOVERY", label: "Recovery", policy: "Risk is falling after a rough spell: stay selective until it settles." },
];
const METHOD = "Points per factor (0 ok, 1 raised, 2 high). 0-1 Normal, 2-3 Caution, 4-5 High risk, 6+ Severe; after High or Severe, Recovery until 6 calm hours. Missing BTC data counts as risk.";

const RULES: [string, string, string][] = [
  ["Signals", "Capital protection", "No new signal while closed signals lost 3R today or 6R this week, on a coin whose volatility is far above normal, or where the model's recent hit rate fell well below its test."],
  ["Signals", "Stop-run guard", "No new signal against a fresh stop run (liquidity grab) on the coin in the last 6 hours."],
  ["Signals", "News pause", "No new entries 45 minutes before to 30 minutes after major US data."],
  ["Signals", "One-sided limit", "At most 12 running signals in the same direction."],
  ["Signals", "Bigger trend, costs, grade", "Calls against both higher timeframes, with targets too small for fees, or below the required grade are held back."],
  ["Practice auto-trade", "Follows the risk level", "High risk: half size. Severe: no new auto-trades. You can switch this off in Portfolio."],
  ["Practice auto-trade", "Daily loss and exposure", "Stops for the day after a 5% loss and keeps at most 50% of the account in use (your settings)."],
];

export default function Risk() {
  const r = useApi<any>("/risk-state", 60000);
  const dash4 = useApi<any>("/dashboard?timeframe=4h", 60000).data;
  const d = r.data;
  const factors: any[] = d?.factors ?? [];
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">Risk</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">One market risk level from measured data. It protects capital; the AI never sets it.</p>
      </header>
      {r.error && <ErrorBox error={r.error} retry={r.reload} />}
      <MarketStatus status4={dash4?.market_status} rows={dash4?.rows} />
      <div className="grid-even grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card title="What is being checked" right={<span className="text-xs text-mute">{d?.generated_at ? `updated ${ago(d.generated_at)}` : ""}</span>}>
          <ul className="divide-y" style={{ borderColor: "var(--hair)" }}>
            {factors.map((f) => {
              const [lbl, cls] = ST[f.status] ?? ST.unknown;
              return (
                <li key={f.key} className="flex items-start gap-3 py-2.5" style={{ borderColor: "var(--hair)" }}>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{f.label}{f.critical && <span className="ml-2 text-xs text-mute">critical</span>}</div>
                    <div className="text-xs text-mute">{f.detail}{f.source ? ` · ${f.source}` : ""}</div>
                  </div>
                  <span className={`v3-pill ${cls}`}>{lbl}</span>
                </li>
              );
            })}
            {!factors.length && <li className="py-2 text-sm text-mute">Waiting for the first reading.</li>}
          </ul>
        </Card>
        <div className="ov-stack flex min-w-0 flex-col gap-4">
          <Card title="Levels and what they do">
            <ul className="space-y-2.5">
              {((d?.levels?.length ? d.levels : LEVELS) as any[]).map((l: any) => (
                <li key={l.state} className={`rounded-lg px-3 py-2 ${l.state === d?.state ? "v3-glass" : ""}`} style={{ border: "1px solid var(--hair)" }}>
                  <div className="flex items-center gap-2 text-sm font-medium"><span className="v3-dot" style={{ background: `rgb(var(${COLOR[l.state] ?? "--mute"}))` }} />{l.label}{l.state === d?.state && <span className="text-xs text-mute">· now</span>}</div>
                  <div className="mt-0.5 text-xs text-mute">{l.policy}</div>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-mute">{d?.method || METHOD}</p>
          </Card>
        </div>
      </div>
      <Card title="Risk score, last 7 days"><Series s={d?.series ?? []} /></Card>
      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <Card title="Protection in force">
          <ul className="space-y-3">
            {RULES.map(([who, t, x]) => (
              <li key={t}><div className="text-sm font-medium">{t} <span className="ml-1 text-xs text-mute">{who}</span></div><div className="text-xs text-mute">{x}</div></li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-mute">The risk level itself is shown and recorded on every new signal. It will block signals only after a replay test on past data proves it helps.</p>
        </Card>
        <Card title="Level changes">
          <ul className="divide-y" style={{ borderColor: "var(--hair)" }}>
            {[...(d?.log ?? [])].reverse().slice(0, 12).map((x: any) => (
              <li key={x.at} className="flex gap-3 py-2 text-sm" style={{ borderColor: "var(--hair)" }}>
                <span className="num w-24 shrink-0 text-xs text-mute">{new Date(x.at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                <span className="min-w-0"><b className="font-medium">{x.from ?? "start"} → {x.to}</b><span className="block text-xs text-mute">{x.why}</span></span>
              </li>
            ))}
            {!(d?.log ?? []).length && <li className="py-2 text-sm text-mute">No changes yet.</li>}
          </ul>
        </Card>
      </div>
    </div>
  );
}
