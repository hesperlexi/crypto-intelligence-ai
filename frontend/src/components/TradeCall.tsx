// One clear answer per coin: go long, go short, buy, sell or wait, at which prices, with what risk.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DASH, base, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, isGoldSignal } from "../lib/format";
import { useLive } from "../lib/live";
import { CoinAvatar } from "./Polish";
import { AiNote, CallStatusRow, RiskBadge } from "./SignalExtras";
import { AiTag } from "./ui";
import { AdjustButton, AdjustHistory, adjustedPlan, UpdatedBadge } from "./SignalAdjust";
import { Explain, PLAIN, useIsPro } from "../lib/mode";

export type Market = "spot" | "futures";
type Tone = "bull" | "bear" | "wait";

interface Verdict { label: string; tone: Tone; headline: string }

/** Signal strength: A = strong (trend, AI and track record agree), B = moderate (AI-led, proven out-of-sample edge). */
export function GradeBadge({ grade, small = false }: { grade?: string | null; small?: boolean }) {
  if (grade !== "A" && grade !== "B") return null;
  const a = grade === "A";
  return (
    <span title={a ? "Strong signal: trend, AI models and their track record all agree" : "Moderate signal: AI-led call where the model's out-of-sample record shows an edge"}
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-[5px] border font-semibold leading-none ${small ? "px-1.5 py-[3px] text-[11px]" : "px-2 py-1 text-xs"} ${a ? "border-accent/45 bg-accent/[0.12] text-accent" : "border-glass/20 bg-glass/[0.05] text-text/85"}`}>
      {a ? "A · strong" : "B · moderate"}
    </span>
  );
}

export function verdictOf(r: any, market: Market): Verdict {
  const p = r?.plan;
  if (market === "futures") {
    if (r?.side > 0 && p?.valid) return r.action === "LONG ON PULLBACK"
      ? { label: "LONG ON PULLBACK", tone: "bull", headline: "Wait for a small dip, then open a LONG" }
      : { label: "GO LONG", tone: "bull", headline: "Open a LONG position" };
    if (r?.side < 0 && p?.valid) return { label: "GO SHORT", tone: "bear", headline: "Open a SHORT position" };
    return { label: "WAIT", tone: "wait", headline: "No trade right now" };
  }
  const d = r?.decision ?? "";
  if (d === "BUY") return { label: "BUY", tone: "bull", headline: "Buy now, inside the entry zone" };
  if (d === "BUY ON PULLBACK") return { label: "BUY ON DIP", tone: "bull", headline: "Wait for a small dip, then buy" };
  if (d === "SELL") return { label: "SELL / STAY OUT", tone: "bear", headline: "Take profit or stay out — no new buys" };
  return { label: "WAIT", tone: "wait", headline: "No trade right now" };
}

const TONE = {
  bull: { pill: "bg-bull text-ink", ring: "border-bull/45", soft: "bg-bull/10", text: "text-bull" },
  bear: { pill: "bg-bear text-white", ring: "border-bear/45", soft: "bg-bear/10", text: "text-bear" },
  wait: { pill: "bg-glass/15 text-text", ring: "border-glass/15", soft: "bg-glass/[0.04]", text: "text-mute" },
} as const;

const pct = (a: number, b: number) => (isNum(a) && isNum(b) && b ? (a / b - 1) * 100 : null);

function entryStatus(side: "LONG" | "SHORT", px: number, zone: [number, number]) {
  const [lo, hi] = [Math.min(zone[0], zone[1]), Math.max(zone[0], zone[1])];
  if (!isNum(px)) return null;
  if (px >= lo && px <= hi) return { ok: true, text: "Price is inside the entry zone now" };
  if (side === "LONG") return px > hi ? { ok: false, text: `Price is above the zone: wait for ${fmtPrice(hi)} or lower` } : { ok: false, text: `Price dipped below the zone: wait for it to recover to ${fmtPrice(lo)}` };
  return px < lo ? { ok: false, text: `Price is below the zone: wait for ${fmtPrice(lo)} or higher` } : { ok: false, text: `Price rose above the zone: wait for it to fall back to ${fmtPrice(hi)}` };
}

/** Plain-text version of the plan, for copying into notes or an exchange. */
function planText(r: any, market: Market, v: Verdict, plan: any) {
  const parts = [`${r.symbol} ${market === "futures" ? "futures" : "spot"} · ${String(r.timeframe ?? "").toUpperCase()} · ${v.label}`];
  if (plan) {
    parts.push(`Entry ${fmtPrice(plan.entry_zone?.[0])}–${fmtPrice(plan.entry_zone?.[1])} (ideal ${fmtPrice(plan.entry)})`);
    parts.push(`Stop-loss ${fmtPrice(plan.stop)}`);
    parts.push((plan.targets ?? []).map((t: any) => `${t.name} ${fmtPrice(t.price)}`).join(", "));
    if (market === "futures") parts.push(`Leverage ${plan.suggested_leverage}x (liquidation ${fmtPrice(plan.liquidation_at_suggested)})`);
  }
  parts.push(`${r.grade ? `Grade ${r.grade} · ` : ""}Hit rate ${fmtProb(r.confidence)} · Crypto Intelligence AI · not financial advice`);
  return parts.join("\n");
}

export default function TradeCall({ r, market, m, compact = false }: { r: any; market: Market; m?: any; compact?: boolean }) {
  const { tickers } = useLive();
  const nav = useNavigate();
  const pro = useIsPro();
  const [copied, setCopied] = useState(false);
  if (!r) return null;
  const px = tickers[r.symbol]?.last ?? r.price;
  const v = verdictOf(r, market);
  const t = TONE[v.tone];
  // an open call the admin adjusted: the card shows the stop / TP1 now in force (history below the status)
  const call = r.call;
  const raw = adjustedPlan(r.plan, call);
  // spot never shorts: a short plan has no spot meaning
  const plan = raw && (market === "futures" || raw.side === "LONG") ? raw : null;
  const active = v.tone !== "wait" && !!plan && (market === "futures" || v.tone === "bull");
  const side: "LONG" | "SHORT" = plan?.side === "SHORT" ? "SHORT" : "LONG";
  const status = active && plan?.entry_zone ? entryStatus(side, px, plan.entry_zone) : null;
  const funding = m?.funding_rate ?? r.funding_rate;
  const upPct = Math.round((r.p_up ?? 0) * 100), downPct = Math.round((r.p_down ?? 0) * 100);

  // price ladder: every level sorted top to bottom, with the live price slotted in
  const levels: { k: string; price: number; cls: string; note?: string }[] = [];
  if (plan) {
    const run = plan.runner?.on ? plan.runner : null;
    const SPLIT = run ? ["stop → break-even", "stop → TP1", "stop → TP2"] : ["close 50%", "close 25%", "close 25%"];
    for (const [i, tg] of [...(plan.targets ?? [])].entries()) levels.push({ k: `Take-profit ${tg.name.replace("TP", "")} · 1:${isNum(tg.rr) ? (Math.round(tg.rr * 100) / 100).toString() : "?"}`, price: tg.price, cls: "text-bull",
      note: [SPLIT[i], isNum(tg.probability) ? `${fmtProb(tg.probability)} reached before the stop` : null].filter(Boolean).join(" · ") });
    if (run && isNum(run.target)) levels.push({ k: `Runner target · 1:${run.rr}`, price: run.target, cls: "text-bull", note: "AI: let it run · closes 100%" });
    levels.push({ k: "Entry (ideal)", price: plan.entry, cls: "text-accent", note: plan.entry_zone ? `zone ${fmtPrice(Math.min(...plan.entry_zone))} – ${fmtPrice(Math.max(...plan.entry_zone))}` : undefined });
    levels.push({ k: "Stop-loss", price: plan.stop, cls: "text-bear", note: isNum(plan.risk_pct) ? `risk ${fmtPctRaw(plan.risk_pct, 1, false)}` : undefined });
    if (market === "futures" && isNum(plan.liquidation_at_suggested)) levels.push({ k: `Liquidation at ${plan.suggested_leverage}x`, price: plan.liquidation_at_suggested, cls: "text-warn" });
    if (isNum(px)) levels.push({ k: "Price now", price: px, cls: "text-text", note: "live" });
    levels.sort((a, b) => b.price - a.price);
  }

  // price move to a level, plus the return on margin at the suggested leverage (how exchanges show ROI)
  const roiSub = (level: number | undefined) => {
    const m = level == null ? null : pct(level, plan?.entry);
    if (m == null) return undefined;
    const lev = market === "futures" && isNum(plan?.suggested_leverage) && plan.suggested_leverage > 1 ? plan.suggested_leverage : null;
    const gain = side === "SHORT" ? -m : m;              // profit on the trade (a short gains when price falls)
    return lev ? `${fmtPctRaw(m, 1)} move · ${fmtPctRaw(gain * lev, 1)} ROI` : fmtPctRaw(m, 1);
  };

  const paper = () => {
    const q = new URLSearchParams({ market, symbol: r.symbol, side: market === "spot" ? "LONG" : side,
      ...(market === "futures" && plan?.suggested_leverage ? { lev: String(plan.suggested_leverage) } : {}),
      ...(plan?.stop ? { sl: String(plan.stop) } : {}), ...(plan?.targets?.[1]?.price ? { tp: String(plan.targets[1].price) } : {}) });
    nav(`/paper?${q}`);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(planText(r, market, v, plan)); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  };

  if (r.status && r.status !== "OK") {
    return (
      <section className="panel p-4">
        <div className="flex items-center gap-3"><CoinAvatar symbol={r.symbol} /><span className="font-semibold">{r.symbol}</span></div>
        <p className="mt-3 text-sm text-mute">{r.reason ?? "Signals for this coin arrive after the next engine runs (about 15–30 minutes)."}</p>
      </section>
    );
  }

  const tfLabel = String(r.timeframe ?? "").toUpperCase();
  const lev = market === "futures" && isNum(plan?.suggested_leverage) ? plan.suggested_leverage : null;
  // context lines (quiet section): only what applies to this card
  const notes = [
    r.record_status === "already_open" && <p key="open">Following the open call: this setup is already in the record, so it is not logged twice.</p>,
    v.tone !== "wait" && r.decision_basis && <p key="why"><span className="text-text/80">Why:</span> {r.decision_basis}</p>,
    pro && v.tone !== "wait" && isNum(r.filter_score) && <p key="filter" className="text-bull" title="A second model trained on which past setups actually reached their targets before the stop">✓ Passed the trade filter ({Math.round(r.filter_score * 100)}% vs a {Math.round((r.filter_threshold ?? 0) * 100)}% bar)</p>,
    isGoldSignal(r.symbol) && <p key="gold"><span className="font-semibold text-accent">Gold (XAU/USD).</span> Levels are in PAXG, which follows the gold price closely. On forex.com, use the same % distances from your entry (shown under each level).</p>,
    market === "spot" && v.tone === "bear" && <p key="spot">The trend points down. If you hold {base(r.symbol)}, consider taking profit or protecting it with a stop; avoid new buys for now.</p>,
  ].filter(Boolean);

  return (
    <section className={`panel signal-card overflow-hidden sc-${v.tone}`}>
      {/* header row: coin · timeframe · market | grade · side */}
      <header className="sc-head">
        <Link to={`/asset/${slug(r.symbol)}`} className="flex min-w-0 items-center gap-3 hover:text-accent">
          <CoinAvatar symbol={r.symbol} size={compact ? 32 : 38} />
          <div className="min-w-0">
            <div className="flex items-baseline gap-1.5"><span className="font-display text-lg font-bold leading-tight">{base(r.symbol)}</span><span className="text-xs text-mute">/USDT</span></div>
            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-mute">
              <span className="sc-chip">{tfLabel}</span><span className="sc-chip">{market}</span><span className="num">{fmtPrice(px)}</span>
            </div>
          </div>
        </Link>
        <div className="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-center sm:gap-2">
          {v.tone !== "wait" && <GradeBadge grade={r.grade} small />}
          <span className={`sc-side sc-side-${v.tone}`}>{v.tone === "bull" ? "▲ " : v.tone === "bear" ? "▼ " : ""}{v.label}</span>
        </div>
      </header>

      <div className="space-y-3.5 p-4 sm:p-5">
        {r.stale === true && (
          <div className="sc-alert sc-alert-warn font-semibold" role="status">Data delayed — no trade</div>
        )}
        {/* decision */}
        <div>
          <h3 className={`sc-headline ${v.tone === "wait" ? "" : t.text}`}>{v.headline}</h3>
          {active && plan && (
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-mute">
              <RiskBadge entry={plan.entry} stop={plan.stop} leverage={market === "futures" ? plan.suggested_leverage : 1} />
              {lev != null && <span className="num">{lev}x suggested</span>}
              {status && <span className={`flex items-center gap-1.5 ${status.ok ? "text-bull" : "text-warn"}`}><span aria-hidden="true">{status.ok ? "●" : "◐"}</span>{status.text}</span>}
            </div>
          )}
          {v.tone === "wait" && (
            <p className="mt-1.5 text-sm text-mute">
              Models lean <span className={r.lean === "LONG" ? "text-bull" : r.lean === "SHORT" ? "text-bear" : ""}>{r.lean ?? "neither way"}</span> ({upPct}% up · {downPct}% down){r.decision_reason ? `, but ${r.decision_reason}` : ""}. Set an alert and the app tells you when a setup appears.
            </p>
          )}
          <div className="mt-2.5 empty:hidden"><CallStatusRow call={r.call} px={px} /></div>
          {(call?.adjustments?.length || call?.status === "OPEN") && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 empty:hidden">
              <UpdatedBadge adj={call?.adjustments} />
              <AdjustButton call={call} symbol={r.symbol} timeframe={r.timeframe} />
            </div>
          )}
        </div>

        {r.news_risk && (
          <div className="sc-alert sc-alert-bear">⚠ Major US data ({r.news_risk.title}) {r.news_risk.when}: new entries pause until 30 min after the release.</div>
        )}

        {/* the numbers that matter: one aligned strip */}
        {active && plan && (
          <div>
            <div className="metric-strip">
              <Metric k={market === "futures" ? (side === "LONG" ? "Long entry" : "Short entry") : "Buy at"} v={fmtPrice(plan.entry)} cls="text-accent" sub={plan.entry_zone ? `${fmtPrice(Math.min(...plan.entry_zone))} – ${fmtPrice(Math.max(...plan.entry_zone))}` : undefined} />
              <Metric k="Stop-loss" v={fmtPrice(plan.stop)} cls="text-bear" sub={pct(plan.stop, plan.entry) != null ? fmtPctRaw(pct(plan.stop, plan.entry)!, 1) : undefined} />
              {plan.runner?.on
                ? <Metric k={`AI: let it run · 1:${plan.runner.rr}`} v={fmtPrice(plan.runner.target)} cls="text-bull" sub={roiSub(plan.runner.target)} />
                : <Metric k="TP1 · 1:1 · close 50%" v={fmtPrice(plan.targets?.[0]?.price)} cls="text-bull" sub={roiSub(plan.targets?.[0]?.price)} />}
              {market === "futures"
                ? <Metric k="Leverage" v={`${plan.suggested_leverage}x`} sub={`liq. ${fmtPrice(plan.liquidation_at_suggested)}`} />
                : <Metric k="Reward : risk" v={isNum(plan.risk_reward) ? `${plan.risk_reward.toFixed(1)} : 1` : DASH} sub="blended: 50% at TP1, 25% TP2, 25% TP3" />}
            </div>
            {lev != null && lev > 1 && <p className="mt-1.5 text-[11px] text-warn">ROI is shown at {lev}x leverage. Leverage magnifies losses too.</p>}
          </div>
        )}
        {active && plan && (
          <Explain className="space-y-0.5">
            <span className="block">{PLAIN.entry}</span>
            <span className="block">{PLAIN.stop}</span>
            <span className="block">{PLAIN.targets}</span>
            {market === "futures" && <span className="block">{PLAIN.leverage}</span>}
          </Explain>
        )}

        {/* full ladder */}
        {!compact && plan && levels.length > 0 && (
          <div className={`sc-section ${active ? "" : "opacity-70"}`}>
            <div className="sc-label">{active ? "Price levels" : `Watching a possible ${plan.side} — not valid yet${plan.reason ? `: ${plan.reason}` : ""}`}</div>
            <ul className="sc-ladder">
              {levels.map((l) => (
                <li key={l.k} className={l.k === "Price now" ? "is-now" : ""}>
                  <span className="min-w-0"><span className={`font-medium ${l.cls}`}>{l.k}</span>{l.note && <span className="ml-2 hidden text-xs text-mute sm:inline">{l.note}</span>}</span>
                  <span className="num shrink-0 text-right"><span className={l.cls}>{fmtPrice(l.price)}</span>{l.k !== "Price now" && isNum(px) && <span className="ml-2 inline-block w-12 text-xs text-mute">{fmtPctRaw(pct(l.price, px)!, 1)}</span>}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {compact && active && plan && (
          <div className="num flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
            {(plan.targets ?? []).slice(1).map((tg: any) => <span key={tg.name}>{tg.name} <span className="text-bull">{fmtPrice(tg.price)}</span></span>)}
            {isNum(plan.risk_reward) && <span>R:R {plan.risk_reward.toFixed(1)}</span>}
          </div>
        )}

        {/* secondary: admin changes and context, quiet */}
        {call?.adjustments?.length > 0 && (
          <div className="sc-section"><AdjustHistory adj={call.adjustments} /></div>
        )}
        {notes.length > 0 && (
          <div className="sc-section space-y-1 text-xs leading-relaxed text-mute">
            <div className="sc-label">Context</div>
            {notes}
          </div>
        )}

        {/* AI: advisor note + confidence (advanced numbers: Pro view only) */}
        {(r.ai?.rationale || pro) && (
          <div className="sc-section space-y-2">
            <AiNote ai={r.ai} />
            {pro && <div className="ai-block px-3 py-2">
              <div className="mb-1.5"><AiTag label="AI confidence" /></div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div title="How often the AI was right in past out-of-sample calls leaning the same way by a similar margin"><div className="text-mute">Hit rate (similar calls)</div><div className="num mt-0.5 text-base font-semibold">{fmtProb(r.confidence)}</div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-glass/10"><div className="h-full rounded-full bg-ai" style={{ width: `${Math.round((r.confidence ?? 0) * 100)}%` }} /></div></div>
                <div><div className="text-mute">Up / down</div><div className="num mt-0.5 text-base font-semibold"><span className="text-bull">{upPct}%</span> / <span className="text-bear">{downPct}%</span></div></div>
                {market === "futures"
                  ? <div><div className="text-mute">Funding 8h</div><div className="num mt-0.5 text-base font-semibold">{isNum(funding) ? fmtPctRaw(funding * 100, 3) : "0.010%"}</div></div>
                  : <div><div className="text-mute">Trend</div><div className="mt-0.5 text-base font-semibold">{r.regime ?? DASH}</div></div>}
              </div>
            </div>}
          </div>
        )}
        {!pro && v.tone !== "wait" && r.grade && <Explain>{PLAIN.grade}</Explain>}

        <div className="grid grid-cols-[1fr_auto_auto] gap-2 pt-1">
          <button className={`btn ${active ? "btn-primary" : ""}`} onClick={paper}>{active ? "Practise this trade" : "Paper trade"}</button>
          <Link className="btn px-3" to={`/alerts?symbol=${encodeURIComponent(r.symbol)}&timeframe=${r.timeframe ?? "4h"}&market=${market}`} aria-label="Set an alert" title="Alert me when a setup appears">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 01-3.4 0" /></svg>
          </Link>
          <button className="btn px-3" onClick={copy} aria-label="Copy the plan" title="Copy the plan as text">{copied ? "Copied" : "Copy"}</button>
        </div>
        {!compact && <p className="text-[11px] text-mute">Plan for the next {tfLabel} candles, refreshed every few minutes. A probability, not a promise: always use the stop-loss.</p>}
      </div>
    </section>
  );
}

/** One cell of the key-numbers strip: small label, big tabular value, quiet sub line. */
function Metric({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return (
    <div className="metric">
      <div className="metric-k" title={k}>{k}</div>
      <div className={`metric-v num ${cls}`}>{v}</div>
      {sub && <div className="metric-sub num">{sub}</div>}
    </div>
  );
}
