// Phone / desktop notifications for alerts.
//
// * While the app is open but in the background, new alerts are shown as system notifications directly.
// * When the app is closed, the engine sends web-push messages through Firebase Cloud Messaging to every device
//   that turned notifications on. That needs the project's public "Web Push certificate" key (VAPID), which is
//   created once in the Firebase console and pasted into Settings → Notifications (stored in config/push).
import { deleteDoc, doc, getDoc, setDoc } from "firebase/firestore";
import { app, db } from "./firebase";
import { getSession, myUid } from "./session";
import { SITE_HOST } from "./brand";

const LS_TOKEN = "cia-push-token";

// The Android app opens the site with an android-app:// referrer on its first page; remember it for the session.
try { if (document.referrer.startsWith("android-app://")) localStorage.setItem("cia-android-app", "1"); } catch { /* ignore */ }
export function inAndroidApp(): boolean {
  try { return localStorage.getItem("cia-android-app") === "1"; } catch { return false; }
}

/** What to do when notifications are blocked, for the device the person is on. */
export function blockedHelp(): string {
  const ua = navigator.userAgent;
  if (inAndroidApp()) return "Notifications are switched off for the Crypto AI app. Open your phone's Settings → Apps → Crypto AI → Notifications and turn them on (or long-press the app icon → App info → Notifications), then come back and tap Turn on again.";
  if (/android/i.test(ua)) return `Notifications are blocked for this site in Chrome. Tap the lock icon next to the address (or Chrome menu → Settings → Site settings → Notifications), allow ${location.hostname || SITE_HOST}, then tap Turn on again. Also check phone Settings → Apps → Chrome → Notifications.`;
  if (/iphone|ipad|ipod/i.test(ua)) return "On iPhone: open the app from the Home Screen icon (not Safari), then Settings → Notifications → Crypto Intelligence AI → Allow Notifications.";
  return "Notifications are blocked for this site. Click the lock icon in the address bar → Site settings → Notifications → Allow, then reload and try again.";
}

/** Keeps the last failure on the account so the owner can see what went wrong on the Users page. */
async function report(stage: string, e: any) {
  try {
    const uid = myUid();
    if (!uid) return;
    await setDoc(doc(db, "user_state", uid), { push_error: { stage, code: String(e?.code ?? e?.name ?? ""), message: String(e?.message ?? e).slice(0, 300),
      app: inAndroidApp() ? "android-app" : "browser", ua: navigator.userAgent.slice(0, 160), at: Date.now() } }, { merge: true });
  } catch { /* ignore */ }
}

function friendly(e: any): string {
  const m = String(e?.code ?? "") + " " + String(e?.message ?? e);
  if (/permission-blocked|permission-default|NotAllowedError|denied/i.test(m)) return blockedHelp();
  if (/token-subscribe-failed|token-update-failed|Requested entity was not found|API has not been used|PERMISSION_DENIED/i.test(m))
    return "The notification service refused this device. The app owner has been told; please try again later.";
  if (/applicationServerKey|InvalidStateError|push service error|AbortError/i.test(m))
    return "This device had an old notification registration. Tap Turn on again; if it still fails, turn notifications off and on in the phone settings for the app.";
  if (/unsupported|not supported/i.test(m)) return "This browser cannot receive push notifications. Install the Android app, or use Chrome.";
  return `Could not turn on notifications: ${String(e?.message ?? e)}`;
}

export function pushSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
}

export function permission(): NotificationPermission | "unsupported" {
  return pushSupported() ? Notification.permission : "unsupported";
}

export function savedToken(): string | null {
  try { return localStorage.getItem(LS_TOKEN); } catch { return null; }
}

export async function vapidKey(): Promise<string | null> {
  const d = (await getDoc(doc(db, "config", "push"))).data();
  return d?.vapid_key || null;
}

export async function saveVapidKey(key: string) {
  const k = key.trim();
  if (k && !/^[A-Za-z0-9_-]{80,100}$/.test(k)) throw new Error("that does not look like a Web Push public key (about 88 letters and digits)");
  await setDoc(doc(db, "config", "push"), { vapid_key: k || null, updated_at: Date.now() }, { merge: true });
}

/** Ask for permission and register this device for push. Returns a short status text. */
export async function enable(): Promise<string> {
  if (!pushSupported()) {
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    throw new Error(ios ? "On iPhone / iPad, first add the app to your Home Screen (Safari → Share → Add to Home Screen), open it from there, then turn notifications on." : "This browser does not support notifications. Install the Android app, or use Chrome.");
  }
  let perm: NotificationPermission;
  try { perm = await Notification.requestPermission(); } catch (e) { await report("permission", e); throw new Error(friendly(e)); }
  if (perm !== "granted") { await report("permission", { code: perm, message: `permission ${perm}` }); throw new Error(blockedHelp()); }
  const key = await vapidKey();
  if (!key) return "Notifications are on while the app is open. To get them when the app is closed, the app owner still has to add the Web Push key.";
  const reg = await navigator.serviceWorker.ready;
  const { getMessaging, getToken, isSupported } = await import("firebase/messaging");
  if (!(await isSupported())) return "Notifications are on while the app is open (this browser cannot receive push when closed).";
  let token: string | null = null;
  try {
    token = await getToken(getMessaging(app), { vapidKey: key, serviceWorkerRegistration: reg });
  } catch (e1) {
    // a registration made with another key (or a stale one) blocks a new subscription: clear it and retry once
    try {
      const sub = await reg.pushManager.getSubscription();
      if (sub) await sub.unsubscribe();
      token = await getToken(getMessaging(app), { vapidKey: key, serviceWorkerRegistration: reg });
    } catch (e2) {
      await report("token", e2);
      throw new Error(friendly(e2));
    }
  }
  if (!token) { await report("token", { message: "empty token" }); throw new Error("Could not register this device for notifications. Please try again."); }
  await setDoc(doc(db, "push_tokens", token), { token, uid: myUid(), email: getSession()?.email ?? null, created_at: Date.now(), ua: navigator.userAgent.slice(0, 160), app: inAndroidApp() ? "android-app" : "browser" });
  try { localStorage.setItem(LS_TOKEN, token); } catch { /* ignore */ }
  try { await setDoc(doc(db, "user_state", myUid()), { push_error: null, push_ok_at: Date.now() }, { merge: true }); } catch { /* ignore */ }
  return "Done: this device will get alert notifications, also when the app is closed.";
}

export async function disable() {
  const t = savedToken();
  if (t) {
    await deleteDoc(doc(db, "push_tokens", t)).catch(() => {});
    try {
      const { getMessaging, deleteToken } = await import("firebase/messaging");
      await deleteToken(getMessaging(app));
    } catch { /* ignore */ }
  }
  try { localStorage.removeItem(LS_TOKEN); } catch { /* ignore */ }
}

/** System notification from the open app (used when push is not set up and the app is in the background). */
export async function localNotify(title: string, body: string, url = "/alerts") {
  if (permission() !== "granted" || savedToken()) return;        // push devices get it from the engine instead
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) await reg.showNotification(title, { body, icon: "/icons/icon-192.png", badge: "/icons/icon-192.png", data: { url } });
    else new Notification(title, { body, icon: "/icons/icon-192.png" });
  } catch { /* ignore */ }
}
