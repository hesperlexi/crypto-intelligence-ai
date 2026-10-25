import { doc, setDoc } from "firebase/firestore";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, del, post, put, useApi } from "../lib/api";
import { db } from "../lib/firebase";
import { base, fmtPctRaw, fmtPrice, slug } from "../lib/format";
import { useLimits } from "../lib/limits";
import { useLive } from "../lib/live";
import { myUid, useIsAdmin } from "../lib/session";
import { CoinAvatar } from "./Polish";
import { Card, SignalBadge } from "./ui";

async function saveMine(list: string[], limit: number) {
  await setDoc(doc(db, "user_coins", myUid()), { symbols: list.slice(0, limit), updated_at: Date.now() });
}

/** Live price tiles for the shared coins plus the member's own coins, with add / remove / pin in place. */
export default function MyCoins({ rows }: { rows?: any[] }) {
  const admin = useIsAdmin();
  const meta = useApi<any>("/meta");
  const [edit, setEdit] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<string[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const list: { symbol: string; pinned: number; mine?: boolean }[] = [...(meta.data?.watchlist ?? [])]
    .sort((a, b) => b.pinned - a.pinned || Number(!!b.mine) - Number(!!a.mine));
  const mine: string[] = meta.data?.my_coins ?? [];
  const MY_COIN_LIMIT = useLimits().member_coin_limit;
  const full = !admin && mine.length >= MY_COIN_LIMIT;

  const act = async (fn: () => Promise<any>, done: string) => {
    try { await fn(); setMsg(done); meta.reload?.(); } catch (e: any) { setMsg(e.message); }
  };
  const search = async () => {
    const q = query.trim();
    if (!q) return;
    try { setResults((await api<any>(`/search?q=${encodeURIComponent(q)}`)).results); setMsg(null); } catch (e: any) { setMsg(e.message); }
  };
  const add = (s: string) => admin
    ? act(() => post("/watchlist", { symbol: s }), `${s} added for everyone. Prices show now; forecasts follow within the next engine runs.`)
    : act(() => saveMine([...mine, s], MY_COIN_LIMIT), `${s} added to your coins. Live price now; signals and AI forecasts arrive within about 15–30 minutes.`);
  const remove = (s: string, own: boolean) => own
    ? act(() => saveMine(mine.filter((x) => x !== s), MY_COIN_LIMIT), `${s} removed from your coins.`)
    : act(() => del(`/watchlist/${slug(s)}`), `${s} removed`);

  return (
    <Card title="My coins" right={
      <button className={`btn px-2.5 py-1 text-xs ${edit ? "btn-on" : ""}`} onClick={() => { setEdit((v) => !v); setResults(null); setMsg(null); }}>
        {edit ? "Done" : admin ? "+ Add / edit" : `+ Add coin · ${mine.length}/${MY_COIN_LIMIT}`}
      </button>}>
      {edit && (
        <div className="mb-4 space-y-2 rounded-xl border border-accent/25 bg-accent/[0.04] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <input className="input w-full sm:w-64" placeholder="Search any coin, e.g. PEPE, SOL, TON" value={query} autoFocus
              onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} aria-label="Search cryptocurrency" />
            <button className="btn btn-primary" onClick={search}>Search</button>
          </div>
          {results && (
            <div className="flex flex-wrap gap-1.5">
              {results.map((s) => (
                <button key={s} className="btn px-2.5 py-1 text-xs hover:border-accent/60" disabled={list.some((w) => w.symbol === s) || full} onClick={() => add(s)}>
                  + {s}
                </button>
              ))}
              {!results.length && <span className="text-sm text-mute">No USDT market found on Binance</span>}
            </div>
          )}
          <p className="text-xs text-mute">
            {admin ? "Coins you add here are tracked for everyone. ★ pins a coin to the front, ✕ stops tracking it."
              : full ? `You follow ${MY_COIN_LIMIT} coins of your own (the maximum). Remove one with ✕ to add another.`
              : `Add up to ${MY_COIN_LIMIT} coins of your own. Each gets live prices, signals, AI forecasts, alerts and paper trading. Only you see them in your list.`}
          </p>
        </div>
      )}
      {msg && <p className="mb-3 text-sm text-accent">{msg}</p>}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
        {list.map((w) => <CoinTile key={w.symbol} w={w} row={rows?.find((r) => r.symbol === w.symbol)} edit={edit} admin={admin}
          onPin={() => act(() => put(`/watchlist/${slug(w.symbol)}/pin`, { pinned: !w.pinned }), w.pinned ? "Unpinned" : "Pinned")}
          onRemove={() => remove(w.symbol, !!w.mine)} />)}
        {!list.length && <p className="col-span-full text-sm text-mute">{meta.loading ? "Loading…" : "No coins yet. Tap “+ Add coin”."}</p>}
      </div>
    </Card>
  );
}

function CoinTile({ w, row, edit, admin, onPin, onRemove }: { w: any; row?: any; edit: boolean; admin: boolean; onPin: () => void; onRemove: () => void }) {
  const { tickers } = useLive();
  const tk = tickers[w.symbol];
  const price = tk?.last ?? row?.price;
  const ch = tk?.change_pct ?? row?.change_24h_pct;
  // flash green / red when the live price ticks
  const prev = useRef<number | null>(null);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    if (price == null) return;
    if (prev.current != null && price !== prev.current) {
      setFlash(price > prev.current ? "up" : "down");
      const t = window.setTimeout(() => setFlash(""), 700);
      prev.current = price;
      return () => window.clearTimeout(t);
    }
    prev.current = price;
  }, [price]);
  const canRemove = admin ? !w.mine : !!w.mine;
  return (
    <div className={`coin-tile group relative ${w.mine ? "coin-tile-mine" : ""}`}>
      <Link to={`/asset/${slug(w.symbol)}`} className="block p-3">
        <div className="flex items-center gap-2.5">
          <CoinAvatar symbol={w.symbol} />
          <div className="min-w-0">
            <div className="flex items-center gap-1 font-semibold leading-tight">{w.pinned ? <span className="text-warn" aria-label="pinned">★</span> : null}{base(w.symbol)}</div>
            <div className="text-[11px] text-mute">{w.mine ? "your coin" : "USDT"}</div>
          </div>
        </div>
        <div className={`num mt-2.5 truncate text-lg font-semibold transition-colors duration-500 ${flash === "up" ? "text-bull" : flash === "down" ? "text-bear" : ""}`}>{fmtPrice(price)}</div>
        <div className="mt-1 flex items-center justify-between gap-1">
          <span className={`num rounded-md px-1.5 py-0.5 text-[11px] ${ch == null ? "text-mute" : ch >= 0 ? "bg-bull/10 text-bull" : "bg-bear/10 text-bear"}`}>{fmtPctRaw(ch)}</span>
          {row?.signal ? <span className="origin-right scale-90"><SignalBadge signal={row.signal} /></span> : <span className="text-[10px] text-mute">{w.mine ? "forecast soon" : ""}</span>}
        </div>
      </Link>
      {edit && (canRemove || admin) && (
        <div className="absolute right-1.5 top-1.5 flex gap-1 rounded-md bg-ink/80 px-1">
          {admin && !w.mine && <button className={w.pinned ? "text-warn" : "text-mute hover:text-warn"} title={w.pinned ? "Unpin" : "Pin to front"} aria-label={w.pinned ? "Unpin" : "Pin to front"} onClick={onPin}>{w.pinned ? "★" : "☆"}</button>}
          {canRemove && <button className="text-mute hover:text-bear" title="Remove" aria-label={`Remove ${w.symbol}`} onClick={onRemove}>✕</button>}
        </div>
      )}
    </div>
  );
}

