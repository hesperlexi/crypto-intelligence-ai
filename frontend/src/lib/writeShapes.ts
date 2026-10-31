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
/** post_meta/{uid}: time of the person's latest post (the rules allow one post per 30 s). */
export const postMeta = (now: number) => ({ last: now });

/** users/{uid}.payment: a membership payment proof (lib/membership.ts). */
export const paymentProof = (p: { method: string; months: number; amount: number; currency: string; txid: string | null; proof: string | null }, now: number) =>
  ({ method: p.method, months: p.months, amount: p.amount, currency: p.currency, txid: p.txid, proof: p.proof, status: "submitted", submitted_at: now });
