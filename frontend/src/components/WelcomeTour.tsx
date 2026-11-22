// v2.68 welcome tour (owner, 22 Nov 2026): five short steps the first time a member opens the app - Signals, reading a
// signal, practising it, alerts, Results - each with a small drawing and a button that opens that page. Shown once per
// account (localStorage cia-tour-<uid>); Settings → "Take the tour" opens it again (event "cia-tour"). No data, no reads.
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { useSession, useIsAdmin } from "../lib/session";

const KEY = (uid: string) => `cia-tour-${uid}`;
export const openTour = () => window.dispatchEvent(new Event("cia-tour"));

type Step = { title: string; text: string; to: string; cta: string; art: JSX.Element };

const G = "rgb(var(--accent))", B = "rgb(var(--bull))", R = "rgb(var(--bear))", A = "rgb(var(--ai))", M = "rgb(var(--glass) / 0.18)";

const ART = {
  signals: (
    <svg viewBox="0 0 220 120" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <g key={i} transform={`translate(${14 + i * 66} ${18 + (i % 2) * 10})`}>
          <rect width="58" height="80" rx="10" fill="rgb(var(--panel))" stroke={i === 1 ? G : M} />
          <circle cx="14" cy="16" r="7" fill={i === 1 ? G : M} />
          <rect x="25" y="12" width="24" height="7" rx="3" fill={M} />
          <rect x="10" y="32" width="38" height="9" rx="4" fill={i === 2 ? R : B} opacity="0.85" />
          <rect x="10" y="50" width="38" height="4" rx="2" fill={M} /><rect x="10" y="60" width="28" height="4" rx="2" fill={M} />
        </g>
      ))}
    </svg>
  ),
  read: (
    <svg viewBox="0 0 220 120" aria-hidden="true">
      <line x1="20" y1="70" x2="200" y2="70" stroke={M} strokeWidth="6" strokeLinecap="round" />
      <line x1="20" y1="70" x2="70" y2="70" stroke={R} strokeWidth="6" strokeLinecap="round" />
      <line x1="70" y1="70" x2="128" y2="70" stroke={B} strokeWidth="6" strokeLinecap="round" />
      {[[20, "SL", R], [70, "Entry", G], [128, "TP1", B], [164, "TP2", B], [200, "TP3", B]].map(([x, t, c]) => (
        <g key={t as string}><circle cx={x as number} cy="70" r="7" fill="rgb(var(--ink))" stroke={c as string} strokeWidth="2.5" />
          <text x={x as number} y="96" textAnchor="middle" fontSize="11" fontWeight="700" fill={c as string}>{t as string}</text></g>
      ))}
      <circle cx="128" cy="70" r="9" fill="#fff" stroke={B} strokeWidth="3" />
      <text x="110" y="36" textAnchor="middle" fontSize="13" fontWeight="700" fill={B}>+1.0R</text>
    </svg>
  ),
  practice: (
    <svg viewBox="0 0 220 120" aria-hidden="true">
      <rect x="30" y="18" width="160" height="84" rx="12" fill="rgb(var(--panel))" stroke={M} />
      <text x="110" y="48" textAnchor="middle" fontSize="12" fill="rgb(var(--mute))">Practice balance</text>
      <text x="110" y="74" textAnchor="middle" fontSize="22" fontWeight="800" fill={G}>$1,000</text>
      <rect x="52" y="84" width="52" height="10" rx="5" fill={B} /><rect x="116" y="84" width="52" height="10" rx="5" fill={R} />
    </svg>
  ),
  alerts: (
    <svg viewBox="0 0 220 120" aria-hidden="true">
      <path d="M110 22c-18 0-30 13-30 31v18l-9 12h78l-9-12V53c0-18-12-31-30-31z" fill="none" stroke={G} strokeWidth="4" strokeLinejoin="round" />
      <circle cx="110" cy="92" r="7" fill={G} />
      <circle cx="140" cy="30" r="10" fill={R} /><text x="140" y="34" textAnchor="middle" fontSize="11" fontWeight="800" fill="#fff">1</text>
      {[48, 60, 72].map((r) => <circle key={r} cx="110" cy="56" r={r} fill="none" stroke={A} strokeOpacity={0.5 - r / 200} />)}
    </svg>
  ),
  results: (
    <svg viewBox="0 0 220 120" aria-hidden="true">
      <circle cx="70" cy="60" r="34" fill="none" stroke={M} strokeWidth="10" />
      <circle cx="70" cy="60" r="34" fill="none" stroke={B} strokeWidth="10" strokeDasharray="130 214" transform="rotate(-90 70 60)" strokeLinecap="round" />
      <text x="70" y="65" textAnchor="middle" fontSize="15" fontWeight="800" fill="rgb(var(--text))">Wins</text>
      {[0, 1, 2, 3, 4].map((i) => <rect key={i} x={124 + i * 16} y={40 + (i % 3) * 8} width="10" height={50 - (i % 3) * 8} rx="3" fill={i === 2 ? R : B} opacity="0.85" />)}
    </svg>
  ),
};

const STEPS: Step[] = [
  { title: "Welcome! Start with Signals", text: "Every trade idea the AI finds, on six timeframes. Long = it expects the price to rise, Short = to fall.", to: "/signals", cta: "Open Signals", art: ART.signals },
  { title: "Read a signal in 10 seconds", text: "Entry is where to open, the stop-loss limits the loss, TP1-TP3 are the targets. Grade A is the strongest. Tap \"Why this signal?\" for the reasons.", to: "/signals", cta: "See a signal", art: ART.read },
  { title: "Practise first, with virtual money", text: "Your practice account starts with $1,000 of virtual USDT. Try any signal and see how it plays out - nothing real is ever traded.", to: "/paper", cta: "Open practice", art: ART.practice },
  { title: "Let the app tell you", text: "Turn on notifications to hear about new signals, targets hit and stops, even when the app is closed.", to: "/alerts", cta: "Set up alerts", art: ART.alerts },
  { title: "Check the honest record", text: "Results shows every published signal, wins and losses, after fees. Judge the AI over many signals, not one.", to: "/results?tab=track", cta: "See results", art: ART.results },
];

export default function WelcomeTour() {
  const s = useSession();
  const admin = useIsAdmin();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!s?.uid) return;
    let seen = true;
    try { seen = localStorage.getItem(KEY(s.uid)) === "1"; } catch { /* storage off: never auto-open */ }
    const force = new URLSearchParams(window.location.search).get("tour") === "1";
    if ((!seen && !admin) || force) { setI(0); setOpen(true); }
    const again = () => { setI(0); setOpen(true); };
    window.addEventListener("cia-tour", again);
    return () => window.removeEventListener("cia-tour", again);
  }, [s?.uid, admin]);
  if (!open || !s?.uid) return null;
  const done = () => { try { localStorage.setItem(KEY(s.uid), "1"); } catch { /* ignore */ } setOpen(false); };
  const st = STEPS[i];
  const last = i === STEPS.length - 1;
  return createPortal(
    <div className="tour-back" role="dialog" aria-modal="true" aria-labelledby="tour-title" onKeyDown={(e) => { if (e.key === "Escape") done(); }}>
      <div className="tour-card">
        <button type="button" className="tour-skip" onClick={done}>Skip</button>
        <div className="tour-art">{st.art}</div>
        <div className="tour-step">Step {i + 1} of {STEPS.length}</div>
        <h2 id="tour-title" className="tour-title">{st.title}</h2>
        <p className="tour-text">{st.text}</p>
        <div className="tour-dots" aria-hidden="true">{STEPS.map((_x, k) => <i key={k} className={k === i ? "on" : ""} />)}</div>
        <div className="tour-actions">
          <button type="button" className="btn" disabled={i === 0} onClick={() => setI(i - 1)}>Back</button>
          <button type="button" className="btn" onClick={() => { done(); nav(st.to); }}>{st.cta}</button>
          <button type="button" className="btn btn-primary" autoFocus onClick={() => (last ? done() : setI(i + 1))}>{last ? "Finish" : "Next"}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
