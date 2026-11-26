import { Card, ErrorBox } from "../components/ui";
import DataStatus, { DataLegend } from "../components/DataStatus";
import { MacroCard, VolOptionsCard } from "../components/Derivs";
import { useApi } from "../lib/api";
import { ago } from "../lib/format";

/* V3.4 Stage 5 · Market Intelligence → Market regime. One reading of the whole market (services/market_regime ->
   views/market_regime): label, how much the inputs agree, data quality, every input with its status, pending change.
   Context only: the regime never opens, blocks or sizes a trade. */

const TONE: Record<string, string> = {
  strong_bull: "--bull", weak_bull: "--bull", breakout: "--bull", strong_bear: "--bear", weak_bear: "--bear",
  breakdown: "--bear", sideways: "--mute", unstable: "--warn", uncertain: "--mute",
};
const SUPPORTS: Record<string, [string, string]> = {
  bull: ["Supports up", "text-bull"], bear: ["Supports down", "text-bear"], risk: ["Risk", "text-warn"],
  neutral: ["Neutral", "text-mute"], none: ["—", "text-mute"],
};
const word = (k?: string | null) => (k ? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "—");

export default function Regime() {
  const r = useApi<any>("/market-regime", 120_000);
  const d = r.data;
  const label = d?.regime ?? d?.primary;
  const tone = TONE[label ?? ""] ?? "--mute";
  const pend = d?.transition?.pending;
  const ev: any[] = d?.evidence ?? [];
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">Market regime</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">One reading of the whole market, with every input behind it. Context only: it never opens or blocks a trade.</p>
      </header>
      {r.error && <ErrorBox error={r.error} retry={r.reload} />}
      <div className="grid-even grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="ov-stack flex min-w-0 flex-col gap-4">
        <Card title="Now" right={<span className="text-xs text-mute">{d?.generated_at ? `updated ${ago(d.generated_at)}` : ""}</span>}>
          {!d ? <div className="skeleton h-40 rounded-xl" /> : (
            <div className="space-y-4">
              <div>
                <div className="text-2xl font-semibold" style={{ color: `rgb(var(${tone}))` }}>{d.regime_word ?? word(label)}</div>
                <div className="mt-1 flex flex-wrap gap-2 text-xs">
                  {(d.labels ?? []).filter((l: string) => l.endsWith("volatility")).map((l: string) => <span key={l} className="v3-pill v3-watch">{word(l)}</span>)}
                  <span className="v3-pill v3-muted">Confidence: {d.confidence}</span>
                  <span className={`v3-pill ${d.data_quality === "good" ? "v3-ok" : d.data_quality === "partial" ? "v3-watch" : "v3-act"}`}>Data: {d.data_quality}</span>
                </div>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-xs text-mute">Inputs agreeing</dt><dd className="num font-medium">{d.agreement != null ? `${Math.round(d.agreement * 100)}%` : "—"}</dd></div>
                <div><dt className="text-xs text-mute">Inputs measured</dt><dd className="num font-medium">{d.inputs ? `${d.inputs.total - d.inputs.unavailable} of ${d.inputs.total}` : "—"}</dd></div>
                <div><dt className="text-xs text-mute">Since</dt><dd className="font-medium">{d.transition?.since ? ago(d.transition.since) : "—"}</dd></div>
                <div><dt className="text-xs text-mute">Changing to</dt><dd className="font-medium">{pend ? `${word(pend.label)} (${pend.runs} of 3 checks)` : "no change pending"}</dd></div>
              </dl>
              {!!(d.reasons ?? []).length && <ul className="space-y-1 text-xs text-mute">{d.reasons.map((x: string) => <li key={x}>· {x}</li>)}</ul>}
              <p className="text-xs text-mute">"Inputs agreeing" counts readings, it is not a chance of anything. A new label is confirmed only after it holds for 3 checks and 30 minutes.</p>
            </div>
          )}
        </Card>
        <Card title="Regime changes">
          <ul className="divide-y" style={{ borderColor: "var(--hair)" }}>
            {[...(d?.log ?? [])].reverse().slice(0, 12).map((x: any) => (
              <li key={x.at} className="flex gap-3 py-2 text-sm" style={{ borderColor: "var(--hair)" }}>
                <span className="num w-28 shrink-0 text-xs text-mute">{new Date(x.at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                <span className="min-w-0"><b className="font-medium">{word(x.from)} → {word(x.to)}</b><span className="block text-xs text-mute">confidence {x.confidence} · data {x.data_quality}</span></span>
              </li>
            ))}
            {!(d?.log ?? []).length && <li className="py-2 text-sm text-mute">No changes yet.</li>}
          </ul>
        </Card>
        </div>
        <Card title="Evidence" right={<span className="text-xs text-mute">{ev.length ? `${ev.length} inputs` : ""}</span>}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-mute"><th className="py-1.5 pr-3 font-normal">Input</th><th className="py-1.5 pr-3 font-normal">Reading</th><th className="py-1.5 pr-3 font-normal">Reads as</th><th className="py-1.5 font-normal">Data</th></tr></thead>
              <tbody>
                {ev.map((e) => {
                  const [s, c] = SUPPORTS[e.supports] ?? SUPPORTS.none;
                  return (
                    <tr key={e.input} className="border-t" style={{ borderColor: "var(--hair)" }}>
                      <td className="py-2 pr-3">{e.input}</td>
                      <td className="num py-2 pr-3">{e.reading}</td>
                      <td className={`py-2 pr-3 ${c}`}>{s}</td>
                      <td className="py-2"><DataStatus status={e.status} title={e.source ?? undefined} /></td>
                    </tr>
                  );
                })}
                {!ev.length && <tr><td colSpan={4} className="py-3 text-mute">Waiting for the first reading.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="mt-3"><DataLegend /></div>
          <p className="mt-2 text-xs text-mute">ETF and exchange flows are not shown: no reliable free source exists, and nothing is guessed.</p>
        </Card>
      </div>
      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <VolOptionsCard />
        <MacroCard />
      </div>
    </div>
  );
}
