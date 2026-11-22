// v2.68 "Why this signal?" (owner, 22 Nov 2026). One tap under the signal's reason chips opens a short plain-English
// explanation built ONLY from numbers the engine already published: the call itself (grade, trend, AI lean, reward),
// the engine's reason line, the advisor note, and the coin report (main risk, invalidation, nearest levels) - read only
// when opened (views/coin_reports comes from the Cloudflare edge, so it costs no Firestore read). Nothing is predicted.
import { useState } from "react";
import { useApi } from "../lib/api";
import { fmtPctRaw, fmtPrice, isNum, slug } from "../lib/format";

const regimeWord = (s?: string) => (s ? s.replace(/_/g, " ").toLowerCase() : "");

export default function WhySignal({ r, plan, px }: { r: any; plan: any; px?: number }) {
  const [open, setOpen] = useState(false);
  const rep = useApi<any>(open ? `/coin-reports/${slug(r.symbol)}` : null);
  const side: "LONG" | "SHORT" = plan?.side === "SHORT" ? "SHORT" : "LONG";
  const long = side === "LONG";
  const stopPct = isNum(plan?.stop) && isNum(plan?.entry) ? ((plan.stop - plan.entry) / plan.entry) * 100 : null;
  const lean = long ? r.p_up : r.p_down;
  const rp = rep.data;

  const why: string[] = [];
  if (r.grade === "A") why.push("Grade A: the price trend and the AI models point the same way, and this kind of setup has worked on data the models never saw.");
  else if (r.grade === "B") why.push("Grade B: the AI models lead this call; they have shown an edge on unseen data, but the trend is less clear.");
  if (r.regime) why.push(`The ${String(r.timeframe).toUpperCase()} trend reads ${regimeWord(r.regime)}.`);
  if (isNum(lean)) why.push(`The AI gives ${Math.round(lean * 100)}% to the price moving ${long ? "up" : "down"} next.`);
  if (isNum(plan?.risk_reward)) why.push(`Possible reward is about ${plan.risk_reward.toFixed(1)}× the risk (half closes at TP1, a quarter at TP2 and TP3).`);

  const cancel: string[] = [];
  if (isNum(plan?.stop)) cancel.push(`The price reaching the stop at ${fmtPrice(plan.stop)}${isNum(stopPct) ? ` (${fmtPctRaw(stopPct, 1)} from the entry)` : ""} ends the trade with a loss.`);
  if (rp?.invalidation?.text) cancel.push(rp.invalidation.text);
  const lv = long ? rp?.levels?.resistance?.[0] : rp?.levels?.support?.[0];
  if (isNum(lv)) cancel.push(`Nearest ${long ? "resistance" : "support"} on 4H at ${fmtPrice(lv)}${isNum(px) ? ` (${fmtPctRaw(((lv - px) / px) * 100, 1)} away)` : ""}: the price often slows there.`);

  const risks: string[] = [];
  if (rp?.risk) risks.push(rp.risk);
  if (r.news_risk) risks.push(`Major US data (${r.news_risk.title}) ${r.news_risk.when}: prices can jump around releases.`);
  risks.push("Leverage makes losses bigger, and in fast markets the stop can fill at a worse price.");

  return (
    <div className="why-sig">
      <button type="button" className="why-sig-btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="why-sig-dot" aria-hidden="true">?</span>
        {open ? "Hide the reasons" : "Why this signal?"}
      </button>
      {open && (
        <div className="why-sig-panel" role="region" aria-label="Why this signal">
          <section><h4>Why the AI likes it</h4><ul>{why.map((x) => <li key={x}>{x}</li>)}</ul></section>
          <section><h4>What would cancel it</h4><ul>{cancel.map((x) => <li key={x}>{x}</li>)}</ul></section>
          <section><h4>Main risk</h4><ul>{risks.map((x) => <li key={x}>{x}</li>)}</ul></section>
          {r.ai?.rationale && <p className="why-sig-ai"><span className="ai-tag mr-1.5 inline-flex rounded px-1.5 py-0.5 text-xs font-semibold">AI note</span>{r.ai.rationale}</p>}
          <p className="text-xs text-mute">Built from the engine's own numbers. An explanation, not advice: no signal is sure to work.</p>
        </div>
      )}
    </div>
  );
}
