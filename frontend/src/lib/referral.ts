// v2.16 referral programme. A member shares https://cryptointelai.com/?ref=<code>; the code is remembered on this device
// (30 days) and stored as users/{uid}.referred_by when the new account's record is created (lib/session.tsx). When the
// admin approves that friend's first paid payment, the member gets 1 free month (lib/membership.ts grantMembership).
import { doc, getDoc, writeBatch } from "firebase/firestore";
import { db } from "./firebase";
import { REF_CODE_RE, refCodeDoc, refCodeOnUser } from "./writeShapes";

const KEY = "cia-ref";
const KEEP_MS = 30 * 86_400_000;
export const SHARE_HOST = "https://cryptointelai.com";
export const inviteLink = (code: string) => `${SHARE_HOST}/?ref=${code}`;

/** Remembers ?ref=<code> from the address and removes it from the address bar. Runs once when this module loads. */
export function captureRef(loc: Location | null = typeof location !== "undefined" ? location : null) {
  if (!loc) return;
  try {
    const u = new URL(loc.href);
    const code = (u.searchParams.get("ref") ?? "").trim().toLowerCase();
    if (!u.searchParams.has("ref")) return;
    if (REF_CODE_RE.test(code)) localStorage.setItem(KEY, JSON.stringify({ code, at: Date.now() }));
    u.searchParams.delete("ref");
    history.replaceState(history.state, "", u.pathname + (u.search ? u.search : "") + u.hash);
  } catch { /* storage blocked: no referral */ }
}
captureRef();

export function storedRef(): string | null {
  try {
    const r = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return r && REF_CODE_RE.test(r.code) && Date.now() - Number(r.at) < KEEP_MS ? r.code : null;
  } catch { return null; }
}
export const clearRef = () => { try { localStorage.removeItem(KEY); } catch { /* ignore */ } };

/** The referrer of a brand-new account (one read of ref_codes/{code}), or null (no link, unknown code, own code). */
export async function pendingReferral(myUid: string): Promise<{ uid: string; code: string } | null> {
  const code = storedRef();
  if (!code) return null;
  try {
    const s = await getDoc(doc(db, "ref_codes", code));
    const uid = s.exists() ? (s.data() as any)?.uid : null;
    return typeof uid === "string" && uid && uid !== myUid ? { uid, code } : null;
  } catch { return null; }
}

const ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789";      // no 0/o, 1/l
export const newCode = () => Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => ALPHABET[b % ALPHABET.length]).join("");

/** Member: create my code (once). Two writes, one batch; the rules allow it only once per member. */
export async function createMyCode(uid: string): Promise<string> {
  for (let i = 0; i < 3; i++) {
    const code = newCode();
    if ((await getDoc(doc(db, "ref_codes", code))).exists()) continue;     // taken (very unlikely): try another
    const b = writeBatch(db);
    const now = Date.now();
    b.set(doc(db, "ref_codes", code), refCodeDoc(uid, now));
    b.update(doc(db, "users", uid), refCodeOnUser(code));
    await b.commit();
    return code;
  }
  throw new Error("Could not make a code just now. Please try again.");
}
