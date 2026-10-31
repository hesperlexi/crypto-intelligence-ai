import { useMemo } from "react";
import { Link } from "react-router-dom";
import { GradeBadge } from "../components/TradeCall";
import { LogFilters, useLogFilters } from "../components/LogFilters";
import { Badge, Card, Empty, ErrorBox, Loading, SignalBadge, signalTone, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { RoiFigure } from "../components/SignalExtras";
import { DASH, fmtDate, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, slug, tone } from "../lib/format";
import { UpdatedBadge } from "../components/SignalAdjust";

const hit = (v: number, tracked: boolean) => (!tracked ? <span className="text-mute">{DASH}</span> : v ? <span className="text-bull">HIT</span> : <span className="text-mute">not hit</span>);

export default function History() {
  const h = useApi<any>("/signals/history?limit=300", 60000);
  const sum = h.data?.summary;
  const all: any[] = h.data?.signals ?? [];
  const f = useLogFilters();
  const shown = useMemo(() => f.apply(all), [all, f.apply]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="space-y-4">
      <h1 className="page-title">Signal history</h1>
      {h.error && <ErrorBox error={h.error} retry={h.reload} />}
      {sum && (
        <Card title="Tracked trade signals">
          {sum.closed ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="Closed signals" value={sum.closed} />
              <Stat label="Win rate" value={fmtProb(sum.win_rate, 1)} />
              <Stat label={isNum(sum.avg_roi_pct) ? "Average ROI on margin" : "Average price move"} value={<span className={tone(isNum(sum.avg_roi_pct) ? sum.avg_roi_pct : sum.avg_return_pct)}>{fmtPctRaw(isNum(sum.avg_roi_pct) ? sum.avg_roi_pct : sum.avg_return_pct)}</span>} />
              <Stat label="Outcomes" value={<span className="text-sm">{Object.entries(sum.by_status).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>} />
            </div>
          ) : <Empty>{sum.note} Only signals this installation actually issued are counted; nothing is back-filled.</Empty>}
        </Card>
      )}
      <Card title="All logged signals">
        {h.data && <LogFilters f={f} total={all.length} shown={shown.length} />}
        {!h.data && h.loading && <Loading />}
        <div className="table-wrap">
          <table className="grid-table">
            <thead><tr><th>When</th><th>Asset</th><th>TF</th><th>Grade</th><th>Signal</th><th>Decision</th><th className="text-right">Price</th><th className="text-right">Conf.</th><th className="text-right">Stop</th><th>TP1</th><th>TP2</th><th>TP3</th><th>Stop hit</th><th>Status</th><th className="text-right">ROI on margin</th></tr></thead>
            <tbody>
              {shown.map((s: any) => {
                const tracked = s.side !== 0;
                return (
                  <tr key={s.id} title={s.payload?.decision_reason ?? ""}>
                    <td className="text-mute" title={fmtTime(s.created_at)}>{fmtDate(s.created_at)}</td>
                    <td><Link className="font-medium hover:text-accent" to={`/asset/${slug(s.symbol)}`}>{s.symbol}</Link></td>
                    <td className="uppercase text-mute">{s.timeframe}</td>
                    <td>{tracked ? <GradeBadge grade={s.payload?.grade} small /> : null}</td>
                    <td><SignalBadge signal={s.signal} /></td><td><Badge tone={signalTone(s.decision)}>{s.decision}</Badge></td>
                    <td className="num text-right">{fmtPrice(s.price)}</td><td className="num text-right">{fmtProb(s.confidence)}</td>
                    <td className="num text-right" title={s.adjustments?.length ? s.adjustments.map((a: any) => `${a.field === "stop" ? "Stop-loss" : "TP1"} ${fmtPrice(a.old)} → ${fmtPrice(a.new)} · ${a.note}`).join("\n") : undefined}>{fmtPrice(s.stop)}</td>
                    <td>{hit(s.tp1_hit, tracked)}</td><td>{hit(s.tp2_hit, tracked)}</td><td>{hit(s.tp3_hit, tracked)}</td>
                    <td>{!tracked ? <span className="text-mute">{DASH}</span> : s.stop_hit ? <span className="text-bear">HIT</span> : <span className="text-mute">not hit</span>}</td>
                    <td><UpdatedBadge adj={s.adjustments} /> <Badge tone={s.status === "OPEN" ? "accent" : s.status === "STOPPED" ? "bear" : s.status.startsWith("TP") ? "bull" : "mute"}>{s.status === "INFO" ? "not traded" : s.status === "NOT_FILLED" ? "NOT FILLED" : s.status}</Badge>{s.exit_reason === "break_even" && <span className="ml-1 text-[11px] text-mute">· break-even</span>}{s.status === "OPEN" && s.fill_status === "PENDING" && <span className="ml-1 text-[11px] text-mute">· waiting for entry</span>}</td>
                    <td className="text-right">{isNum(s.return_pct) && tracked ? <RoiFigure x={s} size="sm" /> : <span className="text-mute">{DASH}</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {h.data && !all.length && <Empty>No signals logged yet. A row is added whenever an asset's signal or decision changes.</Empty>}
        {h.data && all.length > 0 && !shown.length && <Empty>No signals match these filters. <button className="text-accent hover:underline" onClick={f.clear}>Clear all filters</button></Empty>}
      </Card>
    </div>
  );
}
