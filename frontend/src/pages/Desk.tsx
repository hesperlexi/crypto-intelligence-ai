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
  const closes = (data ?? []).map((c) => c[4]).filter(isNum) as number[];
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

/** The "neural shell": every coin on the board and every call of the record as a strand around a torus. Slow turn,
 *  still under reduced motion, paused while the tab is hidden. Strand colour = the call's result (green / red / gold open). */
const Torus = memo(function Torus({ strands }: { strands: { c: string; w: number; seed: number }[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const ctx = cv.getContext("2d"); if (!ctx) return;
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const phone = matchMedia("(max-width: 640px)").matches;
    // the record's strands first (tinted), then fine silver filler strands so the shell reads as one dense ball
    const N = phone ? 260 : 520;
    const all = [...strands.filter((s) => !s.c.startsWith("rgba(140")), ...Array.from({ length: Math.max(0, N - strands.length) }, (_, i) => ({ c: "", w: 0.5, seed: (i * 0.6180339) % 1 }))];
    const pts = phone ? 64 : 84;
    let raf = 0, a = 0, last = 0, prev = 0;
    const draw = (now: number) => {
      raf = requestAnimationFrame(draw);
      if (document.hidden || now - last < (phone ? 60 : 40)) return;
      last = now;
      a += Math.min(0.1, (now - (prev || now)) / 1000) * (still ? 0.12 : 0.45);
      prev = now;
      const dpr = Math.min(2, devicePixelRatio || 1), W = cv.clientWidth, Hh = cv.clientHeight;
      if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(Hh * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(Hh * dpr); }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, Hh);
      // the "tire": a torus of thread that keeps turning (it spins about a slanted vertical axis, so its outline changes
      // like the reference) while the strands also flow along themselves
      const E = Math.min(W * (W < 520 ? 0.52 : 0.32), Hh * 0.82) / 2, R = E / 1.96, rr = R * 0.96;
      const cx = W * 0.4, cy = Hh / 2;
      const b = 0.9 + a * 0.55, cb = Math.cos(b), sb = Math.sin(b), c = 0.45, cc = Math.cos(c), sc = Math.sin(c);
      const hx = cx, hy = cy;
      ctx.lineWidth = 0.5;
      for (let i = 0; i < 46; i++) {
        const f = i / 45, ang = -1.1 + f * 2.2;
        const sx = cx + Math.cos(ang) * E * 1.02, sy = cy + Math.sin(ang) * E * 1.02;
        ctx.strokeStyle = `rgba(210,225,255,${0.05 + 0.1 * Math.sin(f * Math.PI)})`;
        ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(W, cy + (f - 0.5) * Hh * 1.1); ctx.stroke();
      }
      ctx.globalCompositeOperation = "lighter";
      all.forEach((s, k) => {
        const ph = s.seed * 6.283, off = (k * 2.39996) % 6.283, n = 1 + (k % 4);
        ctx.lineWidth = s.c ? 0.8 : 0.5;
        ctx.strokeStyle = s.c ? s.c.replace(/[\d.]+\)$/, ".35)") : `rgba(225,233,255,${0.06 + (k % 7) * 0.013})`;
        ctx.beginPath();
        for (let i = 0; i <= pts; i++) {
          const t = (i / pts) * 6.283;
          const u = off + t, v = ph + n * t + a * (0.9 + (k % 3) * 0.3);
          const ring = R + rr * Math.cos(v);
          const x = ring * Math.cos(u), y = ring * Math.sin(u), z = rr * Math.sin(v);
          const x1 = x * cb + z * sb, z1 = -x * sb + z * cb;
          const y2 = y * cc - z1 * sc;
          const px = cx + x1, py = cy + y2;
          i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
        }
        ctx.stroke();
      });
      // bright knot where the strands converge
      const g = ctx.createRadialGradient(hx, hy, 0, hx, hy, R * 0.55);
      g.addColorStop(0, "rgba(255,255,255,.35)"); g.addColorStop(0.35, "rgba(220,235,255,.22)"); g.addColorStop(1, "rgba(220,235,255,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(hx, hy, R * 0.55, 0, 6.283); ctx.fill();
      ctx.globalCompositeOperation = "source-over";
      // gold link from the shell to the live trades column
      ctx.strokeStyle = "#E8B637"; ctx.lineWidth = 1.4; ctx.shadowColor = "#E8B637"; ctx.shadowBlur = 6;
      ctx.beginPath(); ctx.moveTo(hx, cy - R * 0.1); ctx.bezierCurveTo(cx + E * 0.9, cy - E * 0.1, W - 60, cy - E * 0.9, W - 2, 18); ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "rgba(150,165,190,.7)"; ctx.font = "11px 'IBM Plex Sans', sans-serif";
      ["0°", "90°", "180°"].forEach((t, i) => ctx.fillText(t, 6, 24 + i * (Hh * 0.27)));
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [strands]);
  return <div className="qd-torus"><canvas ref={ref} aria-hidden="true" /></div>;
});

function Shell({ closed, open, board }: { closed: any[]; open: any[]; board: any[] }) {
  const strands = useMemo(() => {
    const out: { c: string; w: number; seed: number }[] = [];
    const h = (s: string) => { let x = 7; for (const ch of s) x = (x * 31 + ch.charCodeAt(0)) % 9973; return x / 9973; };
    board.forEach((r) => out.push({ c: "rgba(140,160,200,.10)", w: 0.6, seed: h(r.symbol) }));
    closed.forEach((x) => { const n = net(x) ?? 0; out.push({ c: n > 0 ? "rgba(14,203,129,.45)" : "rgba(246,70,93,.45)", w: 0.8, seed: h(x.id + "c") }); });
    open.forEach((x) => out.push({ c: "rgba(232,182,55,.55)", w: 1.1, seed: h(x.id + "o") }));
    return out;
  }, [closed, open, board]);
  const last = closed.slice().sort((a, b) => (b.closed_at ?? 0) - (a.closed_at ?? 0))[0];
  return (
    <Panel title="Neural shell · record torus" tag={`Calls ${closed.length + open.length} · coins ${board.length}`} className="qd-shell">
      <Torus strands={strands} />
      <div className="qd-legend"><i className="qd-bg-up" /> won <i className="qd-bg-dn" /> lost <i style={{ background: "#E8B637" }} /> running <i style={{ background: "#dfe6f5" }} /> market strands</div>
      {last && <div className="qd-shellnote num">Last close · {base(last.symbol)} {last.timeframe.toUpperCase()} {last.side} · <span className={col(net(last))}>{sgn(net(last))}%</span> · {hhmm(last.closed_at)} UTC</div>}
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
      <div className="qd-trio">
        <div><small>Mean</small><b className={`num ${col(mean)}`}>{rs.length ? `${sgn(mean)}R` : DASH}</b></div>
        <div><small>95% range</small><b className="num">{rs.length > 1 ? `${sgn(mean - 1.96 * se)} … ${sgn(mean + 1.96 * se)}` : DASH}</b></div>
        <div><small>Verdict</small><b className={rs.length < 30 ? "qd-gold" : mean - 1.96 * se > 0 ? "qd-up" : mean + 1.96 * se < 0 ? "qd-dn" : "qd-gold"}>{rs.length < 30 ? "Too early" : mean - 1.96 * se > 0 ? "Edge" : mean + 1.96 * se < 0 ? "Negative" : "Not proven"}</b></div>
      </div>
    </Panel>
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
