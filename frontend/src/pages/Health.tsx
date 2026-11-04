// Admin Health "command centre" (v2.19, 4 Nov 2026). One screen for the owner: KPI row (engine, database writes /
// reads, open record calls) · System health service tiles (dot = ok / warn / down; tap → its details below) · open
// signals · data sources with freshness · models · demo bots · safeguards; full details (database use, engine,
// market data + candle series, models table, recent errors) stay on the page in collapsible sections.
// Data: views/health (+ admin-only views/health_errors), views/track_record, views/bots, views/news,
// owner/telegram_status, and views/guardian only when another release publishes it (nothing shown otherwise).
import { doc, onSnapshot } from "firebase/firestore";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Segmented, Tile, Tone } from "../components/kit";
import { Card, Empty, ErrorBox, Loading, Note, Row } from "../components/ui";
import { useApi } from "../lib/api";
import { db } from "../lib/firebase";
import { ago, DASH, fmtDate, fmtNum, fmtPctRaw, fmtTime, isNum } from "../lib/format";
import { useLive } from "../lib/live";

const toneOf = (s: string) => (["LIVE", "OK", "active", "done"].includes(s) ? "bull" : ["DOWN", "failed"].includes(s) ? "bear" : ["POLLING", "running", "queued"].includes(s) ? "accent" : "warn") as Tone;

const FREE_LIMIT = 20_000;      // Firebase free (Spark) plan: document writes per day (day = midnight US Pacific)
const READ_LIMIT = 50_000;      // free plan: document reads per day (same day)
const DEFAULT_BUDGET = 15_000;  // backend sinks.FIRESTORE_DAILY_BUDGET default: the engine goes lean above it
const MIN = 60_000, HOUR = 3_600_000;
const TF_ORDER = ["15m", "1h", "4h", "12h", "1d", "3d", "1w"];
const arr = (x: any): any[] => (Array.isArray(x) ? x : []);
const age = (ms: unknown) => (isNum(ms) ? Date.now() - ms : null);

type Level = "ok" | "warn" | "down" | "off";
const DOT: Record<Level, string> = { ok: "bg-bull", warn: "bg-warn", down: "bg-bear", off: "bg-mute/60" };
const LEVEL_TONE: Record<Level, Tone> = { ok: "bull", warn: "warn", down: "bear", off: "mute" };
const SIDE_BAR = (side: string) => (side === "SHORT" ? "bg-bear" : "bg-bull");

function Dot({ level, pulse = false }: { level: Level; pulse?: boolean }) {
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0" aria-hidden="true">
      {pulse && level === "ok" && <span className="absolute inset-0 animate-ping rounded-full bg-bull/50 motion-reduce:hidden" />}
      <span className={`relative inline-block h-2 w-2 rounded-full ${DOT[level]}`} />
    </span>
  );
}

/** Small-caps section label used across the page (matches the card headers). */
function Caps({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <h2 className={`label ${className}`}>{children}</h2>;
}

// ---- icons (stroke, currentColor) ---------------------------------------------------------------------------
const ICONS: Record<string, string> = {
  pulse: "M3 12h4l3-8 4 16 3-8h4",
  db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zm0-4a5 5 0 1 0 0-10 5 5 0 0 0 0 10zm0-4a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
};
function Icon({ name }: { name: keyof typeof ICONS }) {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-accent/80"><path d={ICONS[name]} /></svg>;
}

/** One headline figure: label top-left, icon top-right, big number, chip + caption, optional bar. */
function Kpi({ label, icon, value, valueClass = "", chip, caption, bar, to }: {
  label: string; icon: keyof typeof ICONS; value: ReactNode; valueClass?: string; chip?: ReactNode; caption?: ReactNode; bar?: ReactNode; to?: string;
}) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-2"><span className="label">{label}</span><Icon name={icon} /></div>
      <div className={`num mt-3 truncate text-2xl font-semibold leading-none ${valueClass}`}>{value}</div>
      {(chip || caption) && <div className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mute">{chip}{caption && <span className="min-w-0">{caption}</span>}</div>}
      {bar && <div className="mt-3">{bar}</div>}
    </>
  );
  const cls = "panel block min-w-0 p-4 sm:p-5";
  return to ? <Link to={to} className={`${cls} transition-colors hover:border-accent/40`}>{body}</Link> : <section className={cls}>{body}</section>;
}

function Bar({ pct, marker, tone, label }: { pct: number; marker?: number; tone: string; label: string }) {
  return (
    <div className="relative h-2 overflow-hidden rounded-full bg-glass/[0.08]" role="img" aria-label={label}>
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
      {marker != null && <div className="absolute inset-y-0 w-px bg-text/60" style={{ left: `${Math.min(100, marker)}%` }} title="lean from here" />}
    </div>
  );
}

/** A collapsible details section; `open` can be forced from a service tile. */
function Section({ id, title, right, open, onToggle, children }: { id: string; title: string; right?: ReactNode; open: boolean; onToggle: (id: string, open: boolean) => void; children: ReactNode }) {
  return (
    <details id={id} open={open} onToggle={(e) => { const o = (e.currentTarget as HTMLDetailsElement).open; if (o !== open) onToggle(id, o); }} className="panel scroll-mt-24 group">
      <summary className="flex min-h-[46px] cursor-pointer list-none items-center justify-between gap-3 px-4 py-2.5 [&::-webkit-details-marker]:hidden">
        <span className="label flex min-w-0 items-start gap-2 text-text/75">
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} className="mt-[3px] shrink-0 transition-transform group-open:rotate-90"><path d="M9 6l6 6-6 6" /></svg>
          {title}
        </span>
        {right}
      </summary>
      <div className="border-t border-glass/[0.06] p-4">{children}</div>
    </details>
  );
}

/** Live Firestore document for the admin only (no api path needed): null while missing / not allowed. */
function useDoc(path: [string, string]): any {
  const [v, setV] = useState<any>(null);
  useEffect(() => onSnapshot(doc(db, path[0], path[1]), (s) => setV(s.data() ?? null), () => setV(null)), [path[0], path[1]]);
  return v;
}

/** views/<name> written by the engine as {json}; null when missing or unreadable. */
function useViewDoc(name: string): any {
  const raw = useDoc(["views", name]);
  return useMemo(() => { try { return raw?.json ? JSON.parse(raw.json) : null; } catch { return null; } }, [raw]);
}

type Service = { id: string; name: string; level: Level; line: string; target: string };

export default function Health() {
  const h = useApi<any>("/system/health", 10000);
  // raw error texts live in an admin-only document (v2.13); the Health page is admin-only, so it reads both
  const he = useApi<any>("/system/errors", 30000);
  const tr = useApi<any>("/track-record");
  const bv = useApi<any>("/bots");
  const nv = useApi<any>("/news");
  const tg = useDoc(["owner", "telegram_status"]);
  const guardian = useViewDoc("guardian");     // Trade Guardian (separate admin page): shown only when published
  const { connected, feed } = useLive();
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [sigSort, setSigSort] = useState<"oldest" | "newest">("oldest");
  const toggle = (id: string, o: boolean) => setOpen((s) => ({ ...s, [id]: o }));
  const jump = (id: string) => {
    setOpen((s) => ({ ...s, [id]: true }));
    requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const errs = he.data && typeof he.data === "object" ? he.data : {};
  const modelMsg: Record<string, string> = Object.fromEntries(arr(errs.model_messages).map((m: any) => [m.symbol + "|" + m.timeframe, m.message]));
  const raw = h.data;
  // the engine publishes {error} instead of the view when it could not build it (e.g. too large for one document)
  const viewError: string | null = raw && typeof raw === "object" && raw.error && !raw.status ? String(raw.error) : null;
  const d = raw && !viewError ? { ...raw, engine: raw.engine ?? {}, market_data: raw.market_data ?? {}, exchange: raw.exchange ?? {},
    database: raw.database ?? {}, config: raw.config ?? {}, series: arr(raw.series), models: arr(raw.models),
    model_libraries: arr(raw.model_libraries), recent_errors: arr(errs.recent_errors ?? raw.recent_errors), safety: arr(raw.safety) } : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="page-title">System health</h1>
        {d?.status && <Badge tone={toneOf(d.status)}>● {d.status}</Badge>}
        {d?.generated_at && <span className="text-xs text-mute">report {ago(d.generated_at)}</span>}
      </div>
      {h.error && <ErrorBox error={h.error} retry={h.reload} />}
      {viewError && <ErrorBox error={`The engine could not publish the health report: ${viewError}`} retry={h.reload} />}
      {!d && h.loading && <Loading />}
      {d && <Centre d={d} raw={raw} errs={errs} modelMsg={modelMsg} tr={tr.data} bots={bv.data} news={nv.data} tg={tg} guardian={guardian}
        connected={connected} feed={feed} open={open} toggle={toggle} jump={jump} sigSort={sigSort} setSigSort={setSigSort} />}
    </div>
  );
}

function Centre({ d, raw, errs, modelMsg, tr, bots, news, tg, guardian, connected, feed, open, toggle, jump, sigSort, setSigSort }: any) {
  const e = d.engine;
  // ---- engine
  const tickAge = age(e.last_tick_finished);
  const failed = arr(e.failed_steps);
  const engineLevel: Level = tickAge == null ? "off" : tickAge > 45 * MIN ? "down" : tickAge > 15 * MIN || failed.length ? "warn" : "ok";
  // ---- database writes / reads
  const writes = isNum(e.firestore_writes_today) ? e.firestore_writes_today : null;
  const budget = isNum(e.firestore_write_budget) ? e.firestore_write_budget : DEFAULT_BUDGET;
  const wLimit = isNum(e.firestore_free_limit) ? e.firestore_free_limit : FREE_LIMIT;
  const engineBudget = isNum(e.firestore_engine_budget) ? e.firestore_engine_budget : budget;
  const reserve = isNum(e.firestore_member_reserve) ? e.firestore_member_reserve : null;
  const wPct = writes != null ? (writes / wLimit) * 100 : 0;
  const wLevel: Level = writes == null ? "off" : writes >= wLimit * 0.95 ? "down" : writes >= engineBudget || e.firestore_lean ? "warn" : "ok";
  const reads = isNum(e.firestore_reads_today) ? e.firestore_reads_today : null;
  const rLimit = isNum(e.firestore_read_limit) ? e.firestore_read_limit : READ_LIMIT;
  const rPct = reads != null ? (reads / rLimit) * 100 : 0;
  const rLevel: Level = reads == null ? "off" : reads >= rLimit * 0.8 ? "down" : reads >= rLimit * 0.5 ? "warn" : "ok";
  // ---- record
  const live = tr?.live ?? {};
  const openSigs = arr(live.signals).filter((x: any) => x.status === "OPEN");
  const closed = isNum(live.summary?.closed) ? live.summary.closed : null;
  // ---- market / futures / news / telegram / training / safeguards
  const md = d.market_data, ex = d.exchange;
  const mdLevel: Level = !isNum(md.quality_pct) ? "off" : md.stale_series || ex.errors ? "warn" : md.quality_pct < 99 ? "warn" : "ok";
  const funding = bots?.funding && typeof bots.funding === "object" ? Object.values(bots.funding) as any[] : null;
  const fundSrc = funding ? [...new Set(funding.map((f) => f?.source).filter(Boolean))].join(", ") : "";
  const futLevel: Level = funding == null ? "off" : funding.length ? "ok" : "warn";
  const newsErr = arr(news?.errors);
  const newsAge = age(news?.generated_at);
  const newsLevel: Level = !news ? "off" : newsErr.length ? "warn" : newsAge != null && newsAge > 3 * HOUR ? "warn" : "ok";
  const tgAge = age(tg?.checked_at ?? tg?.last_post_at);
  const tgLevel: Level = !tg ? "off" : !tg.ok ? "warn" : tgAge != null && tgAge > 3 * HOUR ? "off" : "ok";
  const trainAge = age(e.last_train?.finished_at);
  const trainLevel: Level = trainAge == null ? "off" : trainAge > 54 * HOUR ? "down" : trainAge > 30 * HOUR ? "warn" : "ok";
  const fc = Object.entries((raw?.fail_closed ?? {}) as Record<string, any>);
  const safety = d.safety as any[];
  const models = d.models as any[];
  const modelErr = models.filter((m) => m.state === "failed" || (m.state !== "active" && m.state !== "running" && m.state !== "queued" && m.state !== "done"));
  const active = models.filter((m) => m.state === "active");
  const oldest = models.reduce((a: number | null, m: any) => (isNum(m.age_h) && (a == null || m.age_h > a) ? m.age_h : a), null);
  const edge = models.filter((m) => m.edge_confirmed).length;
  const recent = d.recent_errors as any[];
  const errCount = recent.length || (isNum(raw?.recent_errors_count) ? raw.recent_errors_count : 0);

  const services: Service[] = [
    { id: "hc-engine", name: "Engine loop", level: engineLevel, target: "hc-engine",
      line: tickAge == null ? "not run yet" : `${ago(e.last_tick_finished)} · ${failed.length ? `${failed.length} failed step${failed.length > 1 ? "s" : ""}` : "no failed steps"}` },
    { id: "hc-market", name: "Market data", level: mdLevel, target: "hc-market",
      line: isNum(md.quality_pct) ? `${fmtNum(md.quality_pct, 2)}% quality · ${md.stale_series ?? 0} stale` : "after the next cycle" },
    { id: "hc-futures", name: "Futures data", level: futLevel, target: "hc-sources",
      line: funding == null ? "no bots report yet" : funding.length ? `funding for ${funding.length} coins${fundSrc ? ` · ${fundSrc}` : ""}` : "base rate (no live funding)" },
    { id: "hc-news", name: "News & calendar", level: newsLevel, target: "hc-sources",
      line: !news ? "not published yet" : newsErr.length ? `${newsErr.length} feed problem${newsErr.length > 1 ? "s" : ""}` : `updated ${ago(news.generated_at)}` },
    { id: "hc-tg", name: "Telegram autopilot", level: tgLevel, target: "hc-sources",
      line: !tg ? "not connected" : !tg.ok ? "last run had problems" : tgLevel === "off" ? `idle · checked ${ago(tg.checked_at)}` : `ok${tg.last_post_at ? ` · posted ${ago(tg.last_post_at)}` : ""}` },
    { id: "hc-train", name: "Training", level: trainLevel, target: "hc-engine", line: trainAge == null ? "not yet" : `last run ${ago(e.last_train.finished_at)}` },
    { id: "hc-failsafe", name: "Fail-safe checks", level: fc.length ? "warn" : "ok", target: "hc-safeguards", line: fc.length ? `${fc.length} not working` : "all working" },
    { id: "hc-safety", name: "Safety switch", level: safety.length ? "warn" : "ok", target: "hc-safeguards", line: safety.length ? `${safety.length} paused` : "all active" },
    { id: "hc-db", name: "Database", level: !d.database.ok ? "down" : wLevel === "off" ? "ok" : wLevel, target: "hc-db",
      line: `${d.database.engine ?? "engine state"} ${d.database.ok ? "OK" : "DOWN"} · ${e.firestore_lean ? "lean mode" : "normal mode"}` },
    { id: "hc-prices", name: "Live prices", level: connected ? "ok" : "warn", target: "hc-sources", line: connected ? "this browser · live" : "this browser · reconnecting" },
  ];
  if (guardian) {
    const gs = String(guardian.status ?? guardian.state ?? "").trim();
    const gl: Level = !gs ? "off" : /^(ok|live|active|on|running|healthy)$/i.test(gs) ? "ok" : /^(down|error|failed|off)$/i.test(gs) ? "down" : "warn";
    services.push({ id: "hc-guardian", name: "Trade Guardian", level: gl, target: "/guardian", line: `${gs || "published"}${guardian.generated_at ? ` · ${ago(guardian.generated_at)}` : ""}` });
  }
  const attention = services.filter((s) => s.level === "warn" || s.level === "down");

  const sigs = [...openSigs].sort((a, b) => (sigSort === "oldest" ? 1 : -1) * ((a.created_at ?? 0) - (b.created_at ?? 0))).slice(0, 5);

  const sources: { name: string; sub: string; at: unknown; level: Level }[] = [
    { name: "Engine cycle", sub: `every ${e.schedule_minutes ?? 5} min`, at: e.last_tick_finished, level: engineLevel },
    { name: "Candles (Binance spot)", sub: e.data_host?.replace("https://", "") ?? "market data", at: md.last_update_ms ?? ex.last_ok_ms, level: mdLevel },
    { name: "Live prices (this browser)", sub: "Binance WebSocket", at: feed?.last_update_ms, level: connected ? "ok" : "warn" },
    { name: "Futures funding", sub: fundSrc || "bots report", at: bots?.generated_at, level: futLevel },
    { name: "News & calendar", sub: newsErr.length ? newsErr.slice(0, 1).join("") : "headlines + US releases", at: news?.generated_at, level: newsLevel },
    { name: "Telegram", sub: tg?.last_post_at ? `last post ${ago(tg.last_post_at)}` : "autopilot status", at: tg?.checked_at ?? tg?.last_post_at, level: tgLevel },
    { name: "Nightly training", sub: "train.yml + merge", at: e.last_train?.finished_at, level: trainLevel },
  ];
  const fresh = sources.filter((s) => s.level === "ok").length;

  const botRows = arr(bots?.bots).slice().sort((a: any, b: any) => TF_ORDER.indexOf(a.config?.timeframe) - TF_ORDER.indexOf(b.config?.timeframe));

  return (
    <>
      {/* ---- KPI row ---- */}
      <div className="grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:gap-4 xl:grid-cols-4">
        <Kpi label="Engine" icon="pulse" value={engineLevel === "ok" ? "LIVE" : engineLevel === "off" ? DASH : engineLevel === "down" ? "STALE" : "LATE"}
          valueClass={engineLevel === "ok" ? "text-bull" : engineLevel === "down" ? "text-bear" : engineLevel === "warn" ? "text-warn" : ""}
          chip={<Badge tone={LEVEL_TONE[engineLevel]}>{tickAge == null ? "no cycle" : ago(e.last_tick_finished)}</Badge>}
          caption={isNum(e.last_tick_seconds) ? `cycle ${e.last_tick_seconds}s · every ${e.schedule_minutes ?? 5} min` : `every ${e.schedule_minutes ?? 5} min`} />
        <Kpi label="Writes today" icon="db" value={writes != null ? fmtNum(writes, 0) : DASH}
          valueClass={wLevel === "down" ? "text-bear" : wLevel === "warn" ? "text-warn" : ""}
          chip={writes != null ? <Badge tone={LEVEL_TONE[wLevel]}>{wPct.toFixed(0)}%</Badge> : undefined}
          caption={`lean at ${fmtNum(engineBudget, 0)} · limit ${fmtNum(wLimit, 0)}`}
          bar={<Bar pct={wPct} marker={(engineBudget / wLimit) * 100} tone={writes != null && writes >= engineBudget ? "bg-warn" : "bg-accent"}
            label={writes != null ? `${fmtNum(writes, 0)} of ${fmtNum(wLimit, 0)} writes used` : "no data"} />} />
        <Kpi label="Reads today" icon="eye" value={reads != null ? fmtNum(reads, 0) : DASH}
          valueClass={rLevel === "down" ? "text-bear" : rLevel === "warn" ? "text-warn" : ""}
          chip={reads != null ? <Badge tone={LEVEL_TONE[rLevel]}>{rPct.toFixed(1)}%</Badge> : undefined}
          caption={reads != null ? `limit ${fmtNum(rLimit, 0)}/day` : "after the next update"}
          bar={<Bar pct={rPct} tone={reads != null && reads >= rLimit * 0.5 ? "bg-warn" : "bg-accent"} label={reads != null ? `${fmtNum(reads, 0)} of ${fmtNum(rLimit, 0)} reads used` : "no data"} />} />
        <Kpi label="Open signals" icon="target" to="/results?tab=track" value={tr ? openSigs.length : DASH}
          chip={closed != null ? <Badge tone="text">{closed} closed</Badge> : undefined}
          caption={tr?.record_since ? `since ${fmtDate(tr.record_since)}` : "track record"} />
      </div>

      {/* ---- system health · open signals · data sources ---- */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <Card title="System health" right={
          <span className={`inline-flex items-center gap-1.5 text-xs font-semibold ${attention.length ? (attention.some((s) => s.level === "down") ? "text-bear" : "text-warn") : "text-bull"}`}>
            <Dot level={attention.length ? (attention.some((s) => s.level === "down") ? "down" : "warn") : "ok"} />
            {attention.length ? `${attention.length} need${attention.length === 1 ? "s" : ""} attention` : "All systems operational"}
          </span>}>
          <ul className="grid grid-cols-1 gap-2 min-[360px]:grid-cols-2 lg:grid-cols-1 min-[1180px]:grid-cols-2">
            {services.map((s) => {
              const inner = (
                <>
                  <span className="flex items-start justify-between gap-2">
                    <span className="min-w-0 break-words text-sm font-medium leading-snug text-text">{s.name}</span>
                    <span className="flex h-5 shrink-0 items-center"><Dot level={s.level} pulse={s.id === "hc-engine"} /></span>
                  </span>
                  <span className="mt-0.5 block break-words text-xs leading-snug text-mute">{s.line}</span>
                </>
              );
              const cls = "tile block h-full w-full min-w-0 px-3 py-2.5 text-left transition-colors hover:border-accent/40 focus-visible:border-accent/60";
              return (
                <li key={s.id} className="min-w-0 h-full">
                  {s.target.startsWith("/") ? <Link to={s.target} className={cls}>{inner}</Link>
                    : <button type="button" className={cls} onClick={() => jump(s.target)} aria-label={`${s.name}: ${s.line}. Show details`}>{inner}</button>}
                </li>
              );
            })}
          </ul>
        </Card>

        <Card title="Open signals" right={<Segmented label="Order" value={sigSort} onChange={setSigSort} options={[["oldest", "Oldest"], ["newest", "Newest"]] as const} />}>
          {!tr ? <Loading /> : sigs.length ? (
            <ul className="-my-1 divide-y divide-glass/[0.06]">
              {sigs.map((x: any) => {
                const pending = x.fill_status === "PENDING";
                const hit = x.tp3_hit ? "TP3 hit" : x.tp2_hit ? "TP2 hit" : x.tp1_hit ? "TP1 hit" : pending ? "waiting for entry" : "running";
                return (
                  <li key={x.id} className="flex min-w-0 items-stretch gap-3 py-2.5">
                    <span className={`w-1 shrink-0 rounded-full ${SIDE_BAR(x.side)}`} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{x.symbol} <span className="num text-xs uppercase text-mute">{x.timeframe}</span></div>
                      <div className="truncate text-xs"><span className={x.side === "SHORT" ? "text-bear" : "text-bull"}>{x.side}</span><span className="text-mute"> · grade {x.grade ?? DASH}</span></div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="num text-sm">{ago(x.created_at).replace(" ago", "")}</div>
                      <div className={`text-xs ${x.tp1_hit ? "text-bull" : "text-mute"}`}>{hit}</div>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : <Empty>No open signals right now.</Empty>}
          <Link to="/results?tab=track" className="mt-3 block border-t border-glass/[0.06] pt-3 text-center text-sm text-mute transition-colors hover:text-accent">
            View all{openSigs.length > sigs.length ? ` ${openSigs.length}` : ""} in Results →
          </Link>
        </Card>

        <Card title="Data sources" right={<span className="text-xs font-semibold text-mute"><span className={fresh === sources.length ? "text-bull" : "text-warn"}>{fresh}/{sources.length}</span> fresh</span>} className="lg:col-span-2 xl:col-span-1">
          <ul id="hc-sources" className="-my-1 scroll-mt-24 divide-y divide-glass/[0.06]">
            {sources.map((s) => (
              <li key={s.name} className="flex min-w-0 items-center gap-3 py-2.5">
                <Dot level={s.level} />
                <div className="min-w-0 flex-1">
                  <div className="break-words text-sm leading-snug">{s.name}</div>
                  <div className="truncate text-xs text-mute" title={s.sub}>{s.sub}</div>
                </div>
                <div className="num shrink-0 text-right text-sm">{isNum(s.at) ? ago(s.at).replace(" ago", "") : DASH}<div className="text-xs text-mute">{isNum(s.at) ? "ago" : "no data"}</div></div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      {/* ---- models · bots · safeguards ---- */}
      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <Card title="Models" right={<Badge tone={modelErr.length ? "warn" : "bull"}>{modelErr.length ? `${modelErr.length} in error` : "no errors"}</Badge>}>
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 min-[360px]:grid-cols-3">
            <Tile label="Active" value={`${active.length}/${models.length}`} />
            <Tile label="Edge confirmed" value={edge} />
            <Tile label="Oldest" value={oldest != null ? `${oldest}h` : DASH} valueClass={oldest != null && oldest > 48 ? "text-warn" : ""} />
          </div>
          <div className="mt-4 border-t border-glass/[0.06] pt-2">
            {(d.model_libraries as any[]).map((l) => <Row key={l.name} k={l.label} v={l.available ? "available" : l.reason} className={l.available ? "text-bull" : "text-mute"} />)}
            <Row k="Retrain interval" v={isNum(d.config.retrain_interval_h) ? `${d.config.retrain_interval_h}h` : DASH} />
          </div>
          <button type="button" onClick={() => jump("hc-models")} className="mt-3 block w-full border-t border-glass/[0.06] pt-3 text-center text-sm text-mute transition-colors hover:text-accent">Model table →</button>
        </Card>

        <Card title="Demo bots" right={bots ? <span className="text-xs text-mute">since restart</span> : undefined}>
          {!bots ? <Loading /> : botRows.length ? (
            <ul className="-my-1 divide-y divide-glass/[0.06]">
              {botRows.map((b: any) => {
                const r = b.stats?.return_pct;
                const nOpen = arr(b.positions).length + arr(b.pending).length;
                const tf = String(b.config?.timeframe ?? "").toUpperCase();
                const grades = arr(b.config?.grades).join("+") || (String(b.config?.name ?? "").match(/\b(A\+B|A|B)\b/)?.[1] ?? "");
                return (
                  <li key={b.config?.id} className="flex min-w-0 items-stretch gap-3 py-2">
                    <span className={`w-1 shrink-0 rounded-full ${!isNum(r) || r === 0 ? "bg-mute/40" : r > 0 ? "bg-bull" : "bg-bear"}`} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm" title={b.config?.name ?? b.config?.id}><span className="num font-medium">{tf || b.config?.id}</span>
                        <span className="text-xs text-mute"> · {b.config?.market === "spot" ? "spot" : "futures"}{grades ? ` · grade ${grades}` : ""}</span></div>
                      <div className="truncate text-xs text-mute">{nOpen} open · {b.stats?.trades ?? 0} closed{b.config?.enabled === false ? " · paused" : ""}</div>
                    </div>
                    <div className={`num shrink-0 self-center text-right text-sm ${!isNum(r) || r === 0 ? "text-mute" : r > 0 ? "text-bull" : "text-bear"}`}>{isNum(r) ? fmtPctRaw(r) : DASH}</div>
                  </li>
                );
              })}
            </ul>
          ) : <Empty>No bots yet.</Empty>}
          <Link to="/results?tab=bots" className="mt-3 block border-t border-glass/[0.06] pt-3 text-center text-sm text-mute transition-colors hover:text-accent">View all bots →</Link>
        </Card>

        <Card title="Safeguards" className="lg:col-span-2 xl:col-span-1">
          <div id="hc-safeguards" className="scroll-mt-24 space-y-4">
            <div>
              <div className="mb-2 flex items-center justify-between gap-2"><Caps>Safety switch</Caps><Badge tone={safety.length ? "warn" : "bull"}>{safety.length ? `${safety.length} paused` : "all active"}</Badge></div>
              {safety.length ? (
                <ul className="space-y-1.5 text-sm">
                  {safety.map((x: any) => (
                    <li key={x.symbol + x.timeframe} className="flex flex-wrap justify-between gap-x-2 gap-y-0.5 rounded-lg bg-glass/[0.04] px-2.5 py-1.5">
                      <span className="font-medium">{x.symbol} <span className="uppercase text-mute">{x.timeframe}</span></span>
                      <span className="text-xs text-mute">paused {ago(x.paused_at)}{x.trigger ? ` · last ${x.trigger.n} signals avg ${Number(x.trigger.avg_return_pct).toFixed(2)}%, ${Math.round(x.trigger.tp1_rate * 100)}% hit TP1` : ""}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-mute">No coin or timeframe is paused.</p>}
              <Note>Pauses after a losing run; resumes by itself.</Note>
            </div>
            <div className="border-t border-glass/[0.06] pt-4">
              <div className="mb-2 flex items-center justify-between gap-2"><Caps>Fail-safe checks</Caps><Badge tone={fc.length ? "warn" : "bull"}>{fc.length ? `${fc.length} not working` : "all working"}</Badge></div>
              {fc.length ? (
                <ul className="space-y-1.5 text-sm">
                  {fc.map(([k, x]) => (
                    <li key={k} className="flex flex-wrap justify-between gap-x-2 gap-y-0.5 rounded-lg bg-glass/[0.04] px-2.5 py-1.5">
                      <span className="font-medium">{k.replace(/_/g, " ")} <span className="text-xs text-mute">{x.symbol} {String(x.timeframe ?? "").toUpperCase()}</span></span>
                      <span className="text-xs text-warn">{ago(x.at)} · {x.count}x · {x.detail}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-mute">Every required check ran in the last 24 h.</p>}
              <Note>A check that cannot run blocks new calls (no trade).</Note>
            </div>
          </div>
        </Card>
      </div>

      {/* ---- details (collapsible) ---- */}
      <div className="space-y-3">
        <Caps className="px-1">Details</Caps>

        <Section id="hc-db" title="Database use today (Firebase free plan)" open={!!open["hc-db"]} onToggle={toggle}
          right={e.firestore_lean ? <Badge tone="warn">lean mode</Badge> : writes != null ? <Badge tone="bull">normal</Badge> : undefined}>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <Tile label="Engine writes today" value={writes != null ? fmtNum(writes, 0) : DASH} valueClass={wLevel === "down" ? "text-bear" : wLevel === "warn" ? "text-warn" : "text-bull"}
              sub={`budget ${fmtNum(budget, 0)} · limit ${fmtNum(wLimit, 0)}/day`} />
            <div className="text-right text-xs text-mute">
              {reserve != null && <div>kept for members: <span className="num text-text">{fmtNum(reserve, 0)}</span>{isNum(e.firestore_members_active) ? ` (${e.firestore_members_active} active in 24 h)` : ""}</div>}
              <div>engine goes lean at <span className="num text-text">{fmtNum(engineBudget, 0)}</span></div>
            </div>
          </div>
          <div className="mt-3"><Bar pct={wPct} marker={(engineBudget / wLimit) * 100} tone={writes != null && writes >= engineBudget ? "bg-warn" : "bg-accent"} label="writes used" /></div>
          <div className="mt-4 border-t border-glass/[0.06] pt-3">
            <Tile label="Engine reads today" value={reads != null ? fmtNum(reads, 0) : DASH} valueClass={rLevel === "down" ? "text-bear" : rLevel === "warn" ? "text-warn" : "text-bull"}
              sub={reads != null ? `limit ${fmtNum(rLimit, 0)}/day · ${rPct.toFixed(1)}% used` : "after the next update"} />
            <div className="mt-2"><Bar pct={rPct} tone={reads != null && reads >= rLimit * 0.5 ? "bg-warn" : "bg-accent"} label="reads used" /></div>
          </div>
          <div className="mt-3"><Note>Counts only the engine's own writes and reads.</Note></div>
        </Section>

        <Section id="hc-engine" title="Engine & configuration" open={!!open["hc-engine"]} onToggle={toggle} right={<Badge tone={LEVEL_TONE[engineLevel]}>{failed.length ? `${failed.length} failed` : `${e.ticks ?? 0} cycles`}</Badge>}>
          <div className="grid gap-x-8 md:grid-cols-2">
            <div>
              <Row k="Last cycle" v={e.last_tick_finished ? ago(e.last_tick_finished) : "not run yet"} className={tickAge != null && tickAge > 45 * MIN ? "text-warn" : ""} />
              <Row k="Runs every" v={`${e.schedule_minutes ?? 5} min · ${e.ticks ?? 0} cycles so far`} />
              <Row k="Cycle duration" v={isNum(e.last_tick_seconds) ? `${e.last_tick_seconds}s` : DASH} />
              <Row k="Failed steps" v={failed.length ? failed.join(", ") : "none"} className={failed.length ? "text-warn" : ""} />
              <Row k="Last training run" v={e.last_train?.finished_at ? ago(e.last_train.finished_at) : "not yet"} />
            </div>
            <div>
              <Row k="Mode" v="Analysis + demo only" />
              <Row k="Market data host" v={e.data_host?.replace("https://", "") ?? DASH} />
              <Row k="Database (engine state)" v={d.database.engine ? `${d.database.engine} · ${d.database.ok ? "OK" : "DOWN"}` : DASH} />
              <Row k="Retrain interval" v={isNum(d.config.retrain_interval_h) ? `${d.config.retrain_interval_h}h` : DASH} />
              <Row k="Deep models" v={d.config.deep_models ? "enabled" : "disabled"} />
            </div>
          </div>
          {tickAge != null && tickAge > 45 * MIN && <div className="mt-2"><Note>The engine is late. If it lasts hours, check GitHub Actions.</Note></div>}
        </Section>

        <Section id="hc-market" title="Market data & candle series" open={!!open["hc-market"]} onToggle={toggle} right={<Badge tone={LEVEL_TONE[mdLevel]}>{isNum(md.quality_pct) ? `${fmtNum(md.quality_pct, 2)}%` : DASH}</Badge>}>
          <div className="grid gap-x-8 md:grid-cols-2">
            <div>
              <Row k="Candle data quality" v={isNum(md.quality_pct) ? `${fmtNum(md.quality_pct, 2)}%` : DASH} />
              <Row k="Stale series" v={md.stale_series ?? DASH} className={md.stale_series ? "text-warn" : ""} />
            </div>
            <div>
              <Row k="API errors in cycle" v={ex.errors ?? DASH} className={ex.errors ? "text-warn" : ""} />
              <Row k="Clock difference" v={isNum(ex.clock_skew_ms) ? `${ex.clock_skew_ms} ms` : DASH} />
            </div>
          </div>
          {(errs.exchange_last_error ?? ex.last_error) && <div className="mt-2"><Note>Last error: {errs.exchange_last_error ?? ex.last_error}</Note></div>}
          <div className="mt-4 max-h-96 overflow-auto"><table className="grid-table">
            <thead><tr><th>Asset</th><th>TF</th><th>Status</th><th className="text-right">Candles</th><th className="text-right">Missing</th><th className="text-right">Duplicates</th><th className="text-right">Malformed</th><th className="text-right">Quality</th><th>Last candle closed</th></tr></thead>
            <tbody>{(d.series as any[]).map((s) => (
              <tr key={s.symbol + s.timeframe}><td className="font-medium">{s.symbol}</td><td className="uppercase text-mute">{s.timeframe}</td><td><Badge tone={toneOf(s.status)} caps>{s.status}</Badge></td>
                <td className="num text-right">{s.candles}</td><td className={`num text-right ${s.missing ? "text-warn" : ""}`}>{s.missing}</td><td className="num text-right">{s.duplicates}</td><td className={`num text-right ${s.malformed ? "text-warn" : ""}`}>{s.malformed}</td>
                <td className="num text-right">{isNum(s.quality_pct) ? `${fmtNum(s.quality_pct, 2)}%` : DASH}</td><td className="text-mute">{isNum(s.age_s) ? ago(Date.now() - s.age_s * 1000) : DASH}</td></tr>
            ))}</tbody>
          </table></div>
          {!d.series.length && <Empty>No series yet</Empty>}
        </Section>

        <Section id="hc-models" title="Models" open={!!open["hc-models"]} onToggle={toggle} right={<Badge tone={modelErr.length ? "warn" : "mute"}>{models.length} models</Badge>}>
          <div className="max-h-96 overflow-auto"><table className="grid-table">
            <thead><tr><th>Asset</th><th>TF</th><th>State</th><th>Edge</th><th className="text-right">Age</th><th>Detail</th></tr></thead>
            <tbody>{models.map((m) => (
              <tr key={m.symbol + m.timeframe}><td className="font-medium">{m.symbol}</td><td className="uppercase text-mute">{m.timeframe}</td>
                <td><Badge tone={toneOf(m.state)} caps>{m.state}{m.state === "running" && isNum(m.progress) ? ` ${(m.progress * 100).toFixed(0)}%` : ""}</Badge></td>
                <td className="text-xs text-mute">{m.edge_confirmed == null ? DASH : m.edge_confirmed ? "confirmed" : "none"}</td><td className="num text-right text-mute">{isNum(m.age_h) ? `${m.age_h}h` : DASH}</td>
                <td className="max-w-[16rem] truncate text-xs text-mute" title={modelMsg[m.symbol + "|" + m.timeframe] ?? m.message ?? ""}>{modelMsg[m.symbol + "|" + m.timeframe] ?? m.message ?? m.version ?? ""}</td></tr>
            ))}</tbody>
          </table></div>
          {!models.length && <Empty>No models yet</Empty>}
        </Section>

        <Section id="hc-errors" title="Recent errors" open={!!open["hc-errors"]} onToggle={toggle} right={<Badge tone={errCount ? "warn" : "mute"}>{errCount}</Badge>}>
          {recent.length ? recent.slice(0, 8).map((x: any, i: number) => (
            <p key={i} className="border-b border-line/50 py-1.5 text-xs last:border-0"><span className="text-mute">{fmtTime(x.ts)} · {x.where}: </span><span className="break-words text-warn">{x.error}</span></p>
          )) : <p className="text-sm text-mute">None</p>}
        </Section>
      </div>
    </>
  );
}
