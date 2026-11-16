// v2.44 coin passport (owner: premium upgrade): one card at the top of a coin page with (1) our real record on this
// coin (views/radar.scorecard, after fees), (2) the AI lean on every signal timeframe in one strip (the six /futures
// boards the Signals page uses) and (3) the nearest support / resistance as a ladder around the live price.
import { base, fmtPrice, isNum } from "../lib/format";
import { useApi } from "../lib/api";
import { useTicker } from "../lib/live";
import { Ring } from "./Premium";

const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"] as const;

function useBoards() {
  const b = TFS.map((t) => useApi<any>(`/futures?timeframe=${t}`)); // fixed order and count: hooks stay stable
  return b;
}

function LeanStrip({ symbol }: { symbol: string }) {
  const boards = useBoards();
  return (
    <div>
      <div className="text-xs text-mute">AI lean on every timeframe</div>
      <div className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-6">
        {TFS.map((t, i) => {
          const row = (boards[i].data?.rows ?? []).find((r: any) => r.symbol === symbol);
          const up = row?.p_up, dn = row?.p_down;
          const ok = isNum(up) && isNum(dn);
          const lean = ok ? up - dn : 0;
          const call = row && row.side && row.plan?.valid ? (row.side > 0 ? "LONG" : "SHORT") : null;
          return (
            <div key={t} className={`lean-cell ${call === "LONG" ? "is-long" : call === "SHORT" ? "is-short" : ""}`}>
              <div className="flex items-center justify-between text-xs"><span className="font-semibold">{t.toUpperCase()}</span>{row?.grade && call && <span className="text-accent">{row.grade}</span>}</div>
              <div className="lean-meter" aria-hidden="true"><span style={{ left: `${50 + Math.max(-50, Math.min(50, lean * 100))}%` }} className={lean > 0.05 ? "up" : lean < -0.05 ? "down" : ""} /></div>
              <div className={`text-xs ${call ? (call === "LONG" ? "text-bull" : "text-bear") : "text-mute"}`}>{call ?? (!ok ? "—" : lean > 0.05 ? "leans up" : lean < -0.05 ? "leans down" : "neutral")}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Ladder({ price, a }: { price?: number | null; a: any }) {
  const res = (a?.levels?.zones?.resistance ?? []).map((z: any) => z.mid).filter(isNum).filter((p: number) => !isNum(price) || p > price).sort((x: number, y: number) => x - y).slice(0, 2);
  const sup = (a?.levels?.zones?.support ?? []).map((z: any) => z.mid).filter(isNum).filter((p: number) => !isNum(price) || p < price).sort((x: number, y: number) => y - x).slice(0, 2);
  if (!isNum(price) || (!res.length && !sup.length)) return null;
  const rows: [string, number, string][] = [...res.reverse().map((p: number, i: number) => [`Resistance ${res.length - i}`, p, "text-bear"] as [string, number, string]),
    ["Price now", price, "text-accent"], ...sup.map((p: number, i: number) => [`Support ${i + 1}`, p, "text-bull"] as [string, number, string])];
  return (
    <div>
      <div className="text-xs text-mute">Key levels ({String(a?.timeframe ?? "").toUpperCase()})</div>
      <ul className="lvl-ladder mt-2">
        {rows.map(([k, p, cls]) => (
          <li key={k} className={k === "Price now" ? "is-now" : ""}>
            <span className={`text-xs ${cls}`}>{k}</span>
            <span className="num text-sm">{fmtPrice(p)}{k !== "Price now" && <span className="ml-2 text-xs text-mute">{`${((p / price - 1) * 100) > 0 ? "+" : ""}${((p / price - 1) * 100).toFixed(1)}%`}</span>}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function CoinPassport({ symbol, analysis }: { symbol: string; analysis: any }) {
  const radar = useApi<any>("/radar");
  const tk = useTicker(symbol);
  const coin = (radar.data?.scorecard?.coins ?? []).find((c: any) => c.symbol === symbol);
  const label = radar.data?.scorecard?.labels?.[coin?.category] ?? coin?.category;
  const wr = isNum(coin?.win_rate) ? coin.win_rate : null;
  const name = base(symbol) === "PAXG" ? "GOLD" : base(symbol);
  return (
    <section className="panel passport p-4 sm:p-5" aria-label={`${name} passport`}>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex items-center gap-4">
          <Ring value={wr ?? 0} size={92} stroke={9} tone={wr == null ? "--mute" : wr >= 0.5 ? "--bull" : "--bear"} label={wr == null ? "No closed signals yet" : `${Math.round(wr * 100)}% won`}>
            <div><div className="num text-lg font-semibold">{wr == null ? "—" : `${Math.round(wr * 100)}%`}</div><div className="text-xs leading-none text-mute">won</div></div>
          </Ring>
          <div className="min-w-0">
            <div className="text-xs text-mute">Our record on {name}</div>
            {coin ? (
              <>
                <div className={`num text-xl font-semibold ${isNum(coin.total_net_pct) ? (coin.total_net_pct >= 0 ? "text-bull" : "text-bear") : ""}`}>
                  {isNum(coin.total_net_pct) ? `${coin.total_net_pct > 0 ? "+" : ""}${coin.total_net_pct.toFixed(1)}%` : "—"}
                </div>
                <div className="text-xs text-mute">{coin.closed} closed · {coin.wins} won{coin.open ? ` · ${coin.open} running` : ""} · after fees</div>
                {label && <div className="mt-1 text-xs text-accent">{label}</div>}
              </>
            ) : <div className="text-sm text-mute">No signals on this coin yet.</div>}
          </div>
        </div>
        <LeanStrip symbol={symbol} />
        <Ladder price={tk?.last ?? analysis?.price} a={analysis?.status === "OK" ? analysis : null} />
      </div>
    </section>
  );
}
