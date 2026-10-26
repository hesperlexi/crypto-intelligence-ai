// Asks for notification permission the first time the installed app (Android APK, Chrome "Install app" or iPhone
// Home Screen) is opened. In the Android app the system permission dialog opens straight away; elsewhere a small
// banner with an "Allow" button asks (browsers only show the dialog after a tap).
import { useEffect, useState } from "react";
import * as push from "../lib/push";

const LS_ASKED = "cia-notify-asked";

function installed(): boolean {
  try {
    return push.inAndroidApp() || window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true;
  } catch { return false; }
}
function asked(): boolean { try { return localStorage.getItem(LS_ASKED) === "1"; } catch { return false; } }
function markAsked() { try { localStorage.setItem(LS_ASKED, "1"); } catch { /* ignore */ } }

export default function NotifyPrompt() {
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const allow = async () => {
    setBusy(true); markAsked();
    try { await push.enable(); setShow(false); }
    catch (e: any) { setMsg(e?.message ?? "Could not turn on notifications."); setShow(true); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (!installed() || asked() || push.permission() !== "default") return;
    if (push.inAndroidApp()) { allow(); return; }          // the app asks Android directly: no tap needed
    setShow(true);
  }, []);

  if (!show) return null;
  return (
    <div className="panel animate-in fixed inset-x-3 bottom-4 z-[60] mx-auto max-w-md p-3 text-sm sm:inset-x-auto sm:right-4" role="dialog" aria-label="Notifications">
      <p className="font-semibold">Turn on alerts?</p>
      <p className="mt-1 text-mute">{msg ?? "Get a notification the moment a new signal or target hit arrives."}</p>
      <div className="mt-2 flex gap-2">
        {!msg && <button className="btn btn-primary" disabled={busy} onClick={allow}>Allow</button>}
        <button className="btn" onClick={() => { markAsked(); setShow(false); }}>{msg ? "Close" : "Not now"}</button>
      </div>
    </div>
  );
}
