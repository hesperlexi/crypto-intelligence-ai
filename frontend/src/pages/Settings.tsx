import { useEffect, useState } from "react";
import { SymbolSelect, TfTabs, useMeta, useSymbols } from "../components/Pickers";
import { AppearancePanel } from "../components/AppearancePanel";
import { Card, ErrorBox, Loading, Note, Row } from "../components/ui";
import { checkForUpdate } from "../lib/updater";
import * as push from "../lib/push";
import { myUid, useIsAdmin } from "../lib/session";
import { APP_VERSION, BUILD_ID, COPYRIGHT } from "../lib/version";
import { MembershipCard } from "../components/Membership";
import { post, put, queueJob, useApi } from "../lib/api";
import { fmtProb } from "../lib/format";

const RISK_FIELDS: [string, string][] = [
  ["portfolio", "Portfolio size ($)"], ["risk_per_trade_pct", "Maximum risk per trade (%)"], ["max_daily_loss_pct", "Maximum daily loss (%)"],
  ["max_exposure_pct", "Maximum portfolio exposure (%)"], ["max_position_pct", "Maximum single position (%)"], ["target_annual_vol_pct", "Volatility target, annual (%)"],
];
const REFRESH_LABEL: Record<number, string> = { 60: "1 minute", 300: "5 minutes", 900: "15 minutes", 1800: "30 minutes", 3600: "1 hour" };

export default function Settings() {
  const admin = useIsAdmin();
  if (!admin) return <MemberSettings />;
  return <AdminSettings />;
}

function MemberSettings() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Settings</h1>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Appearance"><AppearancePanel /></Card>
        <div className="space-y-4"><MembershipCard /><ManualCard /><NotificationsCard /><AndroidCard /><AboutCard /></div>
      </div>
      <Note>Coins, bots, the risk profile and the signal weights are managed by the app owner.</Note>
    </div>
  );
}

function AdminSettings() {
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
        <div className="space-y-4"><ManualCard /><NotificationsCard /><AndroidCard /><AboutCard /></div>
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

function ManualCard() {
  const href = `/manual.pdf?v=${BUILD_ID}`;
  return (
    <Card title="User manual">
      <div className="flex items-center gap-3">
        <img src="/icons/icon-192.png" alt="" className="h-12 w-12 rounded-xl" />
        <p className="text-sm text-mute">Step-by-step guide: reading signals, futures, alerts, paper trading, demo bots and how far to trust the models.</p>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <a className="btn btn-primary" href={href} target="_blank" rel="noopener">Open manual</a>
        <a className="btn" href={href} download="Crypto-Intelligence-AI-User-Manual.pdf">Download PDF</a>
      </div>
    </Card>
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

function NotificationsCard() {
  const admin = useIsAdmin();
  const [perm, setPerm] = useState(push.permission());
  const [token, setToken] = useState(push.savedToken());
  const [key, setKey] = useState("");
  const [hasKey, setHasKey] = useState<boolean | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { push.vapidKey().then((k) => setHasKey(!!k)).catch(() => setHasKey(false)); }, []);
  const act = async (fn: () => Promise<string | void>) => {
    setBusy(true);
    try { const t = await fn(); if (t) setMsg({ ok: true, text: t }); } catch (e: any) { setMsg({ ok: false, text: e.message }); }
    finally { setBusy(false); setPerm(push.permission()); setToken(push.savedToken()); }
  };
  return (
    <section id="notifications">
      <Card title="Notifications">
        <Row k="This device" v={perm === "granted" ? (token ? "on — also when the app is closed" : "on while the app is open") : perm === "denied" ? "blocked in browser settings" : perm === "unsupported" ? "not supported" : "off"} />
        <Row k="Push key (Web Push certificate)" v={hasKey == null ? "…" : hasKey ? "added" : "not added yet"} />
        <div className="mt-3 flex flex-wrap gap-2">
          {perm !== "granted" || !token ? <button className="btn btn-primary" disabled={busy || perm === "denied"} onClick={() => act(push.enable)}>Turn on notifications</button>
            : <button className="btn" disabled={busy} onClick={() => act(async () => { await push.disable(); return "Notifications turned off on this device."; })}>Turn off on this device</button>}
          <button className="btn" disabled={busy} onClick={() => act(async () => { await queueJob("test_push", { uid: myUid() }); return "Test queued: the engine sends it on its next run (within about 15 minutes)."; })}>Send a test notification</button>
        </div>
        {msg && <p className={`mt-2 text-sm ${msg.ok ? "text-accent" : "text-bear"}`}>{msg.text}</p>}
        {!hasKey && !admin && <p className="mt-3 text-xs text-mute">Notifications while the app is closed need a one-time setup by the app owner.</p>}
        {!hasKey && admin && (
          <div className="mt-4 border-t border-glass/[0.06] pt-3">
            <p className="text-sm">One-time setup so alerts also arrive when the app is closed:</p>
            <ol className="mt-1 list-decimal pl-5 text-xs leading-relaxed text-mute">
              <li>Open the Firebase console → your project → ⚙ Project settings → <b>Cloud Messaging</b>.</li>
              <li>Under <b>Web Push certificates</b>, click <b>Generate key pair</b>.</li>
              <li>Copy the long key shown there and paste it here, then press Save and “Turn on notifications”.</li>
            </ol>
            <div className="mt-2 flex gap-2">
              <input className="input" placeholder="Paste the Web Push key (starts with B…)" value={key} onChange={(e) => setKey(e.target.value)} />
              <button className="btn" disabled={busy || !key.trim()} onClick={() => act(async () => { await push.saveVapidKey(key); setHasKey(true); return "Key saved. Now press “Turn on notifications” on each device."; })}>Save</button>
            </div>
          </div>
        )}
        <Note>iPhone / iPad: notifications work only for the app added to the Home Screen (Safari → Share → Add to Home Screen), iOS 16.4 or newer. Turn them on separately on each device.</Note>
      </Card>
    </section>
  );
}

const APK_URL = "https://github.com/hesperlexi/crypto-intelligence-ai/releases/download/android/crypto-intelligence-ai.apk";

function AndroidCard() {
  const [info, setInfo] = useState<any>(undefined);
  useEffect(() => { fetch(`/download/android.json?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then(setInfo).catch(() => setInfo(null)); }, []);
  return (
    <Card title="Android app">
      {info === undefined ? <p className="text-sm text-mute">Checking…</p> : info ? (<>
        <a className="btn btn-primary w-full sm:w-auto" href={info.url ?? APK_URL}>Download the Android app (APK)</a>
        <p className="mt-2 text-xs text-mute">Version {info.version} · {(info.bytes / 1e6).toFixed(1)} MB</p>
      </>) : <p className="text-sm text-mute">The Android app is being built; it appears here after the next deploy.</p>}
      <Note>On your phone: download, open the file, and allow “install unknown apps” for your browser when Android asks. The app opens this site in Chrome, so it always shows the newest version without reinstalling; you only reinstall to pick up a new app icon. Sign in once with Google inside the app.</Note>
    </Card>
  );
}
