// Opportunity radar: coins outside the app's list that are outperforming the market, with the screen's own record.
import { useState } from "react";
import { Link } from "react-router-dom";
import { saveMine } from "../components/MyCoins";
import { CoinAvatar } from "../components/Polish";
import { Empty, ErrorBox, Info, Loading, Tile } from "../components/ui";
import { post, useApi } from "../lib/api";
import { ago, base, fmtNum, fmtPrice, fmtTime, isNum } from "../lib/format";
import { useLimits } from "../lib/limits";
import { useIsAdmin } from "../lib/session";

const pct = (v: unknown, d = 0) => (isNum(v) ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%` : "—");
const tone = (v: unknown) => (isNum(v) ? (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "") : "text-mute");

/** A radar figure that has no value yet: a calm word instead of a bare dash. */
const Waiting = () => <span className="text-base font-normal text-mute">Not yet</span>;

export default function Radar() {
  const v = useApi<any>("/radar");
  const meta = useApi<any>("/meta");
  const admin = useIsAdmin();
  const limit = useLimits().member_coin_limit;
  const [msg, setMsg] = useState<string | null>(null);
  const mine: string[] = meta.data?.my_coins ?? [];
  const have = new Set<string>([...(meta.data?.watchlist ?? []).map((w: any) => w.symbol), ...mine]);
  const add = async (s: string) => {
    try {
      if (admin) await post("/watchlist", { symbol: s });
      else {
        if (mine.length >= limit) throw new Error(`You can follow up to ${limit} coins of your own. Remove one on the dashboard first.`);
        await saveMine([...mine, s], limit);
      }
      setMsg(`${s} added${admin ? " for everyone" : " to your coins"}. Live price now; AI signals follow once its model is trained (usually within a few engine runs).`);
      meta.reload?.();
    } catch (e: any) { setMsg(e.message); }
  };
  if (v.loading && !v.data) return <Loading />;
  if (v.error) return /not published/i.test(v.error) ? <Empty>The radar runs once an hour; the first scan appears after the next engine run.</Empty> : <ErrorBox error={v.error} retry={v.reload} />;
  const d = v.data ?? {};
  const h = d.historical ?? {}, live = d.live ?? {};

  const Card = ({ p }: { p: any }) => (
    <li className="panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="font-display w-6 text-center text-lg font-bold text-accent/70">{p.rank}</span>
          <CoinAvatar symbol={p.symbol} size={34} />
          <div className="min-w-0">
            <div className="font-display text-lg font-bold leading-tight">{base(p.symbol)}<span className="text-sm font-normal text-mute">/USDT</span></div>
            <div className="num text-xs text-mute">{fmtPrice(p.price)} · <span className={tone(p.change_24h_pct)}>{isNum(p.change_24h_pct) ? `${p.change_24h_pct > 0 ? "+" : ""}${p.change_24h_pct.toFixed(1)}%` : "—"} 24h</span> · vol ${fmtNum(p.quote_volume / 1e6, 0)}M</div>
          </div>
        </div>
        {have.has(p.symbol)
          ? <span className="shrink-0 rounded-lg border border-glass/15 px-3 py-1.5 text-xs text-mute">Following</span>
          : <button className="btn btn-primary shrink-0 px-3 py-1.5 text-xs" onClick={() => add(p.symbol)}>+ Add</button>}
      </div>
      <div className="num mt-3 grid grid-cols-3 gap-2 text-xs">
        <div><div className="text-mute">vs BTC 7d</div><div className={`text-sm font-semibold ${tone(p.rs_7d)}`}>{pct(p.rs_7d)}</div></div>
        <div><div className="text-mute">vs BTC 30d</div><div className={`text-sm font-semibold ${tone(p.rs_30d)}`}>{pct(p.rs_30d)}</div></div>
        <div><div className="text-mute">Volume</div><div className="text-sm font-semibold">{isNum(p.vol_surge) ? `${p.vol_surge.toFixed(1)}x` : "—"}</div></div>
      </div>
      {p.reasons?.length > 0 && <ul className="mt-2 flex flex-wrap gap-1.5">{p.reasons.map((r: string) => <li key={r} className={`rounded-md px-2 py-0.5 text-xs ${r.includes("extended") ? "bg-warn/15 text-warn" : "bg-glass/[0.06] text-text/80"}`}>{r}</li>)}</ul>}
    </li>
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">Radar · coins to watch</h1>
        <p className="text-sm text-mute">Coins beating the market, updated hourly. Ideas, not trade signals.</p>
      </div>
      {msg && <div role="status" className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-sm">{msg}</div>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {/* UI v2.15: shared Tile; a figure that does not exist yet says so in words instead of a bare dash */}
        <Tile variant="box" className="panel" label="Coins screened" value={d.screened ?? <Waiting />} sub={d.generated_at ? `updated ${ago(d.generated_at)}` : "first scan after the next engine run"} />
        <Tile variant="box" className="panel" label="Past check: top 5 vs BTC" valueClass={tone(h.avg_excess_vs_btc_pct)} value={isNum(h.avg_excess_vs_btc_pct) ? `${h.avg_excess_vs_btc_pct > 0 ? "+" : ""}${h.avg_excess_vs_btc_pct.toFixed(1)}%` : <Waiting />} sub={`avg over the next 7 days · ${h.days ?? 0} test days`} />
        <Tile variant="box" className="panel" label="Past check: beat BTC" value={isNum(h.beat_btc_rate) ? `${Math.round(h.beat_btc_rate * 100)}%` : <Waiting />} sub="of test days" />
        <Tile variant="box" className="panel" label="Live record" value={isNum(live.beat_btc_rate) ? `${Math.round(live.beat_btc_rate * 100)}%` : <Waiting />} sub={live.evaluated ? `${live.evaluated} picks scored after 7 days` : `${live.picks ?? 0} picks logged · first scores in 7 days`} />
      </div>
      <ul className="grid gap-3 md:grid-cols-2">{(d.picks ?? []).map((p: any) => <Card key={p.symbol} p={p} />)}</ul>
      {(d.extended ?? []).length > 0 && (
        <section>
          <h2 className="label mb-2">Hot but already extended: wait for a pullback</h2>
          <ul className="grid gap-3 md:grid-cols-3">{d.extended.map((p: any) => <Card key={p.symbol} p={p} />)}</ul>
        </section>
      )}
      {(live.recent ?? []).length > 0 && (
        <section className="panel p-0">
          <div className="card-head border-b border-glass/[0.06] px-4 py-2.5"><h2 className="label">Radar picks and how they did after 7 days</h2></div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wide text-mute"><th className="px-4 py-2">Coin</th><th>Picked</th><th>Price then</th><th>7 days later</th><th className="pr-4 text-right">vs BTC</th></tr></thead>
              <tbody className="divide-y divide-glass/[0.06]">
                {live.recent.map((r: any, i: number) => {
                  const ex = isNum(r.ret_7d) && isNum(r.btc_ret_7d) ? r.ret_7d - r.btc_ret_7d : null;
                  return <tr key={i}><td className="px-4 py-2 font-semibold">{base(r.symbol)}</td><td className="text-xs text-mute">{fmtTime(r.ts)} · #{r.rank}</td><td className="num">{fmtPrice(r.price)}</td>
                    <td className={`num ${tone(r.ret_7d)}`}>{isNum(r.ret_7d) ? pct(r.ret_7d, 1) : "pending"}</td><td className={`num pr-4 text-right font-semibold ${tone(ex)}`}>{ex != null ? pct(ex, 1) : "…"}</td></tr>;
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <p className="text-xs text-mute">Added coins appear on the <Link to="/" className="text-accent hover:underline">dashboard</Link> and in Signals. {(d.method || h.note) && <Info label="How the radar works">{d.method} {h.note}</Info>}</p>
    </div>
  );
}
