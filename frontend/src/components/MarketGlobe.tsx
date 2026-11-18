// v2.53 Market heat globe (owner, 17 Nov 2026: "make it animated and look real; the card is very empty, add insights").
// A real Earth (Natural Earth 1:110m land, public domain, via world-atlas) drawn on a canvas with d3-geo's orthographic
// projection: it turns slowly (drag to spin it), the night side is shaded from the real position of the sun, and the
// four main stock exchanges glow while their session is open. Beside it, only real numbers: each session's status and
// countdown, BTC's move and share of volume in each trading session over the last 24 hours (public Binance 1h candles,
// already used by this page), hourly volume heat, and the next high-impact US release. No Firestore reads.
// Motion: about 20 frames a second while on screen and the tab is visible; still under prefers-reduced-motion.
import { useEffect, useMemo, useRef, useState } from "react";
import { geoCircle, geoGraticule10, geoOrthographic, geoPath, type GeoPermissibleObjects } from "d3-geo";
import { useKlines } from "../lib/klines";
import { isNum } from "../lib/format";

type Market = { name: string; lon: number; lat: number; open: number; close: number; tz: string };
// main cash session in UTC (winter hours; Tokyo's lunch break ignored). Weekends closed; holidays are not known here.
const MARKETS: Market[] = [
  { name: "Tokyo", lon: 139.7, lat: 35.7, open: 0, close: 6, tz: "TSE" },
  { name: "Dubai", lon: 55.3, lat: 25.2, open: 6, close: 11, tz: "DFM" },
  { name: "London", lon: -0.1, lat: 51.5, open: 8, close: 16.5, tz: "LSE" },
  { name: "New York", lon: -74, lat: 40.7, open: 14.5, close: 21, tz: "NYSE" },
];
// crypto's own trading day, by where most volume comes from (UTC hours)
const SESSIONS: [string, number, number][] = [["Asia", 0, 8], ["Europe", 8, 14], ["US", 14, 21], ["Late US", 21, 24]];

const pct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const dur = (h: number) => { const m = Math.max(0, Math.round(h * 60)); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };

function sunPosition(d: Date): [number, number] {
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  const day = Math.floor((Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) - Date.UTC(d.getUTCFullYear(), 0, 0)) / 864e5);
  return [(12 - h) * 15, -23.44 * Math.cos((2 * Math.PI * (day + 10)) / 365)];
}

function marketState(m: Market, d: Date): { open: boolean; text: string } {
  const h = d.getUTCHours() + d.getUTCMinutes() / 60, wd = d.getUTCDay();
  const weekday = wd >= 1 && wd <= 5;
  if (weekday && h >= m.open && h < m.close) return { open: true, text: `closes in ${dur(m.close - h)}` };
  // next opening: later today (weekday) or the next weekday
  let add = weekday && h < m.open ? m.open - h : 24 - h + m.open;
  let next = (wd + (weekday && h < m.open ? 0 : 1)) % 7;
  while (next === 0 || next === 6) { add += 24; next = (next + 1) % 7; }
  return { open: false, text: `opens in ${dur(add)}` };
}

let landCache: GeoPermissibleObjects | null = null;
function useLand(): GeoPermissibleObjects | null {
  const [land, setLand] = useState(landCache);
  useEffect(() => {
    if (landCache) return;
    let live = true;
    import("../data/land110.json").then((m) => {
      landCache = { type: "MultiPolygon", coordinates: (m.default as unknown) as number[][][][] } as GeoPermissibleObjects;
      if (live) setLand(landCache);
    }).catch(() => {});
    return () => { live = false; };
  }, []);
  return land;
}

function Globe({ size = 340 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const land = useLand();
  const rot = useRef<number | null>(null);
  const drag = useRef<{ x: number; r: number } | null>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv || !land) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = size * dpr; cv.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const R = size / 2 - 14, C = size / 2;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const proj = geoOrthographic().scale(R).translate([C, C]).clipAngle(90).precision(0.6);
    const path = geoPath(proj, ctx);
    const grat = geoGraticule10();
    let raf = 0, last = 0, visible = true, t0 = performance.now();
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; if (visible && !raf) raf = requestAnimationFrame(frame); }, { threshold: 0.05 });
    io.observe(cv);

    function draw(now: number) {
      const d = new Date();
      const [slon, slat] = sunPosition(d);
      if (rot.current == null) rot.current = -10;                       // start over Europe, Africa and the Atlantic
      proj.rotate([rot.current, -18]);
      ctx!.clearRect(0, 0, size, size);
      // atmosphere
      const atm = ctx!.createRadialGradient(C, C, R * 0.92, C, C, R + 14);
      atm.addColorStop(0, "rgba(240,185,11,0.28)"); atm.addColorStop(1, "rgba(240,185,11,0)");
      ctx!.fillStyle = atm; ctx!.beginPath(); ctx!.arc(C, C, R + 14, 0, 2 * Math.PI); ctx!.fill();
      // ocean
      const sea = ctx!.createRadialGradient(C - R * 0.35, C - R * 0.4, R * 0.1, C, C, R);
      sea.addColorStop(0, "#2a4560"); sea.addColorStop(0.55, "#163049"); sea.addColorStop(1, "#08121c");
      ctx!.fillStyle = sea; ctx!.beginPath(); path({ type: "Sphere" }); ctx!.fill();
      // graticule
      ctx!.strokeStyle = "rgba(240,185,11,0.10)"; ctx!.lineWidth = 0.6; ctx!.beginPath(); path(grat); ctx!.stroke();
      // land
      const lg = ctx!.createLinearGradient(C - R, C - R, C + R, C + R);
      lg.addColorStop(0, "#b39556"); lg.addColorStop(0.5, "#8c7341"); lg.addColorStop(1, "#5e4c2b");
      ctx!.fillStyle = lg; ctx!.beginPath(); path(land!); ctx!.fill();
      ctx!.strokeStyle = "rgba(255,214,120,0.55)"; ctx!.lineWidth = 0.7; ctx!.stroke();
      // night side: a soft terminator around the point opposite the sun
      const anti: [number, number] = [slon + 180, -slat];
      for (const [r, a] of [[97, 0.08], [94, 0.12], [91, 0.16], [88, 0.38]] as const) {
        ctx!.fillStyle = `rgba(2,4,10,${a})`; ctx!.beginPath(); path(geoCircle().center(anti).radius(r)()); ctx!.fill();
      }
      // the sun's spot on the day side
      const sp = proj([slon, slat]);
      if (sp && geoPath(proj)({ type: "Point", coordinates: [slon, slat] })) {
        const g = ctx!.createRadialGradient(sp[0], sp[1], 0, sp[0], sp[1], R * 0.75);
        g.addColorStop(0, "rgba(255,226,150,0.20)"); g.addColorStop(1, "rgba(255,226,150,0)");
        ctx!.fillStyle = g; ctx!.beginPath(); path({ type: "Sphere" }); ctx!.fill();
      }
      // exchanges
      const pulse = (Math.sin((now - t0) / 380) + 1) / 2;
      ctx!.font = "600 12px Geist, Inter, system-ui, sans-serif";
      for (const m of MARKETS) {
        const on = marketState(m, d).open;
        const p = proj([m.lon, m.lat]);
        if (!p || !geoPath(proj)({ type: "Point", coordinates: [m.lon, m.lat] })) continue;
        if (on) {
          ctx!.fillStyle = `rgba(240,185,11,${0.18 + 0.22 * (1 - pulse)})`;
          ctx!.beginPath(); ctx!.arc(p[0], p[1], 6 + 10 * pulse, 0, 2 * Math.PI); ctx!.fill();
        }
        ctx!.fillStyle = on ? "#ffd65c" : "rgba(200,190,170,0.75)";
        ctx!.beginPath(); ctx!.arc(p[0], p[1], on ? 4 : 3, 0, 2 * Math.PI); ctx!.fill();
        ctx!.lineWidth = 3; ctx!.strokeStyle = "rgba(6,8,12,0.85)";
        const right = p[0] < C + R * 0.35;                       // labels turn inward near the right edge
        ctx!.textAlign = right ? "left" : "right";
        const lx = p[0] + (right ? 8 : -8), ly = p[1] - 7;
        ctx!.strokeText(m.name, lx, ly);
        ctx!.fillStyle = on ? "#fff1c4" : "rgba(220,212,196,0.85)"; ctx!.fillText(m.name, lx, ly);
      }
      // rim light
      const rim = ctx!.createRadialGradient(C - R * 0.45, C - R * 0.5, R * 0.2, C, C, R * 1.02);
      rim.addColorStop(0, "rgba(255,255,255,0.06)"); rim.addColorStop(0.75, "rgba(255,255,255,0)"); rim.addColorStop(1, "rgba(240,185,11,0.25)");
      ctx!.fillStyle = rim; ctx!.beginPath(); path({ type: "Sphere" }); ctx!.fill();
      ctx!.strokeStyle = "rgba(240,185,11,0.6)"; ctx!.lineWidth = 1; ctx!.beginPath(); path({ type: "Sphere" }); ctx!.stroke();
    }
    function frame(now: number) {
      raf = 0;
      if (!visible || document.hidden) return;
      if (now - last >= 50) {                                   // ~20 fps is smooth for a slow turn and light on phones
        if (!drag.current && !reduce && last) rot.current = (rot.current ?? 0) + ((now - last) / 1000) * 6;   // 6° a second
        last = now;
        draw(now);
      }
      if (!reduce) raf = requestAnimationFrame(frame);
    }
    const wake = () => { if (!document.hidden && !raf) raf = requestAnimationFrame(frame); };
    document.addEventListener("visibilitychange", wake);
    draw(performance.now());
    raf = requestAnimationFrame(frame);
    // drag to spin
    const down = (e: PointerEvent) => { drag.current = { x: e.clientX, r: rot.current ?? 0 }; cv.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => { if (drag.current) { rot.current = drag.current.r + (e.clientX - drag.current.x) * 0.5; if (reduce) draw(performance.now()); } };
    const up = () => { drag.current = null; };
    cv.addEventListener("pointerdown", down); cv.addEventListener("pointermove", move);
    cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up);
    return () => {
      cancelAnimationFrame(raf); io.disconnect(); document.removeEventListener("visibilitychange", wake);
      cv.removeEventListener("pointerdown", down); cv.removeEventListener("pointermove", move);
      cv.removeEventListener("pointerup", up); cv.removeEventListener("pointercancel", up);
    };
  }, [land, size]);
  return (
    <div className="mg-globe" style={{ width: size, maxWidth: "100%" }}>
      {!land && <div className="skeleton absolute inset-0 rounded-full" />}
      <canvas ref={ref} style={{ width: "100%", aspectRatio: "1", touchAction: "pan-y" }}
        aria-label="World map: the main stock exchanges glow while open; the dark side is night now. Drag to turn." role="img" />
    </div>
  );
}

export default function MarketGlobe({ news }: { news: any }) {
  const k = useKlines("BTC/USDT", "1h", 48, 600_000);
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 30_000); return () => window.clearInterval(t); }, []);
  const states = MARKETS.map((m) => ({ m, ...marketState(m, now) }));

  const stats = useMemo(() => {
    const all = k.data ?? [];
    const closed = all.slice(0, -1);                      // the newest candle is still forming
    const day = closed.slice(-24);
    if (day.length < 12) return null;
    const vol = day.reduce((a, c) => a + c[5], 0);
    const avg48 = closed.length ? closed.reduce((a, c) => a + c[5], 0) / closed.length : 0;
    const lastVol = closed.length ? closed[closed.length - 1][5] : null;
    // each session: its most recent stretch of hours inside the last 24 closed hours
    const sessions = SESSIONS.map(([name, a, b]) => {
      const idx = day.map((c, i) => [i, new Date(c[0]).getUTCHours()] as const).filter(([, h]) => h >= a && h < b).map(([i]) => i);
      if (!idx.length) return { name, a, b, change: null as number | null, share: null as number | null, hours: 0 };
      // keep the latest contiguous run
      let s = idx.length - 1;
      while (s > 0 && idx[s - 1] === idx[s] - 1) s--;
      const run = idx.slice(s).map((i) => day[i]);
      const change = (run[run.length - 1][4] / run[0][1] - 1) * 100;
      const v = run.reduce((acc, c) => acc + c[5], 0);
      return { name, a, b, change, share: vol ? v / vol : null, hours: run.length };
    });
    const bars = day.map((c) => ({ t: c[0], v: c[5], up: c[4] >= c[1] }));
    return { sessions, bars, ratio: isNum(lastVol) && avg48 ? lastVol / avg48 : null, max: Math.max(...day.map((c) => c[5])) };
  }, [k.data]);
  const next = news?.next_high && news.next_high.ts > Date.now() ? news.next_high : null;
  const busiest = stats ? stats.sessions.filter((s) => isNum(s.share)).sort((a, b) => (b.share ?? 0) - (a.share ?? 0))[0] : null;

  return (
    <div className="grid items-center gap-5 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      <div className="flex flex-col items-center gap-2">
        <Globe />
        <div className="text-center text-xs text-mute">Live sunlight · {states.filter((s) => s.open).length ? `${states.filter((s) => s.open).map((s) => s.m.name).join(" · ")} open` : "stock markets closed · crypto trades 24/7"} · drag to turn</div>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2">
        <div className="mg-cell sm:col-span-2">
          <div className="mg-h">Stock exchanges now</div>
          <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
            {states.map(({ m, open, text }) => (
              <div key={m.name} className={`mg-mkt ${open ? "is-open" : ""}`}>
                <div className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${open ? "bg-bull live-dot" : "bg-mute/60"}`} /><b className="text-sm">{m.name}</b><span className="text-xs text-mute">{m.tz}</span></div>
                <div className={`text-xs ${open ? "text-bull" : "text-mute"}`}>{open ? "Open" : "Closed"} · {text}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mg-cell">
          <div className="mg-h">BTC by trading session <span className="text-mute">· last 24 h</span></div>
          {stats ? (
            <ul className="mt-2 space-y-1.5">
              {stats.sessions.map((s) => (
                <li key={s.name} className="grid grid-cols-[64px_minmax(0,1fr)_60px] items-center gap-2 text-xs">
                  <span className="font-semibold text-text">{s.name}</span>
                  <span className="mg-share" title={`${Math.round((s.share ?? 0) * 100)} % of the day's volume`}><span style={{ width: `${Math.round((s.share ?? 0) * 100)}%` }} /></span>
                  <span className={`num text-right font-semibold ${s.change == null ? "text-mute" : s.change >= 0 ? "text-bull" : "text-bear"}`}>{s.change == null ? "—" : pct(s.change)}</span>
                </li>
              ))}
            </ul>
          ) : <div className="skeleton mt-2 h-20 rounded-lg" />}
          {busiest && <div className="mt-2 text-xs text-mute">Busiest: <b className="text-text">{busiest.name}</b> with {Math.round((busiest.share ?? 0) * 100)} % of the volume. Bar = share of volume.</div>}
        </div>
        <div className="mg-cell">
          <div className="mg-h">Volume heat <span className="text-mute">· BTC, hour by hour</span></div>
          {stats ? (
            <>
              <div className="mg-heat mt-2" role="img" aria-label="BTC volume in each of the last 24 hours">
                {stats.bars.map((b) => <span key={b.t} className={b.up ? "is-up" : "is-down"} style={{ height: `${Math.max(6, (b.v / stats.max) * 100)}%` }} title={`${new Date(b.t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}: ${b.up ? "up" : "down"} hour`} />)}
              </div>
              <div className="mt-1.5 flex justify-between text-[11px] text-mute"><span>24 h ago</span><span>now</span></div>
              <div className="mt-1 text-xs">Last hour <b className={stats.ratio == null ? "" : stats.ratio >= 1.3 ? "text-accent" : ""}>{stats.ratio == null ? "—" : `${stats.ratio.toFixed(2)}×`}</b> <span className="text-mute">the 48-hour average{stats.ratio == null ? "" : stats.ratio >= 1.3 ? " · busy" : stats.ratio < 0.7 ? " · quiet" : " · normal"}</span></div>
            </>
          ) : <div className="skeleton mt-2 h-20 rounded-lg" />}
        </div>
        <div className="mg-cell sm:col-span-2">
          <div className="mg-h">Next high-impact US release</div>
          {next ? (
            <div className="mt-1 flex flex-wrap items-baseline justify-between gap-2">
              <b>{next.title}</b>
              <span className="text-xs text-mute">{new Date(next.ts).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })} · in {dur((next.ts - now.getTime()) / 3.6e6)} · new signals pause 45 min before</span>
            </div>
          ) : <div className="mt-1 text-sm text-mute">None scheduled soon.</div>}
        </div>
      </div>
    </div>
  );
}
