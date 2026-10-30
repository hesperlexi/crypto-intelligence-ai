import { Link } from "react-router-dom";
import { Badge, Card, Empty, ErrorBox, Loading, SignalBadge, signalTone, Stat } from "../components/ui";
import { useApi } from "../lib/api";
import { DASH, fmtDate, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, slug, tone } from "../lib/format";

const hit = (v: number, tracked: boolean) => (!tracked ? <span className="text-mute">{DASH}</span> : v ? <span className="text-bull">HIT</span> : <span className="text-mute">not hit</span>);

export default function History() {
  const h = useApi<any>("/signals/history?limit=300", 60000);
  const sum = h.data?.summary;
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
              <Stat label="Average return" value={<span className={tone(sum.avg_return_pct)}>{fmtPctRaw(sum.avg_return_pct)}</span>} />
              <Stat label="Outcomes" value={<span className="text-sm">{Object.entries(sum.by_status).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>} />
            </div>
          ) : <Empty>{sum.note} Only signals this installation actually issued are counted; nothing is back-filled.</Empty>}
        </Card>
      )}
      <Card title="All logged signals">
        {!h.data && h.loading && <Loading />}
        <div className="table-wrap">
          <table className="grid-table">
            <thead><tr><th>When</th><th>Asset</th><th>TF</th><th>Signal</th><th>Decision</th><th className="text-right">Price</th><th className="text-right">Conf.</th><th className="text-right">Stop</th><th>TP1</th><th>TP2</th><th>TP3</th><th>Stop hit</th><th>Status</th><th className="text-right">Return</th></tr></thead>
            <tbody>
              {(h.data?.signals ?? []).map((s: any) => {
                const tracked = s.side !== 0;
                return (
                  <tr key={s.id} title={s.payload?.decision_reason ?? ""}>
                    <td className="text-mute" title={fmtTime(s.created_at)}>{fmtDate(s.created_at)}</td>
                    <td><Link className="font-medium hover:text-accent" to={`/asset/${slug(s.symbol)}`}>{s.symbol}</Link></td>
                    <td className="uppercase text-mute">{s.timeframe}</td>
                    <td><SignalBadge signal={s.signal} /></td><td><Badge tone={signalTone(s.decision)}>{s.decision}</Badge></td>
                    <td className="num text-right">{fmtPrice(s.price)}</td><td className="num text-right">{fmtProb(s.confidence)}</td>
                    <td className="num text-right">{fmtPrice(s.stop)}</td>
                    <td>{hit(s.tp1_hit, tracked)}</td><td>{hit(s.tp2_hit, tracked)}</td><td>{hit(s.tp3_hit, tracked)}</td>
                    <td>{!tracked ? <span className="text-mute">{DASH}</span> : s.stop_hit ? <span className="text-bear">HIT</span> : <span className="text-mute">not hit</span>}</td>
                    <td><Badge tone={s.status === "OPEN" ? "accent" : s.status === "STOPPED" ? "bear" : s.status.startsWith("TP") ? "bull" : "mute"}>{s.status === "INFO" ? "not traded" : s.status}</Badge></td>
                    <td className={`num text-right ${tone(s.return_pct)}`}>{isNum(s.return_pct) && tracked ? fmtPctRaw(s.return_pct) : DASH}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {h.data && !h.data.signals.length && <Empty>No signals logged yet. A row is added whenever an asset's signal or decision changes.</Empty>}
      </Card>
    </div>
  );
}
