// The exact documents the website writes to Firestore for accounts, usernames, Community and payments.
// One place, no imports: the app builds its writes with these, and the rules tests (tests/rules) import the
// same functions, so the tests always check the real write shapes against firestore.rules.

export type Provider = "google" | "password";

/** users/{uid}: the access request filed automatically on first sign-in (lib/session.tsx). */
export const newUserRecord = (u: { uid: string; email: string | null; displayName: string | null; photoURL: string | null }, provider: Provider, now: number,
  ref?: { uid: string; code: string } | null) =>
  ({ uid: u.uid, email: u.email, name: u.displayName ?? "", photo: u.photoURL ?? "", provider, status: "pending", requested_at: now,
    ...(ref && ref.uid !== u.uid ? referralFields(ref.uid, ref.code) : {}) });

/* ---------------------------------------------------------------- referrals, v2.16
 * A member's code: ref_codes/{code} {uid, created_at} + users/{uid}.ref_code, one batch, write-once (rules).
 * A new account opened from ?ref=<code> stores referred_by (the referrer's uid) + ref_via (the code) in the record it
 * CREATES; the rules check the code belongs to that uid and that it is not the person themselves. */
export const REF_CODE_RE = /^[a-z0-9]{8}$/;
export const refCodeDoc = (uid: string, now: number) => ({ uid, created_at: now });
export const refCodeOnUser = (code: string) => ({ ref_code: code });
export const referralFields = (referrerUid: string, code: string) => ({ referred_by: referrerUid, ref_via: code });

/** Free months (referral reward, leaderboard prize): never income - amount 0, free, with what it was for. */
export type FreeMonthKind = "referral" | "prize";
export const isRewardEntry = (h: any) => h?.kind === "referral" || h?.kind === "prize";
/** Whether this approval is the person's first PAID one (> 0 USDT, not free; reward months do not count as payments). */
export const isFirstPaid = (u: any, price: number | null, free: boolean) =>
  !free && Number(price) > 0 && !(u?.history ?? []).some((h: any) => !isRewardEntry(h) && !h?.free && Number(h?.amount) > 0);
/** The referrer's reward is due: a referred friend's first paid approval, once per friend, never yourself. */
export const referralDue = (friendUid: string, friend: any, price: number | null, free: boolean) =>
  typeof friend?.referred_by === "string" && !!friend.referred_by && friend.referred_by !== friendUid && !friend.referral_reward && isFirstPaid(friend, price, free);
/** One free month for `u` (approved members only; expired ones restart from now). null = not eligible (blocked, pending,
 *  rejected or no record). A member with no end date keeps it (nothing to extend; the month is still recorded). */
export function freeMonth(u: any, now: number, by: string | null, kind: FreeMonthKind, meta: Record<string, any>, addMonths: (from: number, m: number) => number) {
  if (!u || u.status !== "approved") return null;
  const permanent = !u.expires_at;
  const from = !permanent && u.expires_at > now ? u.expires_at : now;
  const to = permanent ? null : addMonths(from, 1);
  const entry = { months: 1, amount: 0, free: true, kind, ...meta, granted_at: now, granted_by: by, from, to };
  return { entry, fields: permanent ? {} : { expires_at: to } };
}
/** owner/leaderboard: prizes given (one per month and winner) and members kept out of the ranking. */
export const prizeAwarded = (month: string, uid: string, now: number, by: string | null) => ({ awarded: { [month]: { [uid]: { at: now, by } } } });
export const BADGE_PREFIX = "lb:";

/** usernames/{name}: who owns a username. Written in one batch with usernameOnUser / ownerProfile. */
export const usernameClaim = (uid: string, now: number) => ({ uid, created_at: now });
/** users/{uid} update: the username, set once. */
export const usernameOnUser = (name: string) => ({ username: name });
/** owner/profile (merge): the owner's username (the owner has no users/{uid} record). */
export const ownerProfile = (uid: string, name: string) => ({ username: name, uid });

/** posts/{id}: one Community post. */
export const postDoc = (uid: string, username: string, text: string, now: number, admin: boolean) =>
  ({ author_uid: uid, username, text, created_at: now, ...(admin ? { admin: true } : {}) });
/** posts/{id}: the id of a post is <uid>_<created_at> (the rules require it, so one batch cannot add two posts). */
export const postId = (uid: string, now: number) => `${uid}_${now}`;
/** post_meta/{uid}: time of the person's latest post (the rules allow one post per 30 s). */
export const postMeta = (now: number) => ({ last: now });

/** users/{uid}.payment: a membership payment proof (lib/membership.ts). The screenshot itself goes to
 *  payment_proofs/{uid} (proofImageDoc); the payment keeps proof: null and has_proof: true. Older records may still
 *  carry the image inline in payment.proof (still accepted by the rules and shown on the Users page). */
export const paymentProof = (p: { method: string; months: number; amount: number; currency: string; txid: string | null; proof: string | null }, now: number) =>
  ({ method: p.method, months: p.months, amount: p.amount, currency: p.currency, txid: p.txid, proof: null, has_proof: !!p.proof, status: "submitted", submitted_at: now });
/** payment_proofs/{uid}: the payment screenshot (an image data URL), written together with paymentProof. */
export const proofImageDoc = (uid: string, proof: string, now: number) => ({ uid, proof, submitted_at: now });
/** Admin: the payment with its screenshot removed (legacy inline image cleared; has_proof false; when it was removed). */
export const paymentWithoutProof = (payment: any, now: number) => ({ ...payment, proof: null, has_proof: false, proof_deleted_at: now });

/** A payment screenshot the app may show: only an image data URL (PNG, JPEG or WebP). Same pattern as the rules. */
export const PROOF_IMAGE_RE = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;
export const isProofImage = (s: unknown): s is string => typeof s === "string" && s.length < 900_000 && PROOF_IMAGE_RE.test(s);

/* ---------------------------------------------------------------- practice (paper) accounts, v2.14
 * New accounts start with $1,000 virtual USDT. "Add funds" adds virtual USDT and records it as a deposit, so
 * P&L = equity − total deposited and the return is measured on what was deposited (never inflated by top-ups).
 * The rules (paper/{uid}_spot|_futures) check: deposited only goes up, by a positive amount, at most $1,000,000 in
 * total, the balance grows by exactly the deposit, and deposit_count goes up by one. */
export const PAPER_START = 1_000;
export const PAPER_MAX_DEPOSITED = 1_000_000;
export const PAPER_DEPOSITS_KEPT = 50;
export type PaperMarket = "spot" | "futures";
/** Total virtual USDT put in so far (older accounts without the field: their starting balance). */
export const depositedOf = (acc: any): number => (typeof acc?.deposited === "number" ? acc.deposited : Number(acc?.starting_balance ?? 0));
/** The balance field of each account kind (spot: cash, futures: wallet). */
export const fundsOf = (acc: any, market: PaperMarket): number => Number(market === "futures" ? acc?.wallet ?? 0 : acc?.cash ?? 0);
/** Largest top-up still allowed on this account. */
export const maxTopUp = (acc: any) => Math.max(0, PAPER_MAX_DEPOSITED - depositedOf(acc));
/** Fields of a brand-new (or reset) practice account. */
export const newPaperFields = (balance: number = PAPER_START) => ({ starting_balance: balance, deposited: balance, deposit_count: 0, deposits: [] as any[] });
/** The update for "Add funds": the balance, deposited, deposit_count and the deposit history (last 50 kept). */
export function paperTopUp(acc: any, amount: number, market: PaperMarket, now: number) {
  const amt = Math.round(Number(amount) * 100) / 100;
  if (!(amt > 0)) throw new Error("enter a positive amount");
  if (amt > maxTopUp(acc) + 1e-9) throw new Error(`the most a practice account can hold in deposits is $${PAPER_MAX_DEPOSITED.toLocaleString("en-US")} (you can add $${maxTopUp(acc).toLocaleString("en-US")} more)`);
  const deposited = Math.round((depositedOf(acc) + amt) * 100) / 100;
  const deposits = [...(Array.isArray(acc?.deposits) ? acc.deposits : []), { amount: amt, at: now }].slice(-PAPER_DEPOSITS_KEPT);
  return { [market === "futures" ? "wallet" : "cash"]: fundsOf(acc, market) + amt, deposited, deposit_count: Number(acc?.deposit_count ?? 0) + 1, deposits };
}
