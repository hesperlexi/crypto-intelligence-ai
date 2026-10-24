import { useState } from "react";
import { Link } from "react-router-dom";
import { api, del, post, put, useApi } from "../lib/api";
import { base, fmtPctRaw, fmtPrice, slug, tone } from "../lib/format";
import { useLive } from "../lib/live";
import { useIsAdmin } from "../lib/session";
import { Card } from "./ui";

/** Live price tiles for every coin on the watchlist, with add / remove / pin in place. */
export default function MyCoins({ rows }: { rows?: any[] }) {
  const { tickers } = useLive();
  const admin = useIsAdmin();
  const meta = useApi<any>("/meta");
  const [edit, setEdit] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const list: { symbol: string; pinned: number }[] = [...(meta.data?.watchlist ?? [])].sort((a, b) => b.pinned - a.pinned);

  const act = async (fn: () => Promise<any>, done: string) => {
    try { await fn(); setMsg(done); meta.reload?.(); } catch (e: any) { setMsg(e.message); }
  };
  const search = async () => {
    const q = query.trim();
    if (!q) return;
    try { setResults((await api<any>(`/search?q=${encodeURIComponent(q)}`)).results); setMsg(null); } catch (e: any) { setMsg(e.message); }
  };

  return (
    <Card title="My coins" right={!admin ? undefined :
      <button className={`btn px-2.5 py-1 text-xs ${edit ? "btn-on" : ""}`} onClick={() => { setEdit((v) => !v); setResults(null); setMsg(null); }}>
        {edit ? "Done" : "+ Add / edit"}
      </button>}>
      {edit && (
        <div className="mb-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <input className="input w-full sm:w-56" placeholder="Search a coin, e.g. PEPE" value={query} autoFocus
              onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} aria-label="Search cryptocurrency" />
            <button className="btn" onClick={search}>Search</button>
          </div>
          {results && (
            <div className="flex flex-wrap gap-1.5">
              {results.map((s) => (
                <button key={s} className="btn btn-primary px-2 py-1 text-xs" disabled={list.some((w) => w.symbol === s)}
                  onClick={() => act(() => post("/watchlist", { symbol: s }), `${s} added. Prices show now; signals and forecasts follow within the next engine runs.`)}>
                  + {s}
                </button>
              ))}
              {!results.length && <span className="text-sm text-mute">No USDT market found on Binance</span>}
            </div>
          )}
          <p className="text-xs text-mute">★ pins a coin to the front. ✕ removes it from tracking.</p>
        </div>
      )}
      {msg && <p className="mb-2 text-sm text-accent">{msg}</p>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {list.map((w) => {
          const tk = tickers[w.symbol];
          const row = rows?.find((r) => r.symbol === w.symbol);
          const ch = tk?.change_pct ?? row?.change_24h_pct;
          return (
            <div key={w.symbol} className="relative tile p-3 transition-colors hover:border-accent/40">
              <Link to={`/asset/${slug(w.symbol)}`} className="block">
                <div className="flex items-center gap-1 font-semibold">{w.pinned ? <span className="text-warn" aria-label="pinned">★</span> : null}{base(w.symbol)}</div>
                <div className="num mt-1 truncate text-lg">{fmtPrice(tk?.last ?? row?.price)}</div>
                <div className={`num text-xs ${tone(ch)}`}>{fmtPctRaw(ch)} 24h</div>
              </Link>
              {edit && (
                <div className="absolute right-1.5 top-1.5 flex gap-1">
                  <button className={w.pinned ? "text-warn" : "text-mute hover:text-warn"} title={w.pinned ? "Unpin" : "Pin to front"}
                    onClick={() => act(() => put(`/watchlist/${slug(w.symbol)}/pin`, { pinned: !w.pinned }), w.pinned ? "Unpinned" : "Pinned")}>{w.pinned ? "★" : "☆"}</button>
                  <button className="text-mute hover:text-bear" title="Remove"
                    onClick={() => act(() => del(`/watchlist/${slug(w.symbol)}`), `${w.symbol} removed`)}>✕</button>
                </div>
              )}
            </div>
          );
        })}
        {!list.length && <p className="col-span-full text-sm text-mute">{meta.loading ? "Loading…" : admin ? "No coins yet. Tap “+ Add / edit”." : "No coins yet."}</p>}
      </div>
    </Card>
  );
}
