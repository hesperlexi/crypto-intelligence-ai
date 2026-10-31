// Email + password accounts (next to Google sign-in) and usernames.
// Passwords go straight to Firebase Authentication: they are never logged, stored or sent anywhere else.
import {
  createUserWithEmailAndPassword, reload, sendEmailVerification, sendPasswordResetEmail, signInWithEmailAndPassword, User,
} from "firebase/auth";
import { doc, getDoc, onSnapshot, writeBatch } from "firebase/firestore";
import { useEffect, useState } from "react";
import { auth, db } from "./firebase";
import { ownerProfile, usernameClaim, usernameOnUser } from "./writeShapes";

export const MIN_PASSWORD = 8;
export const RESEND_WAIT_S = 60;

/** "password" for email accounts, "google" otherwise (every account before 31 Oct 2026 was Google). */
export function providerOf(u: Pick<User, "providerData"> | null | undefined): "password" | "google" {
  const ids = (u?.providerData ?? []).map((p) => p?.providerId);
  return ids.includes("google.com") || !ids.includes("password") ? "google" : "password";
}
/** Email accounts must confirm their address before they can use the app (the database rules require it too). */
export const needsVerification = (u: User | null | undefined) => !!u && providerOf(u) === "password" && !u.emailVerified;

/** Friendly words for Firebase Authentication error codes. */
export function authMessage(e: any): string {
  const code = String(e?.code ?? "");
  const map: Record<string, string> = {
    "auth/invalid-email": "That email address doesn't look right.",
    "auth/missing-email": "Enter your email address.",
    "auth/missing-password": "Enter your password.",
    "auth/weak-password": `Choose a longer password (at least ${MIN_PASSWORD} characters).`,
    "auth/email-already-in-use": "An account with this email already exists. Sign in instead, or reset the password.",
    "auth/invalid-credential": "Wrong email or password.",
    "auth/invalid-login-credentials": "Wrong email or password.",
    "auth/wrong-password": "Wrong email or password.",
    "auth/user-not-found": "Wrong email or password.",
    "auth/user-disabled": "This account has been turned off. Contact support if you think this is a mistake.",
    "auth/too-many-requests": "Too many attempts. Please wait a few minutes and try again.",
    "auth/network-request-failed": "No connection. Check your internet and try again.",
    "auth/operation-not-allowed": "Email sign-in is not switched on yet. Please use Google for now.",
    "auth/popup-closed-by-user": "The Google window was closed before signing in.",
    "auth/cancelled-popup-request": "The Google window was closed before signing in.",
    "auth/popup-blocked": "Your browser blocked the Google window. Allow pop-ups for this site and try again.",
    "auth/account-exists-with-different-credential": "This email already has an account with another sign-in method. Use that method.",
    "auth/requires-recent-login": "Please sign in again and retry.",
    "auth/too-many-requests-resend": "Too many emails sent. Please wait a few minutes.",
  };
  return map[code] ?? (code ? "Something went wrong. Please try again." : String(e?.message ?? "Something went wrong."));
}

export function checkPassword(pw: string): string | null {
  if (pw.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`;
  if (pw.length > 128) return "That password is too long (128 characters at most).";
  return null;
}

/** Where the verification / reset links send people back to. */
const continueUrl = () => ({ url: `${location.origin}/`, handleCodeInApp: false });

export async function signUp(email: string, password: string) {
  const bad = checkPassword(password);
  if (bad) throw Object.assign(new Error(bad), { code: "" });
  const cred = await createUserWithEmailAndPassword(auth, email.trim(), password);
  try { await sendEmailVerification(cred.user, continueUrl()); } catch { /* the inbox screen offers "Resend" */ }
  markSent();
  return cred.user;
}
export const signInEmail = (email: string, password: string) => signInWithEmailAndPassword(auth, email.trim(), password);
export const resetPassword = (email: string) => sendPasswordResetEmail(auth, email.trim(), continueUrl());

const SENT_KEY = "verify-sent-at";
function markSent() { try { sessionStorage.setItem(SENT_KEY, String(Date.now())); } catch { /* private mode */ } }
/** Seconds until another verification email may be sent (client-side limit). */
export function resendWait(): number {
  try { const t = Number(sessionStorage.getItem(SENT_KEY) ?? 0); return Math.max(0, Math.ceil((t + RESEND_WAIT_S * 1000 - Date.now()) / 1000)); } catch { return 0; }
}
export async function resendVerification(u: User) {
  if (resendWait() > 0) throw Object.assign(new Error(`Please wait ${resendWait()} s before sending another email.`), { code: "" });
  markSent();
  await sendEmailVerification(u, continueUrl());
}
/** After the person clicked the link: reload the account and get a fresh token (so the rules see email_verified). */
export async function refreshVerified(u: User): Promise<boolean> {
  await reload(u);
  const cur = auth.currentUser ?? u;
  if (cur.emailVerified) await cur.getIdToken(true);
  return cur.emailVerified;
}

/* ---------------------------------------------------------------- usernames */
// Kept in step with validUsername() in firestore.rules.template.
export const RESERVED = ["admin", "administrator", "support", "crypto", "cryptointelai", "cryptointel", "hesper", "moderator", "mod", "root", "system",
  "owner", "staff", "team", "official", "help", "security", "null", "undefined", "anonymous", "everyone"];
const RESERVED_PARTS = ["admin", "support", "moderator", "cryptointel"];

export function usernameProblem(raw: string, admin = false): string | null {
  const n = raw.trim().toLowerCase();
  if (n.length < 3) return "At least 3 characters.";
  if (n.length > 20) return "At most 20 characters.";
  if (!/^[a-z0-9_]+$/.test(n)) return "Only letters a-z, numbers and _ (no spaces).";
  if (!admin && (RESERVED.includes(n) || RESERVED_PARTS.some((p) => n.includes(p)))) return "That name is reserved. Please choose another.";
  return null;
}

export async function usernameTaken(n: string): Promise<boolean> {
  return (await getDoc(doc(db, "usernames", n.toLowerCase()))).exists();
}

/** Claims the name and writes it on the account in one batch (the rules check both halves together).
 *  Members: users/{uid}.username. The owner has no access-request record: owner/profile.username. */
export async function claimUsername(user: User, raw: string, opts: { admin: boolean }) {
  const n = raw.trim().toLowerCase();
  const bad = usernameProblem(n, opts.admin);
  if (bad) throw new Error(bad);
  if (await usernameTaken(n)) throw new Error("That username is taken. Please choose another.");
  const b = writeBatch(db);
  b.set(doc(db, "usernames", n), usernameClaim(user.uid, Date.now()));
  if (opts.admin) b.set(doc(db, "owner", "profile"), ownerProfile(user.uid, n), { merge: true });
  else b.update(doc(db, "users", user.uid), usernameOnUser(n));
  try { await b.commit(); } catch (e: any) {
    throw new Error(/permission|denied/i.test(String(e?.code ?? e?.message)) ? "That username was just taken or is not allowed. Please choose another." : "Could not save the username. Please try again.");
  }
  return n;
}

/** The signed-in person's username: undefined while loading, null when none is chosen yet. */
export function useMyUsername(uid: string | null | undefined, admin: boolean): string | null | undefined {
  const [n, setN] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    setN(undefined);
    if (!uid) return;
    return onSnapshot(admin ? doc(db, "owner", "profile") : doc(db, "users", uid), (s) => setN(s.data()?.username ?? null), () => setN(null));
  }, [uid, admin]);
  return n;
}

/** The signed-in person's users/{uid} record: undefined while loading, null when there is none. */
export function useAccountRecord(uid: string | null | undefined): any | null | undefined {
  const [r, setR] = useState<any | null | undefined>(undefined);
  useEffect(() => {
    setR(undefined);
    return uid ? onSnapshot(doc(db, "users", uid), (s) => setR(s.data() ?? null), () => setR(null)) : undefined;
  }, [uid]);
  return r;
}

/* ---------------------------------------------------------------- the one-time username prompt */
// Shown only to accounts created on this device (watchRole marks them) and only until answered ("Later" or saved).
// Existing members are never stopped by it; they choose a username when they first post in Community.
const askKey = (uid: string) => `ask-username-${uid}`;
export function markNewAccount(uid: string) { try { localStorage.setItem(askKey(uid), "1"); } catch { /* ignore */ } }
export function shouldAskUsername(uid: string): boolean { try { return localStorage.getItem(askKey(uid)) === "1"; } catch { return false; } }
export function answeredUsername(uid: string) { try { localStorage.removeItem(askKey(uid)); } catch { /* ignore */ } }
