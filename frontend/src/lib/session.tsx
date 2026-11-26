// Who is signed in and what they may do. Admins are the accounts in the ADMIN_EMAILS repository variable
// (enforced by the Firestore rules); everyone else needs an approved users/{uid} record.
// Sign-in is Google or email + password (email accounts only once their address is verified).
import { User } from "firebase/auth";
import { doc, getDoc, onSnapshot, setDoc } from "firebase/firestore";
import { createContext, useContext } from "react";
import { db } from "./firebase";
import { markNewAccount, providerOf } from "./account";
import { newUserRecord } from "./writeShapes";
import { clearRef, pendingReferral } from "./referral";

export type Role = "loading" | "admin" | "member" | "pending" | "expired" | "blocked" | "unreachable";
export interface Session { uid: string; email: string; name: string; role: Role; username?: string }

let current: Session | null = null;
export const getSession = () => current;
export const setSession = (s: Session | null) => { current = s; };
export const isAdmin = () => current?.role === "admin";
export const myUid = () => current?.uid ?? "";

export const SessionCtx = createContext<Session | null>(null);
export const useSession = () => useContext(SessionCtx);
export const useIsAdmin = () => useContext(SessionCtx)?.role === "admin";

async function probeAdmin(): Promise<boolean> {
  try { await getDoc(doc(db, "admin", "probe")); return true; } catch { return false; }
}

/** approved + no end date = permanent member (people approved before memberships existed). */
export function roleOf(d: any): Role {
  if (d.status === "blocked") return "blocked";
  if (d.status !== "approved") return "pending";
  return d.expires_at && d.expires_at <= Date.now() ? "expired" : "member";
}

/** Watches the account's role. New non-admin accounts file an access request automatically. */
export function watchRole(user: User, cb: (role: Role) => void): () => void {
  let stop = () => {};
  let alive = true;
  let last: any = null;
  let timer: any = null;
  let creating = false;
  let retry: any = null;
  probeAdmin().then((admin) => {
    if (!alive) return;
    if (admin) { cb("admin"); return; }
    const ref = doc(db, "users", user.uid);
    stop = onSnapshot(ref, (s) => {
      const d = s.data();
      // v2.52 on-device cache: "no record" is only believed from the server (offline, a missing cache entry must never
      // create a new record over the real one)
      if (!d && s.metadata?.fromCache) return;
      if (!d) {
        markNewAccount(user.uid);
        // v2.16: an account opened from an invite link records who invited it (only now, at creation)
        if (!creating) {
          creating = true;
          pendingReferral(user.uid)
            .then((r) => setDoc(ref, newUserRecord(user, providerOf(user), Date.now(), r))
              .catch((e) => (r ? setDoc(ref, newUserRecord(user, providerOf(user), Date.now())) : Promise.reject(e))))
            .then(clearRef)
            .catch(() => { creating = false; cb("unreachable"); });
        }
        cb("pending");
        return;
      }
      last = d;
      cb(roleOf(d));
    }, () => {
      // V3.4: a read the database refused (daily limit, network, anti-bot check) is NOT "no access": say so and retry
      cb("unreachable");
      if (alive && !retry) retry = setTimeout(() => { retry = null; if (alive) { stop(); if (timer) clearInterval(timer); stop = watchRole(user, cb); } }, 20_000);
    });
    // memberships end while the app is open too
    timer = setInterval(() => { if (last) cb(roleOf(last)); }, 60_000);
  });
  return () => { alive = false; stop(); if (timer) clearInterval(timer); if (retry) clearTimeout(retry); };
}
