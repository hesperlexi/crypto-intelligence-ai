// Paid memberships: a member pays with Binance Pay, uploads the proof, and the owner approves it for a number
// of months. Prices live in config/membership (editable on the Users page); these are the defaults.
import { arrayUnion, doc, getDoc, onSnapshot, setDoc, updateDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { db } from "./firebase";
import { getSession } from "./session";

export interface Plan { months: number; price: number; label: string }
export interface MembershipConfig { plans: Plan[]; currency: string; pay_note: string; qr_url: string }

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
export async function submitPayment(plan: Plan, txid: string, proof: string | null, currency: string) {
  const s = getSession();
  if (!s) throw new Error("not signed in");
  const t = txid.trim();
  if (!proof && t.length < 6) throw new Error("Add the payment screenshot or the Binance order / transaction ID.");
  const payment = { months: plan.months, amount: plan.price, currency, txid: t || null, proof: proof || null,
    status: "submitted", submitted_at: Date.now() };
  const ref = doc(db, "users", s.uid);
  const cur = await getDoc(ref);
  if (!cur.exists()) {
    await setDoc(ref, { uid: s.uid, email: s.email, name: s.name, photo: "", status: "pending", requested_at: Date.now(), payment });
  } else {
    await updateDoc(ref, { payment });
  }
}

/** Admin: accept a payment (or grant time without one). Extends from the current end date if still active. */
export async function grantMembership(uid: string, u: any, months: number, price: number | null) {
  const now = Date.now();
  const base = u?.status === "approved" && u?.expires_at && u.expires_at > now ? u.expires_at : now;
  const expires_at = addMonths(base, months);
  const p = u?.payment;
  const entry = { months, amount: price, txid: p?.txid ?? null, paid_submitted_at: p?.submitted_at ?? null, granted_at: now,
    granted_by: getSession()?.email ?? null, from: base, to: expires_at };
  await updateDoc(doc(db, "users", uid), {
    status: "approved", expires_at, plan_months: months, approved_at: u?.approved_at ?? now, approved_by: getSession()?.email ?? null,
    ...(p && p.status === "submitted" ? { payment: { ...p, status: "accepted", decided_at: now } } : {}),
    history: arrayUnion(entry),
  });
  return expires_at;
}

export async function rejectPayment(uid: string, u: any, reason: string) {
  await updateDoc(doc(db, "users", uid), { payment: { ...u.payment, status: "rejected", reason: reason || null, decided_at: Date.now() } });
}
