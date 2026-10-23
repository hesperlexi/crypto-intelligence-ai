import { useEffect, useState } from "react";
import { SymbolSelect, TfTabs, useMeta, useSymbols } from "../components/Pickers";
import { AppearancePanel } from "../components/AppearancePanel";
import { Card, ErrorBox, Loading, Note, Row } from "../components/ui";
import { checkForUpdate } from "../lib/updater";
import { APP_VERSION, BUILD_ID, COPYRIGHT } from "../lib/version";
import { post, put, useApi } from "../lib/api";
import { fmtProb } from "../lib/format";

const RISK_FIELDS: [string, string][] = [
  ["portfolio", "Portfolio size ($)"], ["risk_per_trade_pct", "Maximum risk per trade (%)"], ["max_daily_loss_pct", "Maximum daily loss (%)"],
  ["max_exposure_pct", "Maximum portfolio exposure (%)"], ["max_position_pct", "Maximum single position (%)"], ["target_annual_vol_pct", "Volatility target, annual (%)"],
];
const REFRESH_LABEL: Record<number, string> = { 60: "1 minute", 300: "5 minutes", 900: "15 minutes", 1800: "30 minutes", 3600: "1 hour" };

export default function Settings() {
  const st = useApi<any>("/settings");
  const meta = useMeta();
  const symbols = useSymbols();
  const [risk, setRisk] = useState<any>(null);
  const [weights, setWeights] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [optSymbol, setOptSymbol] = useState("BTC/USDT");
  const [optTf, setOptTf] = useState("4h");
  const [opt, setOpt] = useState<any>(null);

  useEffect(() => {
    if (st.data) {
      setRisk(st.data.risk_profile);
      setWeights(st.data.signal_weights);
    }
  }, [st.data]);

  const save = async (body: any, done: string) => {
    try {
      await put("/settings", body);
      setMsg(done);
      setErr(null);
      st.reload();
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const optimise = async () => {
    try {
      setOpt(await post("/settings/optimise-weights", { symbol: optSymbol, timeframe: optTf }));
    } catch (e: any) {
      setErr(e.message);
    }
  };
  if (!st.data || !risk || !weights) return st.error ? <ErrorBox error={st.error} retry={st.reload} /> : <Loading />;
  const total = Object.values(weights).reduce((a: number, b: any) => a + Number(b || 0), 0) as number;
  const policy = meta.data?.policy;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      {msg && <p className="text-sm text-accent">{msg}</p>}
      {err && <ErrorBox error={err} />}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Appearance"><AppearancePanel /></Card>
        <AboutCard />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Risk profile">
          <div className="grid gap-3 sm:grid-cols-2">
            {RISK_FIELDS.map(([k, label]) => (
              <label key={k} className="text-xs text-mute">{label}<input className="input mt-1" inputMode="decimal" value={risk[k]} onChange={(e) => setRisk({ ...risk, [k]: e.target.value })} /></label>
            ))}
          </div>
          <button className="btn btn-primary mt-3" onClick={() => save({ risk_profile: risk }, "Risk profile saved")}>Save risk profile</button>
          <Note>Position sizes are computed from these limits and the stop distance only. Risk management never looks at the forecast.</Note>
        </Card>
        <Card title="Forecast refresh">
          <div className="flex flex-wrap gap-2">
            {st.data.refresh_options_s.map((s: number) => (
              <button key={s} className={`btn ${st.data.forecast_refresh_s === s ? "btn-on" : ""}`} aria-pressed={st.data.forecast_refresh_s === s} onClick={() => save({ forecast_refresh_s: s }, `Forecasts now refresh every ${REFRESH_LABEL[s]}`)}>{REFRESH_LABEL[s]}</button>
            ))}
          </div>
          <Note>The engine re-scores every asset every 15 minutes (its schedule is set in the GitHub workflow). Refreshing never retrains; models are retrained by a separate daily run. Saved settings are picked up by the next cycle.</Note>
          {policy && (
            <div className="mt-4">
              <div className="label mb-1">Signal policy (set in the backend .env)</div>
              <Row k="Minimum confidence to trade" v={fmtProb(policy.min_confidence)} />
              <Row k="Minimum model agreement" v={fmtProb(policy.min_model_agreement)} />
              <Row k="Minimum risk / reward" v={`1 : ${policy.min_risk_reward}`} />
              <Row k="ML drives the score only with a confirmed edge" v={policy.require_edge_for_ml ? "yes" : "no"} />
              <Row k="Refuse trades without a confirmed edge" v={policy.require_edge_for_trade ? "yes" : "no"} />
              <Row k="Significance level for the edge test" v={policy.edge_alpha} />
            </div>
          )}
        </Card>
      </div>
      <Card title="Signal scoring weights" right={<span className={`num text-xs ${Math.abs(total - 1) < 0.005 ? "text-mute" : "text-warn"}`}>sum {total.toFixed(2)} (normalised automatically)</span>}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Object.keys(weights).map((k) => (
            <label key={k} className="text-xs capitalize text-mute">{k === "htf" ? "Higher timeframe" : k === "ml" ? "ML probability" : k}
              <input className="input mt-1" inputMode="decimal" value={weights[k]} onChange={(e) => setWeights({ ...weights, [k]: e.target.value })} />
            </label>
          ))}
        </div>
        <button className="btn btn-primary mt-3" onClick={() => save({ signal_weights: Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, Number(v)])) }, "Weights saved")}>Save weights</button>
        <div className="mt-5 border-t border-line pt-4">
          <div className="label mb-2">Suggest weights from data</div>
          <div className="flex flex-wrap items-end gap-3">
            <SymbolSelect value={optSymbol} onChange={setOptSymbol} symbols={symbols.length ? symbols : [optSymbol]} />
            <TfTabs value={optTf} onChange={setOptTf} />
            <button className="btn" onClick={optimise}>Fit weights</button>
          </div>
          {opt && (opt.ok ? (
            <div className="mt-3">
              <p className="text-sm">Out-of-sample direction accuracy <span className="num">{fmtProb(opt.test_accuracy, 1)}</span> vs base rate <span className="num">{fmtProb(opt.test_base_rate, 1)}</span> on {opt.test_rows} later bars.</p>
              <div className="mt-2 grid gap-x-8 sm:grid-cols-2">{["trend", "momentum", "volume", "structure", "volatility"].map((k) => <Row key={k} k={k} v={`${Number(weights[k]).toFixed(2)} → ${opt.weights[k].toFixed(2)}`} />)}</div>
              <button className="btn mt-2" onClick={() => setWeights(Object.fromEntries(Object.entries(opt.weights).map(([k, v]) => [k, Number((v as number).toFixed(3))])))}>Load suggestion into the form</button>
              <Note>{opt.note} If accuracy is not above the base rate, the suggestion has no demonstrated value: keep the defaults.</Note>
            </div>
          ) : <p className="mt-3 text-sm text-warn">{opt.reason}</p>)}
        </div>
      </Card>
    </div>
  );
}

function AboutCard() {
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <Card title="About">
      <Row k="App" v="Crypto Intelligence AI" />
      <Row k="Version" v={`v${APP_VERSION}`} />
      <Row k="Build" v={BUILD_ID} />
      <Row k="Updates" v="automatic after every deploy" />
      <div className="mt-3 flex items-center gap-3">
        <button className="btn" onClick={async () => { setMsg("Checking…"); setMsg((await checkForUpdate(true)) ? "Updating…" : "You have the latest version."); }}>Check for updates</button>
        {msg && <span className="text-sm text-mute">{msg}</span>}
      </div>
      <Note>{COPYRIGHT}</Note>
    </Card>
  );
}
