// Market-moving news: the economic calendar (US data releases and central-bank decisions) and the latest
// crypto headlines, plus how the engine treats high-impact releases.
import { useEffect, useState } from "react";
import NewsBanner, { countdown } from "../components/NewsBanner";
import { ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { ago } from "../lib/format";

const IMPACT: Record<string, string> = { High: "bg-bear/15 text-bear border-bear/40", Medium: "bg-warn/15 text-warn border-warn/40" };

function dayKey(ms: number) {
  return new Date(ms).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}
const hhmm = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

export default function News() {
  const v = useApi<any>("/news");
  const [now, setNow] = useState(Date.now());
  const [all, setAll] = useState(false);
  useEffect(() => { const id = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(id); }, []);
  if (v.loading && !v.data) return <Loading />;
  if (v.error) return <ErrorBox error={v.error} retry={v.reload} />;
  const d = v.data ?? {};
  const cal: any[] = (d.calendar ?? []).filter((e: any) => all || e.impact === "High");
  const upcoming = cal.filter((e) => e.ts > now - 60 * 60_000);
  const past = cal.filter((e) => e.ts <= now - 60 * 60_000).reverse().slice(0, 8);
  const groups: [string, any[]][] = [];
  for (const e of upcoming) {
    const k = dayKey(e.ts);
    const g = groups.find((x) => x[0] === k);
    if (g) g[1].push(e); else groups.push([k, [e]]);
  }
  const heads: any[] = d.headlines ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">News & economic calendar</h1>
        <p className="text-sm text-mute">US data releases move crypto within minutes. High-impact releases pause new signals from 45 minutes before to 30 minutes after, and members with notifications on get a heads-up 30 minutes before.</p>
      </div>
      <NewsBanner hours={24} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <section className="panel p-0">
          <div className="card-head flex items-center justify-between border-b border-glass/[0.06] px-4 py-2.5">
            <h2 className="label">Economic calendar · your local time</h2>
            <label className="flex items-center gap-2 text-xs text-mute"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />show medium impact</label>
          </div>
          {!groups.length && <p className="px-4 py-6 text-sm text-mute">No high-impact releases scheduled in the next days{d.errors?.length ? " (the calendar could not be loaded on the last run)" : ""}.</p>}
          {groups.map(([day, evs]) => (
            <div key={day}>
              <div className="bg-glass/[0.03] px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-mute">{day}</div>
              <ul className="divide-y divide-glass/[0.06]">
                {evs.map((e) => {
                  const near = Math.abs(e.ts - now) <= 45 * 60_000;
                  return (
                    <li key={e.id} className={`grid grid-cols-[52px_minmax(0,1fr)_auto] items-start gap-3 px-4 py-2.5 ${near ? "bg-bear/[0.06]" : ""}`}>
                      <span className="num pt-0.5 text-sm">{hhmm(e.ts)}</span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded border border-glass/15 px-1.5 text-[10px] font-bold text-mute">{e.country}</span>
                          <span className="font-medium">{e.title}</span>
                          <span className={`rounded border px-1.5 text-[10px] font-bold ${IMPACT[e.impact] ?? ""}`}>{e.impact}</span>
                        </div>
                        {e.explain && <p className="mt-0.5 text-xs text-mute">{e.explain}</p>}
                        {(e.forecast || e.previous || e.actual) && (
                          <div className="num mt-1 flex flex-wrap gap-x-4 text-xs">
                            {e.actual && <span>Actual <b className="text-text">{e.actual}</b></span>}
                            {e.forecast && <span className="text-mute">Forecast <span className="text-text">{e.forecast}</span></span>}
                            {e.previous && <span className="text-mute">Previous <span className="text-text">{e.previous}</span></span>}
                          </div>
                        )}
                      </div>
                      <span className={`num whitespace-nowrap pt-0.5 text-xs ${near ? "font-semibold text-bear" : "text-mute"}`}>{countdown(e.ts, now)}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {past.length > 0 && (
            <details className="border-t border-glass/[0.06] px-4 py-2 text-sm">
              <summary className="cursor-pointer text-mute">Earlier this week ({past.length})</summary>
              <ul className="mt-2 space-y-1 text-xs text-mute">
                {past.map((e) => <li key={e.id}><span className="num">{dayKey(e.ts)} {hhmm(e.ts)}</span> · {e.country} {e.title}{e.actual ? ` · actual ${e.actual}` : ""}</li>)}
              </ul>
            </details>
          )}
          <p className="border-t border-glass/[0.06] px-4 py-2 text-[11px] text-mute">Source: {d.sources?.calendar ?? "economic calendar"}. Times shown in your local time.</p>
        </section>

        <section className="panel self-start p-0">
          <div className="card-head border-b border-glass/[0.06] px-4 py-2.5"><h2 className="label">Crypto headlines</h2></div>
          {!heads.length && <p className="px-4 py-6 text-sm text-mute">Headlines arrive with the next engine run (about every 15 minutes).</p>}
          <ul className="divide-y divide-glass/[0.06]">
            {heads.slice(0, 25).map((h) => (
              <li key={h.url}>
                <a href={h.url} target="_blank" rel="noopener noreferrer" className="block px-4 py-2.5 hover:bg-glass/[0.04]">
                  <div className="text-sm font-medium leading-snug">{h.title}</div>
                  <div className="mt-0.5 text-[11px] text-mute">{h.source}{h.ts ? ` · ${ago(h.ts)}` : ""}</div>
                </a>
              </li>
            ))}
          </ul>
          <p className="border-t border-glass/[0.06] px-4 py-2 text-[11px] text-mute">Headlines are for context; the AI's signals do not read them. Sources: {d.sources?.headlines ?? "public RSS feeds"}.</p>
        </section>
      </div>
    </div>
  );
}
