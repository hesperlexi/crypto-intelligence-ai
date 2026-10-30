// DEV PREVIEW ONLY. Stand-in for "firebase/auth". The preview role comes from ?preview=<role> (kept per tab).
export type User = { uid: string; email: string | null; displayName: string | null; photoURL: string | null };
export class GoogleAuthProvider {}
export const getAuth = () => ({ mock: true });
function current(): User | null {
  const as = sessionStorage.getItem("preview-as") ?? "admin";
  if (as === "signedout") return null;
  const who: Record<string, User> = {
    admin: { uid: "owner", email: "owner@example.com", displayName: "Hesper", photoURL: null },
    member: { uid: "u_member", email: "sara.k@example.com", displayName: "Sara Kim", photoURL: null },
    pending: { uid: "u_new", email: "new.person@example.com", displayName: "New Person", photoURL: null },
  };
  return who[as] ?? who.admin;
}
export function onAuthStateChanged(_a: any, cb: (u: User | null) => void) { const t = setTimeout(() => cb(current()), 20); return () => clearTimeout(t); }
export async function signInWithPopup() { sessionStorage.setItem("preview-as", "member"); location.reload(); }
export async function signOut() { sessionStorage.setItem("preview-as", "signedout"); location.reload(); }
