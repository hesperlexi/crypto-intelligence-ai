// v2.76 coin search (owner, 22 Nov 2026: "where is the coin page?"). Type a ticker anywhere in the top bar and open that
// coin's page: the watchlist first (instant, from views/meta already loaded), then any Binance spot or futures pair on
// Enter / "Search Binance". Keyboard: ↑ ↓ choose, Enter opens, Esc closes; "/" focuses the box on computers.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApi } from "../lib/api";
import { search as binanceSearch, searchFuturesOnly } from "../lib/binance";
import { base, slug } from "../lib/format";
import { CoinAvatar } from "./Polish";

export default function CoinSearch({ className = "", autoFocus = false, onDone }: { className?: string; autoFocus?: boolean; onDone?: () => void }) {
  const nav = useNavigate();
  const meta = useApi<any>("/meta");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  const [more, setMore] = useState<string[] | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const wl: string[] = useMemo(() => ((meta.data?.watchlist ?? []) as any[]).map((w) => w.symbol), [meta.data]);
  const Q = q.trim().toUpperCase().replace(/[/-]|USDT$/g, "");
  const names: Record<string, string> = { GOLD: "PAXG", SILVER: "XAG" };
  const hits = useMemo(() => {
    if (!Q) return wl.slice(0, 8);
    const alias = names[Q];
    return wl.filter((s) => base(s).startsWith(Q) || s.startsWith(Q) || (alias && s.startsWith(alias)))
      .concat(wl.filter((s) => !base(s).startsWith(Q) && base(s).includes(Q))).slice(0, 8);
  }, [Q, wl]);   // eslint-disable-line react-hooks/exhaustive-deps
  const list = [...hits, ...(more ?? []).filter((s) => !hits.includes(s))].slice(0, 12);
  useEffect(() => { setI(0); setMore(null); }, [Q]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "/" && !/input|textarea|select/i.test((e.target as HTMLElement)?.tagName ?? "")) { e.preventDefault(); box.current?.focus(); }
    };
    window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k);
  }, []);
  const go = (s: string) => { setQ(""); setOpen(false); box.current?.blur(); onDone?.(); nav(`/asset/${slug(s)}`); };
  const wider = async () => {
    if (!Q) return;
    try {
      const [sp, fu] = await Promise.all([binanceSearch(Q).catch(() => [] as string[]), searchFuturesOnly(Q).catch(() => [] as string[])]);
      setMore([...sp, ...fu].slice(0, 10));
    } catch { setMore([]); }
  };
  return (
    <div className={`csx ${className}`} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpen(false); }}>
      <svg className="csx-ico" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M11 18a7 7 0 100-14 7 7 0 000 14zM21 21l-4.3-4.3" /></svg>
      <input ref={box} className="csx-input" value={q} autoFocus={autoFocus} placeholder="Search a coin…" aria-label="Search a coin and open its page"
        role="combobox" aria-expanded={open} aria-controls="csx-list" autoComplete="off" spellCheck={false}
        onFocus={() => setOpen(true)} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setI((v) => Math.min(v + 1, Math.max(0, list.length - 1))); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setI((v) => Math.max(0, v - 1)); }
          else if (e.key === "Enter") { e.preventDefault(); if (list[i]) go(list[i]); else void wider(); }
          else if (e.key === "Escape") { setOpen(false); box.current?.blur(); onDone?.(); }
        }} />
      <kbd className="csx-kbd" aria-hidden="true">/</kbd>
      {open && (
        <div id="csx-list" role="listbox" className="csx-list">
          {list.map((s, k) => (
            <button key={s} type="button" role="option" aria-selected={k === i} className={`csx-item ${k === i ? "is-on" : ""}`}
              onMouseEnter={() => setI(k)} onMouseDown={(e) => e.preventDefault()} onClick={() => go(s)}>
              <CoinAvatar symbol={s} size={22} /><b>{base(s)}</b><span className="text-mute">/USDT</span>
              {!wl.includes(s) && <span className="ml-auto text-xs text-mute">not on the watchlist</span>}
            </button>
          ))}
          {Q && more === null && <button type="button" className="csx-more" onMouseDown={(e) => e.preventDefault()} onClick={wider}>Search Binance for “{Q}”</button>}
          {Q && more !== null && !list.length && <p className="csx-none">No coin “{Q}” on Binance. Use the ticker, e.g. SOL.</p>}
        </div>
      )}
    </div>
  );
}
