// Market-moving news: the AI news mood, the economic calendar (US data releases and central-bank decisions), the
// latest crypto headlines (with the coins they mention) and how the engine treats high-impact releases.
//   views/news: {calendar[], headlines[{title,url,source,ts,summary?,coins?[]}], sentiment?{latest{market,BTC,ETH,alts}, series[]},
//                risk_now?, next_high?, sources{calendar, headlines}, errors[]}
import { useEffect, useMemo, useState } from "react";
import NewsBanner, { countdown } from "../components/NewsBanner";
import { AiTag, ErrorBox, Loading } from "../components/ui";
import { useApi } from "../lib/api";
import { ago, isNum } from "../lib/format";

const IMPACT: Record<string, string> = { High: "bg-bear/15 text-bear border-bear/40", Medium: "bg-warn/15 text-warn border-warn/40" };
const SRC_DOT: Record<string, string> = { CoinDesk: "bg-accent", Cointelegraph: "bg-bull", Decrypt: "bg-warn" };

function dayKey(ms: number) {
  return new Date(ms).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}
const hhmm = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** -1..1 news score -> words and tone. */
function mood(v?: number | null): [string, string] {
  if (!isNum(v)) return ["No reading", "text-mute"];
  if (v >= 0.35) return ["Bullish", "text-bull"];
  if (v >= 0.1) return ["Leaning bullish", "text-bull"];
  if (v > -0.1) return ["Neutral", "text-text"];
  if (v > -0.35) return ["Leaning bearish", "text-bear"];
  return ["Bearish", "text-bear"];
}

/** Position on a -1..1 bar. */
function MoodBar({ v }: { v?: number | null }) {
  const x = isNum(v) ? ((Math.max(-1, Math.min(1, v)) + 1) / 2) * 100 : null;
  return (
    <div className="relative mt-2 h-1.5 rounded-full bg-gradient-to-r from-bear/60 via-glass/20 to-bull/60" aria-hidden="true">
      <span className="absolute left-1/2 top-[-3px] h-3 w-px bg-glass/30" />
      {x != null && <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-text shadow" style={{ left: `${x}%` }} />}
    </div>
  );
}

function Spark({ pts }: { pts: { ts: number; score: number }[] }) {
  if (pts.length < 2) return null;
  const w = 220, h = 44;
  const t0 = pts[0].ts, t1 = pts[pts.length - 1].ts || t0 + 1;
  const X = (t: number) => ((t - t0) / Math.max(1, t1 - t0)) * w;
  const Y = (s: number) => h / 2 - Math.max(-1, Math.min(1, s)) * (h / 2 - 3);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.ts).toFixed(1)},${Y(p.score).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1].score;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="mt-2 h-11 w-full" preserveAspectRatio="none" role="img" aria-label="News mood over the last 48 hours">
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} className="stroke-glass/20" strokeDasharray="3 3" />
      <path d={d} fill="none" strokeWidth="1.6" vectorEffect="non-scaling-stroke" className={last >= 0 ? "stroke-bull" : "stroke-bear"} />
    </svg>
  );
}

function Overview({ d, now, heads }: { d: any; now: number; heads: any[] }) {
  const s = d.sentiment;
  const m = s?.latest?.market;
  const [word, tone] = mood(m?.score);
  const nh = d.next_high;
  const risk = d.risk_now;
  const day = heads.filter((h) => h.ts && now - h.ts <= 24 * 3_600_000).length;
  const week = (d.calendar ?? []).filter((e: any) => e.impact === "High" && e.ts > now && e.ts - now <= 7 * 86_400_000).length;
  return (
    <section className="panel grid overflow-hidden p-0 md:grid-cols-2 xl:grid-cols-[1.3fr_1fr_1fr_1fr]">
      <div className="ai-card border-b border-glass/[0.06] p-4 md:border-r xl:border-b-0">
        <div className="label flex items-center gap-1.5"><AiTag />News mood</div>
        {m ? (
          <>
            <div className={`mt-1 font-display text-2xl font-semibold ${tone}`}>{word}</div>
            <div className="num text-xs text-mute">score {m.score > 0 ? "+" : ""}{m.score.toFixed(2)} · {m.source === "calendar" ? "from the calendar only" : `${m.headlines ?? "recent"} headlines`} · {ago(m.ts)}</div>
            <MoodBar v={m.score} />
            <Spark pts={s.series ?? []} />
            <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wide text-mute"><span>48 h ago</span><span>now</span></div>
          </>
        ) : (
          <p className="mt-2 text-sm text-mute">The AI scores the headlines once an hour; the first reading appears after the next scoring.</p>
        )}
      </div>
      <div className="border-b border-glass/[0.06] p-4 xl:border-b-0 xl:border-r">
        <div className="label">Next high-impact release</div>
        {nh ? (
          <>
            <div className="mt-1 font-display text-lg font-semibold leading-tight">{nh.title}</div>
            <div className="num mt-1 text-2xl font-semibold text-accent">{countdown(nh.ts, now)}</div>
            <div className="text-xs text-mute">{dayKey(nh.ts)} · {hhmm(nh.ts)}</div>
          </>
        ) : <p className="mt-2 text-sm text-mute">None scheduled in the next days.</p>}
      </div>
      <div className="border-b border-glass/[0.06] p-4 md:border-b-0 md:border-r">
        <div className="label">New signals</div>
        {risk ? (
          <>
            <div className="mt-1 flex items-center gap-2 font-display text-lg font-semibold text-bear"><span className="h-2 w-2 animate-pulse rounded-full bg-bear" />Paused for the news</div>
            <p className="mt-1 text-xs text-mute">{risk.reason ?? risk.title}</p>
          </>
        ) : (
          <>
            <div className="mt-1 flex items-center gap-2 font-display text-lg font-semibold text-bull"><span className="h-2 w-2 rounded-full bg-bull" />Running normally</div>
            <p className="mt-1 text-xs text-mute">New entries pause 45 min before to 30 min after each high-impact US release.</p>
          </>
        )}
      </div>
      <div className="p-4">
        <div className="label">News flow</div>
        <div className="mt-1 grid grid-cols-2 gap-3">
          <div><div className="num font-display text-2xl font-semibold">{day}</div><div className="text-xs text-mute">headlines · 24 h</div></div>
          <div><div className="num font-display text-2xl font-semibold">{week}</div><div className="text-xs text-mute">high-impact · 7 days</div></div>
        </div>
        {s?.latest && (
          <div className="mt-3 space-y-1.5">
            {(["BTC", "ETH", "alts"] as const).filter((g) => s.latest[g]).map((g) => {
              const v = s.latest[g].score as number;
              const [w, t] = mood(v);
              return (
                <div key={g} className="grid grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-2 text-xs">
                  <span className="font-semibold">{g === "alts" ? "Alts" : g}</span>
                  <div className="h-1 overflow-hidden rounded-full bg-glass/10"><div className={`h-full ${v >= 0 ? "bg-bull" : "bg-bear"}`} style={{ width: `${Math.round(Math.abs(v) * 100)}%`, marginLeft: v >= 0 ? "0" : "auto" }} /></div>
                  <span className={`num ${t}`}>{w}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function Headlines({ heads, sources }: { heads: any[]; sources?: string }) {
  const [src, setSrc] = useState<string>("all");
  const [coin, setCoin] = useState<string>("all");
  const srcs = useMemo(() => Array.from(new Set(heads.map((h) => h.source).filter(Boolean))) as string[], [heads]);
  const coins = useMemo(() => {
    const c: Record<string, number> = {};
    for (const h of heads) for (const x of h.coins ?? []) c[x] = (c[x] ?? 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [heads]);
  const list = heads.filter((h) => (src === "all" || h.source === src) && (coin === "all" || (h.coins ?? []).includes(coin)));
  const [lead, ...rest] = list;
  const chip = (on: boolean) => `rounded-full border px-2.5 py-1 text-xs transition-colors ${on ? "border-accent/50 bg-accent/10 text-accent" : "border-glass/[0.12] text-mute hover:text-text"}`;
  return (
    <section className="panel self-start p-0">
      <div className="card-head flex flex-wrap items-center justify-between gap-2 border-b border-glass/[0.06] px-4 py-2.5">
        <h2 className="label">Crypto headlines</h2>
        {srcs.length > 1 && (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Source">
            <button className={chip(src === "all")} onClick={() => setSrc("all")}>All sources</button>
            {srcs.map((s) => <button key={s} className={chip(src === s)} onClick={() => setSrc(s)}>{s}</button>)}
          </div>
        )}
      </div>
      {coins.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-glass/[0.06] px-4 py-2" role="group" aria-label="Coins in the news">
          <span className="mr-1 text-[11px] uppercase tracking-wide text-mute">Coins in the news</span>
          <button className={chip(coin === "all")} onClick={() => setCoin("all")}>All</button>
          {coins.map(([c, n]) => <button key={c} className={chip(coin === c)} onClick={() => setCoin(c)}>{c} <span className="num opacity-70">{n}</span></button>)}
        </div>
      )}
      {!heads.length && <p className="px-4 py-10 text-center text-sm text-mute">Headlines arrive with the next engine run (every 5 minutes).</p>}
      {heads.length > 0 && !list.length && <p className="px-4 py-8 text-center text-sm text-mute">No headlines match this filter.</p>}
      {lead && (
        <a href={lead.url} target="_blank" rel="noopener noreferrer" className="group block border-b border-glass/[0.06] px-4 py-4 hover:bg-glass/[0.03]">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-mute">
            <span className={`h-1.5 w-1.5 rounded-full ${SRC_DOT[lead.source] ?? "bg-mute"}`} />{lead.source}{lead.ts ? ` · ${ago(lead.ts)}` : ""}
            <span className="ml-auto rounded border border-accent/30 px-1.5 text-[10px] font-bold text-accent">LATEST</span>
          </div>
          <div className="mt-1.5 font-display text-lg font-semibold leading-snug group-hover:text-accent">{lead.title}</div>
          {lead.summary && <p className="mt-1 line-clamp-3 text-sm text-mute">{lead.summary}</p>}
          <Tags coins={lead.coins} />
        </a>
      )}
      <ul className="divide-y divide-glass/[0.06]">
        {rest.slice(0, 30).map((h) => (
          <li key={h.url ?? h.title}>
            <a href={h.url} target="_blank" rel="noopener noreferrer" className="group grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-2.5 hover:bg-glass/[0.03]">
              <div className="min-w-0">
                <div className="text-sm font-medium leading-snug group-hover:text-accent">{h.title}</div>
                {h.summary && <p className="mt-0.5 line-clamp-1 text-xs text-mute">{h.summary}</p>}
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-mute">
                  <span className={`h-1.5 w-1.5 rounded-full ${SRC_DOT[h.source] ?? "bg-mute"}`} />{h.source}
                  <Tags coins={h.coins} inline />
                </div>
              </div>
              <span className="num whitespace-nowrap pt-0.5 text-[11px] text-mute">{h.ts ? ago(h.ts) : ""}</span>
            </a>
          </li>
        ))}
      </ul>
      <p className="border-t border-glass/[0.06] px-4 py-2 text-[11px] text-mute">Headlines are for context; the AI's signals do not read them. Coin tags are matched from the title. Sources: {sources ?? "public RSS feeds"}.</p>
    </section>
  );
}

function Tags({ coins, inline = false }: { coins?: string[]; inline?: boolean }) {
  if (!coins?.length) return null;
  return (
    <span className={`${inline ? "" : "mt-2 "}flex flex-wrap gap-1`}>
      {coins.map((c) => <span key={c} className="rounded border border-glass/[0.12] bg-glass/[0.04] px-1.5 text-[10px] font-semibold text-text">{c}</span>)}
    </span>
  );
}

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
        <h1 className="page-title">News & economic calendar</h1>
        <p className="text-sm text-mute">What is moving crypto now: the AI's read of the headlines, the US data releases that move prices within minutes, and the latest stories.</p>
      </div>
      <NewsBanner hours={24} />
      <Overview d={d} now={now} heads={heads} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <Headlines heads={heads} sources={d.sources?.headlines} />

        <section className="panel self-start p-0">
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
                    <li key={e.id ?? `${e.ts}-${e.title}`} className={`grid grid-cols-[52px_minmax(0,1fr)_auto] items-start gap-3 px-4 py-2.5 ${near ? "bg-bear/[0.06]" : ""}`}>
                      <span className="num pt-0.5 text-sm">{hhmm(e.ts)}</span>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded border border-glass/15 px-1.5 text-[11px] font-bold text-mute">{e.country}</span>
                          <span className="font-medium">{e.title}</span>
                          <span className={`rounded border px-1.5 text-[11px] font-bold ${IMPACT[e.impact] ?? ""}`}>{e.impact}</span>
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
                {past.map((e) => <li key={e.id ?? `${e.ts}-${e.title}`}><span className="num">{dayKey(e.ts)} {hhmm(e.ts)}</span> · {e.country} {e.title}{e.actual ? ` · actual ${e.actual}` : ""}</li>)}
              </ul>
            </details>
          )}
          <p className="border-t border-glass/[0.06] px-4 py-2 text-[11px] text-mute">Source: {d.sources?.calendar ?? "economic calendar"}. Times shown in your local time.</p>
        </section>
      </div>
      <p className="text-[11px] text-mute">The news mood is the AI advisor's reading of the headlines, scored hourly: context only, it does not change any signal. Analysis only, not financial advice.</p>
    </div>
  );
}
