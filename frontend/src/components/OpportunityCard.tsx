/* AI opportunity analysis (owner brief, 24 Nov 2026): the whole case for one coin and timeframe in one card, so a
   trader can read it in under a minute. Built only from what the engine already publishes for the coin page
   (`/analysis/<coin>`): the ensemble forecast (per-model votes, calibrated probabilities, walk-forward edge test),
   the technical signal's reasons and warnings, the bigger-trend check, support / resistance, the trade plan's stop,
   the central market-risk state and the news calendar. Nothing here changes a decision; it explains it. */
import { useApi } from "../lib/api";
import { ago, fmtPrice, fmtProb, isNum } from "../lib/format";
import { useIsAdmin } from "../lib/session";

type Item = { text: string; tag?: string };

const LEAN: Record<string, [string, string]> = {
  up: ["Leaning up", "opp-bull"], down: ["Leaning down", "opp-bear"], neutral: ["No clear direction", "opp-flat"],
};

function decisionLine(a: any): string {
  const d = String(a?.decision ?? "").toUpperCase();
  const grade = a?.grade === "A" || a?.grade === "B" ? ` · grade ${a.grade}` : "";
  if (d === "BUY" || d === "LONG") return `Decision: long call${grade}`;
  if (d === "SELL" || d === "SHORT") return `Decision: short call${grade}`;
  return a?.decision_reason ? `Decision: no trade · ${a.decision_reason}` : "Decision: no trade";
}

export default function OpportunityCard({ a, tf }: { a: any; tf: string }) {
  const admin = useIsAdmin();
  const news = useApi<any>("/news").data;
  const risk = useApi<any>("/risk-state", 60000).data;
  const fc = a?.forecast;
  if (!fc?.available || !fc.probabilities) return null;

  const pred: "up" | "down" | "neutral" = fc.predicted === "up" || fc.predicted === "down" ? fc.predicted : "neutral";
  const [lean, leanCls] = LEAN[pred];
  const members: any[] = (fc.per_model ?? []).filter((m: any) => Array.isArray(m.calibrated) && !m.baseline && m.weight > 0);
  const agrees = (m: any) => m.calibrated.indexOf(Math.max(...m.calibrated)) === fc.predicted_class;
  const against = members.filter((m) => !agrees(m)).map((m) => m.label);
  const agreeing = fc.models_agreeing ?? members.filter(agrees).length;
  const total = fc.models_total ?? members.length;
  const p = pred === "neutral" ? fc.probabilities.neutral : fc.probabilities[pred];
  const chanceLabel = pred === "up" ? "Chance price goes up" : pred === "down" ? "Chance price goes down" : "Chance of a flat candle";

  // ---- evidence for the lean
  const forItems: Item[] = [];
  const sig = a.signal ?? {};
  const sigDir = sig.signal === "BUY" || sig.signal === "STRONG_BUY" ? "up" : sig.signal === "SELL" || sig.signal === "STRONG_SELL" ? "down" : "neutral";
  if (pred !== "neutral" && sigDir === pred) (sig.reasons ?? []).slice(0, 3).forEach((r: string) => forItems.push({ text: r, tag: "technical" }));
  const ex = fc.explanation;
  const push = pred === "up" ? ex?.positive : pred === "down" ? ex?.negative : null;
  (push ?? []).slice(0, 2).forEach((f: any) => forItems.push({ text: f.label, tag: "model input" }));
  const rows: any[] = a.mtf?.rows ?? [];
  const same = rows.filter((r) => r.available && r.timeframe !== tf && ((pred === "up" && r.direction > 0) || (pred === "down" && r.direction < 0)));
  if (pred !== "neutral" && same.length) forItems.push({ text: `${same.map((r) => r.timeframe).join(", ")} point the same way`, tag: "bigger trend" });
  forItems.splice(5);
  if (risk?.state === "NORMAL") forItems.push({ text: "Market risk is normal", tag: "risk" });

  // ---- what would cancel it
  const cancel: Item[] = [];
  const setup = a.setup;
  const price = a.last_close ?? a.price;
  if (setup?.valid && isNum(setup.stop)) cancel.push({ text: `Price reaches the stop at ${fmtPrice(setup.stop)}` });
  else if (pred !== "neutral" && isNum(price)) {
    const zones: any[] = pred === "up" ? a.levels?.zones?.support ?? [] : a.levels?.zones?.resistance ?? [];
    const lvl = zones.map((z) => z.mid).filter((m) => isNum(m) && (pred === "up" ? m < price : m > price))
      .sort((x, y) => Math.abs(x - price) - Math.abs(y - price))[0];
    if (isNum(lvl)) cancel.push({ text: `A ${tf} close ${pred === "up" ? "below support at" : "above resistance at"} ${fmtPrice(lvl)}` });
  }
  if (a.mtf?.conflict && a.mtf.conflict_note) cancel.push({ text: a.mtf.conflict_note, tag: "bigger trend" });
  (sig.warnings ?? []).slice(0, 2).forEach((w: string) => cancel.push({ text: w, tag: "technical" }));
  if (risk?.state === "HIGH" || risk?.state === "SEVERE") cancel.push({ text: `Market risk is ${risk.state === "HIGH" ? "high" : "severe"}`, tag: "risk" });
  const vol = a.volatility?.state;
  if (vol === "HIGH" || vol === "EXTREME") cancel.push({ text: `Volatility is ${vol.toLowerCase()}: stops get hit more often`, tag: "volatility" });
  const nh = news?.next_high;
  if (nh?.ts && nh.ts > Date.now() && nh.ts - Date.now() < 24 * 3_600_000) {
    const h = Math.max(1, Math.round((nh.ts - Date.now()) / 3_600_000));
    cancel.push({ text: `US ${nh.title} in about ${h} h: no new entries from 45 min before`, tag: "news" });
  }

  const conf = fc.confidence;
  return (
    <section className="opp" aria-label="AI opportunity analysis">
      <header className="opp-head">
        <div>
          <div className="opp-kicker">AI opportunity analysis · {tf.toUpperCase()}</div>
          <div className={`opp-lean ${leanCls}`}>{lean}</div>
        </div>
        <p className="opp-decision">{decisionLine(a)}</p>
      </header>
      <div className="opp-top">
        <div>
          <div className="opp-k">Models agreeing</div>
          <div className="opp-v">{agreeing} of {total}</div>
          <div className="opp-dots" aria-hidden="true">
            {members.map((m) => <i key={m.name} title={`${m.label}: ${m.predicted}`} className={agrees(m) ? leanCls : ""} />)}
          </div>
          <div className="opp-s">{against.length ? `${against.join(", ")} ${against.length > 1 ? "disagree" : "disagrees"}` : "All models agree"}</div>
        </div>
        <div>
          <div className="opp-k">{chanceLabel}</div>
          <div className="opp-v">{fmtProb(p)}</div>
          <div className="opp-bar" aria-hidden="true"><i style={{ width: `${Math.round((p ?? 0) * 100)}%` }} /></div>
          <div className="opp-s">Next {tf} candle, calibrated on unseen data</div>
        </div>
        <div className="opp-edge">
          <div className="opp-k">Proven trading edge</div>
          <div className={`opp-v ${fc.edge_confirmed ? "opp-bull" : "opp-warn"}`}>{fc.edge_confirmed ? "Established" : "Not established"}</div>
          <div className="opp-s">{fc.edge_confirmed ? "Passed the walk-forward test on unseen data" : "The walk-forward test on unseen data has not passed"}</div>
        </div>
      </div>
      <div className="opp-cols">
        <section>
          <h3 className={leanCls}>{pred === "neutral" ? "What the models see" : `Why it leans ${pred}`}</h3>
          {forItems.length ? <ul>{forItems.map((x, i) => <li key={i}><span>{x.text}</span>{x.tag && <em>{x.tag}</em>}</li>)}</ul>
            : <p className="opp-none">No strong evidence either way.</p>}
        </section>
        <section>
          <h3 className="opp-bear">What would cancel it</h3>
          {cancel.length ? <ul>{cancel.map((x, i) => <li key={i}><span>{x.text}</span>{x.tag && <em>{x.tag}</em>}</li>)}</ul>
            : <p className="opp-none">Nothing specific right now.</p>}
        </section>
      </div>
      <footer className="opp-foot">
        {admin && conf?.n ? <span>Similar past calls: <b>{conf.n}</b>, right <b>{fmtProb(conf.confidence)}</b> <span className="opp-admin">admin only</span></span> : null}
        {fc.trained_at ? <span>Models trained <b>{ago(fc.trained_at)}</b></span> : null}
        <span>A lean is not a signal: only calls on the Signals page are trades.</span>
      </footer>
    </section>
  );
}
