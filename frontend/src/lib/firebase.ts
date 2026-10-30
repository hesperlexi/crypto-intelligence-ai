import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";
import { getFirestore } from "firebase/firestore";

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
export const db = getFirestore(app);
export const googleProvider = new GoogleAuthProvider();

// Firebase App Check (reCAPTCHA v3): only switched on when a site key is provided at build time
// (VITE_APPCHECK_SITE_KEY). Without it nothing loads and nothing changes. Enforcement is turned on in the
// Firebase console, never here, so the Android app and older clients keep working while tokens are monitored.
const appCheckKey = import.meta.env.VITE_APPCHECK_SITE_KEY as string | undefined;
if (appCheckKey) {
  import("firebase/app-check")
    .then(({ initializeAppCheck, ReCaptchaV3Provider }) => {
      initializeAppCheck(app, { provider: new ReCaptchaV3Provider(appCheckKey), isTokenAutoRefreshEnabled: true });
    })
    .catch(() => {});
}

// Google Analytics for Firebase (page views and basic usage), loaded after start so it never delays the first screen.
import("firebase/analytics")
  .then(({ getAnalytics, isSupported }) => isSupported().then((ok) => { if (ok) getAnalytics(app); }))
  .catch(() => {});
