import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { doc, setDoc } from "firebase/firestore";
import { Card } from "../components/ui";
import { MyCapital, MyPositions } from "../components/V3Home";
import { NumField } from "../components/AutoTrade";
import { useApi } from "../lib/api";
import { db } from "../lib/firebase";
import { myUid } from "../lib/session";
import { DASH, base, fmtPrice } from "../lib/format";

/* V3.0 Portfolio (owner brief, 24 Nov 2026): the member's practice capital in one place - account, open positions,
   the auto-trade protection limits (engine services/autopaper.protection) and the latest closed trades. Practice only. */

function Protection() {
  const cur = useApi<any>("/auto-paper").data;
  const [s, setS] = useState({ daily_loss_pct: 5, max_exposure_pct: 50, follow_risk: true });
  const [msg, setMsg] = useState("");
  useEffect(() => {
    if (cur) setS({ daily_loss_pct: Number(cur.daily_loss_pct ?? 5), max_exposure_pct: Number(cur.max_exposure_pct ?? 50), follow_risk: cur.follow_risk !== false });
  }, [cur]);
  const save = async () => {
    try { await setDoc(doc(db, "auto_paper", myUid()), { ...s, updated_at: Date.now() }, { merge: true }); setMsg("Saved. The engine uses it from its next round."); }
    catch (e: any) { setMsg(e.message); }
  };
  return (
    <Card title="Auto-trade protection" right={<span className="v3-pill v3-muted">Practice</span>}>
      <p className="mb-3 text-sm text-mute">Limits the engine applies before every auto-trade in your practice account. Manual trades are never touched.</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="text-sm">Daily loss limit (% of the account)
          <NumField value={s.daily_loss_pct} min={0.5} max={100} onChange={(n) => setS({ ...s, daily_loss_pct: n })} /></label>
        <label className="text-sm">Most of the account in use (%)
          <NumField value={s.max_exposure_pct} min={5} max={100} onChange={(n) => setS({ ...s, max_exposure_pct: n })} /></label>
      </div>
      <label className="mt-4 flex items-center gap-3 text-sm">
        <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--accent))]" checked={s.follow_risk} onChange={(e) => setS({ ...s, follow_risk: e.target.checked })} />
        Follow the market risk level (High risk: half size · Severe: no new auto-trades)
      </label>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary" onClick={save}>Save protection</button>
        <Link to="/paper" className="btn">Auto-trade settings</Link>
        {msg && <span className="text-sm text-mute">{msg}</span>}
      </div>
    </Card>
  );
}

function Closed() {
  const acc = useApi<any>("/paper/futures").data;
  const rows: any[] = ((acc?.trades ?? []) as any[]).filter((t) => t.type === "CLOSE").sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0)).slice(0, 10);
  return (
    <Card title="Latest closed trades" right={<Link to="/paper" className="text-xs text-accent hover:underline">Trade ›</Link>}>
      {rows.length === 0 ? <p className="text-sm text-mute">No closed practice trades yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs text-mute"><th className="pb-2 font-normal">Coin</th><th className="pb-2 font-normal">Exit</th>
            <th className="hidden pb-2 font-normal sm:table-cell">Why</th><th className="pb-2 text-right font-normal">P&amp;L</th></tr></thead>
          <tbody className="[&_td]:border-t [&_td]:py-2 [&_td]:[border-color:var(--hair)]">
            {rows.map((t, i) => (
              <tr key={i}>
                <td>{base(t.symbol)} <span className={t.side > 0 ? "text-bull" : "text-bear"}>{t.side > 0 ? "long" : "short"}</span>{t.auto && <span className="ml-1 text-xs text-mute">auto</span>}</td>
                <td className="num">{fmtPrice(t.price)}</td>
                <td className="hidden text-mute sm:table-cell">{t.reason ?? DASH}</td>
                <td className={`num text-right ${(t.realized_pnl ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>{(t.realized_pnl ?? 0) >= 0 ? "+" : "−"}${Math.abs(t.realized_pnl ?? 0).toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Portfolio() {
  return (
    <div className="space-y-4 sm:space-y-5">
      <header>
        <h1 className="v3-title">Portfolio</h1>
        <p className="mt-1.5 text-[0.9375rem] text-mute">Your practice capital, open positions and protection. Virtual money only.</p>
      </header>
      <div className="grid-even grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <MyCapital />
        <MyPositions />
      </div>
      <div className="grid-even grid gap-4 lg:grid-cols-2">
        <Protection />
        <Closed />
      </div>
    </div>
  );
}
