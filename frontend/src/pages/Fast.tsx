import FastRadar from "../components/FastRadar";
import { Card, ErrorBox } from "../components/ui";
import { useApi } from "../lib/api";
import { ago, isNum } from "../lib/format";

/* V3.4 Stage 5 · Opportunities → Fast radar (EXPERIMENTAL, display only). Meme coins and altcoins ranked on closed 1h or 4h
   data with every reason and warning (views/radar.fast). It is never a signal: nothing here is traded or published, and
   the "how they did" figures are price moves after a coin appeared, before costs - not trade results. */

const pct = (x: any, d = 1) => (isNum(x) ? `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}%` : "–");
const tone = (x: any) => (isNum(x) ? (x > 0 ? "text-bull" : x < 0 ? "text-bear" : "") : "text-mute");

function Tracked({ t }: { t: any }) {
  const cell = (k: string, label: string) => {
    const s = t?.[k] ?? {};
    return (
      <div className="rounded-lg px-3 py-2.5" style={{ border: "1px solid var(--hair)" }}>
        <div className="text-xs text-mute">{label}</div>
        <div className="num mt-0.5 text-lg font-semibold">{isNum(s.worked_share) ? `${Math.round(s.worked_share * 100)}%` : "—"}</div>
        <div className="text-xs text-mute">beat BTC within 24 h · {s.n ?? 0} checked{s.n && !s.enough ? " (too few to judge)" : ""}</div>
        <div className={`num text-xs ${tone(s.avg_rs_24h_pct)}`}>avg {pct(s.avg_rs_24h_pct, 2)} vs BTC{s.ci95 ? ` · 95 %: ${pct(s.ci95[0], 2)} to ${pct(s.ci95[1], 2)}` : ""}</div>
      </div>
    );
  };
  return (
    <Card title="How past appearances did" right={<span className="text-xs text-mute">{t?.tracking ?? 0} still being followed</span>}>
      <div className="grid gap-3 sm:grid-cols-3">{cell("meme", "Meme coins")}{cell("alt", "Altcoins")}{cell("all", "All")}</div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-mute"><th className="py-1.5 pr-3 font-normal">Coin</th><th className="py-1.5 pr-3 font-normal">First seen</th><th className="py-1.5 pr-3 text-right font-normal">4 h vs BTC</th><th className="py-1.5 pr-3 text-right font-normal">24 h vs BTC</th><th className="py-1.5 text-right font-normal">72 h vs BTC</th></tr></thead>
          <tbody>
            {(t?.recent ?? []).map((r: any) => (
              <tr key={`${r.coin}${r.first_seen}`} className="border-t" style={{ borderColor: "var(--hair)" }}>
                <td className="py-2 pr-3 font-medium">{r.coin} <span className="text-xs font-normal text-mute">{r.category}</span></td>
                <td className="py-2 pr-3 text-xs text-mute">{ago(r.first_seen)}</td>
                <td className={`num py-2 pr-3 text-right ${tone(r.rs_4h)}`}>{pct(r.rs_4h)}</td>
                <td className={`num py-2 pr-3 text-right ${tone(r.rs_24h)}`}>{pct(r.rs_24h)}</td>
                <td className={`num py-2 text-right ${tone(r.rs_72h)}`}>{pct(r.rs_72h)}</td>
              </tr>
            ))}
            {!(t?.recent ?? []).length && <tr><td colSpan={5} className="py-3 text-mute">Nothing has appeared yet.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-mute">{t?.basis ?? "Price move after the coin first appeared, vs BTC, before costs; not a trade result."}</p>
    </Card>
  );
}

export default function Fast() {
  const r = useApi<any>("/radar", 300_000);
  const f = r.data?.fast;
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">Fast radar</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">Experimental: fast-moving coins ranked with reasons and warnings. Display only, never a signal.</p>
      </header>
      <div className="exp-banner" role="note">
        <span className="v3-pill v3-watch">Experimental</span>
        <span>Not a validated trading signal. Nothing here is traded or published; memecoins can drop fast and cost more to trade.</span>
      </div>
      {r.error && <ErrorBox error={r.error} retry={r.reload} />}
      {!r.data && !r.error && <div className="skeleton h-64 rounded-xl" />}
      {f && (
        <>
          <div className="grid-even grid gap-4 xl:grid-cols-2">
            <FastRadar fast={f} category="meme" title="Meme coins" />
            <FastRadar fast={f} category="alt" title="Altcoins" />
          </div>
          {(f.not_covered ?? []).length > 0 && <p className="text-xs text-mute">Not covered (no Binance or MEXC spot pair): {f.not_covered.join(", ")}.</p>}
          <Tracked t={f.tracking} />
        </>
      )}
      {r.data && !f && <p className="text-sm text-mute">The fast scan has not run yet. It runs hourly.</p>}
    </div>
  );
}
