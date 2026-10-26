import { useEffect, useMemo, useState } from "react";
import { useIsAdmin } from "../lib/session";
import { Link, useParams } from "react-router-dom";
import TVChart from "../components/TVChart";
import { useMarketStream } from "../lib/stream";
import CandleChart, { Marker, OVERLAY_COLORS, PriceLine } from "../components/CandleChart";
import { MODEL_TFS, TfTabs } from "../components/Pickers";

const ASSET_TFS = ["15m", "1h", "4h", "12h", "1d", "3d", "1w"] as const;
import { Badge, Card, Check, Empty, ErrorBox, FlagList, Loading, Meter, Note, ProbBar, RegimeBadge, Row, ScoreBar, SignalBadge, signalTone, Stat } from "../components/ui";
import TradeCall, { Market } from "../components/TradeCall";
import { post, useApi } from "../lib/api";
import { DASH, fmtCompact, fmtNum, fmtPct, fmtPctRaw, fmtPrice, fmtProb, fmtTime, isNum, slug, tone } from "../lib/format";
import { useTicker } from "../lib/live";

const OVERLAY_GROUPS: Record<string, string[]> = {
  EMA: ["ema_9", "ema_21", "ema_50", "ema_200"],
  VWAP: ["vwap"],
  Bollinger: ["bb_upper", "bb_mid", "bb_lower"],
};

export default function Asset() {
  const params = useParams();
  const symbol = (params.symbol ?? "BTC-USDT").replace("-", "/").toUpperCase();
  const s = slug(symbol);
  const [tf, setTf] = useState("4h");
  const [groups, setGroups] = useState<string[]>(["EMA", "VWAP"]);
  const [showLevels, setShowLevels] = useState(true);
  const [showPlan, setShowPlan] = useState(true);
  const [pro, setPro] = useState(() => { try { return localStorage.getItem("chart_pro") === "1"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("chart_pro", pro ? "1" : "0"); } catch { /* ignore */ } }, [pro]);
  const tk = useTicker(symbol);
  const an = useApi<any>(`/analysis/${s}?timeframe=${tf}`, 60000);
  const oh = useApi<any>(`/market/${s}/ohlcv?timeframe=${tf}&limit=500`);
  const live = useMarketStream(symbol, "spot", tf);          // every trade moves the forming candle, no polling delay
  const a = an.data;
  const ok = a?.status === "OK";
  const price = tk?.last ?? a?.price;
  const setup = a?.setup;
  const fc = a?.forecast;

  const lines = useMemo<PriceLine[]>(() => {
    const out: PriceLine[] = [];
    if (!ok) return out;
    if (showLevels) {
      (a.levels?.zones?.resistance ?? []).slice(0, 3).forEach((z: any) => out.push({ price: z.mid, title: "Resistance", color: "rgba(246,70,93,0.75)", dashed: true }));
      (a.levels?.zones?.support ?? []).slice(0, 3).forEach((z: any) => out.push({ price: z.mid, title: "Support", color: "rgba(14,203,129,0.75)", dashed: true }));
      (a.levels?.liquidity ?? []).slice(0, 4).forEach((l: any) => out.push({ price: l.level, title: l.kind === "high" ? "Liquidity ↑" : "Liquidity ↓", color: "rgba(232,179,57,0.6)", dashed: true }));
      (a.levels?.supply_demand?.demand ?? []).slice(-1).forEach((z: any) => out.push({ price: z.high, title: "Demand", color: "rgba(14,203,129,0.45)" }));
      (a.levels?.supply_demand?.supply ?? []).slice(-1).forEach((z: any) => out.push({ price: z.low, title: "Supply", color: "rgba(246,70,93,0.45)" }));
    }
    if (showPlan && setup?.valid) {
      out.push({ price: setup.ideal_entry, title: "Entry", color: "#5aa0ff" });
      out.push({ price: setup.stop, title: "Stop", color: "#f6465d" });
      setup.targets.forEach((t: any) => out.push({ price: t.price, title: t.name, color: "#0ecb81" }));
    }
    return out;
  }, [a, ok, showLevels, showPlan, setup]);

  const markers = useMemo<Marker[]>(() => (ok && showLevels ? (a.events ?? []).map((e: any) => ({ ts: e.ts, text: `${e.type}${e.direction > 0 ? " ↑" : " ↓"}`, up: e.direction > 0 })) : []), [a, ok, showLevels]);
  const show = useMemo(() => groups.flatMap((g) => OVERLAY_GROUPS[g]), [groups]);
  const toggle = (g: string) => setGroups((cur) => (cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g]));

  return (
    <div className="space-y-4">
      {/* ---- header ---- */}
      <div className="panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{symbol}</h1>
              {ok && <RegimeBadge regime={a.regime.regime} />}
              {ok && <SignalBadge signal={a.signal.signal} />}
              <Link className="btn px-2.5 py-1 text-xs" to={`/alerts?symbol=${encodeURIComponent(symbol)}&timeframe=${["1h", "4h", "12h", "1d"].includes(tf) ? tf : "4h"}`}
                title="Get an alert with entry, stop-loss and take-profits when a trade signal appears">🔔 Alert me</Link>
            </div>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <span className="num text-3xl">{fmtPrice(price)}</span>
              <span className={`num ${tone(tk?.change_pct)}`}>{fmtPctRaw(tk?.change_pct)} 24h</span>
              <span className="num text-sm text-mute">Vol {fmtCompact(tk?.quote_volume)} USDT</span>
              {isNum(tk?.spread_bps) && <span className="num text-sm text-mute">Spread {fmtNum(tk?.spread_bps, 2)} bps</span>}
            </div>
          </div>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:items-end">
            <TfTabs value={tf} onChange={setTf} options={ASSET_TFS} />
            {ok && (
              <div className="grid grid-cols-3 gap-3 rounded-xl border border-glass/[0.08] bg-glass/[0.03] p-3 sm:flex sm:items-start sm:gap-5 sm:border-0 sm:bg-transparent sm:p-0 sm:text-right">
                <Stat label="Decision" value={<Badge tone={signalTone(a.decision)}>{a.decision}</Badge>} />
                <Stat label="Signal score" value={isNum(a.signal.score) ? `${a.signal.score.toFixed(0)}/100` : DASH} />
                <Stat label="Confidence" value={isNum(a.confidence) ? `${(a.confidence * 100).toFixed(0)}/100` : DASH} />
              </div>
            )}
          </div>
        </div>
        {ok && a.flags?.length > 0 && <div className="mt-3"><FlagList flags={a.flags} /></div>}
        {ok && a.decision_reason && <p className="mt-2 text-sm text-mute">Why {a.decision.toLowerCase()}: {a.decision_reason}.</p>}
      </div>

      {an.error && <ErrorBox error={an.error} retry={an.reload} />}
      <AssetCall symbol={symbol} tf={tf} />
      {a && !ok && <Card title="Insufficient data"><Empty>{a.reason ?? "Not enough closed candles for this timeframe yet."} The system does not predict without data.</Empty></Card>}

      {/* ---- chart ---- */}
      <Card title={`${symbol} · ${tf.toUpperCase()} · ${oh.data?.exchange ?? ""}`} right={
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 inline-flex rounded-lg border border-glass/10 p-0.5">
            <button className={`rounded-md px-2 py-0.5 text-xs ${!pro ? "bg-accent text-ink font-semibold" : "text-mute"}`} aria-pressed={!pro} onClick={() => setPro(false)}>AI chart</button>
            <button className={`rounded-md px-2 py-0.5 text-xs ${pro ? "bg-accent text-ink font-semibold" : "text-mute"}`} aria-pressed={pro} onClick={() => setPro(true)}>Pro chart</button>
          </span>
          {!pro && Object.keys(OVERLAY_GROUPS).map((g) => (
            <button key={g} className={`btn px-2 py-0.5 text-xs ${groups.includes(g) ? "btn-on" : ""}`} aria-pressed={groups.includes(g)} onClick={() => toggle(g)}>{g}</button>
          ))}
          {!pro && <button className={`btn px-2 py-0.5 text-xs ${showLevels ? "btn-on" : ""}`} aria-pressed={showLevels} onClick={() => setShowLevels(!showLevels)}>Structure</button>}
          {!pro && <button className={`btn px-2 py-0.5 text-xs ${showPlan ? "btn-on" : ""}`} aria-pressed={showPlan} onClick={() => setShowPlan(!showPlan)}>Trade plan</button>}
        </div>}>
        {pro ? <TVChart symbol={symbol} tf={tf} /> : oh.error ? <ErrorBox error={oh.error} retry={oh.reload} /> : !oh.data ? <Loading what="Loading candles" /> : (
          <>
            <CandleChart candles={oh.data.candles} overlays={oh.data.overlays} show={show} lines={lines} markers={markers} liveCandle={live.live} livePrice={live.live ? null : tk?.last} />
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-mute">
              {show.map((k) => <span key={k} className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-4" style={{ background: OVERLAY_COLORS[k] }} />{k.replace("_", " ").toUpperCase()}</span>)}
              <span>Times in UTC</span>
              {oh.data.quality?.missing > 0 && <span className="text-warn">{oh.data.quality.missing} missing candles in view</span>}
            </div>
          </>
        )}
      </Card>

      {ok && (
        <>
          <Card title="Commentary (generated from the calculated values above)"><p className="text-sm leading-relaxed">{a.commentary}</p></Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <ForecastCard fc={fc} tf={tf} price={a.last_close} />
            <ConsensusCard fc={fc} symbol={symbol} tf={tf} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Forecast by horizon">
              <div className="overflow-x-auto">
                <table className="grid-table">
                  <thead><tr><th>Horizon</th><th className="text-right">Expected</th><th className="text-right">P(up)</th><th className="text-right">80% range</th><th>Status</th></tr></thead>
                  <tbody>
                    {(a.horizons ?? []).map((h: any) => (
                      <tr key={h.horizon}>
                        <td className="font-medium">{h.horizon}</td>
                        <td className={`num text-right ${tone(h.expected_return)}`}>{fmtPct(h.expected_return)}</td>
                        <td className="num text-right">{fmtProb(h.p_up)}</td>
                        <td className="num text-right text-mute">{h.interval80 ? `${fmtPct(h.interval80.low_return, 1)} … ${fmtPct(h.interval80.high_return, 1)}` : DASH}</td>
                        <td className="text-xs text-mute">{h.available ? (h.edge_confirmed ? "edge confirmed" : "no confirmed edge") : h.status?.toLowerCase()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Note>Each row is one bar ahead on that row's own timeframe model. Nothing is extrapolated from a shorter timeframe.</Note>
            </Card>
            <MtfCard mtf={a.mtf} />
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <SetupCard setup={setup} decision={a.decision} />
            <WhyCard sig={a.signal} explanation={fc?.explanation} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <RiskCard a={a} tf={tf} />
            <Card title="Regime">
              <div className="flex items-center gap-2"><RegimeBadge regime={a.regime.regime} /><span className="num text-sm text-mute">score {fmtNum(a.regime.score)}</span></div>
              <div className="mt-3 space-y-0.5">
                <Row k="Regime confidence (input agreement)" v={fmtProb(a.regime.confidence)} />
                <Row k="Trend strength" v={a.regime.trend_strength ?? DASH} />
                <Row k="Momentum" v={a.regime.momentum ?? DASH} />
                <Row k="Volatility" v={a.volatility.state} className={a.volatility.state === "EXTREME" || a.volatility.state === "HIGH" ? "text-warn" : ""} />
              </div>
              {a.regime.transition?.probabilities ? (
                <div className="mt-3">
                  <div className="label mb-1">Regime {a.regime.transition.horizon_bars} bars ahead (historical frequency, n={a.regime.transition.n})</div>
                  {Object.entries(a.regime.transition.probabilities).map(([g, p]) => <Row key={g} k={`${a.regime.transition.from_group} → ${g}`} v={fmtProb(p as number)} />)}
                </div>
              ) : <Note>Regime-change probabilities need more history.</Note>}
            </Card>
            <LiquidityCard symbol={symbol} a={a} />
          </div>

          <Card title="Model performance" right={<Link to={`/accuracy?symbol=${s}&tf=${tf}`} className="text-xs text-accent hover:underline">Full accuracy panel</Link>}>
            {fc?.available ? (
              <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <Stat label="Model version" value={<span className="text-sm">{fc.model_version}</span>} sub={`trained ${fmtTime(fc.trained_at)}`} />
                <Stat label="Edge test" value={<Badge tone={fc.edge_confirmed ? "bull" : "warn"}>{fc.edge_confirmed ? "Confirmed" : "Not confirmed"}</Badge>} sub={fc.edge_failed_checks?.join(", ")} />
                <Stat label="80% interval coverage (OOS)" value={fmtProb(fc.interval_coverage?.coverage?.["80"], 1)} sub={`target 80% · n=${fc.interval_coverage?.n ?? 0}`} />
                <Stat label="Comparable cases" value={fc.confidence?.n ?? DASH} sub={fc.confidence?.basis} />
              </div>
            ) : <Empty>{fc?.reason ?? "No model for this timeframe."}</Empty>}
          </Card>
        </>
      )}
    </div>
  );
}

function ForecastCard({ fc, tf, price }: { fc: any; tf: string; price: number }) {
  if (!fc?.available) {
    return <Card title="AI forecast"><Empty><Badge tone="warn">{fc?.status ?? "NO FORECAST"}</Badge><div className="mt-2">{fc?.reason}</div>{!MODEL_TFS.includes(tf as any) && <div className="mt-1">Pick 1h, 4h, 12h, 1d, 3d or 1w for a model forecast.</div>}</Empty></Card>;
  }
  const d = fc.distribution;
  const p = fc.probabilities;
  const raw = fc.raw_probabilities;
  return (
    <Card title={`AI forecast · next ${tf.toUpperCase()} bar`} right={<span className="text-xs text-mute">from the close at {fmtPrice(price)}</span>}>
      <ProbBar up={p.up} neutral={p.neutral} down={p.down} />
      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat label="Point forecast" value={d ? fmtPrice(d.expected_price) : DASH} sub={<span className={tone(fc.expected_return)}>{fmtPct(fc.expected_return)}</span>} />
        <Stat label="Raw → calibrated P(up)" value={`${fmtProb(raw.up)} → ${fmtProb(p.up)}`} sub="final uses calibrated" />
        <Stat label="Model confidence" value={isNum(fc.confidence?.confidence) ? fmtProb(fc.confidence.confidence) : DASH} sub={fc.confidence?.n ? `hit-rate of ${fc.confidence.n} similar past calls` : fc.confidence?.basis} />
      </div>
      {d ? (
        <div className="mt-4">
          <div className="label mb-1">Forecast range (empirical, out-of-sample errors)</div>
          {(["50", "80", "95"] as const).map((k) => (
            <Row key={k} k={`${k}% interval`} v={`${fmtPrice(d.intervals[k].low_price)} – ${fmtPrice(d.intervals[k].high_price)}  (${fmtPct(d.intervals[k].low_return, 1)} … ${fmtPct(d.intervals[k].high_return, 1)})`} />
          ))}
        </div>
      ) : <Note>Too few out-of-sample errors to build a forecast range.</Note>}
      {fc.touch && (
        <div className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2">
          <div><div className="label mb-1">Chance of reaching (next bar)</div>{fc.touch.upside.map((u: any) => <Row key={u.move} k={fmtPct(u.move, 0)} v={fmtProb(u.probability)} className="text-bull" />)}</div>
          <div><div className="label mb-1">Chance of downside</div>{fc.touch.downside.map((u: any) => <Row key={u.move} k={fmtPct(u.move, 0)} v={fmtProb(u.probability)} className="text-bear" />)}</div>
        </div>
      )}
      <Note>Point forecast, range and confidence are three different things. The neutral band is ±{fmtPct(fc.neutral_band, 2, false)}. {fc.touch ? `Touch frequencies from ${fc.touch.n} ${fc.touch.basis}.` : ""}</Note>
    </Card>
  );
}

function ConsensusCard({ fc, symbol, tf }: { fc: any; symbol: string; tf: string }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const train = async () => {
    setBusy(true);
    try {
      await post("/models/train", { symbol, timeframe: tf });
      setMsg("Training queued. It runs in the next engine cycle (within about 10 minutes); this panel updates by itself.");
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };
  const isAdm = useIsAdmin();
  const canTrain = MODEL_TFS.includes(tf as any) && isAdm;
  return (
    <Card title="Model consensus" right={canTrain ? <button className="btn px-2 py-0.5 text-xs" disabled={busy} onClick={train}>Retrain</button> : undefined}>
      {msg && <p className="mb-2 text-xs text-accent">{msg}</p>}
      {!fc?.available ? <Empty>{fc?.reason ?? "No model"}</Empty> : (
        <>
          <div className="mb-3 flex items-center gap-4">
            <Stat label="Model agreement" value={fmtProb(fc.model_agreement)} sub={`${fc.models_agreeing} of ${fc.models_total} models`} className={fc.model_agreement < 0.6 ? "text-warn" : ""} />
            <div className="flex-1"><Meter value={fc.model_agreement} tone={fc.model_agreement < 0.6 ? "warn" : "accent"} /></div>
          </div>
          <div className="overflow-x-auto">
            <table className="grid-table">
              <thead><tr><th>Model</th><th>Call</th><th className="text-right">P(up)</th><th className="text-right">P(down)</th><th className="text-right">Weight</th><th className="text-right">OOS acc.</th></tr></thead>
              <tbody>
                {fc.per_model.map((m: any) => (
                  <tr key={m.name} className={m.baseline ? "text-mute" : ""}>
                    <td>{m.label}{m.baseline && <span className="ml-1 text-[10px] uppercase">benchmark</span>}</td>
                    {m.error ? <td colSpan={5} className="text-bear">{m.error}</td> : (
                      <>
                        <td><Badge tone={m.predicted === "UP" ? "bull" : m.predicted === "DOWN" ? "bear" : "mute"}>{m.predicted}</Badge></td>
                        <td className="num text-right">{fmtProb(m.calibrated[2])}</td>
                        <td className="num text-right">{fmtProb(m.calibrated[0])}</td>
                        <td className="num text-right">{m.baseline ? DASH : fmtProb(m.weight)}</td>
                        <td className="num text-right">{fmtProb(m.oos_accuracy, 1)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Note>Weights come from recent out-of-sample Brier skill versus the class prior{fc.regime_weights_used ? ", specific to the current regime" : ""}. Models that fail live are down-weighted{fc.live_downweighted?.length ? ` (now: ${fc.live_downweighted.join(", ")})` : ""}.</Note>
        </>
      )}
    </Card>
  );
}

function MtfCard({ mtf }: { mtf: any }) {
  return (
    <Card title="Multi-timeframe" right={<span className="num text-xs text-mute">alignment {fmtProb(mtf?.alignment)}</span>}>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {(mtf?.rows ?? []).map((r: any) => (
          <div key={r.timeframe} className="rounded-md border border-line bg-raised/50 p-2 text-center" title={r.reason ?? ""}>
            <div className="label">{r.timeframe}</div>
            {r.available ? (
              <>
                <div className={`mt-1 text-sm font-semibold ${r.direction > 0 ? "text-bull" : r.direction < 0 ? "text-bear" : "text-mute"}`}>{r.direction > 0 ? "▲ " : r.direction < 0 ? "▼ " : ""}{r.direction_label}</div>
                <div className="num mt-0.5 text-[11px] text-mute">{fmtNum(r.regime_score)}</div>
              </>
            ) : <div className="mt-1 text-xs text-mute">no data</div>}
          </div>
        ))}
      </div>
      <div className="mt-3"><Meter value={mtf?.alignment} tone={mtf?.alignment < 0.5 ? "warn" : "accent"} /></div>
      {mtf?.conflict && <div className="mt-2"><Badge tone="warn">{mtf.conflict_note}</Badge></div>}
      <Note>Alignment is the weighted share of timeframes pointing the dominant way ({mtf?.dominant_label ?? DASH}); neutral timeframes count half. Signals lose a level when timeframes disagree.</Note>
    </Card>
  );
}

function SetupCard({ setup, decision }: { setup: any; decision: string }) {
  if (!setup) return <Card title="Trade setup"><Empty>No directional signal, so no setup is generated.</Empty></Card>;
  return (
    <Card title={`Trade setup · ${setup.side ?? ""}`} right={<Badge tone={setup.valid ? signalTone(decision) : "warn"}>{setup.valid ? decision : "No valid setup"}</Badge>}>
      {!setup.valid && <p className="mb-3 text-sm text-warn">{setup.reason}</p>}
      {setup.ideal_entry != null && (
        <div className={setup.valid ? "" : "opacity-60"}>
          <div className="grid gap-x-6 sm:grid-cols-2">
            <div>
              <Row k="Entry zone" v={`${fmtPrice(setup.entry_zone[0])} – ${fmtPrice(setup.entry_zone[1])}`} />
              <Row k="Ideal entry" v={fmtPrice(setup.ideal_entry)} className="text-accent" />
              <Row k="Aggressive" v={fmtPrice(setup.aggressive_entry)} />
              <Row k="Conservative" v={fmtPrice(setup.conservative_entry)} />
            </div>
            <div>
              <Row k={`Stop (${setup.stop_basis})`} v={fmtPrice(setup.stop)} className="text-bear" />
              <Row k="Risk to stop" v={fmtPctRaw(setup.risk_pct, 2, false)} />
              <Row k="Risk / reward (TP2)" v={`1 : ${fmtNum(setup.risk_reward, 1)}`} />
              <Row k="Expectancy at TP2" v={isNum(setup.expectancy_r) ? `${setup.expectancy_r > 0 ? "+" : ""}${setup.expectancy_r.toFixed(2)} R` : DASH} className={tone(setup.expectancy_r)} />
            </div>
          </div>
          <div className="mt-3 overflow-x-auto"><table className="grid-table">
            <thead><tr><th>Target</th><th className="text-right">Price</th><th className="text-right">Move</th><th className="text-right">R</th><th className="text-right">Reached before stop</th><th>Basis</th></tr></thead>
            <tbody>
              {setup.targets.map((t: any) => (
                <tr key={t.name}>
                  <td className="font-medium">{t.name}</td><td className="num text-right text-bull">{fmtPrice(t.price)}</td>
                  <td className="num text-right">{fmtPctRaw(t.move_pct, 1)}</td><td className="num text-right">{fmtNum(t.rr, 1)}</td>
                  <td className="num text-right" title={`n=${t.probability_n}`}>{fmtProb(t.probability)}</td><td className="text-xs text-mute">{t.basis}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
          <Note>Target probabilities are historical base rates within {setup.horizon_bars} bars ({setup.targets[0]?.probability_basis ?? "history"}), with the stop assumed first if both are touched in one bar. They are not model promises.</Note>
        </div>
      )}
    </Card>
  );
}

function WhyCard({ sig, explanation }: { sig: any; explanation: any }) {
  return (
    <Card title="Why this signal?" right={<SignalBadge signal={sig.signal} />}>
      <div className="space-y-2">
        {sig.components.map((c: any) => (
          <div key={c.key} className={`grid grid-cols-[minmax(0,11rem)_1fr_4.5rem] items-center gap-3 text-sm ${c.available ? "" : "opacity-45"}`}>
            <span className="truncate">{c.label} <span className="num text-xs text-mute">{fmtProb(c.effective_weight)}</span></span>
            <ScoreBar value={c.available ? c.score : null} />
            <span className={`num text-right ${tone(c.score)}`}>{c.available ? (c.score > 0 ? "+" : "") + c.score.toFixed(2) : "n/a"}</span>
          </div>
        ))}
      </div>
      {sig.weights_note && <Note>{sig.weights_note}</Note>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <div><div className="label mb-1">Reasons</div>{sig.reasons.length ? sig.reasons.map((r: string) => <Check key={r} ok>{r}</Check>) : <span className="text-sm text-mute">None</span>}</div>
        <div><div className="label mb-1">Warnings</div>{sig.warnings.length ? sig.warnings.map((r: string) => <div key={r} className="flex gap-2 text-sm"><span className="text-warn" aria-hidden>!</span><span>{r}</span></div>) : <span className="text-sm text-mute">None</span>}</div>
      </div>
      {explanation && (explanation.positive.length > 0 || explanation.negative.length > 0) && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div><div className="label mb-1">Model: pushing up</div>{explanation.positive.slice(0, 6).map((f: any) => <Row key={f.feature} k={f.label} v={`+${(f.contribution * 100).toFixed(1)} pp`} className="text-bull" />)}</div>
          <div><div className="label mb-1">Model: pushing down</div>{explanation.negative.slice(0, 6).map((f: any) => <Row key={f.feature} k={f.label} v={`${(f.contribution * 100).toFixed(1)} pp`} className="text-bear" />)}</div>
        </div>
      )}
      {explanation && <Note>Model factors: {explanation.method}.{explanation.shap ? ` SHAP values for ${explanation.shap.model} are available via the API.` : ""}</Note>}
    </Card>
  );
}

function RiskCard({ a, tf }: { a: any; tf: string }) {
  const [portfolio, setPortfolio] = useState("");
  const [riskPct, setRiskPct] = useState("");
  const [custom, setCustom] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const setup = a.setup;
  const r = custom ?? a.risk;
  const recalc = async () => {
    if (!setup?.ideal_entry) return;
    try {
      const profile: any = {};
      if (portfolio) profile.portfolio = Number(portfolio);
      if (riskPct) profile.risk_per_trade_pct = Number(riskPct);
      setCustom(await post("/risk/position-size", { entry: setup.ideal_entry, stop: setup.stop, timeframe: tf, sigma_bar: a.indicators?.sigma_bar, profile }));
      setErr(null);
    } catch (e: any) {
      setErr(e.message);
    }
  };
  return (
    <Card title="Risk analysis">
      {!r ? <Empty>Position sizing needs an entry and a stop; there is no setup right now.</Empty> : (
        <>
          <div className="mb-3 grid grid-cols-[1fr_1fr_auto] items-end gap-2">
            <label className="text-xs text-mute">Portfolio ($)<input className="input mt-1" inputMode="decimal" placeholder={String(r.profile?.portfolio ?? "")} value={portfolio} onChange={(e) => setPortfolio(e.target.value)} /></label>
            <label className="text-xs text-mute">Risk per trade (%)<input className="input mt-1" inputMode="decimal" placeholder={String(r.profile?.risk_per_trade_pct ?? "")} value={riskPct} onChange={(e) => setRiskPct(e.target.value)} /></label>
            <button className="btn" onClick={recalc}>Size</button>
          </div>
          {err && <ErrorBox error={err} />}
          {r.allowed === false ? <p className="text-sm text-warn">{r.reason}</p> : (
            <>
              <Row k="Position size" v={`${fmtNum(r.qty, 6)} units`} />
              <Row k="Notional" v={`$${fmtNum(r.notional)} (${fmtPctRaw(r.notional_pct, 1, false)})`} />
              <Row k="Maximum loss at stop" v={`$${fmtNum(r.max_loss)} (${fmtPctRaw(r.max_loss_pct, 2, false)})`} className="text-bear" />
              <Row k="Stop distance" v={fmtPctRaw(r.stop_distance_pct, 2, false)} />
              <Row k="Binding constraint" v={r.binding_constraint} />
              <Row k="Daily loss budget left" v={`$${fmtNum(r.daily_loss_remaining)}`} />
            </>
          )}
          {(r.notes ?? []).map((n: string) => <Note key={n}>{n}</Note>)}
          <Note>Sizing is independent of the forecast: it uses only the stop distance, volatility and your limits (edit defaults in Settings).</Note>
        </>
      )}
    </Card>
  );
}

function LiquidityCard({ symbol, a }: { symbol: string; a: any }) {
  const s = slug(symbol);
  const book = useApi<any>(`/market/${s}/orderbook`, 30000);
  const der = useApi<any>(`/market/${s}/derivatives`, 300000);
  const m = book.data?.metrics;
  const d = der.data;
  return (
    <Card title="Volume & liquidity">
      <Row k="Relative volume" v={`${fmtNum(a.liquidity.relative_volume)}x`} className={a.liquidity.volume_spike ? "text-warn" : ""} />
      <Row k="Buy pressure (20 bars)" v={fmtNum(a.liquidity.buy_pressure)} className={tone(a.liquidity.buy_pressure)} />
      {m ? (
        <>
          <Row k="Spread" v={`${fmtNum(m.spread_bps, 2)} bps`} />
          <Row k="Order-book imbalance (±1%)" v={fmtPct(m.imbalance, 0)} className={tone(m.imbalance)} />
          <Row k="Bid / ask depth" v={`$${fmtCompact(m.bid_value)} / $${fmtCompact(m.ask_value)}`} />
          {m.walls.slice(0, 3).map((w: any) => <Row key={w.side + w.price} k={`Large ${w.side} order`} v={`${fmtPrice(w.price)} (${fmtPctRaw(w.distance_pct, 2)})`} />)}
        </>
      ) : <Note>{book.data?.reason ?? "Order book not available from this data source."}</Note>}
      {d?.available ? (
        <div className="mt-3">
          <div className="label mb-1">Derivatives · {d.venue}</div>
          {d.funding && <Row k="Funding rate" v={fmtPct(d.funding.rate, 4)} className={tone(d.funding.rate)} />}
          {d.open_interest && <Row k={`Open interest, ${d.open_interest.hours}h change`} v={fmtPct(d.open_interest.change)} className={tone(d.open_interest.change)} />}
          {d.oi_price && <p className="mt-2 text-sm"><span className="font-medium">{d.oi_price.label}:</span> <span className="text-mute">{d.oi_price.meaning}</span></p>}
        </div>
      ) : <Note>Funding / open interest: {d?.reason ?? "loading"}.</Note>}
    </Card>
  );
}

/** The clear trade call for this coin, spot or futures, from the engine's futures view. */
function AssetCall({ symbol, tf }: { symbol: string; tf: string }) {
  const t = ["1h", "4h", "12h", "1d"].includes(tf) ? tf : "4h";
  const v = useApi<any>(`/futures?timeframe=${t}`);
  const [market, setMarket] = useState<Market>("futures");
  const row = (v.data?.rows ?? []).find((r: any) => r.symbol === symbol);
  if (!row) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Trade call{t !== tf ? <span className="ml-2 text-xs font-normal text-mute">(from the {t.toUpperCase()} chart)</span> : null}</h2>
        <div className="inline-flex rounded-xl border border-glass/10 bg-ink/40 p-1" role="group" aria-label="Market">
          {(["futures", "spot"] as const).map((k) => (
            <button key={k} aria-pressed={market === k} onClick={() => setMarket(k)}
              className={`rounded-lg px-3 py-1 text-xs font-semibold ${market === k ? "bg-accent text-ink" : "text-mute hover:text-text"}`}>{k === "futures" ? "Futures" : "Spot"}</button>
          ))}
        </div>
      </div>
      <TradeCall r={row} market={market} />
    </div>
  );
}
