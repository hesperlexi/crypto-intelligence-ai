// Heads-up for market-moving news: shown on the dashboard and the signals page when a high-impact US data
// release (CPI, jobs report, Fed decision...) is close or happening now.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";

export function countdown(ts: number, now = Date.now()): string {
  const m = Math.round((ts - now) / 60000);
  if (m <= 0 && m > -60) return m === 0 ? "now" : `${-m} min ago`;
  if (m < 0) return "earlier";
  if (m < 60) return `in ${m} min`;
  const h = Math.floor(m / 60), r = m % 60;
  if (h < 24) return `in ${h} h${r ? ` ${r} min` : ""}`;
  return `in ${Math.floor(h / 24)} d ${h % 24} h`;
}

function useNow(ms = 30000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), ms); return () => window.clearInterval(id); }, [ms]);
  return now;
}

export default function NewsBanner({ hours = 6 }: { hours?: number }) {
  const v = useApi<any>("/news");
  const now = useNow();
  const risk = v.data?.risk_now;
  const next = v.data?.next_high;
  const soon = next && next.ts - now < hours * 3_600_000 && next.ts - now > -30 * 60_000;
  if (!risk && !soon) return null;
  const ev = risk ?? next;
  const live = !!risk || (next && Math.abs(next.ts - now) <= 45 * 60_000);
  return (
    <Link to="/news" className={`panel flex flex-wrap items-center gap-x-3 gap-y-1 border px-4 py-2.5 text-sm transition hover:border-accent/60 ${live ? "border-bear/50 bg-bear/[0.07]" : "border-warn/45 bg-warn/[0.06]"}`}>
      <span className={`rounded-md px-2 py-0.5 text-[11px] font-extrabold tracking-wide ${live ? "bg-bear text-white" : "bg-warn text-ink"}`}>{live ? "NEWS NOW" : "HIGH-IMPACT NEWS"}</span>
      <span className="font-semibold">US {ev.title}</span>
      <span className="num text-mute">{countdown(ev.ts, now)}</span>
      <span className="text-mute">{live ? "· new signals are paused until 30 min after the release" : "· expect volatility; signals pause 45 min before"}</span>
      <span className="ml-auto text-xs text-accent">Calendar →</span>
    </Link>
  );
}
