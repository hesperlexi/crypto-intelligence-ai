// One clear answer per coin: go long, go short, buy, sell or wait, at which prices, with what risk.
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DASH, base, fmtPctRaw, fmtPrice, fmtProb, isNum, slug, isGoldSignal } from "../lib/format";
import { useLive } from "../lib/live";
import { CoinAvatar } from "./Polish";
import { AiNote, CallStatusRow, RiskBadge } from "./SignalExtras";
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
      className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-md border font-bold leading-none ${small ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs"} ${a ? "border-accent/60 bg-accent/15 text-accent" : "border-warn/50 bg-warn/10 text-warn"}`}>
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
  const raw = r.plan;
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

  return (
    <section className={`panel overflow-hidden border ${t.ring}`}>
      {/* header: coin, price, verdict */}
      <div className={`flex items-center justify-between gap-3 px-4 py-3 ${t.soft}`}>
        <Link to={`/asset/${slug(r.symbol)}`} className="flex min-w-0 items-center gap-3 hover:text-accent">
          <CoinAvatar symbol={r.symbol} size={compact ? 32 : 40} />
          <div className="min-w-0">
            <div className="font-display text-lg font-bold leading-tight">{base(r.symbol)}<span className="text-sm font-normal text-mute">/USDT</span></div>
            <div className="num text-sm text-mute">{fmtPrice(px)} · {String(r.timeframe ?? "").toUpperCase()} {market}</div>
          </div>
        </Link>
        <span className={`shrink-0 rounded-lg px-3 py-1.5 text-sm font-extrabold tracking-wide ${t.pill}`}>
          {v.tone === "bull" ? "▲ " : v.tone === "bear" ? "▼ " : ""}{v.label}
        </span>
      </div>

      <div className="space-y-3 p-4">
        {v.tone !== "wait" && (r.grade || (active && plan)) && (
          <div className="flex flex-wrap items-center gap-1.5">
            <GradeBadge grade={r.grade} small />
            {active && plan && <RiskBadge entry={plan.entry} stop={plan.stop} leverage={market === "futures" ? plan.suggested_leverage : 1} />}
            {active && plan && market === "futures" && isNum(plan.suggested_leverage) && <span className="num text-[11px] text-mute">· {plan.suggested_leverage}x suggested</span>}
          </div>
        )}
        {r.stale === true && (
          <div className="rounded-lg border border-warn/40 bg-warn/[0.08] px-2.5 py-1.5 text-sm font-semibold text-warn" role="status">Data delayed — no trade</div>
        )}
        <div>
          <div className={`text-base font-semibold ${v.tone === "wait" ? "" : t.text}`}>{v.headline}</div>
          {r.record_status === "already_open" && <p className="mt-1 text-xs text-mute">Following the open call: this setup is already in the record, so it is not logged twice.</p>}
          <div className="mt-1.5"><CallStatusRow call={r.call} px={px} /></div>
          {active && status && (
            <div className={`mt-1 flex items-center gap-1.5 text-sm ${status.ok ? "text-bull" : "text-warn"}`}>
              <span aria-hidden="true">{status.ok ? "●" : "◐"}</span>{status.text}
            </div>
          )}
          {r.news_risk && (
            <div className="mt-1.5 rounded-lg border border-bear/40 bg-bear/[0.08] px-2.5 py-1.5 text-xs text-bear">
              ⚠ Major US data ({r.news_risk.title}) {r.news_risk.when}: new entries pause until 30 min after the release.
            </div>
          )}
          {v.tone === "wait" && (
            <p className="mt-1 text-sm text-mute">
              Models lean <span className={r.lean === "LONG" ? "text-bull" : r.lean === "SHORT" ? "text-bear" : ""}>{r.lean ?? "neither way"}</span> ({upPct}% up · {downPct}% down){r.decision_reason ? `, but ${r.decision_reason}` : ""}. Set an alert and the app tells you when a setup appears.
            </p>
          )}
          {v.tone !== "wait" && r.decision_basis && <p className="mt-1 text-xs text-mute">Why: {r.decision_basis}</p>}
          {isGoldSignal(r.symbol) && <p className="mt-1 rounded-lg border border-accent/30 bg-accent/[0.06] px-2.5 py-1.5 text-xs text-mute"><span className="font-semibold text-accent">Gold (XAU/USD).</span> Levels are in PAXG, which follows the gold price closely. On forex.com, use the same % distances from your entry (shown under each level).</p>}
          {pro && v.tone !== "wait" && isNum(r.filter_score) && <p className="mt-0.5 text-xs text-bull" title="A second model trained on which past setups actually reached their targets before the stop">✓ Passed the trade filter ({Math.round(r.filter_score * 100)}% vs a {Math.round((r.filter_threshold ?? 0) * 100)}% bar)</p>}
          {market === "spot" && v.tone === "bear" && <p className="mt-1 text-sm text-mute">The trend points down. If you hold {base(r.symbol)}, consider taking profit or protecting it with a stop; avoid new buys for now.</p>}
        </div>

        {/* the numbers that matter */}
        {active && plan && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Box k={market === "futures" ? (side === "LONG" ? "Long entry" : "Short entry") : "Buy at"} v={fmtPrice(plan.entry)} cls="text-accent" sub={plan.entry_zone ? `${fmtPrice(Math.min(...plan.entry_zone))} – ${fmtPrice(Math.max(...plan.entry_zone))}` : undefined} />
            <Box k="Stop-loss" v={fmtPrice(plan.stop)} cls="text-bear" sub={pct(plan.stop, plan.entry) != null ? fmtPctRaw(pct(plan.stop, plan.entry)!, 1) : undefined} />
            {plan.runner?.on
              ? <Box k={`AI: let it run · 1:${plan.runner.rr}`} v={fmtPrice(plan.runner.target)} cls="text-bull" sub={roiSub(plan.runner.target)} />
              : <Box k="TP1 · 1:1 · close 50%" v={fmtPrice(plan.targets?.[0]?.price)} cls="text-bull" sub={roiSub(plan.targets?.[0]?.price)} />}
            {market === "futures"
              ? <Box k="Leverage" v={`${plan.suggested_leverage}x`} sub={`liq. ${fmtPrice(plan.liquidation_at_suggested)}`} />
              : <Box k="Reward : risk" v={isNum(plan.risk_reward) ? `${plan.risk_reward.toFixed(1)} : 1` : DASH} sub="blended: 50% at TP1, 25% TP2, 25% TP3" />}
          </div>
        )}
        {active && plan && market === "futures" && isNum(plan.suggested_leverage) && plan.suggested_leverage > 1 && (
          <p className="text-[11px] text-warn">ROI is shown at {plan.suggested_leverage}x leverage. Leverage magnifies losses too.</p>
        )}
        {active && plan && (
          <Explain className="space-y-0.5">
            <span className="block">{PLAIN.entry}</span>
            <span className="block">{PLAIN.stop}</span>
            <span className="block">{PLAIN.targets}</span>
            {market === "futures" && <span className="block">{PLAIN.leverage}</span>}
          </Explain>
        )}
        <AiNote ai={r.ai} />

        {/* full ladder */}
        {!compact && plan && levels.length > 0 && (
          <div className={`rounded-xl border border-glass/[0.08] bg-ink/40 p-2 ${active ? "" : "opacity-70"}`}>
            {!active && <div className="px-2 pb-1 text-xs text-mute">Watching a possible {plan.side} — not valid yet{plan.reason ? `: ${plan.reason}` : ""}</div>}
            <ul>
              {levels.map((l) => (
                <li key={l.k} className={`flex items-baseline justify-between gap-3 rounded-lg px-2 py-1.5 ${l.k === "Price now" ? "bg-glass/[0.06]" : ""}`}>
                  <span className="min-w-0"><span className={`font-medium ${l.cls}`}>{l.k}</span>{l.note && <span className="ml-2 hidden text-xs text-mute sm:inline">{l.note}</span>}</span>
                  <span className="num shrink-0 text-right"><span className={l.cls}>{fmtPrice(l.price)}</span>{l.k !== "Price now" && isNum(px) && <span className="ml-2 text-xs text-mute">{fmtPctRaw(pct(l.price, px)!, 1)}</span>}</span>
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

        {/* confidence and context (advanced numbers: Pro view only) */}
        {pro && <div className="grid grid-cols-3 gap-2 text-xs">
          <div title="How often the AI was right in past out-of-sample calls leaning the same way by a similar margin"><div className="text-mute">Hit rate (similar calls)</div><div className="num mt-0.5 text-sm font-semibold">{fmtProb(r.confidence)}</div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-glass/10"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((r.confidence ?? 0) * 100)}%` }} /></div></div>
          <div><div className="text-mute">Up / down</div><div className="num mt-0.5 text-sm font-semibold"><span className="text-bull">{upPct}%</span> / <span className="text-bear">{downPct}%</span></div></div>
          {market === "futures"
            ? <div><div className="text-mute">Funding 8h</div><div className="num mt-0.5 text-sm font-semibold">{isNum(funding) ? fmtPctRaw(funding * 100, 3) : "0.010%"}</div></div>
            : <div><div className="text-mute">Trend</div><div className="mt-0.5 text-sm font-semibold">{r.regime ?? DASH}</div></div>}
        </div>}
        {!pro && v.tone !== "wait" && r.grade && <Explain>{PLAIN.grade}</Explain>}

        <div className="grid grid-cols-[1fr_auto_auto] gap-2">
          <button className={`btn ${active ? "btn-primary" : ""}`} onClick={paper}>{active ? "Practise this trade" : "Paper trade"}</button>
          <Link className="btn px-3" to={`/alerts?symbol=${encodeURIComponent(r.symbol)}&timeframe=${r.timeframe ?? "4h"}&market=${market}`} aria-label="Set an alert" title="Alert me when a setup appears">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 01-3.4 0" /></svg>
          </Link>
          <button className="btn px-3" onClick={copy} aria-label="Copy the plan" title="Copy the plan as text">{copied ? "Copied" : "Copy"}</button>
        </div>
        {!compact && <p className="text-[11px] text-mute">Plan for the next {String(r.timeframe ?? "").toUpperCase()} candles, refreshed every few minutes. A probability, not a promise: always use the stop-loss.</p>}
      </div>
    </section>
  );
}

function Box({ k, v, sub, cls = "" }: { k: string; v: string; sub?: string; cls?: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-glass/[0.08] bg-ink/40 px-3 py-2.5">
      <div className="truncate text-[11px] font-semibold uppercase tracking-wide text-mute">{k}</div>
      <div className={`num mt-1 truncate text-lg font-semibold leading-tight ${cls}`}>{v}</div>
      {sub && <div className="num mt-0.5 text-[11px] leading-snug text-mute">{sub}</div>}
    </div>
  );
}
