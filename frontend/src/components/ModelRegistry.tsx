// V3.4 Stage 4 (admin, Control room): every model's identity, validation, live drift and status (views/model_registry).
import { useState } from "react";
import { Badge } from "./kit";
import { useApi } from "../lib/api";
import { ago, isNum } from "../lib/format";

const TONE: Record<string, "bull" | "warn" | "bear" | "mute"> = { active: "bull", held: "mute", stale: "warn", invalid: "bear", missing: "bear", error: "bear" };

export default function ModelRegistry() {
  const q = useApi<any>("/model-registry", 600_000);
  const [filter, setFilter] = useState<"problems" | "all">("problems");
  const v = q.data;
  if (!v) return null;
  const rows: any[] = (v.models ?? []).filter((r: any) => filter === "all" || r.status !== "active" || (r.live?.drift?.drifting));
  const tq = v.trade_quality ?? {};
  return (
    <section className="panel p-4" aria-label="Model registry">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="label">Model registry</h2>
        <span className="flex flex-wrap items-center gap-2 text-xs text-mute">
          {Object.entries(v.counts ?? {}).map(([k, n]) => <Badge key={k} tone={TONE[k] ?? "mute"}>{String(n)} {k}</Badge>)}
          {v.drifting > 0 && <Badge tone="warn">{v.drifting} drifting</Badge>}
          <span>updated {ago(v.generated_at)}</span>
        </span>
      </div>
      {v.training && (
        <p className="mb-3 text-xs text-mute">Last nightly training {ago(v.training.finished_at ?? v.training.started_at)} · {v.training.status}
          {v.training.outcome && ` · ${Object.entries(v.training.outcome).filter(([, n]) => Number(n) > 0).map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(" · ")}`}</p>
      )}
      <div className="mb-2 flex gap-2 text-xs">
        <button type="button" className={`chip ${filter === "problems" ? "is-on" : ""}`} onClick={() => setFilter("problems")}>Needs attention</button>
        <button type="button" className={`chip ${filter === "all" ? "is-on" : ""}`} onClick={() => setFilter("all")}>All models</button>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-[rgb(var(--panel))]"><tr className="text-left text-xs text-mute"><th className="py-1.5 pr-2 font-normal">Model</th><th className="pr-2 font-normal">Status</th><th className="pr-2 text-right font-normal">Age</th><th className="pr-2 text-right font-normal">OOS n</th><th className="pr-2 text-right font-normal">Brier</th><th className="pr-2 text-right font-normal">Hit OOS / live</th><th className="font-normal">Why</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.symbol}${r.timeframe}`} className="border-t" style={{ borderColor: "var(--hair)" }}>
                <td className="py-1.5 pr-2">{r.symbol.split("/")[0]} {r.timeframe}</td>
                <td className="pr-2"><Badge tone={TONE[r.status] ?? "mute"}>{r.status}</Badge></td>
                <td className="num pr-2 text-right">{isNum(r.age_h) ? `${Math.round(r.age_h)} h` : "–"}</td>
                <td className="num pr-2 text-right">{r.n_oos ?? "–"}</td>
                <td className="num pr-2 text-right">{isNum(r.validation?.brier) ? r.validation.brier.toFixed(3) : "–"}</td>
                <td className="num pr-2 text-right">{isNum(r.validation?.directional_accuracy) ? `${Math.round(r.validation.directional_accuracy * 100)}%` : "–"} / {isNum(r.live?.recent?.hit) ? `${Math.round(r.live.recent.hit * 100)}%` : "–"}</td>
                <td className="text-xs text-mute">{(r.reasons ?? []).slice(0, 2).join(" · ") || "—"}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={7} className="py-3 text-mute">Nothing needs attention.</td></tr>}
          </tbody>
        </table>
      </div>
      {tq.overall?.n > 0 && (
        <p className="mt-3 text-xs text-mute">Trade quality (what calls earned, net): {tq.overall.n} closed · avg {tq.overall.avg_r}R · by model confidence: {Object.entries(tq.by_confidence ?? {}).filter(([, s]: any) => s.n).map(([k, s]: any) => `${k}: ${s.avg_r}R (${s.n})`).join(" · ")}. Confidence is a hit-rate estimate, not a win probability.</p>
      )}
      <p className="mt-2 text-xs text-mute">{v.rule}</p>
    </section>
  );
}
