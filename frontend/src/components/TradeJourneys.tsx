// AI Intelligence "Journeys" (owner, 25 Nov 2026): one horizontal row per running call with a round crystal ball in
// front. The liquid shows the trade's state - green in profit, yellow at breakeven (within ±0.1R of the entry), red in
// loss - and its level how far the trade has travelled: toward the last target when in profit, toward the stop when in
// loss. Two looks with a switch (remembered on this device): "Lane" (quantum lane, owner's pick: target gates, particle
// stream, orbiting ring) and "Rail" (neural rail: glowing line, target nodes, pulsing price). Same data as before:
// views/track_record (already open on the page) and the live price socket.
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { useLive } from "../lib/live";
import { base, isNum, slug } from "../lib/format";
import { stopNow } from "./RecordDetails";
import { CoinAvatar } from "./Polish";

export const JOURNEY_MAX = 12;
const KEY = "cia-journeys-look";
const name = (s: string) => (base(s) === "PAXG" ? "GOLD" : base(s));
const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const P = (v: number) => `${(clamp(v) * 100).toFixed(2)}%`;
const rTxt = (r: number | null) => (r == null ? "—" : `${r >= 0 ? "+" : "−"}${Math.abs(r).toFixed(2)}R`);
const BE = 0.1;
const COL = { bull: "rgb(var(--bull))", be: "#f0c846", bear: "rgb(var(--bear))", mute: "rgb(var(--mute))" } as const;
type Tone = keyof typeof COL;

type Trip = {
  x: any; s: 1 | -1; tps: number[]; hits: boolean[]; e: number; c: number; r: number | null; pct: number | null;
  pending: boolean; tone: Tone; fill: number; stopTxt: string; left: string | null; runner: boolean;
};

function tripOf(x: any, px: number | undefined): Trip {
  const s: 1 | -1 = x.side === "SHORT" ? -1 : 1;
  const tps = [x.tp1, x.tp2, x.tp3].filter(isNum) as number[];
  const runner = !!(x.runner?.on && isNum(x.runner.target));
  const end = runner ? x.runner.target : tps[tps.length - 1];
  const span = s * (end - x.stop);
  const at = (p: number) => (span > 0 ? clamp((s * (p - x.stop)) / span) : 0);
  const pending = x.fill_status === "PENDING";
  const hits = [x.tp1_hit, x.tp2_hit, x.tp3_hit].map(Boolean);
  const live = isNum(px) && !pending;
  const r = live && x.entry !== x.stop ? (s * ((px as number) - x.entry)) / Math.abs(x.entry - x.stop) : null;
  const pct = live ? (s * ((px as number) / x.entry - 1)) * 100 : null;
  const e = at(x.entry), c = live ? at(px as number) : e;
  const tone: Tone = r == null ? "mute" : Math.abs(r) < BE ? "be" : r > 0 ? "bull" : "bear";
  const fill = r == null ? 0.06 : tone === "bull" ? (c - e) / Math.max(1e-9, 1 - e) : tone === "bear" ? (e - c) / Math.max(1e-9, e) : 0.5;
  const sn = stopNow(x)?.price;
  const stopTxt = isNum(sn) && Math.abs(sn - x.entry) / x.entry < 1e-6 ? "at entry" : isNum(sn) && sn !== x.stop ? "tightened" : "original";
  const exp = Number(x.expires_at) || 0;
  const ms = exp ? exp - Date.now() : 0;
  const left = ms > 0 ? (ms >= 86_400_000 ? `${Math.floor(ms / 86_400_000)}d ${Math.floor((ms % 86_400_000) / 3_600_000)}h left` : `${Math.max(1, Math.floor(ms / 3_600_000))}h left`) : null;
  return { x, s, tps: tps.map(at), hits, e, c, r, pct, pending, tone, fill: clamp(fill, 0.06, 1), stopTxt, left, runner };
}

/** Round crystal ball with moving liquid (pure SVG + CSS; still when the person prefers reduced motion). */
export function Orb({ tone, fill, size = 64, label }: { tone: Tone; fill: number; size?: number; label?: string }) {
  const id = `orb${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const c = COL[tone];
  const y = 74 - clamp(fill) * 68;
  const wave = (yy: number, a: number) => `M0 ${yy} q10 ${-a} 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 V82 H0Z`;
  return (
    <div className={`jo-orb is-${tone}`} style={{ width: size, height: size }}>
      <svg viewBox="0 0 80 80" aria-hidden="true">
        <defs>
          <clipPath id={`${id}c`}><circle cx="40" cy="40" r="34" /></clipPath>
          <radialGradient id={`${id}g`} cx="35%" cy="30%" r="75%">
            <stop offset="0" stopColor="#fff" stopOpacity=".22" /><stop offset=".55" stopColor="#fff" stopOpacity=".04" /><stop offset="1" stopColor={c} stopOpacity=".18" />
          </radialGradient>
          <linearGradient id={`${id}l`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={c} stopOpacity=".95" /><stop offset="1" stopColor={c} stopOpacity=".45" /></linearGradient>
        </defs>
        <circle className="jo-halo" cx="40" cy="40" r="38" fill="none" stroke={c} strokeOpacity=".35" strokeWidth="1.5" />
        <circle cx="40" cy="40" r="34" fill="#05070c" />
        <g clipPath={`url(#${id}c)`}>
          <path className="jo-wave2" d={wave(y + 2, 4)} fill={c} opacity=".5" />
          <path className="jo-wave" d={wave(y, 5)} fill={`url(#${id}l)`} />
          {tone !== "mute" && [[30, 18, 1.6], [48, 22, 1.2], [40, 14, 1]].map(([cx, dy, rr], i) => (
            <circle key={i} className="jo-bub" cx={cx} cy={Math.min(72, y + dy)} r={rr} fill="#fff" style={{ animationDelay: `${i * 0.95}s` }} />
          ))}
        </g>
        <circle cx="40" cy="40" r="34" fill={`url(#${id}g)`} stroke="#ffffff40" strokeWidth="1" />
        <ellipse cx="29" cy="22" rx="11" ry="6" fill="#fff" opacity=".22" transform="rotate(-28 29 22)" />
      </svg>
      {label && <span className="jo-orb-txt num">{label}</span>}
    </div>
  );
}

export function SignalJourneysV2({ track }: { track: any }) {
  const { tickers } = useLive();
  const [look, setLook] = useState<"lane" | "rail">(() => { try { return localStorage.getItem(KEY) === "rail" ? "rail" : "lane"; } catch { return "lane"; } });
  const pick = (v: "lane" | "rail") => { setLook(v); try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
  const all: any[] = (track?.live?.signals ?? []).filter((x: any) => x.status === "OPEN");
  const trips = all.slice(0, JOURNEY_MAX).map((x) => tripOf(x, tickers[x.symbol]?.last ?? undefined)).sort((a, b) => (b.r ?? -99) - (a.r ?? -99));
  const live = trips.filter((t) => t.r != null);
  const green = live.filter((t) => t.tone === "bull").length, red = live.filter((t) => t.tone === "bear").length;
  const avg = live.length ? live.reduce((s, t) => s + (t.r ?? 0), 0) / live.length : null;
  return (
    <div className="fc-wrap">
      <div className="jo-top">
        <div className="fc-sum">
          <span><b className="num">{all.length}</b> running</span>
          <span><b className="num text-bull">{green}</b> in profit</span>
          <span><b className="num" style={{ color: COL.be }}>{live.length - green - red}</b> breakeven</span>
          <span><b className="num text-bear">{red}</b> in loss</span>
          <span>avg <b className={`num ${(avg ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{rTxt(avg)}</b></span>
        </div>
        <div className="jo-switch" role="group" aria-label="Journeys look">
          {(["lane", "rail"] as const).map((v) => (
            <button key={v} type="button" aria-pressed={look === v} className={look === v ? "is-on" : ""} onClick={() => pick(v)}>{v === "lane" ? "Lane" : "Rail"}</button>
          ))}
        </div>
      </div>
      {!all.length ? <p className="py-6 text-center text-sm text-mute">No signals running right now. New calls appear here the moment they open.</p> : (
        <ul className={`jo-list is-${look}`}>{trips.map((t) => <Row key={t.x.id ?? `${t.x.symbol}${t.x.created_at}`} t={t} look={look} />)}</ul>
      )}
      {all.length > JOURNEY_MAX && <Link to="/results?tab=track" className="mt-1 block text-center text-xs font-medium text-accent hover:underline">+{all.length - JOURNEY_MAX} more running · see all in Results</Link>}
    </div>
  );
}

function Row({ t, look }: { t: Trip; look: "lane" | "rail" }) {
  const { x } = t;
  const c = COL[t.tone];
  const a = Math.min(t.e, t.c), b = Math.max(t.e, t.c);
  const stateTxt = t.pending ? "waiting for entry" : t.tone === "be" ? "breakeven" : t.tone === "bull" ? "in profit" : t.tone === "bear" ? "in loss" : "—";
  const marks = t.tps.map((p, k) => ({ p, lab: t.runner && k === t.tps.length - 1 ? `TP${k + 1}` : `TP${k + 1}`, hit: t.hits[k] }));
  const aria = `${name(x.symbol)} ${x.timeframe} ${t.s > 0 ? "long" : "short"}: ${t.pending ? "waiting for entry" : `${rTxt(t.r)}, ${stateTxt}`}, ${t.hits.filter(Boolean).length} of ${t.tps.length} targets hit`;
  const head = (
    <Link to={`/asset/${slug(x.symbol)}?tf=${x.timeframe}`} className="jo-head">
      <CoinAvatar symbol={x.symbol} size={20} />
      <b>{name(x.symbol)}</b>
      <span className="jo-sub">{String(x.timeframe).toUpperCase()} · <span className={t.s > 0 ? "text-bull" : "text-bear"}>{t.s > 0 ? "Long" : "Short"}</span></span>
    </Link>
  );
  const foot = (
    <div className="jo-foot num">
      {isNum(t.pct) && <span style={{ color: c }}>{t.pct >= 0 ? "+" : "−"}{Math.abs(t.pct).toFixed(2)}%</span>}
      {t.left && <span>{t.left}</span>}
      <span>Stop {t.stopTxt}</span>
    </div>
  );
  if (look === "rail") {
    return (
      <li className="jo-row" aria-label={aria}>
        <Orb tone={t.tone} fill={t.fill} size={56} label={t.pending ? "…" : `${Math.round(t.fill * 100)}%`} />
        <div className="jo-body">
          <div className="jo-line1">{head}<span className="jo-r num" style={{ color: c }}>{t.pending ? "Waiting" : rTxt(t.r)}</span></div>
          <div className="jr-rail">
            <i className="jr-line" />
            {!t.pending && t.r != null && <i className="jr-flow" style={{ left: P(a), width: P(b - a), color: c }} />}
            <span className="jr-node is-sl" style={{ left: "0%" }}><em>SL</em></span>
            <span className="jr-node is-en" style={{ left: P(t.e) }}><em>Entry</em></span>
            {marks.map((m) => <span key={m.lab} className={`jr-node ${m.hit ? "is-hit" : ""} ${m.p > 0.97 ? "is-end" : ""}`} style={{ left: P(m.p) }}><em>{m.lab}{m.hit ? " ✓" : ""}</em></span>)}
            {!t.pending && <span className="jr-pulse" style={{ left: P(t.c), color: c }} />}
          </div>
          {foot}
        </div>
      </li>
    );
  }
  return (
    <li className="jo-row" aria-label={aria}>
      <div className="jq-orbwrap"><i className="jq-ring" /><Orb tone={t.tone} fill={t.fill} size={54} label={t.pending ? "…" : `${Math.round(t.fill * 100)}%`} /></div>
      <div className="jo-body">
        <div className="jo-line1">{head}<span className="jo-r num" style={{ color: c }}>{t.pending ? "Waiting" : rTxt(t.r)}</span></div>
        <div className="jq-path">
          <span className="jq-gate is-sl" style={{ left: "1%" }}><em>SL</em></span>
          <span className="jq-gate is-en" style={{ left: P(t.e) }}><em>Entry</em></span>
          {marks.map((m) => <span key={m.lab} className={`jq-gate ${m.hit ? "is-hit" : ""} ${m.p > 0.9 ? "is-end" : ""}`} style={{ left: P(Math.min(m.p, 0.99)) }}><em>{m.lab}{m.hit ? " ✓" : ""}</em></span>)}
          {!t.pending && t.r != null && b - a > 0.01 && (
            <div className={`jq-stream ${t.c < t.e ? "is-back" : ""}`} style={{ left: P(a), width: P(b - a), color: c }}>
              {[0, 0.32, 0.64, 0.96, 1.28].map((d) => <i key={d} style={{ animationDelay: `${d}s` }} />)}
            </div>
          )}
          {!t.pending && <span className="jq-now" style={{ left: P(t.c), color: c }} />}
        </div>
        {foot}
      </div>
    </li>
  );
}
