// V3.3 Stage 2 (admin, Performance Lab): portfolio risk now, results by market regime, and the ML shadow report.
// Figures come from views/perf_lab (portfolio, by_regime, ml_shadow). Nothing here changes a call.
import { Badge } from "./kit";
import { isNum } from "../lib/format";

const r2 = (x: any, d = 2) => (isNum(x) ? `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}R` : "–");
const tn = (x: any) => (isNum(x) ? (x > 0 ? "text-bull" : x < 0 ? "text-bear" : "") : "text-mute");
const ci = (s: any) => (s?.ci95_avg_r ? `95 %: ${r2(s.ci95_avg_r[0])} to ${r2(s.ci95_avg_r[1])}` : "too few for an interval");

function Line({ k, s }: { k: string; s: any }) {
  return (
    <tr>
      <td className="py-1.5 pr-2">{k}</td>
      <td className="num text-right">{s?.n ?? 0}</td>
      <td className={`num text-right ${tn(s?.avg_r)}`}>{r2(s?.avg_r, 3)}</td>
      <td className={`num text-right ${tn(s?.total_r)}`}>{r2(s?.total_r)}</td>
      <td className="hidden text-right text-xs text-mute sm:table-cell">{ci(s)}</td>
    </tr>
  );
}

function Table({ rows }: { rows: [string, any][] }) {
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-xs text-mute"><th className="pb-1">Group</th><th className="text-right">Closed</th>
        <th className="text-right">Avg</th><th className="text-right">Total</th><th className="hidden text-right sm:table-cell">Interval</th></tr></thead>
      <tbody className="divide-y divide-glass/[0.06]">{rows.map(([k, s]) => <Line key={k} k={k} s={s} />)}</tbody>
    </table>
  );
}

export function PortfolioCard({ p }: { p: any }) {
  if (!p) return null;
  if (!p.available) return <section className="xeno-panel p-4"><h2 className="label mb-1">Portfolio risk</h2><p className="text-sm text-bear">Unavailable: new entries are refused until it can be read.</p></section>;
  const lim = p.limits ?? {};
  const st = p.drawdown_state?.state ?? "NORMAL";
  const bar = (v: number, max: number) => (
    <div className="h-1.5 w-full rounded-full bg-glass/[0.08]"><div className={`h-1.5 rounded-full ${v / max >= 0.8 ? "bg-bear" : "bg-accent"}`} style={{ width: `${Math.min(100, (v / max) * 100)}%` }} /></div>
  );
  return (
    <section className="xeno-panel space-y-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="label">Portfolio risk · record</h2>
        <Badge tone={st === "NORMAL" ? "bull" : st === "HALT" ? "bear" : "warn"}>{st === "NORMAL" ? "normal" : st.toLowerCase()}</Badge>
      </div>
      {[["Open risk", p.open_r, lim.max_open_r], ["Longs", p.by_side_r?.long, lim.max_side_r], ["Shorts", p.by_side_r?.short, lim.max_side_r],
        ["BTC-correlated longs", p.btc_correlated_r?.long, lim.max_corr_r], ["BTC-correlated shorts", p.btc_correlated_r?.short, lim.max_corr_r]]
        .map(([k, v, m]: any) => (
          <div key={k} className="space-y-1">
            <div className="flex justify-between text-xs"><span className="text-mute">{k}</span><span className="num">{Number(v ?? 0).toFixed(2)}R of {m}R</span></div>
            {bar(Number(v ?? 0), Number(m || 1))}
          </div>
        ))}
      <p className="text-xs text-mute">
        {p.positions} open or pending · ≈ {p.equity_at_risk_pct_ref}% of equity at the {p.risk_per_trade_pct_ref}% reference size
        {p.drawdown?.dd_r != null && ` · drawdown ${Number(p.drawdown.dd_r).toFixed(1)}R (halt at ${lim.dd_limit_r}R)`}
        {p.mode !== "enforce" && ` · mode ${p.mode}`}
      </p>
    </section>
  );
}

export function RegimeCard({ rows }: { rows: any[] }) {
  if (!rows?.length) return null;
  return (
    <section className="xeno-panel p-4">
      <h2 className="label mb-2">By market risk state at publication</h2>
      <Table rows={rows.map((r) => [r.key === "unknown" ? "not recorded" : String(r.key).toLowerCase(), r])} />
    </section>
  );
}

export function MlShadowCard({ m }: { m: any }) {
  if (!m) return null;
  if (m.available === false) return null;
  const f = m.freshness ?? {};
  return (
    <section className="xeno-panel space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="label">AI filters in shadow</h2>
        <Badge tone="ai">{m.mode?.trade_filter_enforce ? "filters enforcing" : "shadow: nothing blocked"}</Badge>
      </div>
      <p className="text-sm">{m.verdict}</p>
      <Table rows={[["Would have been blocked", m.would_block], ["Let through", m.allowed], ["Runner would let it run", m.would_run]]} />
      <div className="grid gap-2 text-xs text-mute sm:grid-cols-2">
        <div>
          <div className="label mb-1">Scored candles · kept share</div>
          {Object.keys(m.shadow_scored ?? {}).length === 0 ? "none yet" :
            Object.entries(m.shadow_scored).map(([k, s]: any) => (
              <div key={k}>{k.replace("|", " · ")}: {s.n} · kept {isNum(s.kept_share) ? `${Math.round(s.kept_share * 100)}%` : "–"}
                {isNum(s.keep_fraction) ? ` (aim ${Math.round(s.keep_fraction * 100)}%)` : ""}</div>))}
        </div>
        <div>
          <div className="label mb-1">Models</div>
          {Object.entries(f.ages ?? {}).map(([tf, a]: any) => (
            <div key={tf}>{tf}: {a.n} · median {a.median_h} h{a.older_than_48h ? <span className="text-warn"> · {a.older_than_48h} older than 48 h</span> : ""}</div>))}
          {["trade_filter", "runner_model"].map((k) => f.addons?.[k] && (
            <div key={k}>{k.replace("_", " ")}: {f.addons[k].validated} validated of {f.addons[k].enabled} on · {f.addons[k].unknown} not yet reported</div>))}
        </div>
      </div>
      <p className="text-xs text-mute">{m.note}</p>
    </section>
  );
}
