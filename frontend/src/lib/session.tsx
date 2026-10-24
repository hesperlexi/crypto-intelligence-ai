// Who is signed in and what they may do. Admins are the Google accounts in the ADMIN_EMAILS repository
// variable (enforced by the Firestore rules); everyone else needs an approved users/{uid} record.
import { User } from "firebase/auth";
import { doc, getDoc, onSnapshot, setDoc } from "firebase/firestore";
import { createContext, useContext } from "react";
import { db } from "./firebase";

export type Role = "loading" | "admin" | "member" | "pending" | "expired" | "blocked";
export interface Session { uid: string; email: string; name: string; role: Role }

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
  probeAdmin().then((admin) => {
    if (!alive) return;
    if (admin) { cb("admin"); return; }
    const ref = doc(db, "users", user.uid);
    stop = onSnapshot(ref, (s) => {
      const d = s.data();
      if (!d) {
        setDoc(ref, { uid: user.uid, email: user.email, name: user.displayName ?? "", photo: user.photoURL ?? "",
          status: "pending", requested_at: Date.now() }).catch(() => cb("blocked"));
        cb("pending");
        return;
      }
      last = d;
      cb(roleOf(d));
    }, () => cb("blocked"));
    // memberships end while the app is open too
    timer = setInterval(() => { if (last) cb(roleOf(last)); }, 60_000);
  });
  return () => { alive = false; stop(); if (timer) clearInterval(timer); };
}
