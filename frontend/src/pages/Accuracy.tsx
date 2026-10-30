import { useEffect, useState } from "react";
import { useIsAdmin } from "../lib/session";
import { useSearchParams } from "react-router-dom";
import { SymbolSelect, TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Check, Empty, ErrorBox, Loading, Note, Row, Stat } from "../components/ui";
import { post, useApi } from "../lib/api";
import { DASH, fmtDate, fmtNum, fmtPct, fmtProb, fmtTime, isNum, slug, tone } from "../lib/format";

const CHECK_LABELS: Record<string, string> = {
  enough_oos_samples: "Enough out-of-sample predictions",
  beats_all_benchmarks_net: "Beats Buy & Hold, previous-candle, SMA and RSI strategies after costs",
  beats_random_timing: "Beats randomly-timed versions of itself",
  accuracy_above_prior: "Classifies direction better than the class-prior baseline",
  positive_net_return: "Positive net return after fees, spread and slippage",
  trades_at_all: "Actually takes positions",
};

export default function Accuracy() {
  const symbols = useSymbols();
  const [sp, setSp] = useSearchParams();
  const symbol = (sp.get("symbol") ?? "BTC-USDT").replace("-", "/");
  const tf = sp.get("tf") ?? "4h";
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    n.set(k, v);
    setSp(n, { replace: true });
  };
  const s = slug(symbol);
  const models = useApi<any>(`/models/${s}?timeframe=${tf}`, 30000);
  const perf = useApi<any>(`/performance/${s}?timeframe=${tf}`, 60000);
  const all = useApi<any>("/performance", 60000);
  const status = useApi<any>("/models/status", 5000);
  const [msg, setMsg] = useState<string | null>(null);
  const m = models.data;
  const job = (status.data?.training ?? []).find((t: any) => t.symbol === symbol && t.timeframe === tf);
  const running = (status.data?.training ?? []).filter((t: any) => t.state === "running" || t.state === "queued");

  useEffect(() => {
    if (job?.state === "done") models.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.state, job?.version]);

  const admin = useIsAdmin();
  const train = async (scope: "one" | "all") => {
    try {
      const r = await post<any>("/models/train", scope === "one" ? { symbol, timeframe: tf } : {});
      setMsg(`Queued ${r.queued.length} training job(s). Training runs in the background and does not block forecasts.`);
      status.reload();
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  const ens = m?.models?.find((x: any) => x.name === "ensemble");
  const edge = m?.edge;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Forecast accuracy</h1>
          <p className="text-sm text-mute">Is the AI actually working? Every figure here comes from walk-forward out-of-sample tests or from live predictions scored after the fact.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SymbolSelect value={symbol} onChange={(v) => set("symbol", slug(v))} symbols={symbols.length ? symbols : [symbol]} />
          <TfTabs value={tf} onChange={(v) => set("tf", v)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {admin && <button className="btn btn-primary" onClick={() => train("one")}>Train {symbol} {tf}</button>}
        {admin && <button className="btn" onClick={() => train("all")}>Train all</button>}
        {job && job.state !== "done" && <Badge tone={job.state === "failed" ? "bear" : job.state === "skipped" ? "warn" : "accent"}>{job.state}{isNum(job.progress) && job.state === "running" ? ` ${(job.progress * 100).toFixed(0)}%` : ""} · {job.error ?? job.message}</Badge>}
        {running.length > 0 && <span className="text-xs text-mute">{running.length} job(s) in the queue</span>}
        {msg && <span className="text-sm text-accent">{msg}</span>}
      </div>
      {models.error && <ErrorBox error={models.error} retry={models.reload} />}
      {!m && models.loading && <Loading what="Loading model evaluation" />}
      {m && !m.available && <Card title="No model yet"><Empty>{m.reason}. {job?.insufficient ? "INSUFFICIENT DATA: " + job.error : "Start training above, or wait for the background trainer."}</Empty></Card>}

      {m?.available && (
        <>
          <Card title={`${symbol} ${tf.toUpperCase()} · walk-forward out-of-sample verdict`} right={<span className="text-xs text-mute">{m.version} · trained {fmtTime(m.trained_at)}</span>}>
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone={edge.edge_confirmed ? "bull" : "warn"}>{edge.verdict}</Badge>
              <span className="num text-sm text-mute">{edge.n_oos} out-of-sample predictions over {fmtNum(edge.oos_years, 1)} years · α = {edge.alpha}</span>
            </div>
            <div className="mt-3 grid gap-x-8 gap-y-1 md:grid-cols-2">
              {Object.entries(edge.checks).map(([k, v]) => <Check key={k} ok={v as boolean}>{CHECK_LABELS[k] ?? k}</Check>)}
            </div>
            <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="p-value vs random timing" value={fmtNum(edge.p_value_random_timing, 3)} />
              <Stat label="p-value accuracy vs prior" value={fmtNum(edge.p_value_accuracy, 4)} />
              <Stat label="Net return (long/flat)" value={<span className={tone(edge.model.net_return)}>{fmtPct(edge.model.net_return, 1)}</span>} sub={`exposure ${fmtProb(edge.model.exposure)}`} />
              <Stat label="Cost per position change" value={fmtPct(edge.cost_per_turn, 3, false)} sub="fee + slippage + half spread" />
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="grid-table">
                <thead><tr><th>Benchmark (same bars, same costs)</th><th className="text-right">Net return</th><th className="text-right">Sharpe</th><th className="text-right">Max drawdown</th><th>Model beats it?</th></tr></thead>
                <tbody>
                  <tr className="bg-raised/40"><td className="font-medium">AI ensemble</td><td className={`num text-right ${tone(edge.model.net_return)}`}>{fmtPct(edge.model.net_return, 1)}</td><td className="num text-right">{fmtNum(edge.model.sharpe)}</td><td className="num text-right">{fmtPct(edge.model.max_drawdown, 1)}</td><td /></tr>
                  {Object.entries(edge.benchmarks).map(([k, b]: [string, any]) => (
                    <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className={`num text-right ${tone(b.net_return)}`}>{fmtPct(b.net_return, 1)}</td><td className="num text-right">{fmtNum(b.sharpe)}</td><td className="num text-right">{fmtPct(b.max_drawdown, 1)}</td>
                      <td>{edge.beats[k] ? <span className="text-bull">✓ yes</span> : <span className="text-bear">✕ no</span>}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {ens && (
            <Card title="Ensemble · out-of-sample metrics">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                <Stat label="Directional accuracy" value={fmtProb(ens.directional_accuracy, 1)} sub={`on ${ens.directional_n} up/down calls`} />
                <Stat label="3-class accuracy" value={fmtProb(ens.accuracy, 1)} sub={`prior ${fmtProb(edge.model.prior_accuracy, 1)}`} />
                <Stat label="Precision / recall" value={`${fmtProb(ens.precision, 1)} / ${fmtProb(ens.recall, 1)}`} sub={`F1 ${fmtNum(ens.f1, 3)}`} />
                <Stat label="ROC-AUC" value={fmtNum(ens.roc_auc, 3)} sub="one-vs-rest" />
                <Stat label="Brier score" value={fmtNum(ens.brier, 4)} sub="0.667 = uniform guess" />
                <Stat label="Calibration" value={ens.calibration ?? DASH} sub={`ECE ${fmtNum(ens.ece, 3)}`} />
                <Stat label="Forecast MAE" value={fmtPct(ens.reg_mae, 2, false)} sub={`naive ${fmtPct(ens.reg_naive_mae, 2, false)}`} className={ens.reg_beats_naive ? "text-bull" : ""} />
                <Stat label="RMSE / price MAPE" value={`${fmtPct(ens.reg_rmse, 2, false)} / ${fmtPct(ens.reg_mape_price, 2, false)}`} />
                <Stat label="Sharpe" value={fmtNum(ens.sharpe)} sub="long/flat, net of costs" />
                <Stat label="Max drawdown" value={fmtPct(ens.max_drawdown, 1)} />
                <Stat label="Win rate / PF" value={`${fmtProb(ens.win_rate, 0)} / ${fmtNum(ens.profit_factor)}`} sub={`${ens.trades ?? 0} trades`} />
                <Stat label="Net vs gross" value={`${fmtPct(ens.net_return, 1)}`} sub={`gross ${fmtPct(ens.gross_return, 1)}`} className={tone(ens.net_return)} />
              </div>
              {m.interval_coverage?.coverage && <Note>Forecast-range check on held-out errors (n={m.interval_coverage.n}): the 50 / 80 / 95% intervals contained the outcome {fmtProb(m.interval_coverage.coverage["50"], 1)} / {fmtProb(m.interval_coverage.coverage["80"], 1)} / {fmtProb(m.interval_coverage.coverage["95"], 1)} of the time.</Note>}
            </Card>
          )}

          {m.selective && (
            <Card title="Confident calls · accuracy when the model is sure">
              {m.selective.threshold != null ? (<>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <Stat label="All up/down calls" value={fmtProb(m.selective.base?.hit_rate, 1)} sub={`${m.selective.base?.n ?? 0} calls`} />
                  <Stat label={`Calls ≥ ${fmtProb(m.selective.threshold)}`} value={fmtProb(m.selective.hit_rate, 1)} className={m.selective.hit_rate > (m.selective.base?.hit_rate ?? 1) ? "text-bull" : ""}
                    sub={`95% CI ${fmtProb(m.selective.ci95?.[0])}–${fmtProb(m.selective.ci95?.[1])}`} />
                  <Stat label="How often it is that sure" value={fmtProb(m.selective.coverage, 0)} sub={`${m.selective.n} of the test bars`} />
                  <Stat label="Higher-timeframe context" value={m.uses_htf ? `on (${String(m.uses_htf).toUpperCase()})` : m.htf_gate ? "tested · off" : "off"}
                    sub={m.uses_htf ? "it improved accuracy on unseen data" : m.htf_gate ? "it did not improve accuracy on unseen data; re-tested monthly" : "tested at the next nightly training"} />
                </div>
                <Note>Measured on walk-forward out-of-sample bars only: a call is right when the next bar moves in the called direction. The threshold is the one with the best lower 95% bound, so it is not picked for a lucky handful of calls. The Confident-call tracker bot and “confident calls only” alerts use it.</Note>
              </>) : <Empty>{m.selective.reason ?? "Not enough out-of-sample calls to set a confident-call threshold."}</Empty>}
            </Card>
          )}

          <Card title="Model comparison (out-of-sample)" right={m.best_model?.name ? <span className="text-xs text-mute">best single model: <span className="text-text">{m.best_model.label}</span> {m.best_model.supported ? "(statistically supported)" : "(not significantly better than the prior)"}</span> : undefined}>
            <div className="table-wrap">
              <table className="grid-table">
                <thead><tr><th>Model</th><th className="text-right">Weight</th><th className="text-right">Dir. acc.</th><th className="text-right">Prec.</th><th className="text-right">Recall</th><th className="text-right">F1</th><th className="text-right">AUC</th><th className="text-right">Brier</th><th className="text-right">Calib. err.</th><th>Calibration</th><th className="text-right">Net return</th><th className="text-right">Sharpe</th><th className="text-right">Max DD</th><th className="text-right">Win</th><th className="text-right">PF</th></tr></thead>
                <tbody>
                  {m.models.map((r: any) => (
                    <tr key={r.name} className={r.name === "ensemble" ? "bg-raised/40 font-medium" : r.baseline ? "text-mute" : ""}>
                      <td>{r.label}</td><td className="num text-right">{isNum(r.weight) ? fmtProb(r.weight) : DASH}</td>
                      <td className="num text-right">{fmtProb(r.directional_accuracy, 1)}</td><td className="num text-right">{fmtProb(r.precision, 1)}</td><td className="num text-right">{fmtProb(r.recall, 1)}</td>
                      <td className="num text-right">{fmtNum(r.f1, 3)}</td><td className="num text-right">{fmtNum(r.roc_auc, 3)}</td><td className="num text-right">{fmtNum(r.brier, 4)}</td>
                      <td className="num text-right">{fmtNum(r.ece, 3)}</td><td className="text-xs" title={r.calibration_reason ?? ""}>{r.calibration_method ?? DASH}</td>
                      <td className={`num text-right ${tone(r.net_return)}`}>{fmtPct(r.net_return, 1)}</td><td className="num text-right">{fmtNum(r.sharpe)}</td>
                      <td className="num text-right">{fmtPct(r.max_drawdown, 1)}</td><td className="num text-right">{fmtProb(r.win_rate)}</td><td className="num text-right">{fmtNum(r.profit_factor)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Note>{m.selection_note} {!m.has_skill && "No model beat the class prior on the latest validation window, so the ensemble uses equal weights."}</Note>
            {Object.keys(m.failures ?? {}).length > 0 && <p className="mt-2 text-xs text-warn">Models that failed and were left out: {Object.entries(m.failures).map(([k, v]) => `${k} (${v})`).join("; ")}</p>}
            <p className="mt-2 text-xs text-mute">Not installed / disabled: {(m.libraries ?? []).filter((l: any) => !l.available).map((l: any) => `${l.label}: ${l.reason}`).join(" · ") || "none"}</p>
          </Card>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card title="Walk-forward timeline"><Timeline folds={m.folds} live={m.live_fit} sizes={m.sizes} /></Card>
            <Card title="Calibration · predicted confidence vs realised accuracy">
              <div className="table-wrap"><table className="grid-table">
                <thead><tr><th>Confidence bin</th><th className="text-right">Predictions</th><th className="text-right">Mean predicted</th><th className="text-right">Actually correct</th><th className="text-right">Gap</th></tr></thead>
                <tbody>{(m.reliability ?? []).map((b: any) => (
                  <tr key={b.lo}><td className="num">{fmtProb(b.lo)}–{fmtProb(b.hi)}</td><td className="num text-right">{b.n}</td><td className="num text-right">{fmtProb(b.mean_confidence, 1)}</td><td className="num text-right">{fmtProb(b.accuracy, 1)}</td>
                    <td className={`num text-right ${Math.abs(b.accuracy - b.mean_confidence) > 0.07 ? "text-warn" : "text-mute"}`}>{fmtPct(b.accuracy - b.mean_confidence, 1)}</td></tr>
                ))}</tbody>
              </table></div>
              <Note>A well-calibrated model is right about as often as it says it will be. Calibration (Platt or isotonic) is only applied where it improved held-out Brier score.</Note>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <LiveCard perf={perf.data} />
            <DriftCard perf={perf.data} error={perf.error} />
            <Card title="What the ensemble relies on">
              {m.importance?.length ? m.importance.slice(0, 10).map((f: any) => <Row key={f.feature} k={f.label} v={(f.importance * 1000).toFixed(2)} className={f.importance > 0 ? "" : "text-mute"} />) : <Empty>Not computed for this version</Empty>}
              <Note>Permutation importance: increase in Brier score (×1000) when the feature is shuffled on the latest validation window. {m.features} features in total.</Note>
            </Card>
          </div>
        </>
      )}

      <Card title="All trained models">
        {all.error && <ErrorBox error={all.error} />}
        <div className="table-wrap">
          <table className="grid-table">
            <thead><tr><th>Asset</th><th>TF</th><th>Edge</th><th className="text-right">OOS n</th><th className="text-right">OOS dir. acc.</th><th className="text-right">OOS Brier</th><th className="text-right">OOS Sharpe</th><th className="text-right">OOS max DD</th><th className="text-right">Live n</th><th className="text-right">Live acc.</th><th className="text-right">Live 30d</th><th>Trained</th></tr></thead>
            <tbody>{(all.data?.rows ?? []).map((r: any) => (
              <tr key={r.version} className="cursor-pointer" onClick={() => setSp({ symbol: slug(r.symbol), tf: r.timeframe })}>
                <td className="font-medium">{r.symbol}</td><td className="uppercase text-mute">{r.timeframe}</td>
                <td><Badge tone={r.edge_confirmed ? "bull" : "warn"}>{r.edge_confirmed ? "confirmed" : "none"}</Badge></td>
                <td className="num text-right">{r.n_oos}</td><td className="num text-right">{fmtProb(r.oos_directional_accuracy, 1)}</td><td className="num text-right">{fmtNum(r.oos_brier, 4)}</td>
                <td className="num text-right">{fmtNum(r.oos_sharpe)}</td><td className="num text-right">{fmtPct(r.oos_max_drawdown, 1)}</td>
                <td className="num text-right">{r.live_n}</td><td className="num text-right">{fmtProb(r.live_accuracy, 1)}</td><td className="num text-right">{fmtProb(r.live_30d, 1)}</td><td className="text-mute">{fmtDate(r.trained_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {all.data && !all.data.rows.length && <Empty>No models trained yet</Empty>}
      </Card>
    </div>
  );
}

function Timeline({ folds, live, sizes }: { folds: any[]; live: any; sizes: any }) {
  if (!folds?.length) return <Empty>No folds</Empty>;
  const rows = [...folds.map((f) => ({ label: `Fold ${f.fold + 1}`, ...f })), { label: "Live model", train: live.train, val: live.val, test: null }];
  const t0 = Math.min(...rows.map((r) => r.train[0]));
  const t1 = Math.max(...rows.map((r) => (r.test ?? r.val)[1]));
  const pos = (a: number, b: number) => ({ left: `${((a - t0) / (t1 - t0)) * 100}%`, width: `${Math.max(0.6, ((b - a) / (t1 - t0)) * 100)}%` });
  const shown = rows.length > 14 ? [...rows.slice(0, 6), ...rows.slice(-7)] : rows;
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-mute">
        <span><span className="mr-1.5 inline-block h-2 w-4 rounded-sm bg-accent/60" />Train ({sizes.train} bars)</span>
        <span><span className="mr-1.5 inline-block h-2 w-4 rounded-sm bg-warn/70" />Validate / calibrate ({sizes.val})</span>
        <span><span className="mr-1.5 inline-block h-2 w-4 rounded-sm bg-bull/80" />Test, never seen ({sizes.test})</span>
      </div>
      <div className="space-y-1">
        {shown.map((r, i) => (
          <div key={r.label} className="grid grid-cols-[5rem_1fr] items-center gap-2">
            <span className="text-xs text-mute">{rows.length > 14 && i === 6 ? "… " : ""}{r.label}</span>
            <div className="relative h-3 rounded-sm bg-raised">
              <div className="absolute h-full rounded-sm bg-accent/60" style={pos(r.train[0], r.train[1])} title={`train ${fmtDate(r.train[0])} – ${fmtDate(r.train[1])}`} />
              <div className="absolute h-full rounded-sm bg-warn/70" style={pos(r.val[0], r.val[1])} title={`validation ${fmtDate(r.val[0])} – ${fmtDate(r.val[1])}`} />
              {r.test && <div className="absolute h-full rounded-sm bg-bull/80" style={pos(r.test[0], r.test[1])} title={`test ${fmtDate(r.test[0])} – ${fmtDate(r.test[1])}`} />}
            </div>
          </div>
        ))}
      </div>
      <div className="num mt-1 flex justify-between pl-[5.5rem] text-[11px] text-mute"><span>{fmtDate(t0)}</span><span>{fmtDate(t1)}</span></div>
      <Note>{folds.length} folds. Each fold trains on the blue window, fits calibration and ensemble weights on the amber window, and is scored only on the green window that follows. A {sizes.gap}-bar gap separates the segments; data is never shuffled. The live model repeats the recipe on the most recent windows.</Note>
    </div>
  );
}

function LiveCard({ perf }: { perf: any }) {
  const l = perf?.live;
  return (
    <Card title="Live predictions (scored after the outcome)">
      {!l ? <Loading /> : (
        <>
          <div className="grid grid-cols-2 gap-4">
            <Stat label="Scored / pending" value={`${l.resolved} / ${l.pending}`} />
            <Stat label={`Last ${l.last_n.window}`} value={fmtProb(l.last_n.accuracy, 1)} sub={l.last_n.ci95 ? `95% CI ${fmtProb(l.last_n.ci95[0])}–${fmtProb(l.last_n.ci95[1])}` : `n=${l.last_n.n}`} />
          </div>
          <div className="mt-3">{["7d", "30d", "90d"].map((k) => <Row key={k} k={`${k} accuracy`} v={`${fmtProb(l.rolling[k].accuracy, 1)}  (n=${l.rolling[k].n})`} />)}</div>
          {isNum(l.brier) ? (<><Row k="Live Brier" v={fmtNum(l.brier, 4)} /><Row k="Live calibration" v={`${l.calibration} (ECE ${fmtNum(l.ece, 3)})`} /><Row k="Directional (up/down calls)" v={`${fmtProb(l.directional?.accuracy, 1)} (n=${l.directional?.n})`} /></>) : <Note>{l.note}</Note>}
          <Note>3-class accuracy of predictions this installation issued in real time. Nothing here is back-filled from history.</Note>
        </>
      )}
    </Card>
  );
}

function DriftCard({ perf, error }: { perf: any; error: string | null }) {
  const d = perf?.drift;
  return (
    <Card title="Model drift" right={d ? <Badge tone={d.drift_detected ? "warn" : "bull"}>{d.drift_detected ? "⚠ Drift detected" : "Stable"}</Badge> : undefined}>
      {error ? <ErrorBox error={error} /> : !d ? <Empty>{perf?.reason ?? "Loading"}</Empty> : d.error ? <Empty>{d.error}</Empty> : (
        <>
          {d.flags.map((f: string) => <div key={f} className="mb-1 flex gap-2 text-sm"><span className="text-warn" aria-hidden>!</span>{f}</div>)}
          <Row k="Recommendation" v={d.recommendation} className={d.drift_detected ? "text-warn" : ""} />
          <Row k="Features shifted (PSI > 0.25)" v={`${d.feature_drift.shifted} of ${d.feature_drift.n_features}`} />
          <Row k="Median feature PSI" v={fmtNum(d.feature_drift.median_psi, 3)} />
          <Row k="Prediction PSI" v={isNum(d.prediction_psi) ? fmtNum(d.prediction_psi, 3) : "needs 30 live predictions"} />
          <Row k="Volatility percentile now" v={fmtProb(d.vol_pct_now)} />
          {d.performance?.tested ? <Row k="Recent vs reference accuracy" v={`${fmtProb(d.performance.recent_accuracy, 1)} vs ${fmtProb(d.performance.reference_accuracy, 1)} (p=${fmtNum(d.performance.p_value, 3)})`} className={d.performance.degraded ? "text-warn" : ""} /> : <Note>Performance decay test: {d.performance?.reason ?? "not available"}.</Note>}
          {d.feature_drift.top.slice(0, 4).map((f: any) => <Row key={f.feature} k={`PSI · ${f.feature}`} v={fmtNum(f.psi, 3)} className={f.psi > 0.25 ? "text-warn" : "text-mute"} />)}
        </>
      )}
    </Card>
  );
}
