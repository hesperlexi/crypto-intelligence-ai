// V3.3 Fast Opportunity Radar (display only): a ranked list of fast-moving coins on 1h data with the reasons and the
// warnings for each. Comes inside views/radar as `fast` (hourly). Never a signal: no trade button, nothing is followed.
import { useState } from "react";
import { Badge } from "./kit";
import { Info } from "./ui";
import { ago, fmtPrice, isNum } from "../lib/format";

const pct = (x: any, d = 1) => (isNum(x) ? `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}%` : "–");
const tone = (x: any) => (isNum(x) ? (x > 0 ? "text-bull" : x < 0 ? "text-bear" : "") : "text-mute");
const vol = (x: any) => (isNum(x) ? (x >= 1e9 ? `$${(x / 1e9).toFixed(1)}B` : `$${(x / 1e6).toFixed(0)}M`) : "–");

function Row({ c }: { c: any }) {
  const [open, setOpen] = useState(false);
  const warn = (c.warnings ?? []).length;
  return (
    <li className="border-b border-glass/[0.06] last:border-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="grid w-full grid-cols-[2rem_1fr_auto] items-center gap-2 px-4 py-2.5 text-left sm:grid-cols-[2rem_7rem_1fr_6rem_6rem_6rem]">
        <span className="num text-xs text-mute">#{c.rank}</span>
        <span className="font-semibold">{c.coin}{warn > 0 && <span className="ml-2 text-xs font-normal text-warn sm:hidden">⚠ {warn}</span>}</span>
        <span className="hidden truncate text-xs text-mute sm:block">{(c.reasons ?? [])[0] ?? "no standout strength"}</span>
        <span className={`num text-right text-sm ${tone(c.rs_24h_pct)}`} title="vs BTC, 24 h">{pct(c.rs_24h_pct)}</span>
        <span className={`num hidden text-right text-sm sm:block ${tone(c.rs_7d_pct)}`} title="vs BTC, 7 days">{pct(c.rs_7d_pct)}</span>
        <span className="hidden justify-self-end sm:block">
          {warn ? <Badge tone="warn">{warn} warning{warn > 1 ? "s" : ""}</Badge> : <Badge tone="mute">no warnings</Badge>}
        </span>
      </button>
      {open && (
        <div className="grid gap-3 px-4 pb-3 text-sm sm:grid-cols-2">
          <div>
            <div className="label mb-1">Why it ranks here</div>
            <ul className="list-disc space-y-0.5 pl-4 text-mute">
              {(c.reasons ?? []).length ? c.reasons.map((r: string) => <li key={r}>{r}</li>) : <li>no standout strength</li>}
            </ul>
            <div className="mt-2 text-xs text-mute">
              Price {fmtPrice(c.price)} · 24 h {pct(c.ret_24h_pct)} · RSI {isNum(c.rsi14) ? Math.round(c.rsi14) : "–"} · volume {vol(c.quote_volume_24h)}
              {isNum(c.volume_expansion) && ` (${c.volume_expansion.toFixed(1)}x)`} · spread {isNum(c.spread_bps) ? `${c.spread_bps.toFixed(1)} bps` : "unknown"}
            </div>
          </div>
          <div>
            <div className="label mb-1">Warnings</div>
            <ul className="list-disc space-y-0.5 pl-4">
              {(c.warnings ?? []).length ? c.warnings.map((w: string) => <li key={w} className="text-warn">{w}</li>) : <li className="text-mute">none</li>}
            </ul>
          </div>
        </div>
      )}
    </li>
  );
}

export default function FastRadar({ fast }: { fast: any }) {
  if (!fast) return null;
  const list = (fast.coins ?? []).filter((c: any) => isNum(c.score));
  return (
    <section className="panel p-0">
      <div className="card-head flex flex-wrap items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-2.5">
        <h2 className="label">Fast movers · 1h</h2>
        <span className="text-xs text-mute">
          Display only · not a signal{fast.generated_at ? ` · updated ${ago(fast.generated_at)}` : ""}
          {fast.regime && ` · market risk ${String(fast.regime).toLowerCase()}`}
        </span>
      </div>
      {!fast.available ? (
        <p className="px-4 py-3 text-sm text-mute">The fast scan is not available right now.</p>
      ) : list.length === 0 ? (
        <p className="px-4 py-3 text-sm text-mute">No coin has enough 1h history yet.</p>
      ) : (
        <>
          <div className="hidden grid-cols-[2rem_7rem_1fr_6rem_6rem_6rem] gap-2 px-4 pt-2 text-xs text-mute sm:grid">
            <span>#</span><span>Coin</span><span>Main reason</span><span className="text-right">vs BTC 24h</span>
            <span className="text-right">vs BTC 7d</span><span className="text-right">Risk</span>
          </div>
          <ul>{list.map((c: any) => <Row key={c.coin} c={c} />)}</ul>
        </>
      )}
      <p className="px-4 py-2 text-xs text-mute">
        {(fast.not_covered ?? []).length > 0 && `Not covered (no Binance spot pair): ${fast.not_covered.join(", ")}. `}
        <Info label="How fast movers are ranked">
          Each coin gets points for strength against BTC (24 h and 7 days), its 1h trend, momentum and a volume surge; every
          warning (parabolic move, thin volume, wide spread, wick-heavy candles, a one-candle pump, volume without a price
          move, short history, a risk-off market) takes points away. Only closed candles are used. Memecoins cost more to
          trade than the large coins, and nothing here is traded or followed by the app.
        </Info>
      </p>
    </section>
  );
}
