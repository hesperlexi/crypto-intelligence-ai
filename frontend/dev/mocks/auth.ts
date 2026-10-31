// DEV PREVIEW ONLY. Stand-in for "firebase/auth". The preview role comes from ?preview=<role> (kept per tab):
//   admin | member | pending | signedout | unverified (new email account, inbox screen) | nousername (picker)
// Email sign-up / sign-in in the preview never checks a password: it just switches the preview role.
export type User = { uid: string; email: string | null; displayName: string | null; photoURL: string | null; emailVerified: boolean;
  providerData: { providerId: string }[]; getIdToken: (force?: boolean) => Promise<string> };
export class GoogleAuthProvider {}
export const getAuth = () => ({ mock: true, get currentUser() { return current(); } });
const mk = (uid: string, email: string, name: string | null, provider: "google.com" | "password", verified = true): User =>
  ({ uid, email, displayName: name, photoURL: null, emailVerified: verified, providerData: [{ providerId: provider }], getIdToken: async () => "preview" });
function current(): User | null {
  const as = sessionStorage.getItem("preview-as") ?? "admin";
  if (as === "signedout") return null;
  const who: Record<string, User> = {
    admin: mk("owner", "owner@example.com", "Hesper", "google.com"),
    member: mk("u_member", "sara.k@example.com", "Sara Kim", "google.com"),
    pending: mk("u_new", "new.person@example.com", "New Person", "password"),
    unverified: mk("u_email", "alex@example.com", null, "password", sessionStorage.getItem("preview-verified") === "1"),
    nousername: mk("u_nouser", "jordan@example.com", "Jordan Lee", "password"),
  };
  return who[as] ?? who.admin;
}
export function onAuthStateChanged(_a: any, cb: (u: User | null) => void) { const t = setTimeout(() => cb(current()), 20); return () => clearTimeout(t); }
// switch the preview role and reload (without ?preview=..., which would switch it straight back)
const go = (as: string) => {
  sessionStorage.setItem("preview-as", as);
  const u = new URL(location.href); u.searchParams.delete("preview");
  location.replace(u.toString());
};
export async function signInWithPopup() { go("member"); }
export async function signOut() { sessionStorage.removeItem("preview-verified"); go("signedout"); }
export async function createUserWithEmailAndPassword(_a: any, email: string, _pw: string) {
  if (email.startsWith("taken@")) throw Object.assign(new Error("in use"), { code: "auth/email-already-in-use" });
  setTimeout(() => go("unverified"), 50);
  return { user: current() };
}
export async function signInWithEmailAndPassword(_a: any, email: string, _pw: string) {
  if (!email.startsWith("sara")) throw Object.assign(new Error("bad"), { code: "auth/invalid-credential" });
  go("member");
}
export async function sendEmailVerification() {}
export async function sendPasswordResetEmail() {}
/** "I've verified": in the preview the second check succeeds. */
export async function reload(_u: User) {
  const n = Number(sessionStorage.getItem("preview-checks") ?? 0) + 1;
  sessionStorage.setItem("preview-checks", String(n));
  if (n >= 2) { sessionStorage.setItem("preview-verified", "1"); (_u as any).emailVerified = true; }
}
