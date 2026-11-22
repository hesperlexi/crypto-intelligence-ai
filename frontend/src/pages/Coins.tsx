// v2.76 Coins (owner, 22 Nov 2026: "where is the coin page?"): every coin we follow in one place - search any coin (opens
// its page), then the market board as a table (trend, signal, AI outlook, futures, notes). Replaces the old Scanner.
import { useState } from "react";
import CoinSearch from "../components/CoinSearch";
import { PageHeader } from "../components/kit";
import MarketBoard from "../components/MarketBoard";
import { ErrorBox } from "../components/ui";
import { useApi } from "../lib/api";

export default function Coins() {
  const [tf, setTf] = useState(() => { try { return localStorage.getItem("cia-coins-tf") || "4h"; } catch { return "4h"; } });
  const pick = (t: string) => { setTf(t); try { localStorage.setItem("cia-coins-tf", t); } catch { /* ignore */ } };
  const dash = useApi<any>(`/dashboard?timeframe=${tf}`, 60000);
  return (
    <div className="space-y-4">
      <PageHeader title="Coins" sub="Tap a coin for its chart, AI view and futures data" />
      <section className="panel coins-search p-4 sm:p-5">
        <h2 className="font-display text-lg font-semibold">Find a coin</h2>
        <p className="mt-1 text-sm text-mute">Type the ticker (e.g. SOL). Coins we don't follow yet can be opened too - press Enter to search Binance.</p>
        <CoinSearch className="mt-3 !max-w-xl" />
      </section>
      {dash.error && <ErrorBox error={dash.error} retry={dash.reload} />}
      <MarketBoard d={dash.data} tf={tf} onTf={pick} loading={dash.loading} viewKey="cia-coins-view" defaultView="table" title="Coins we follow" />
    </div>
  );
}
