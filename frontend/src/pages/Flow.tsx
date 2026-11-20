// v2.62 Money flow page (owner, 20 Nov 2026). Live from Binance futures public streams in the browser + 24 h net flow
// from public klines. No Firestore reads or writes.
import { useState } from "react";
import { PageHeader } from "../components/kit";
import { Card } from "../components/ui";
import { FlowRiver, FlowStats, FundingBars, NetFlowSankey, useFlowFeed, WhaleWatch, WipeOuts } from "../components/MoneyFlow";
import { useApi } from "../lib/api";

export default function Flow() {
  const feed = useFlowFeed();
  const [paused, setPaused] = useState(false);
  const meta = useApi<any>("/meta");
  const symbols: string[] = (meta.data?.watchlist ?? []).map((w: any) => w.symbol).filter((s: string) => !/MSTR/.test(s));
  return (
    <div className="space-y-4">
      <PageHeader title="Money flow" sub="Every trade on Bitcoin, Ether, Solana and gold, live from Binance futures." />
      <section className="panel panel-hero mf-hero">
        <div className="mf-head">
          <div className="flex items-center gap-2 text-sm">
            <span className={`mf-live ${feed.live ? "is-on" : ""}`} aria-hidden="true" />
            <span className="text-mute">{feed.live ? "Live · Binance futures" : "Connecting…"}</span>
          </div>
          <button type="button" className="btn px-3 py-1 text-xs" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>{paused ? "Resume motion" : "Pause motion"}</button>
        </div>
        <FlowRiver feed={feed} paused={paused} />
        <div className="mf-legend">
          <span><i className="bg-bull" /> buyers in</span><span><i className="bg-bear" /> sellers out</span><span><i className="bg-warn" /> bets wiped out</span><span className="text-mute">dot size = trade size</span>
        </div>
        <FlowStats feed={feed} />
      </section>

      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <Card title="Whale watch" right={<span className="text-xs text-mute">big trades, live</span>}><WhaleWatch feed={feed} /></Card>
        <Card title="Wipe-outs" right={<span className="text-xs text-mute">forced closes since you opened the page</span>}><WipeOuts feed={feed} /></Card>
      </div>

      <div className="grid-even grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card title="Where money moved, 24 hours" right={<span className="text-xs text-mute">buy minus sell volume · your coins</span>}>
          {symbols.length ? <NetFlowSankey symbols={symbols} /> : <div className="skeleton h-72 rounded-xl" />}
          <p className="mt-2 text-xs text-mute">Left: more money sold than bought. Right: more bought than sold. Thicker = bigger difference.</p>
        </Card>
        <Card title="Funding thermometer" right={<span className="text-xs text-mute">who pays whom</span>}><FundingBars feed={feed} /></Card>
      </div>
    </div>
  );
}
