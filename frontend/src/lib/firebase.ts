import { getAnalytics, isSupported } from "firebase/analytics";
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

isSupported()
  .then((ok) => {
    if (ok) getAnalytics(app);
  })
  .catch(() => {});
