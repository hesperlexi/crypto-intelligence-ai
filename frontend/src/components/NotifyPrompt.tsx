// Asks for notification permission when the installed app (Android APK, Chrome "Install app" or iPhone Home Screen)
// is opened. In the Android app the system permission dialog opens straight away; elsewhere a small banner with an
// "Allow notifications" button asks (browsers only show the dialog after a tap).
// v2.15: the answer is remembered only when it is a real answer ("granted" / "denied"). When the question was closed
// or not shown (permission still "default"), a banner offers "Allow notifications" and the app asks again on a later
// launch, at most once a day. New storage key, so everyone gets one fresh ask.
import { useEffect, useState } from "react";
import * as push from "../lib/push";

const LS_ASKED = "cia-notify-asked2";
const DAY = 24 * 3600_000;
type Asked = { result: "granted" | "denied" | "default"; at: number };

function installed(): boolean {
  try {
    return push.inAndroidApp() || window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true;
  } catch { return false; }
}
function readAsked(): Asked | null {
  try { const a = JSON.parse(localStorage.getItem(LS_ASKED) ?? "null"); return a && typeof a.at === "number" ? a : null; } catch { return null; }
}
function remember(result: Asked["result"]) { try { localStorage.setItem(LS_ASKED, JSON.stringify({ result, at: Date.now() })); } catch { /* ignore */ } }
/** True when this launch should ask: never asked, or only "closed" answers and the last one is a day old. */
function dueToAsk(): boolean {
  const a = readAsked();
  if (!a) return true;
  return a.result === "default" && Date.now() - a.at >= DAY;
}

export default function NotifyPrompt() {
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);       // a real error (blocked, saving failed): no "Allow" button

  const allow = async () => {
    setBusy(true);
    try { await push.enable(); remember("granted"); setShow(false); }
    catch (e: any) {
      const p = push.permission();
      if (p === "granted" || p === "denied") remember(p); else remember("default");
      const dismissed = p === "default";
      setFailed(!dismissed);
      setMsg(dismissed ? push.DISMISSED_TEXT : e?.message ?? "Could not turn on notifications.");
      setShow(true);
    }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (!installed()) return;
    const p = push.permission();
    if (p === "granted" || p === "denied") { if (!readAsked() || readAsked()!.result === "default") remember(p); return; }
    if (p !== "default" || !dueToAsk()) return;
    if (push.inAndroidApp()) { void allow(); return; }          // the app asks Android directly: no tap needed
    setShow(true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!show) return null;
  return (
    <div className="panel animate-in fixed inset-x-3 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-[60] mx-auto max-w-md p-3 text-sm sm:inset-x-auto sm:bottom-4 sm:right-4" role="dialog" aria-label="Notifications">
      <p className="font-semibold">Turn on alerts?</p>
      <p className="mt-1 text-mute">{msg ?? "Get notified of new signals and target hits."}</p>
      <div className="mt-2 flex gap-2">
        {!failed && <button className="btn btn-primary" disabled={busy} onClick={allow}>Allow notifications</button>}
        <button className="btn" onClick={() => { if (!failed) remember("default"); setShow(false); }}>{failed ? "Close" : "Not now"}</button>
      </div>
    </div>
  );
}
