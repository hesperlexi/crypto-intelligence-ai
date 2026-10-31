import { BRAND } from "./brand";
// Paid memberships: a member pays with Binance Pay, uploads the proof, and the owner approves it for a number
// of months. Prices live in config/membership (editable on the Users page); these are the defaults.
import { arrayUnion, doc, getDoc, onSnapshot, setDoc, updateDoc, writeBatch } from "firebase/firestore";
import { isProofImage, paymentProof, proofImageDoc } from "./writeShapes";
import { useEffect, useState } from "react";
import { db } from "./firebase";
import { getSession } from "./session";

export interface Plan { months: number; price: number; label: string }
export interface MembershipConfig { plans: Plan[]; currency: string; pay_note: string; qr_url: string; mexc_uid: string; support_email: string }

export const DEFAULT_CONFIG: MembershipConfig = {
  plans: [
    { months: 1, price: 15, label: "1 month" },
    { months: 3, price: 40, label: "3 months" },
    { months: 6, price: 70, label: "6 months" },
    { months: 12, price: 130, label: "1 year" },
  ],
  currency: "USDT",
  pay_note: "Pay with the Binance app: scan the QR code, send the exact amount, then upload the payment screenshot here.",
  qr_url: "/pay/binance-qr.png",
  mexc_uid: "00183657",
  support_email: BRAND.supportEmail,
};

export const DAY = 86_400_000;
export const planLabel = (m: number) => (m === 12 ? "1 year" : m === 1 ? "1 month" : `${m} months`);
export const fmtDate = (ms?: number | null) => (ms ? new Date(ms).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—");
export const daysLeft = (ms?: number | null) => (ms ? Math.ceil((ms - Date.now()) / DAY) : null);

/** Calendar months from a start time (e.g. 31 Jan + 1 month = 28/29 Feb). */
export function addMonths(from: number, months: number): number {
  const d = new Date(from);
  const day = d.getDate();
  d.setDate(1);
  d.setMonth(d.getMonth() + months);
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
  d.setDate(Math.min(day, last));
  return d.getTime();
}

export function useMembershipConfig(): MembershipConfig {
  const [c, setC] = useState<MembershipConfig>(DEFAULT_CONFIG);
  useEffect(() => onSnapshot(doc(db, "config", "membership"), (s) => {
    const d = s.data();
    if (!d) return setC(DEFAULT_CONFIG);
    const plans = Array.isArray(d.plans) && d.plans.length ? d.plans.map((p: any) => ({ months: Number(p.months), price: Number(p.price), label: p.label || planLabel(Number(p.months)) })) : DEFAULT_CONFIG.plans;
    setC({ ...DEFAULT_CONFIG, ...d, plans });
  }, () => setC(DEFAULT_CONFIG)), []);
  return c;
}

export async function saveMembershipConfig(c: MembershipConfig) {
  await setDoc(doc(db, "config", "membership"), { ...c, updated_at: Date.now() });
}

/** The signed-in person's own users/{uid} record (live). */
export function useMyRecord(): any | null | undefined {
  const uid = getSession()?.uid;
  const [r, setR] = useState<any | null | undefined>(undefined);
  useEffect(() => (uid ? onSnapshot(doc(db, "users", uid), (s) => setR(s.data() ?? null), () => setR(null)) : undefined), [uid]);
  return r;
}

/** Shrinks a screenshot to a JPEG data URL that fits comfortably in a Firestore document (< ~600 KB). */
export async function compressImage(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) throw new Error("Please choose an image (a screenshot of the payment).");
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise<HTMLImageElement>((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => bad(new Error("could not read that image")); i.src = url; });
    for (const [max, q] of [[1400, 0.72], [1100, 0.62], [850, 0.55], [650, 0.5]] as const) {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
      const out = c.toDataURL("image/jpeg", q);
      if (out.length < 600_000) return out;
    }
    throw new Error("That image is too large. Crop the screenshot to the payment details and try again.");
  } finally { URL.revokeObjectURL(url); }
}

/** Member: send payment proof for a plan. Creates the access request if it does not exist yet. */
export type PayMethod = "binance" | "mexc";

export async function submitPayment(plan: Plan, txid: string, proof: string | null, currency: string, method: PayMethod = "binance") {
  const s = getSession();
  if (!s) throw new Error("not signed in");
  const t = txid.trim();
  if (!proof && t.length < 6) throw new Error(`Add the payment screenshot or the ${method === "mexc" ? "MEXC" : "Binance"} order / transaction ID.`);
  if (proof && !isProofImage(proof)) throw new Error("That image could not be read. Please choose a PNG or JPG screenshot.");
  const now = Date.now();
  const payment = paymentProof({ method, months: plan.months, amount: plan.price, currency, txid: t || null, proof: proof || null }, now);
  const ref = doc(db, "users", s.uid);
  const cur = await getDoc(ref);
  // one batch: the screenshot in payment_proofs/{uid}, the payment details (without the image) in users/{uid}
  const b = writeBatch(db);
  if (proof) b.set(doc(db, "payment_proofs", s.uid), proofImageDoc(s.uid, proof, now));
  if (!cur.exists()) b.set(ref, { uid: s.uid, email: s.email, name: s.name, photo: "", status: "pending", requested_at: now, payment });
  else b.update(ref, { payment });
  await b.commit();
}

/** Admin: accept a payment (or grant time without one). Extends from the current end date if still active. */
/** free = complimentary (testers, friends): recorded as 0 USDT and marked free, so it never counts as income. */
export async function grantMembership(uid: string, u: any, months: number, price: number | null, free = false) {
  const now = Date.now();
  const base = u?.status === "approved" && u?.expires_at && u.expires_at > now ? u.expires_at : now;
  const expires_at = addMonths(base, months);
  const p = u?.payment;
  const entry = { months, amount: free ? 0 : price, free, txid: free ? null : p?.txid ?? null, paid_submitted_at: p?.submitted_at ?? null, granted_at: now,
    granted_by: getSession()?.email ?? null, from: base, to: expires_at };
  await updateDoc(doc(db, "users", uid), {
    status: "approved", expires_at, plan_months: months, approved_at: u?.approved_at ?? now, approved_by: getSession()?.email ?? null,
    free,
    ...(p && p.status === "submitted" && !free ? { payment: { ...p, status: "accepted", decided_at: now } } : {}),
    history: arrayUnion(entry),
  });
  return expires_at;
}

/** Mark someone as a free (test) member: their recorded payments become 0 USDT, the original amount is kept as
 *  was_amount for reference, and their membership dates do not change. */
export async function markFree(uid: string, u: any) {
  const history = (u?.history ?? []).map((h: any) => (h.free ? h : { ...h, was_amount: h.amount ?? null, amount: 0, free: true }));
  await updateDoc(doc(db, "users", uid), { free: true, history, changed_at: Date.now() });
}

export async function rejectPayment(uid: string, u: any, reason: string) {
  await updateDoc(doc(db, "users", uid), { payment: { ...u.payment, status: "rejected", reason: reason || null, decided_at: Date.now() } });
}

/** mailto: link to the app owner, with the person's account and the page they were on. */
export function supportLink(email: string, subject = "Crypto Intelligence AI: help") {
  const who = getSession()?.email ?? "";
  const body = `Hello,\n\n[Describe the issue here]\n\n---\nAccount: ${who}\nPage: ${typeof location !== "undefined" ? location.pathname : ""}\n`;
  return `mailto:${email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
