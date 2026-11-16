// v2.48 (owner: "I can't find MSTR"): coins searched that exist only as Binance USDⓈ-M perpetuals (no spot market, e.g.
// the MSTR stock perp). The engine reads spot data, so they cannot be followed for AI signals; they open on the Trade
// page's Futures tab for the live chart and demo trading.
// v2.49: coins the engine does follow (binance.isFutOnly, MSTR: candles from MEXC futures) say "AI signals" instead and
// open their coin page.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { isFutOnly, searchFuturesOnly } from "../lib/binance";
import { slug } from "../lib/format";

export default function FutOnlyHits({ query }: { query: string | null }) {
  const [hits, setHits] = useState<string[]>([]);
  useEffect(() => {
    let live = true;
    if (!query) { setHits([]); return; }
    searchFuturesOnly(query).then((h) => { if (live) setHits(h); }).catch(() => live && setHits([]));
    return () => { live = false; };
  }, [query]);
  if (!hits.length) return null;
  const ai = hits.filter(isFutOnly), other = hits.filter((s) => !isFutOnly(s));
  return (
    <>
      {ai.length > 0 && (
        <div className="mt-2 rounded-lg border border-accent/30 bg-accent/[0.06] px-3 py-2 text-sm">
          <div className="text-xs text-mute">Futures only, with AI signals: chart, signals and practice trading</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {ai.map((s) => <Link key={s} to={`/asset/${slug(s)}`} className="btn px-2.5 py-1 text-xs">{s} · AI signals ›</Link>)}
          </div>
        </div>
      )}
      {other.length > 0 && (
        <div className="mt-2 rounded-lg border border-glass/15 bg-glass/[0.03] px-3 py-2 text-sm">
          <div className="text-xs text-mute">Futures only (no AI signals for these): live chart and practice trading</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {other.map((s) => <Link key={s} to={`/paper?market=futures&symbol=${encodeURIComponent(s)}`} className="btn px-2.5 py-1 text-xs">{s} · open in Trade ›</Link>)}
          </div>
        </div>
      )}
    </>
  );
}
