// Notification help shared by Settings, Alerts and the app shell (UI v2.15):
//   BlockedHelp       what to do when notifications are blocked (Android: short collapsible steps)
//   ChromeWarning     the Android app runs without Chrome-backed notifications: install Chrome / the newest app
//   AppChromeBanner   the same as a slim app-wide banner (dismissible for the session)
//   AppUpdateBanner   the installed Android app is older than the newest APK (icon / name changed): update it
//   IconUpdateBanner  iPhone / Android home-screen web app installed before the V3.5 logo: how to get the new icon
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

export interface ApkInfo { version?: string; code?: number; level?: number; url?: string; bytes?: number }

/** True when this is the Android app and a newer APK level is out. */
export function apkUpdateDue(info?: ApkInfo | null): boolean {
  const have = push.installedApkLevel();
  return have > 0 && !!info?.level && have < info.level;
}
const UPD_KEY = "cia-apk-update-later";
const UPD_SNOOZE_MS = 3 * 24 * 3600 * 1000;
/** Android app only: "A new version of the app is ready" with an Update button (snoozed 3 days by Later). */
export function AppUpdateBanner() {
  const apk = useApkInfo();
  const [later, setLater] = useState(() => { try { return Date.now() - Number(localStorage.getItem(UPD_KEY) || 0) < UPD_SNOOZE_MS; } catch { return false; } });
  const [tapped, setTapped] = useState(false);
  if (later || !apkUpdateDue(apk)) return null;
  const size = apk?.bytes ? ` · ${(apk.bytes / 1048576).toFixed(1)} MB` : "";
  return (
    <div className="apk-upd border-b border-accent/30 bg-accent/10 px-3 py-2 text-sm" role="status">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2">
        <img src="/brand/logo-96.png" alt="" width={32} height={32} className="h-8 w-8 shrink-0 rounded-lg max-[359px]:hidden" />
        <span className="min-w-0 flex-1 basis-[13rem]">
          <b className="text-text">New app version ready</b>
          <span className="block text-mute">{tapped ? "Open the downloaded file and tap Update. You stay signed in." : `New logo and fixes${size}`}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => { setLater(true); try { localStorage.setItem(UPD_KEY, String(Date.now())); } catch { /* ignore */ } }}>Later</button>
          <a className="btn btn-primary" href={apk?.url ?? push.APK_URL} onClick={() => setTapped(true)}>Update</a>
        </span>
      </div>
    </div>
  );
}
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

// ---- home-screen icon (V3.5 logo, 26 Nov 2026) ----------------------------------------------------------------
// A web app added to the home screen keeps the icon it had when it was added: iPhone never refreshes it, Chrome on
// Android does by itself within about a day. index.html marks an install that already had saved data as "old".
const ICON_DONE = "cia-icon-v35-ok";
const ICON_LATER = "cia-icon-v35-later";
function standaloneApp(): boolean {
  try { return matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true; } catch { return false; }
}
function isIOS(): boolean {
  try { return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1); } catch { return false; }
}
export function iconUpdateKind(): "ios" | "android" | null {
  try {
    if (push.inAndroidApp() || !standaloneApp() || localStorage.getItem("cia-installed") !== "old") return null;
    if (localStorage.getItem(ICON_DONE)) return null;
    if (Date.now() - Number(localStorage.getItem(ICON_LATER) || 0) < UPD_SNOOZE_MS) return null;
    return isIOS() ? "ios" : /android/i.test(navigator.userAgent) ? "android" : null;
  } catch { return null; }
}
export function IconUpdateBanner() {
  const [kind, setKind] = useState(iconUpdateKind);
  if (!kind) return null;
  const close = (key: string) => { try { localStorage.setItem(key, key === ICON_DONE ? "1" : String(Date.now())); } catch { /* ignore */ } setKind(null); };
  return (
    <div className="apk-upd border-b border-accent/30 bg-accent/10 px-3 py-2 text-sm" role="status">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2">
        <img src="/brand/logo-96.png?v=35" alt="" width={32} height={32} className="h-8 w-8 shrink-0 rounded-lg max-[359px]:hidden" />
        <span className="min-w-0 flex-1 basis-[13rem]">
          <b className="text-text">New app icon</b>
          <span className="block text-mute">{kind === "ios"
            ? "To see it: delete Crypto AI from your home screen, open cryptointelai.com in Safari, then Share → Add to Home Screen. You sign in once more."
            : "Chrome updates it by itself within about a day. To get it now: remove the app, then in Chrome open cryptointelai.com → ⋮ → Install app."}</span>
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => close(ICON_LATER)}>Later</button>
          <button type="button" className="btn btn-primary" onClick={() => close(ICON_DONE)}>Got it</button>
        </span>
      </div>
    </div>
  );
}
