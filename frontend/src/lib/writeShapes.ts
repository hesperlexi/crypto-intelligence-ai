// The exact documents the website writes to Firestore for accounts, usernames, Community and payments.
// One place, no imports: the app builds its writes with these, and the rules tests (tests/rules) import the
// same functions, so the tests always check the real write shapes against firestore.rules.

export type Provider = "google" | "password";

/** users/{uid}: the access request filed automatically on first sign-in (lib/session.tsx). */
export const newUserRecord = (u: { uid: string; email: string | null; displayName: string | null; photoURL: string | null }, provider: Provider, now: number) =>
  ({ uid: u.uid, email: u.email, name: u.displayName ?? "", photo: u.photoURL ?? "", provider, status: "pending", requested_at: now });

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

/** A payment screenshot the app may show: only an image data URL (PNG, JPEG or WebP). Same pattern as the rules. */
export const PROOF_IMAGE_RE = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;
export const isProofImage = (s: unknown): s is string => typeof s === "string" && s.length < 900_000 && PROOF_IMAGE_RE.test(s);
