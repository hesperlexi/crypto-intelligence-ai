// Quant desk (owner, 27 Nov 2026): one dense terminal screen in the style of a trading-desk monitor.
// Only our own real data: the record (views/track_record), the engine's decisions (views/decisions_recent), the 1H
// market board (views/dashboard_1h), BTC candles (public Binance REST) and live prices. Nothing is simulated.
import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/api";
import { useKlines } from "../lib/klines";
import { useLive, useTickerThrottled } from "../lib/live";
import { LiveLogo } from "../components/Logo";
import { base, DASH, fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";

const H = 3_600_000;
const TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const net = (x: any): number | null => (isNum(x?.return_net_pct) ? x.return_net_pct : isNum(x?.return_pct) ? x.return_pct : null);
const riskPct = (x: any) => (isNum(x?.entry) && isNum(x?.stop) && x.entry ? Math.abs(x.entry - x.stop) / x.entry * 100 : null);
const rOf = (x: any) => { const n = net(x), r = riskPct(x); return n != null && r ? n / r : null; };
const hm = (ms: number) => { const m = Math.max(0, Math.round(ms / 60_000)); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };
const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16);
const sgn = (v: number | null | undefined, d = 2) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}` : DASH);
const col = (v: number | null | undefined) => (!isNum(v) || Math.abs(v) < 1e-9 ? "qd-mute" : v > 0 ? "qd-up" : "qd-dn");

function Panel({ title, tag, live, className = "", children }: { title: string; tag?: string; live?: boolean; className?: string; children: React.ReactNode }) {
  return (
    <section className={`qd-panel ${className}`}>
      <header className="qd-ph"><span>◆ {title}</span>{tag && <em>{tag}</em>}{live && <b className="qd-live">● Live</b>}</header>
      <div className="qd-pb">{children}</div>
    </section>
  );
}

function useClock() {
  const [t, setT] = useState(Date.now());
  useEffect(() => { const id = setInterval(() => setT(Date.now()), 1000); return () => clearInterval(id); }, []);
  return t;
}

function Header({ open, stats }: { open: any[]; stats: any }) {
  const btc = useTickerThrottled("BTC/USDT", 1000);
  const t = useClock();
  const longs = open.filter((x) => x.side === "LONG").length;
  return (
    <div className="qd-head">
      <div className="qd-brand">
        <LiveLogo size={40} className="qd-logo" title="Crypto Intelligence AI" />
        <div><small>AI signal engine · record · risk · {TFS.map((x) => x.toUpperCase()).join(" / ")}</small>
          <b>Crypto Intelligence <span className="qd-gold">AI</span> <i>/</i> Quant desk</b>
          <small>Paper trading · net of fees · real record only</small></div>
      </div>
      <div className="qd-hstats">
        <div><small>BTC</small><b className="num">{isNum(btc?.last) ? `$${fmtPrice(btc!.last)}` : DASH}</b></div>
        <div><small>Long / short</small><b className="num">{open.length ? `${longs} / ${open.length - longs}` : DASH}</b></div>
        <div><small>Win rate</small><b className="num">{isNum(stats.wr) ? `${(stats.wr * 100).toFixed(1)}%` : DASH}</b></div>
        <div><small>Closed</small><b className="num">{stats.n}</b></div>
        <div className="qd-clock"><b className="num">{new Date(t).toISOString().slice(11, 19)} UTC</b><small>{isNum(btc?.change_pct) ? `BTC 24h ${sgn(btc!.change_pct)}%` : ""}</small></div>
      </div>
    </div>
  );
}

function Feed({ items }: { items: string[] }) {
  if (!items.length) return null;
  const line = items.join("   ·   ");
  return (
    <div className="qd-feed"><span className="qd-feedtag">● Live feed</span>
      <div className="qd-feedtrack"><span>{line}   ·   </span><span aria-hidden="true">{line}   ·   </span></div>
    </div>
  );
}

function Wallet({ stats }: { stats: any }) {
  return (
    <Panel title="Record" tag="Since start" className="qd-wallet">
      <small className="qd-lbl">Total net return (equal size)</small>
      <div className={`qd-big num ${col(stats.total)}`}>{isNum(stats.total) ? fmtPctRaw(stats.total) : DASH}</div>
      <p className="qd-sub num">Avg {sgn(stats.avg)}% · median {sgn(stats.med)}% · {sgn(stats.totalR, 1)}R</p>
      <div className="qd-trio">
        <div><small>Trades</small><b className="num">{stats.n}</b></div>
        <div><small>Win rate</small><b className="num qd-up">{isNum(stats.wr) ? `${(stats.wr * 100).toFixed(1)}%` : DASH}</b></div>
        <div><small>Avg hold</small><b className="num">{stats.hold ? hm(stats.hold) : DASH}</b></div>
      </div>
      <p className="qd-sub">Long {stats.longShare}% · short {100 - stats.longShare}% <span className="qd-chip">{stats.n < 30 ? "Small sample" : "Sample OK"}</span></p>
    </Panel>
  );
}

function Bowtie({ stats }: { stats: any }) {
  const max = Math.max(1e-9, Math.abs(stats.avgWin ?? 0), Math.abs(stats.avgLoss ?? 0));
  return (
    <Panel title="Payoff bowtie" tag="Win / loss" live>
      <div className="qd-bow">
        <div className="qd-bowcol">
          <div className="qd-bowbar qd-bg-up" style={{ height: `${(Math.abs(stats.avgWin ?? 0) / max) * 70}px` }} />
          <small>Avg win</small><b className="num qd-up">{sgn(stats.avgWin)}%</b><small>{stats.wins} trades</small>
        </div>
        <svg viewBox="0 0 120 80" className="qd-bowsvg" aria-hidden="true">
          <path d={`M0 ${40 - (Math.abs(stats.avgWin ?? 0) / max) * 34} L60 40 L0 ${40 + 2} Z`} fill="rgb(14 203 129 / .35)" stroke="#0ecb81" />
          <path d={`M120 ${40 + (Math.abs(stats.avgLoss ?? 0) / max) * 34} L60 40 L120 ${40 - 2} Z`} fill="rgb(246 70 93 / .35)" stroke="#f6465d" />
          <line x1="0" y1="40" x2="120" y2="40" stroke="#334" />
        </svg>
        <div className="qd-bowcol">
          <div className="qd-bowbar qd-bg-dn" style={{ height: `${(Math.abs(stats.avgLoss ?? 0) / max) * 70}px` }} />
          <small>Avg loss</small><b className="num qd-dn">{sgn(stats.avgLoss)}%</b><small>{stats.losses} trades</small>
        </div>
      </div>
      <p className="qd-sub">Profit factor <b className="num">{isNum(stats.pf) ? stats.pf.toFixed(2) : DASH}</b> · expectancy <b className={`num ${col(stats.avg)}`}>{sgn(stats.avg)}%</b></p>
    </Panel>
  );
}

function Spark({ pts, w = 600, h = 150, zero, band }: { pts: number[]; w?: number; h?: number; zero?: boolean; band?: [number, number] | null }) {
  if (pts.length < 2) return <p className="qd-empty">Waiting for data</p>;
  const lo = Math.min(...pts, ...(zero ? [0] : []), ...(band ?? [])), hi = Math.max(...pts, ...(zero ? [0] : []), ...(band ?? []));
  const y = (v: number) => h - 8 - ((v - lo) / Math.max(1e-9, hi - lo)) * (h - 16);
  const x = (i: number) => (i / (pts.length - 1)) * w;
  const d = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1], up = last >= pts[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="qd-spark" aria-hidden="true">
      {[0.25, 0.5, 0.75].map((f) => <line key={f} x1="0" x2={w} y1={h * f} y2={h * f} className="qd-grid" />)}
      {band && <rect x="0" width={w} y={y(Math.max(...band))} height={Math.abs(y(band[0]) - y(band[1]))} fill="rgb(232 182 55 / .08)" />}
      {zero && <line x1="0" x2={w} y1={y(0)} y2={y(0)} stroke="#E8B637" strokeDasharray="4 4" strokeWidth="1" />}
      <path d={`${d} L${w} ${h} L0 ${h} Z`} fill={up ? "rgb(14 203 129 / .08)" : "rgb(246 70 93 / .08)"} />
      <path d={d} fill="none" stroke={up ? "#0ecb81" : "#f6465d"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function ModelBook({ open, board }: { open: any[]; board: any[] }) {
  const { data } = useKlines("BTC/USDT", "1h", 120);
  const live = useTickerThrottled("BTC/USDT", 1000);
  const closes = (data ?? []).map((c) => c[4]).filter(isNum) as number[];
  if (closes.length && isNum(live?.last)) closes[closes.length - 1] = live!.last;
  const btcCall = open.find((x) => x.symbol === "BTC/USDT");
  const ups = board.filter((r) => r.lean === "LONG" || (isNum(r.p_up) && isNum(r.p_down) && r.p_up > r.p_down)).length;
  return (
    <Panel title="Model book · BTC 1H" tag={btcCall ? `${btcCall.side} ${btcCall.timeframe.toUpperCase()} running` : "No BTC call"} className="qd-book">
      <div className="qd-bookgrid">
        <Spark pts={closes} band={btcCall && isNum(btcCall.stop) && isNum(btcCall.tp1) ? [btcCall.stop, btcCall.tp1] : null} />
        <div className="qd-zones">
          <small>AI lean 1H</small>
          <div><span>Up</span><b className="num qd-up">{board.length ? `${Math.round((ups / board.length) * 100)}%` : DASH}</b></div>
          <div><span>Down</span><b className="num qd-dn">{board.length ? `${100 - Math.round((ups / board.length) * 100)}%` : DASH}</b></div>
          <small>Coins</small><b className="num">{board.length}</b>
          <small>120 h range</small><b className="num">{closes.length ? `${(((Math.max(...closes) / Math.min(...closes)) - 1) * 100).toFixed(1)}%` : DASH}</b>
        </div>
      </div>
      <p className="qd-sub">{btcCall ? "Gold band = the running BTC call's stop → target 1" : "Gold band appears when a BTC call is running"}</p>
    </Panel>
  );
}

function Phase({ trips }: { trips: any[] }) {
  const netR = trips.reduce((a, t) => a + (t.r ?? 0) * t.s, 0);
  const W = 300, Hh = 210, cx = 40, cy = Hh / 2;
  return (
    <Panel title="Inventory phase portrait" live className="qd-phase">
      <svg viewBox={`0 0 ${W} ${Hh}`} className="qd-phasesvg" role="img" aria-label="Running calls fanned out by direction and result">
        {[-1, -0.5, 0, 0.5, 1].map((f) => <line key={f} x1={cx} y1={cy} x2={W - 10} y2={cy - f * (Hh / 2 - 12)} className="qd-grid" />)}
        <text x="8" y="16" className="qd-svgt">Long ↑</text><text x="8" y={Hh - 6} className="qd-svgt">Short ↓</text>
        {trips.map((t) => {
          const r = Math.max(-1.5, Math.min(3, t.r ?? 0));
          const len = 60 + ((r + 1.5) / 4.5) * (W - 110);
          const same = trips.filter((q) => q.s === t.s), k = same.indexOf(t);
          const ang = t.s * (0.12 + (k / Math.max(1, same.length - 1)) * 0.95);
          const lenK = len * (0.75 + 0.25 * ((k % 3) / 2));
          const x2 = cx + lenK * Math.cos(ang), y2 = cy - lenK * Math.sin(ang);
          const c = t.r == null ? "#8892a6" : t.r > 0.1 ? "#0ecb81" : t.r < -0.1 ? "#f6465d" : "#E8B637";
          return (
            <g key={t.x.id}>
              <line x1={cx} y1={cy} x2={x2} y2={y2} stroke={c} strokeOpacity=".55" strokeDasharray="3 3" />
              <circle cx={x2} cy={y2} r="4" fill={c} />
              {(k % 2 === 0 || same.length < 6) && <text x={x2 + 6} y={y2 + 3} className="qd-svgt">{base(t.x.symbol)} {t.x.timeframe}</text>}
            </g>
          );
        })}
        <circle cx={cx} cy={cy} r="5" fill="#5DF1DD" />
      </svg>
      <div className="qd-kv"><span>net directional value</span><b className={`num ${col(netR)}`}>{trips.length ? `${netR > 0 ? "Long" : netR < 0 ? "Short" : "Flat"} ${Math.abs(netR).toFixed(2)}R` : DASH}</b></div>
      <div className="qd-kv"><span>running calls</span><b className="num">{trips.length}</b></div>
    </Panel>
  );
}

function Curve({ closed }: { closed: any[] }) {
  const pts = useMemo(() => { let a = 0; return [0, ...closed.slice().sort((x, y) => (x.closed_at ?? 0) - (y.closed_at ?? 0)).map((x) => (a += net(x) ?? 0))]; }, [closed]);
  let peak = 0, dd = 0; for (const v of pts) { peak = Math.max(peak, v); dd = Math.min(dd, v - peak); }
  return (
    <Panel title="Where it lands · running total" tag="Net %">
      <Spark pts={pts} h={120} zero />
      <p className="qd-sub num">Closed {closed.length} · total {sgn(pts[pts.length - 1])}% · largest drop {dd.toFixed(2)}%</p>
    </Panel>
  );
}

/** The "neural shell" (owner's reference video, 27 Nov 2026): a horn torus of fine thread seen at an angle, so the strands
 *  pour into a funnel on its right. It spins on its axis and wobbles, the tint drifts, spikes stand off the rim. Every
 *  call of the record is one coloured strand (green won, red lost, gold running) among neutral threads; running calls
 *  also sit on the surface as dots. Batched strokes per colour keep it smooth; fewer threads on phones. */
type Strand = { kind: "base" | "win" | "loss" | "open"; seed: number };
const TINTS = [[232, 236, 255], [255, 226, 150], [150, 240, 230]];
const Torus = memo(function Torus({ strands, spinRef }: { strands: Strand[]; spinRef: React.MutableRefObject<HTMLElement | null> }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const phone = matchMedia("(max-width: 640px)").matches;
    const rnd = (k: number) => { const x = Math.sin(k * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
    // geometry in torus space, built once: meridian-like threads with a little jitter, some with a spike off the rim
    const base = phone ? 300 : 820, M = phone ? 34 : 44;
    const list: Strand[] = [...strands, ...Array.from({ length: base }, (_, i) => ({ kind: "base" as const, seed: rnd(i + 1) }))];
    const geo = list.map((st, k) => {
      const u0 = st.seed * 6.283 + rnd(k * 3) * 0.4, j = 0.04 + rnd(k * 7) * 0.06, sk = rnd(k * 11);
      const pts: number[] = [];
      for (let i = 0; i <= M; i++) {
        const v = (i / M) * 6.283 + rnd(k) * 6.283;
        const u = u0 + 0.22 * Math.sin(v * 1.5 + k) + (rnd(k * 5) - 0.5) * 0.3;
        const r = 1 + j * Math.sin(v * 3 + k * 1.7);
        const ring = (1 + Math.cos(v)) * r;
        pts.push(ring * Math.cos(u), ring * Math.sin(u), Math.sin(v) * r);
      }
      const spike = sk < 0.28 ? { u: u0 + rnd(k * 13) * 0.3, len: 0.08 + rnd(k * 17) * 0.22 } : null;
      return { st, pts, spike };
    });
    const dots = list.map((st, k) => ({ st, k })).filter((x) => x.st.kind === "open").map(({ k }) => ({ u: rnd(k * 19) * 6.283, v: rnd(k * 23) * 6.283 }));
    let raf = 0, spin = 0, t = 0, last = 0, prev = 0;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (document.hidden || now - last < (phone ? 50 : 33)) return;
      last = now;
      const dt = Math.min(0.1, (now - (prev || now)) / 1000); prev = now;
      t += dt; spin += dt * 0.5;
      const dpr = Math.min(2, devicePixelRatio || 1), W = cv.clientWidth, Hh = cv.clientHeight;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(Hh * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(Hh * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, Hh);
      const S = Math.min(W * (W < 520 ? 0.4 : 0.3), Hh * 0.4) / 2.05, cx = W * 0.44, cy = Hh * 0.5;
      // spin about the torus axis, then tilt it so the funnel faces right (with a slow wobble)
      const cs = Math.cos(spin), ss = Math.sin(spin);
      const by = 0.85 + 0.28 * Math.sin(t * 0.5), cb = Math.cos(by), sb = Math.sin(by);
      const bx = 0.18 + 0.12 * Math.sin(t * 0.37), cxx = Math.cos(bx), sxx = Math.sin(bx);
      const P = (x: number, y: number, z: number): [number, number, number] => {
        const x1 = x * cs - y * ss, y1 = x * ss + y * cs;
        const x2 = x1 * cb + z * sb, z2 = -x1 * sb + z * cb;
        const y3 = y1 * cxx - z2 * sxx, z3 = y1 * sxx + z2 * cxx;
        return [cx + x2 * S, cy + y3 * S, z3];
      };
      // tint drifts white -> gold -> cyan
      const ph = (t * 0.05) % 3, i0 = Math.floor(ph), f = ph - i0, A = TINTS[i0], B = TINTS[(i0 + 1) % 3];
      const tint = A.map((c, n) => Math.round(c + (B[n] - c) * f)).join(",");
      ctx.globalCompositeOperation = "lighter";
      const groups: Record<string, { w: number; c: string; ks: number[] }> = {
        b1: { w: 0.5, c: `rgba(${tint},.13)`, ks: [] }, b2: { w: 0.6, c: `rgba(${tint},.22)`, ks: [] }, b3: { w: 0.7, c: `rgba(${tint},.36)`, ks: [] },
        win: { w: 0.8, c: "rgba(14,203,129,.45)", ks: [] }, loss: { w: 0.8, c: "rgba(246,70,93,.45)", ks: [] }, open: { w: 0.9, c: "rgba(232,182,55,.5)", ks: [] },
      };
      geo.forEach((g, k) => (g.st.kind === "base" ? groups[["b1", "b2", "b3"][k % 3]] : groups[g.st.kind]).ks.push(k));
      const tips: [number, number][] = [];
      for (const gname in groups) {
        const gr = groups[gname];
        // front half bright, back half dim, so the funnel opening reads as a hole like the reference
        const front = new Path2D(), back = new Path2D();
        for (const k of gr.ks) {
          const p = geo[k].pts;
          let px = 0, py = 0, pz = 0;
          for (let i = 0; i < p.length; i += 3) {
            const [x, y, z] = P(p[i], p[i + 1], p[i + 2]);
            if (i) { const path = (z + pz) / 2 > -0.15 ? front : back; path.moveTo(px, py); path.lineTo(x, y); }
            px = x; py = y; pz = z;
          }
          const sp = geo[k].spike;
          if (sp) {
            const [x0, y0] = P(2 * Math.cos(sp.u), 2 * Math.sin(sp.u), 0), [x1, y1] = P(2 * (1 + sp.len) * Math.cos(sp.u), 2 * (1 + sp.len) * Math.sin(sp.u), 0);
            front.moveTo(x0, y0); front.lineTo(x1, y1); tips.push([x1, y1]);
          }
        }
        ctx.lineWidth = gr.w;
        ctx.strokeStyle = gr.c.replace(/[\d.]+\)$/, (m) => `${(parseFloat(m) * 0.3).toFixed(3)})`); ctx.stroke(back);
        ctx.strokeStyle = gr.c; ctx.stroke(front);
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = `rgba(${tint},.85)`;
      for (const [x, y] of tips) { ctx.beginPath(); ctx.arc(x, y, 1.4, 0, 6.283); ctx.fill(); }
      // funnel glow where every thread converges
      const [fx, fy] = P(0, 0, 0);
      const g = ctx.createRadialGradient(fx, fy, 0, fx, fy, S * 0.28);
      g.addColorStop(0, "rgba(255,255,255,.55)"); g.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(fx, fy, S * 0.28, 0, 6.283); ctx.fill();
      // running calls as dots on the surface
      for (const d of dots) {
        const ring = 1 + Math.cos(d.v), [x, y, z] = P(ring * Math.cos(d.u), ring * Math.sin(d.u), Math.sin(d.v));
        ctx.fillStyle = z > 0 ? "rgba(246,70,93,.95)" : "rgba(246,70,93,.45)"; ctx.beginPath(); ctx.arc(x, y, 2.4, 0, 6.283); ctx.fill();
      }
      // link from the funnel to the live trades column (colour drifts gold -> green)
      const lc = `rgb(${Math.round(232 - 218 * (0.5 + 0.5 * Math.sin(t * 0.5)))},${Math.round(182 + 21 * (0.5 + 0.5 * Math.sin(t * 0.5)))},${Math.round(55 + 74 * (0.5 + 0.5 * Math.sin(t * 0.5)))})`;
      ctx.strokeStyle = lc; ctx.lineWidth = 1.6; ctx.shadowColor = lc; ctx.shadowBlur = 6;
      ctx.beginPath(); ctx.moveTo(fx, fy); ctx.bezierCurveTo(W * 0.8, fy, W - 30, fy, W - 24, Hh * 0.35); ctx.lineTo(W - 24, 30); ctx.quadraticCurveTo(W - 24, 14, W - 2, 14); ctx.stroke();
      ctx.shadowBlur = 0;
      // degree scale on the left
      ctx.fillStyle = "rgba(150,165,190,.75)"; ctx.font = "11px 'IBM Plex Sans', sans-serif"; ctx.strokeStyle = "rgba(150,165,190,.35)"; ctx.lineWidth = 1;
      ["0°", "45°", "90°", "135°", "180°", "225°", "270°", "315°"].forEach((lab, i) => {
        const y = 18 + i * ((Hh - 36) / 7); ctx.beginPath(); ctx.moveTo(4, y); ctx.lineTo(12, y); ctx.stroke(); ctx.fillText(lab, 16, y + 4);
      });
      if (spinRef.current) spinRef.current.textContent = `Spin ${(((spin * 180) / Math.PI) % 360).toFixed(1)}° · axis lock`;
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [strands, spinRef]);
  return <div className="qd-torus"><canvas ref={ref} aria-hidden="true" /></div>;
});

function Shell({ closed, open, board }: { closed: any[]; open: any[]; board: any[] }) {
  const spinRef = useRef<HTMLElement | null>(null);
  const strands = useMemo(() => {
    const out: Strand[] = [];
    const h = (s: string) => { let x = 7; for (const ch of s) x = (x * 31 + ch.charCodeAt(0)) % 9973; return x / 9973; };
    closed.forEach((x) => out.push({ kind: (net(x) ?? 0) > 0 ? "win" : "loss", seed: h(x.id + "c") }));
    open.forEach((x) => out.push({ kind: "open", seed: h(x.id + "o") }));
    return out;
  }, [closed, open]);
  const last = closed.slice().sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0))[0];
  const best = open.slice().sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0];
  return (
    <Panel title="Neural shell · record torus" tag={`Calls ${closed.length + open.length} · coins ${board.length}`} className="qd-shell">
      <div className="qd-shellwrap">
        <Torus strands={strands} spinRef={spinRef} />
        <div className="qd-shellhead"><b>Record torus</b><small>{closed.length + open.length + (typeof window !== "undefined" && matchMedia("(max-width: 640px)").matches ? 300 : 820)} strands · {open.length} running</small></div>
        <small ref={spinRef} className="qd-spin num" />
        {best && <div className="qd-scan num">[Scan · {base(best.symbol)} {best.timeframe.toUpperCase()}]<br />{best.side} @ {fmtPrice(best.entry)} · grade {best.grade ?? DASH}</div>}
        {last && <div className="qd-shellnote num">Last close · {base(last.symbol)} {last.timeframe.toUpperCase()} {last.side} · <span className={col(net(last))}>{sgn(net(last))}%</span> · {hhmm(last.closed_at)} UTC</div>}
      </div>
      <div className="qd-legend"><i className="qd-bg-up" /> won <i className="qd-bg-dn" /> lost <i style={{ background: "#E8B637" }} /> running <i style={{ background: "#dfe6f5" }} /> neural threads</div>
    </Panel>
  );
}

function Trades({ trips, closed }: { trips: any[]; closed: any[] }) {
  const recent = closed.slice().sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 2);
  return (
    <Panel title="Live trades · all timeframes" tag={`${trips.length} running`} className="qd-trades">
      <ul className="qd-tl">
        {trips.slice(0, 5).map((t) => (
          <li key={t.x.id} className={t.s > 0 ? "is-long" : "is-short"}>
            <Link to={`/asset/${slug(t.x.symbol)}?tf=${t.x.timeframe}`}>
              <span className={`qd-pill ${t.s > 0 ? "qd-bg-up" : "qd-bg-dn"}`}>{t.s > 0 ? "Long" : "Short"}</span>
              <b>{base(t.x.symbol)} {t.x.timeframe.toUpperCase()}</b>
              <span className="num qd-mute">@ {fmtPrice(t.x.entry)}</span>
              <span className="num qd-mute">{t.x.grade ? `Grade ${t.x.grade}` : ""}</span>
              <b className={`num ${col(t.r)}`}>{t.pending ? "Waiting" : `${sgn(t.r)}R`}</b>
              <small className="qd-mute">{[t.x.tp1_hit && "TP1", t.x.tp2_hit && "TP2", t.x.tp3_hit && "TP3"].filter(Boolean).join(" · ") || "no target yet"} · {hm(Date.now() - (t.x.created_at ?? Date.now()))} ago</small>
            </Link>
          </li>
        ))}
        {recent.map((x) => (
          <li key={x.id} className="is-done">
            <span className="qd-pill qd-bg-mute">Closed</span>
            <b>{base(x.symbol)} {x.timeframe.toUpperCase()} {x.side}</b>
            <span className="num qd-mute">{x.status}</span><span />
            <b className={`num ${col(net(x))}`}>{sgn(net(x))}%</b>
            <small className="qd-mute">{hhmm(x.closed_at)} UTC</small>
          </li>
        ))}
        {!trips.length && !recent.length && <li className="qd-empty">No calls yet</li>}
      </ul>
    </Panel>
  );
}

function Quant({ board }: { board: any[] }) {
  const { data } = useKlines("BTC/USDT", "1h", 48);
  const cs = (data ?? []).slice(-48).map((k) => ({ open: k[1], high: k[2], low: k[3], close: k[4] }));
  const lo = Math.min(...cs.map((c) => c.low)), hi = Math.max(...cs.map((c) => c.high));
  const W = 480, Hh = 140, bw = W / Math.max(1, cs.length);
  const y = (v: number) => Hh - 6 - ((v - lo) / Math.max(1e-9, hi - lo)) * (Hh - 12);
  const bars = board.filter((r) => isNum(r.change_24h_pct)).sort((a, b) => b.change_24h_pct - a.change_24h_pct);
  const mx = Math.max(1, ...bars.map((r) => Math.abs(r.change_24h_pct)));
  return (
    <Panel title="Quant metrics · BTC 1H + 24H movers" live className="qd-quant">
      <div className="qd-qgrid">
        {cs.length ? (
          <svg viewBox={`0 0 ${W} ${Hh}`} preserveAspectRatio="none" className="qd-candles" aria-hidden="true">
            {cs.map((c: any, i: number) => {
              const up = c.close >= c.open, k = up ? "#0ecb81" : "#f6465d", x = i * bw + bw / 2;
              return <g key={i}><line x1={x} x2={x} y1={y(c.high)} y2={y(c.low)} stroke={k} vectorEffect="non-scaling-stroke" /><rect x={x - bw * 0.32} width={bw * 0.64} y={y(Math.max(c.open, c.close))} height={Math.max(1, Math.abs(y(c.open) - y(c.close)))} fill={k} /></g>;
            })}
          </svg>
        ) : <p className="qd-empty">Loading candles</p>}
        <ul className="qd-movers">
          {bars.slice(0, 6).concat(bars.slice(-6)).map((r, i) => (
            <li key={`${r.symbol}${i}`}><span>{base(r.symbol)}</span><i><em className={r.change_24h_pct >= 0 ? "qd-bg-up" : "qd-bg-dn"} style={{ width: `${(Math.abs(r.change_24h_pct) / mx) * 100}%` }} /></i><b className={`num ${col(r.change_24h_pct)}`}>{sgn(r.change_24h_pct, 1)}%</b></li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

function Edge({ closed }: { closed: any[] }) {
  const rs = closed.map(rOf).filter(isNum) as number[];
  const bins = Array.from({ length: 13 }, (_, i) => -2 + i * 0.5);
  const counts = bins.map((b, i) => rs.filter((r) => r >= b && (i === bins.length - 1 || r < b + 0.5)).length);
  const mx = Math.max(1, ...counts);
  const mean = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0;
  const sd = rs.length > 1 ? Math.sqrt(rs.reduce((a, b) => a + (b - mean) ** 2, 0) / (rs.length - 1)) : 0;
  const se = rs.length ? sd / Math.sqrt(rs.length) : 0;
  const W = 360, Hh = 130;
  const bell = sd > 0 ? Array.from({ length: 61 }, (_, i) => { const x = -2 + (i / 60) * 6.5; return [((x + 2) / 6.5) * W, Hh - 10 - Math.exp(-((x - mean) ** 2) / (2 * sd * sd)) * (Hh - 24)]; }) : [];
  return (
    <Panel title="Edge significance · R per trade" tag={`n=${rs.length}`} className="qd-edge">
      <svg viewBox={`0 0 ${W} ${Hh}`} className="qd-hist" aria-hidden="true">
        {counts.map((c, i) => <rect key={i} x={(i / bins.length) * W + 2} width={W / bins.length - 4} y={Hh - 10 - (c / mx) * (Hh - 24)} height={(c / mx) * (Hh - 24)} fill={bins[i] >= 0 ? "rgb(14 203 129 / .55)" : "rgb(246 70 93 / .55)"} />)}
        {bell.length > 0 && <path d={bell.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ")} fill="none" stroke="#a78bfa" strokeWidth="1.5" />}
        <line x1={(2 / 6.5) * W} x2={(2 / 6.5) * W} y1="0" y2={Hh} stroke="#E8B637" strokeDasharray="3 3" />
        <text x="4" y={Hh - 1} className="qd-svgt">−2R</text><text x={(2 / 6.5) * W + 3} y="10" className="qd-svgt">0R</text><text x={W - 22} y={Hh - 1} className="qd-svgt">+4R</text>
      </svg>
      <EdgeExtras rs={rs} />
      <div className="qd-trio">
        <div><small>Mean</small><b className={`num ${col(mean)}`}>{rs.length ? `${sgn(mean)}R` : DASH}</b></div>
        <div><small>95% range</small><b className="num">{rs.length > 1 ? `${sgn(mean - 1.96 * se)} … ${sgn(mean + 1.96 * se)}` : DASH}</b></div>
        <div><small>Verdict</small><b className={rs.length < 30 ? "qd-gold" : mean - 1.96 * se > 0 ? "qd-up" : mean + 1.96 * se < 0 ? "qd-dn" : "qd-gold"}>{rs.length < 30 ? "Too early" : mean - 1.96 * se > 0 ? "Edge" : mean + 1.96 * se < 0 ? "Negative" : "Not proven"}</b></div>
      </div>
    </Panel>
  );
}

/** CUSUM of R (running sum minus the mean: drifting down = losing edge) and a bootstrap of the mean R (1,000
 *  resamples of the real closed calls, fixed seed so it does not jump on every render). */
function EdgeExtras({ rs }: { rs: number[] }) {
  const { cus, boot } = useMemo(() => {
    const m = rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0;
    let c = 0; const cus = [0, ...rs.map((r) => (c += r - m))];
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const boot: number[] = [];
    if (rs.length >= 3) for (let i = 0; i < 1000; i++) { let s = 0; for (let j = 0; j < rs.length; j++) s += rs[Math.floor(rnd() * rs.length)]; boot.push(s / rs.length); }
    return { cus, boot };
  }, [rs]);
  if (rs.length < 3) return null;
  const W = 170, Hh = 70;
  const lo = Math.min(...cus), hi = Math.max(...cus);
  const cy = (v: number) => Hh - 6 - ((v - lo) / Math.max(1e-9, hi - lo)) * (Hh - 12);
  const bl = Math.min(...boot), bh = Math.max(...boot), nb = 24;
  const bc = Array.from({ length: nb }, (_, i) => boot.filter((v) => Math.min(nb - 1, Math.floor(((v - bl) / Math.max(1e-9, bh - bl)) * nb)) === i).length);
  const bm = Math.max(1, ...bc), share = boot.filter((v) => v > 0).length / boot.length;
  return (
    <div className="qd-edgex">
      <div><small>CUSUM · drift of R</small>
        <svg viewBox={`0 0 ${W} ${Hh}`} preserveAspectRatio="none" aria-hidden="true">
          <path d={cus.map((v, i) => `${i ? "L" : "M"}${((i / (cus.length - 1)) * W).toFixed(1)} ${cy(v).toFixed(1)}`).join(" ")} fill="none" stroke="#f59e0b" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
          <line x1="0" x2={W} y1={cy(0)} y2={cy(0)} stroke="#3a4558" strokeDasharray="3 3" />
        </svg></div>
      <div><small>Bootstrap · {Math.round(share * 100)}% above 0R</small>
        <svg viewBox={`0 0 ${W} ${Hh}`} preserveAspectRatio="none" aria-hidden="true">
          {bc.map((c, i) => <rect key={i} x={(i / nb) * W + 0.5} width={W / nb - 1} y={Hh - 4 - (c / bm) * (Hh - 10)} height={(c / bm) * (Hh - 10)} fill="#8b7cf6" opacity=".8" />)}
          {bl < 0 && bh > 0 && <line x1={((0 - bl) / (bh - bl)) * W} x2={((0 - bl) / (bh - bl)) * W} y1="0" y2={Hh} stroke="#E8B637" strokeDasharray="3 3" />}
        </svg></div>
    </div>
  );
}

function Trace({ decisions }: { decisions: any[] }) {
  return (
    <Panel title="Decision trace · engine log" live className="qd-trace">
      <ol className="qd-log">
        {decisions.slice(0, 12).map((d, i) => (
          <li key={i} className="num"><span className="qd-mute">{hhmm(d.ts)}</span><b>{base(d.symbol ?? "")} {(d.timeframe ?? "").toUpperCase()}</b><span className={/stop|skip|block|no/i.test(d.rule ?? "") ? "qd-dn" : /fill|open|tp|entry/i.test(d.rule ?? "") ? "qd-up" : "qd-gold"}>{String(d.rule ?? "").replace(/_/g, " ")}</span></li>
        ))}
        {!decisions.length && <li className="qd-empty">No engine decisions yet</li>}
      </ol>
    </Panel>
  );
}

function Arrivals({ all }: { all: any[] }) {
  const now = Date.now();
  const cols = 24;
  const grid = TFS.map((tf) => Array.from({ length: cols }, (_, i) => all.filter((x) => x.timeframe === tf && x.created_at >= now - (cols - i) * 7 * H && x.created_at < now - (cols - i - 1) * 7 * H).length));
  const mx = Math.max(1, ...grid.flat());
  const week = all.filter((x) => x.created_at >= now - 7 * 24 * H).length;
  const filled = all.filter((x) => x.fill_status === "FILLED").length;
  return (
    <Panel title="Signal arrival · by timeframe" tag="Last 7 days" className="qd-arrive">
      <div className="qd-heat">
        {grid.map((row, r) => (
          <div key={TFS[r]} className="qd-heatrow"><span>{TFS[r].toUpperCase()}</span>
            {row.map((c, i) => <i key={i} style={{ background: c ? `rgb(232 182 55 / ${0.18 + (c / mx) * 0.8})` : "rgb(255 255 255 / .04)" }} title={`${c} calls`} />)}
          </div>
        ))}
        <div className="qd-heatax"><span>−7d</span><span>now</span></div>
      </div>
      <div className="qd-kv"><span>calls in 7 days</span><b className="num">{week}</b></div>
      <div className="qd-kv"><span>filled share</span><b className="num">{all.length ? `${Math.round((filled / all.length) * 100)}%` : DASH}</b></div>
    </Panel>
  );
}

export default function Desk() {
  const tr = useApi<any>("/track-record");
  const dec = useApi<any>("/decisions");
  const board = useApi<any>("/dashboard?timeframe=1h");
  const { tickers } = useLive();
  const sigs: any[] = tr.data?.live?.signals ?? [];
  const open = sigs.filter((x) => x.status === "OPEN");
  const closed = sigs.filter((x) => x.status !== "OPEN" && net(x) != null && x.fill_status !== "NOT_FILLED");
  const rows: any[] = board.data?.rows ?? [];
  const trips = open.map((x) => {
    const s = x.side === "SHORT" ? -1 : 1, px = tickers[x.symbol]?.last;
    const pending = x.fill_status === "PENDING";
    const r = !pending && isNum(px) && x.entry !== x.stop ? (s * (px - x.entry)) / Math.abs(x.entry - x.stop) : null;
    return { x, s, r, pending };
  }).sort((a, b) => (b.r ?? -99) - (a.r ?? -99));
  const stats = useMemo(() => {
    const ns = closed.map(net) as number[];
    const wins = ns.filter((v) => v > 0), losses = ns.filter((v) => v <= 0);
    const sorted = [...ns].sort((a, b) => a - b);
    const holds = closed.map((x) => (x.closed_at ?? 0) - (x.filled_at ?? x.created_at ?? 0)).filter((v) => v > 0);
    const longs = closed.filter((x) => x.side === "LONG").length;
    return {
      n: ns.length, wr: ns.length ? wins.length / ns.length : null, total: ns.length ? ns.reduce((a, b) => a + b, 0) : null,
      avg: ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : null, med: sorted.length ? sorted[Math.floor(sorted.length / 2)] : null,
      totalR: (closed.map(rOf).filter(isNum) as number[]).reduce((a, b) => a + b, 0),
      hold: holds.length ? holds.reduce((a, b) => a + b, 0) / holds.length : 0, longShare: ns.length ? Math.round((longs / ns.length) * 100) : 50,
      wins: wins.length, losses: losses.length, avgWin: wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : null,
      avgLoss: losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : null,
      pf: losses.length && losses.reduce((a, b) => a + b, 0) !== 0 ? wins.reduce((a, b) => a + b, 0) / Math.abs(losses.reduce((a, b) => a + b, 0)) : null,
    };
  }, [closed]);
  const decisions: any[] = dec.data?.decisions ?? [];
  const feed = useMemo(() => [
    ...closed.slice().sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0)).slice(0, 6).map((x) => `${base(x.symbol)} ${x.timeframe.toUpperCase()} ${x.side} ${x.status} ${sgn(net(x))}%`),
    ...decisions.slice(0, 6).map((d) => `${base(d.symbol ?? "")} ${(d.timeframe ?? "").toUpperCase()} ${String(d.rule ?? "").replace(/_/g, " ")}`),
    ...open.slice(0, 6).map((x) => `${base(x.symbol)} ${x.timeframe.toUpperCase()} ${x.side} RUNNING`),
  ], [closed, decisions, open]);
  return (
    <div className="qd">
      <Header open={open} stats={stats} />
      <Feed items={feed} />
      <div className="qd-grid">
        <div className="qd-c1"><Wallet stats={stats} /><Bowtie stats={stats} /></div>
        <div className="qd-c2"><ModelBook open={open} board={rows} /><Curve closed={closed} /></div>
        <div className="qd-c3"><Phase trips={trips} /></div>
        <div className="qd-c4"><Shell closed={closed} open={open} board={rows} /><div className="qd-pair"><Edge closed={closed} /><Trace decisions={decisions} /></div><Arrivals all={sigs} /></div>
        <div className="qd-c5"><Trades trips={trips} closed={closed} /><Quant board={rows} /></div>
      </div>
      <div className="qd-foot">Record net of 0.15% fees + funding · paper trading · not advice</div>
    </div>
  );
}
