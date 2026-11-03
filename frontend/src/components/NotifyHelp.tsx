// Notification help shared by Settings, Alerts and the app shell (UI v2.15):
//   BlockedHelp       what to do when notifications are blocked (Android: short collapsible steps)
//   ChromeWarning     the Android app runs without Chrome-backed notifications: install Chrome / the newest app
//   AppChromeBanner   the same as a slim app-wide banner (dismissible for the session)
//   useApkInfo        version + build number of the newest APK (/download/android.json, written by deploy.yml)
import { useEffect, useState } from "react";
import * as push from "../lib/push";

export function BlockedHelp({ className = "" }: { className?: string }) {
  const android = push.inAndroidApp() || /android/i.test(navigator.userAgent);
  return (
    <div className={`rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm text-warn ${className}`} role="note">
      <p>{push.blockedHelp()}</p>
      {android && (
        <details className="mt-1.5 text-text/90">
          <summary className="tap-h flex cursor-pointer items-center font-medium text-warn">Still not working? Step by step</summary>
          <ol className="mt-1 list-decimal space-y-1 pl-5">
            {push.ANDROID_STEPS.map((s) => <li key={s}>{s}</li>)}
          </ol>
        </details>
      )}
    </div>
  );
}

export function ChromeWarning({ className = "" }: { className?: string }) {
  const apk = useApkInfo();
  if (!push.appWithoutChrome()) return null;
  return (
    <div className={`rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm ${className}`} role="note">
      <p className="text-warn">This app version cannot show notifications. Install Google Chrome, then the newest app.</p>
      <a className="btn btn-primary mt-2" href={apk?.url ?? push.APK_URL}>Download the new app{apkVersion(apk)}</a>
    </div>
  );
}

const DISMISS_KEY = "cia-chrome-banner-off";
/** Slim banner under the header, only inside the Android app when it cannot get notifications. */
export function AppChromeBanner() {
  const [off, setOff] = useState(() => { try { return sessionStorage.getItem(DISMISS_KEY) === "1"; } catch { return false; } });
  if (off || !push.appWithoutChrome()) return null;
  return (
    <div className="border-b border-warn/30 bg-warn/10 px-3 py-1.5 text-sm text-warn" role="note">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-2">
        <span>Notifications need Google Chrome and the newest app. <a className="font-semibold underline" href={push.APK_URL}>Download</a></span>
        <button type="button" className="tap px-2 text-mute hover:text-text" aria-label="Hide" onClick={() => { setOff(true); try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch { /* ignore */ } }}>✕</button>
      </div>
    </div>
  );
}

export interface ApkInfo { version?: string; code?: number; url?: string; bytes?: number }
let cached: Promise<ApkInfo | null> | null = null;
/** Newest APK's version name + build number (null when the file is not there, e.g. local builds). */
export function useApkInfo(): ApkInfo | null | undefined {
  const [info, setInfo] = useState<ApkInfo | null | undefined>(undefined);
  useEffect(() => {
    cached ??= fetch(`/download/android.json?t=${Date.now()}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    let live = true;
    cached.then((x) => { if (live) setInfo(x && typeof x === "object" ? x : null); });
    return () => { live = false; };
  }, []);
  return info;
}
/** " v2.1.0 (184)" or "" when unknown. */
export const apkVersion = (i?: ApkInfo | null) => (i?.version ? ` v${i.version}${i.code ? ` (${i.code})` : ""}` : "");
