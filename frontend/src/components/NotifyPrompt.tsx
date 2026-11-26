// Asks for notification permission when the installed app (Android APK, Chrome "Install app" or iPhone Home Screen)
// is opened. In the Android app the system permission dialog opens straight away; elsewhere a small banner with an
// "Allow notifications" button asks (browsers only show the dialog after a tap).
// v2.15: the answer is remembered only when it is a real answer ("granted" / "denied"). When the question was closed
// or not shown (permission still "default"), a banner offers "Allow notifications" and the app asks again on a later
// launch, at most once a day. New storage key, so everyone gets one fresh ask.
// 26 Nov 2026: never asks by itself on load (a surprise question that gets dismissed blocked the Android app for good);
// the Android app (level 3+) asks Android itself at start. Already allowed → this phone is registered silently.
// Blocked in the Android app → "Turn on notifications" opens the app's own fix (push.appNotifyLink), or "Update the app".
import { useEffect, useState } from "react";
import * as push from "../lib/push";

const LS_ASKED = "cia-notify-asked2";
const DAY = 24 * 3600_000;
const LS_FIX_LATER = "cia-notify-fix-later";
function fixDue(): boolean { try { return Date.now() - Number(localStorage.getItem(LS_FIX_LATER) || 0) >= 3 * DAY; } catch { return true; } }
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
  const [fix, setFix] = useState(false);             // Android app with notifications off: offer the app's own fix

  const allow = async () => {
    setBusy(true);
    try { await push.enable(); remember("granted"); setShow(false); }
    catch (e: any) {
      const p = push.permission();
      if (p === "granted" || p === "denied") remember(p); else remember("default");
      if (p === "denied" && push.inAndroidApp()) { setFix(true); setMsg(null); setShow(true); return; }
      const dismissed = p === "default";
      setFailed(!dismissed);
      setMsg(dismissed ? push.DISMISSED_TEXT : e?.message ?? "Could not turn on notifications.");
      setShow(true);
    }
    finally { setBusy(false); }
  };

  useEffect(() => {
    // back from the Android app's notification screen: /settings?notify=on|off|update
    let back: string | null = null;
    try {
      const q = new URLSearchParams(location.search);
      back = q.get("notify");
      if (back) {
        q.delete("notify");
        const rest = q.toString();
        history.replaceState(history.state, "", location.pathname + (rest ? `?${rest}` : "") + location.hash);
      }
    } catch { /* ignore */ }
    if (!installed() && !back) return;
    const p = push.permission();
    if (p === "granted") {
      remember("granted");
      if (!push.savedToken()) void push.enable().catch(() => { /* Settings shows the state */ });   // allowed already: register
      return;
    }
    if (push.inAndroidApp() && (p === "denied" || back === "off" || back === "update")) {
      remember("denied");
      if (back || fixDue()) {
        setFix(true);
        setMsg(back === "off" ? "Still off. Switch on “Allow notifications” (and every type under it) for Crypto AI, then come back."
          : back === "on" ? "Notifications are on in your phone. Close the app fully (swipe it away from recent apps) and open it again to finish."
          : null);
        setShow(true);
      }
      return;
    }
    if (p === "denied") { if (!readAsked() || readAsked()!.result === "default") remember(p); return; }
    if (p !== "default" || !dueToAsk()) return;
    setShow(true);                                       // a tap asks (never a surprise question on load)
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!show) return null;
  if (fix) {
    const link = push.appNotifyLink();
    const later = () => { try { localStorage.setItem(LS_FIX_LATER, String(Date.now())); } catch { /* ignore */ } setShow(false); };
    return (
      <div className="panel notify-solid animate-in fixed inset-x-3 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-[60] mx-auto max-w-md p-3 text-sm sm:inset-x-auto sm:bottom-4 sm:right-4" role="dialog" aria-label="Notifications">
        <p className="font-semibold">Notifications are off for this app</p>
        <p className="mt-1 text-mute">{msg ?? (link ? "One tap: your phone asks again, or opens the app's notification switch." : "Update the app first: the new version turns them on with one tap.")}</p>
        <div className="mt-2 flex gap-2">
          {link ? <a className="btn btn-primary" href={link}>Turn on notifications</a>
            : <a className="btn btn-primary" href={push.APK_URL}>Update the app</a>}
          <button className="btn" onClick={later}>Later</button>
        </div>
      </div>
    );
  }
  return (
    <div className="panel notify-solid animate-in fixed inset-x-3 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-[60] mx-auto max-w-md p-3 text-sm sm:inset-x-auto sm:bottom-4 sm:right-4" role="dialog" aria-label="Notifications">
      <p className="font-semibold">Turn on alerts?</p>
      <p className="mt-1 text-mute">{msg ?? "Get notified of new signals and target hits."}</p>
      <div className="mt-2 flex gap-2">
        {!failed && <button className="btn btn-primary" disabled={busy} onClick={allow}>Allow notifications</button>}
        <button className="btn" onClick={() => { if (!failed) remember("default"); setShow(false); }}>{failed ? "Close" : "Not now"}</button>
      </div>
    </div>
  );
}
