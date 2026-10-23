import { useEffect, useMemo, useState } from "react";
import CandleChart, { Candle, PriceLine } from "../components/CandleChart";
import { SymbolSelect, TfTabs, useSymbols } from "../components/Pickers";
import { Badge, Card, Check, Empty, ErrorBox, FlagList, Note, ProbBar, RegimeBadge, Row, SignalBadge, signalTone, Stat } from "../components/ui";
import { api, useApi } from "../lib/api";
import { DASH, fmtPct, fmtPrice, fmtProb, fmtTime, slug, toLocalInput, tone } from "../lib/format";

const toCandles = (rows: any[]): Candle[] => rows.map((r) => [r.ts, r.open, r.high, r.low, r.close, r.volume]);

export default function Replay() {
  const symbols = useSymbols();
  const [symbol, setSymbol] = useState("BTC/USDT");
  const [tf, setTf] = useState("4h");
  const [when, setWhen] = useState("");
  const [res, setRes] = useState<any>(null);
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const range = useApi<any>(`/replay/${slug(symbol)}/range?timeframe=${tf}`);

  useEffect(() => {
    if (range.data?.available) setWhen(toLocalInput(range.data.earliest + (range.data.latest - range.data.earliest) * 0.8));
    setRes(null);
  }, [range.data]);

  const run = async () => {
    if (!when) return;
    setBusy(true);
    setErr(null);
    setRevealed(false);
    try {
      const r = await api<any>(`/replay/${slug(symbol)}?timeframe=${tf}&as_of=${new Date(when).getTime()}&bars_after=40`);
      if (r.status !== "OK") setErr(r.reason ?? r.status);
      setRes(r.status === "OK" ? r : null);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const known = useMemo(() => (res ? toCandles(res.chart.known) : []), [res]);
  const future = useMemo(() => (res && revealed ? toCandles(res.chart.future) : undefined), [res, revealed]);
  const a = res?.analysis;
  const fc = a?.forecast;
  const setup = a?.setup;
  const lines: PriceLine[] = setup?.valid ? [
    { price: setup.ideal_entry, title: "Entry", color: "#5aa0ff" }, { price: setup.stop, title: "Stop", color: "#f0506e" },
    ...setup.targets.map((t: any) => ({ price: t.price, title: t.name, color: "#2ebd85" })),
  ] : [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Replay market</h1>
        <p className="text-sm text-mute">Pick a past moment. The system rebuilds its view using only candles that had closed by then, trains a model on that truncated history, forecasts — and only then shows what happened.</p>
      </div>
      <Card title="Choose a moment">
        <div className="flex flex-wrap items-end gap-3">
          <SymbolSelect value={symbol} onChange={setSymbol} symbols={symbols.length ? symbols : [symbol]} />
          <TfTabs value={tf} onChange={setTf} />
          <label className="text-xs text-mute">Date and time (local)
            <input type="datetime-local" className="input mt-1 w-56" value={when} onChange={(e) => setWhen(e.target.value)}
              min={range.data?.available ? toLocalInput(range.data.earliest) : undefined} max={range.data?.available ? toLocalInput(range.data.latest) : undefined} />
          </label>
          <button className="btn btn-primary" disabled={busy || !when} onClick={run}>{busy ? "Queued — waiting for the engine…" : "Replay"}</button>
        </div>
        {range.data && !range.data.available && <p className="mt-2 text-sm text-warn">{range.data.reason}</p>}
        {range.data?.available && <Note>Replayable range: {fmtTime(range.data.earliest)} to {fmtTime(range.data.latest)}. Replays run on the engine (a model is trained from scratch on the truncated data), so the result arrives with its next cycle, usually within 15 minutes.</Note>}
      </Card>
      {err && <ErrorBox error={err} />}

      {res && a && (
        <>
          <Card title={`What was known at ${fmtTime(res.audit.as_of)}`} right={<div className="flex gap-2"><RegimeBadge regime={a.regime?.regime} /><SignalBadge signal={a.signal?.signal} /><Badge tone={signalTone(a.decision)}>{a.decision}</Badge></div>}>
            <CandleChart candles={known} future={future} lines={lines} height={380} />
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <FlagList flags={a.flags} />
              {!revealed ? <button className="btn btn-primary" onClick={() => setRevealed(true)}>Reveal what happened next</button> : <Badge tone="accent">Future revealed (dimmed candles)</Badge>}
            </div>
          </Card>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card title="Forecast made at that time">
              {fc?.available ? (
                <>
                  <ProbBar up={fc.probabilities.up} neutral={fc.probabilities.neutral} down={fc.probabilities.down} />
                  <div className="mt-3">
                    <Row k="Predicted" v={fc.predicted} />
                    <Row k="Expected return (next bar)" v={fmtPct(fc.expected_return)} className={tone(fc.expected_return)} />
                    <Row k="80% range" v={fc.distribution ? `${fmtPct(fc.distribution.intervals["80"].low_return, 1)} … ${fmtPct(fc.distribution.intervals["80"].high_return, 1)}` : DASH} />
                    <Row k="Model agreement" v={fmtProb(fc.model_agreement)} />
                    <Row k="Confidence" v={fmtProb(a.confidence)} />
                  </div>
                </>
              ) : <Empty>{fc?.reason ?? "No model forecast"}</Empty>}
              {a.decision_reason && <Note>Decision reason: {a.decision_reason}.</Note>}
            </Card>
            <Card title="What actually happened">
              {!revealed ? <Empty>Hidden until you reveal it.</Empty> : res.reveal.bars === 0 ? <Empty>{res.reveal.note}</Empty> : (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <Stat label="Next bar" value={fmtPct(res.reveal.next_bar_return)} className={tone(res.reveal.next_bar_return)} />
                    <Stat label={`After ${res.reveal.bars} bars`} value={fmtPct(res.reveal.final_return)} className={tone(res.reveal.final_return)} />
                    <Stat label="Max up" value={fmtPct(res.reveal.max_up)} className="text-bull" />
                    <Stat label="Max down" value={fmtPct(res.reveal.max_down)} className="text-bear" />
                  </div>
                  {res.reveal.forecast_check && (
                    <div className="mt-3 space-y-1">
                      <Check ok={res.reveal.forecast_check.correct}>Predicted {res.reveal.forecast_check.predicted}, actual {res.reveal.forecast_check.actual}</Check>
                      <Check ok={res.reveal.forecast_check.inside_80_interval}>Outcome inside the 80% forecast range</Check>
                    </div>
                  )}
                  {res.reveal.setup_check && (
                    <div className="mt-3 space-y-1">
                      <Check ok={res.reveal.setup_check.tp1}>TP1 reached</Check><Check ok={res.reveal.setup_check.tp2}>TP2 reached</Check><Check ok={res.reveal.setup_check.tp3}>TP3 reached</Check>
                      <Check ok={!res.reveal.setup_check.stop_hit}>Stop {res.reveal.setup_check.stop_hit ? "was hit" : "not hit"}</Check>
                    </div>
                  )}
                  <Note>One replay is an anecdote, not evidence. Use the Accuracy page for statistics over hundreds of predictions.</Note>
                </>
              )}
            </Card>
            <Card title="Look-ahead audit" right={<Badge tone={res.audit.no_future_data ? "bull" : "bear"}>{res.audit.no_future_data ? "No future data used" : "LEAK DETECTED"}</Badge>}>
              <Row k="Replay time" v={fmtTime(res.audit.as_of)} />
              <Row k="Last candle used closed at" v={fmtTime(res.audit.last_closed_bar_close)} />
              <Row k="Newest candle in any timeframe" v={fmtTime(res.audit.newest_candle_close_used)} />
              <Row k="Model trained on outcomes through" v={fmtTime(res.audit.model_trained_through)} />
              <Row k="Candles known" v={res.audit.candles_known} />
              <Row k="Price at that time" v={fmtPrice(a.last_close)} />
              {res.audit.model_note && <Note>{res.audit.model_note}</Note>}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
