// Phone / desktop notifications for alerts.
//
// * While the app is open but in the background, new alerts are shown as system notifications directly.
// * When the app is closed, the engine sends web-push messages through Firebase Cloud Messaging to every device
//   that turned notifications on. That needs the project's public "Web Push certificate" key (VAPID), which is
//   created once in the Firebase console and pasted into Settings → Notifications (stored in config/push).
import { deleteDoc, doc, getDoc, setDoc } from "firebase/firestore";
import { app, db } from "./firebase";
import { getSession, myUid } from "./session";

const LS_TOKEN = "cia-push-token";

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
    throw new Error(ios ? "On iPhone / iPad, first add the app to your Home Screen (Safari → Share → Add to Home Screen), open it from there, then turn notifications on." : "This browser does not support notifications.");
  }
  const perm = await Notification.requestPermission();
  if (perm !== "granted") throw new Error("Notifications are blocked for this site. Allow them in the browser / phone settings, then try again.");
  const key = await vapidKey();
  if (!key) return "Notifications are on while the app is open. To get them when the app is closed, add the Web Push key below.";
  const reg = await navigator.serviceWorker.ready;
  const { getMessaging, getToken, isSupported } = await import("firebase/messaging");
  if (!(await isSupported())) return "Notifications are on while the app is open (this browser cannot receive push when closed).";
  const token = await getToken(getMessaging(app), { vapidKey: key, serviceWorkerRegistration: reg });
  if (!token) throw new Error("could not register this device for push");
  await setDoc(doc(db, "push_tokens", token), { token, uid: myUid(), email: getSession()?.email ?? null, created_at: Date.now(), ua: navigator.userAgent.slice(0, 160) });
  try { localStorage.setItem(LS_TOKEN, token); } catch { /* ignore */ }
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
