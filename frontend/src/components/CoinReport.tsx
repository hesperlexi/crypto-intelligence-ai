// v2.16 AI coin report (Asset page, near the top): trend, key levels, what the AI expects on 4H / 12H, the open call,
// the main risk and the level that would undo the view. Built by the engine from its own analysis (views/coin_reports,
// one document for every coin, at most hourly); an optional AI line is written only from those numbers.
import { Badge, Tile } from "./kit";
import { Card, Info } from "./ui";
import { useApi } from "../lib/api";
import { ago, fmtPrice, slug } from "../lib/format";

type Expect = { timeframe: string; lean: "up" | "down" | null; confidence?: number | null; above_threshold?: boolean; proven_edge?: boolean; note?: string };

const trendTone = (t: string) => (t === "Uptrend" ? "bull" : t === "Downtrend" ? "bear" : t.startsWith("Mixed") || t === "Unsettled" ? "warn" : "mute");

function Lean({ e }: { e: Expect }) {
  if (!e.lean) return <Tile label={`AI ${e.timeframe.toUpperCase()}`} value={<span className="text-base text-mute">—</span>} sub={e.note ?? "no view"} />;
  const up = e.lean === "up";
  return (
    <Tile label={`AI ${e.timeframe.toUpperCase()}`} valueClass={up ? "text-bull" : "text-bear"}
      value={<>{up ? "▲ Up" : "▼ Down"}</>}
      sub={<>{e.confidence != null ? `${Math.round(e.confidence * 100)}% confidence` : "confidence n/a"}{e.above_threshold ? "" : " · weak"}</>} />
  );
}

export default function CoinReport({ symbol }: { symbol: string }) {
  const v = useApi<any>(`/coin-reports/${slug(symbol)}`);
  const r = v.data;
  if (!r) return null;                       // not published yet (new coin, or before the engine's hourly run): no card
  const sup: number[] = r.levels?.support ?? [];
  const res: number[] = r.levels?.resistance ?? [];
  const call = r.call;
  return (
    <Card ai title="AI coin report" right={<Badge tone={trendTone(r.trend?.label ?? "") as any}>{r.trend?.label}</Badge>}>
      <div className="space-y-3">
        {r.ai?.text ? <p className="text-sm leading-relaxed">{r.ai.text}</p> : <p className="text-sm leading-relaxed">{r.summary}</p>}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(r.expects ?? []).map((e: Expect) => <Lean key={e.timeframe} e={e} />)}
          <Tile label="Support (4H)" value={<span className="text-bull">{sup.length ? fmtPrice(sup[0]) : "—"}</span>} sub={sup[1] ? `then ${fmtPrice(sup[1])}` : undefined} />
          <Tile label="Resistance (4H)" value={<span className="text-bear">{res.length ? fmtPrice(res[0]) : "—"}</span>} sub={res[1] ? `then ${fmtPrice(res[1])}` : undefined} />
        </div>
        {call && (
          <p className="rounded-lg border border-glass/[0.08] bg-glass/[0.03] px-3 py-2 text-sm">
            <span className={`font-semibold ${call.side === "LONG" ? "text-bull" : "text-bear"}`}>{call.side}</span>{" "}
            <span className="text-mute">{String(call.timeframe).toUpperCase()} call {call.fill_status === "PENDING" ? "· waiting for entry" : "· running"}</span>
            <span className="num"> · entry {fmtPrice(call.entry)} · stop {fmtPrice(call.stop)} · TP1 {fmtPrice(call.tp1)}</span>
          </p>
        )}
        <ul className="space-y-1.5 text-sm">
          <li className="flex gap-2"><span className="w-24 shrink-0 text-xs font-semibold uppercase tracking-wide text-warn">Main risk</span><span>{r.risk}</span></li>
          {r.invalidation?.text && <li className="flex gap-2"><span className="w-24 shrink-0 text-xs font-semibold uppercase tracking-wide text-mute">Invalidation</span><span>{r.invalidation.text}</span></li>}
        </ul>
        <p className="text-xs text-mute">
          {r.ai?.text ? `AI line ${ago(r.ai.at)} · ` : ""}From the engine's analysis. Context, not advice.
          <Info label="How this report is made">Trend = 4H and 1D regimes. AI lean and confidence come from the coin's 4H and 12H models (the same figures as on the Signals page); "weak" means below the model's proven threshold. Levels are the nearest 4H support and resistance zones. Updated at most hourly.</Info>
        </p>
      </div>
    </Card>
  );
}
