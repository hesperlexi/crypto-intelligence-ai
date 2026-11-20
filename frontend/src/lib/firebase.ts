import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { clearIndexedDbPersistence, Firestore, getFirestore, initializeFirestore, persistentLocalCache, persistentMultipleTabManager, terminate } from "firebase/firestore";

// Firebase web config is public by design: access is controlled by Firestore security rules + sign-in.
export const firebaseConfig = {
  apiKey: "AIzaSyDvkVKbk2S_gpKfJUWakqBiM7S6I3hE7vM",
  authDomain: "crypapp-6a9b9.firebaseapp.com",
  projectId: "crypapp-6a9b9",
  storageBucket: "crypapp-6a9b9.firebasestorage.app",
  messagingSenderId: "276135412044",
  appId: "1:276135412044:web:5fb1e0bca9abc6eb080fe9",
  measurementId: "G-WPTT76MP5F",
};

export const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
// v2.52 (audit, owner 17 Nov 2026): Firebase's free on-device cache. Pages show the last data at once on the next
// visit and reopened listeners only download what changed (fewer free-plan reads). Without IndexedDB (private
// windows, old browsers) the SDK falls back to memory by itself. The cache is wiped on sign-out and when an account
// stops being a member (`dropLocalCache`), so nothing paid-for stays readable on a shared device.
function makeDb(): Firestore {
  try {
    return initializeFirestore(app, { localCache: persistentLocalCache({ tabManager: persistentMultipleTabManager() }) });
  } catch {
    return getFirestore(app);
  }
}
export const db = makeDb();

/** Wipe the on-device cache (the database connection is closed: reload the page afterwards). */
export async function dropLocalCache(): Promise<void> {
  try { await terminate(db); } catch { /* already closed */ }
  try { await clearIndexedDbPersistence(db); } catch { /* another tab still open: cleared on its next sign-out */ }
}
export const googleProvider = new GoogleAuthProvider();

// Firebase App Check (reCAPTCHA v3): only switched on when a site key is provided at build time
// (VITE_APPCHECK_SITE_KEY). Without it nothing loads and nothing changes. Enforcement is turned on in the
// Firebase console, never here, so the Android app and older clients keep working while tokens are monitored.
const appCheckKey = import.meta.env.VITE_APPCHECK_SITE_KEY as string | undefined;
type AC = { getToken: (a: any, force?: boolean) => Promise<{ token: string }>; inst: any };
const appCheckReady: Promise<AC | null> = appCheckKey
  ? import("firebase/app-check")
    .then(({ initializeAppCheck, ReCaptchaV3Provider, getToken }) => ({
      getToken, inst: initializeAppCheck(app, { provider: new ReCaptchaV3Provider(appCheckKey), isTokenAutoRefreshEnabled: true }),
    }))
    .catch(() => null)
  : Promise.resolve(null);
/** v2.61: the App Check token for calls outside the Firebase SDK (the Ask Cintel worker forwards it to Firestore), or null. */
export async function appCheckToken(): Promise<string | null> {
  try { const ac = await appCheckReady; return ac ? (await ac.getToken(ac.inst, false)).token : null; } catch { return null; }
}

// Google Analytics for Firebase (page views and basic usage), loaded after start so it never delays the first screen.
import("firebase/analytics")
  .then(({ getAnalytics, isSupported }) => isSupported().then((ok) => { if (ok) getAnalytics(app); }))
  .catch(() => {});
