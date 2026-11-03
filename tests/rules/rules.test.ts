// Firestore security rules tests, run inside the Firestore emulator by .github/workflows/rules-test.yml:
//   firebase emulators:exec --only firestore --project demo-test "npm test"
// The rules file is ./firestore.rules (copied by the workflow from ../../firestore.rules, rendered from firestore.rules.template with ADMIN_EMAILS=admin@example.com).
// Account / username / Community / payment documents are built with the website's own builders
// (frontend/src/lib/writeShapes.ts), so these tests check the exact shapes the app sends.
import { assertFails, assertSucceeds, initializeTestEnvironment, RulesTestEnvironment } from "@firebase/rules-unit-testing";
import { addDoc, collection, deleteDoc, doc, Firestore, setDoc, updateDoc, writeBatch } from "firebase/firestore";
import { readFileSync, writeFileSync } from "node:fs";
import { newPaperFields, newUserRecord, ownerProfile, paperTopUp, paymentProof, paymentWithoutProof, postDoc, postId, postMeta, proofImageDoc, usernameClaim, usernameOnUser } from "../../frontend/src/lib/writeShapes";

const ADMIN = { uid: "owner", email: "admin@example.com" };
const NOW = () => Date.now();
const DAY = 86_400_000;

let env: RulesTestEnvironment;
const results: { name: string; ok: boolean; error?: string }[] = [];

/** A signed-in person: Google by default (email_verified true), or email/password. */
function as(uid: string, email: string, opts: { verified?: boolean; provider?: "google.com" | "password" } = {}): Firestore {
  return env.authenticatedContext(uid, {
    email, email_verified: opts.verified ?? true,
    firebase: { sign_in_provider: opts.provider ?? "google.com" },
  } as any).firestore() as unknown as Firestore;
}
const admin = () => as(ADMIN.uid, ADMIN.email);

/** Seeds documents with rules switched off. */
async function seed(docs: Record<string, any>) {
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const [path, data] of Object.entries(docs)) await setDoc(doc(db as any, path), data);
  });
}
const approved = (uid: string, email: string, extra: any = {}) => ({ uid, email, name: "Member", photo: "", status: "approved", requested_at: NOW() - 30 * DAY, expires_at: NOW() + 30 * DAY, ...extra });
const pending = (uid: string, email: string, extra: any = {}) => ({ uid, email, name: "", photo: "", status: "pending", requested_at: NOW() - DAY, ...extra });

async function test(name: string, fn: () => Promise<unknown>) {
  await env.clearFirestore();
  try { await fn(); results.push({ name, ok: true }); console.log(`PASS  ${name}`); }
  catch (e: any) { results.push({ name, ok: false, error: String(e?.message ?? e).slice(0, 400) }); console.log(`FAIL  ${name}\n      ${String(e?.message ?? e).split("\n")[0]}`); }
}

/** The username batch exactly as lib/account.ts claimUsername sends it. */
function claim(db: Firestore, uid: string, name: string, owner = false) {
  const b = writeBatch(db);
  b.set(doc(db, "usernames", name), usernameClaim(uid, NOW()));
  if (owner) b.set(doc(db, "owner", "profile"), ownerProfile(uid, name), { merge: true });
  else b.update(doc(db, "users", uid), usernameOnUser(name));
  return b.commit();
}
/** The Community post batch exactly as pages/Community.tsx sends it. */
function post(db: Firestore, uid: string, username: string, text: string, opts: { admin?: boolean; at?: number } = {}) {
  const at = opts.at ?? NOW();
  const b = writeBatch(db);
  b.set(doc(db, "posts", postId(uid, at)), postDoc(uid, username, text, at, !!opts.admin));
  b.set(doc(db, "post_meta", uid), postMeta(at));
  return b.commit();
}

async function main() {
  env = await initializeTestEnvironment({ projectId: "demo-test", firestore: { rules: readFileSync(new URL("./firestore.rules", import.meta.url), "utf8"), host: "127.0.0.1", port: 8080 } });

  // ---------------------------------------------------------------- usernames
  await test("existing approved Google member sets a username (users.username + usernames/{name} batch)", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com") });
    await assertSucceeds(claim(as("m1", "m1@example.com"), "m1", "sara_k"));
  });
  await test("second user taking the same username is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com", { username: "sara_k" }), "usernames/sara_k": { uid: "m1", created_at: NOW() },
      "users/m2": approved("m2", "m2@example.com") });
    await assertFails(claim(as("m2", "m2@example.com"), "m2", "sara_k"));
  });
  await test("changing the username later is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com", { username: "sara_k" }), "usernames/sara_k": { uid: "m1", created_at: NOW() } });
    await assertFails(claim(as("m1", "m1@example.com"), "m1", "sara_new"));
  });
  await test("username update alone (without the usernames/{name} claim) is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com") });
    await assertFails(updateDoc(doc(as("m1", "m1@example.com"), "users", "m1"), usernameOnUser("lonely")));
  });
  await test("claiming a name for someone else's account is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com"), "users/m2": approved("m2", "m2@example.com") });
    const db = as("m2", "m2@example.com");
    const b = writeBatch(db);
    b.set(doc(db, "usernames", "stolen"), usernameClaim("m1", NOW()));
    b.update(doc(db, "users", "m1"), usernameOnUser("stolen"));
    await assertFails(b.commit());
  });
  for (const bad of ["admin", "support", "hesper", "cryptointelai", "my_admin_1", "ab", "a".repeat(21), "Upper", "has space", "dash-name", "crypto"]) {
    await test(`reserved / invalid username "${bad}" is denied`, async () => {
      await seed({ "users/m1": approved("m1", "m1@example.com") });
      await assertFails(claim(as("m1", "m1@example.com"), "m1", bad));
    });
  }
  await test("username claim with extra fields is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com") });
    const db = as("m1", "m1@example.com");
    const b = writeBatch(db);
    b.set(doc(db, "usernames", "extra_x"), { ...usernameClaim("m1", NOW()), role: "admin" });
    b.update(doc(db, "users", "m1"), usernameOnUser("extra_x"));
    await assertFails(b.commit());
  });
  await test("owner (admin) sets a username via owner/profile", async () => {
    await assertSucceeds(claim(admin(), ADMIN.uid, "hesper_ai", true));
  });
  await test("member cannot use the owner/profile path", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com") });
    await assertFails(claim(as("m1", "m1@example.com"), "m1", "fake_owner", true));
  });
  await test("usernames: get allowed, list denied, delete by member denied, delete by admin allowed", async () => {
    await seed({ "usernames/sara_k": { uid: "m1", created_at: NOW() }, "users/m1": approved("m1", "m1@example.com", { username: "sara_k" }) });
    const db = as("m2", "m2@example.com");
    const { getDoc, getDocs } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(db, "usernames", "sara_k")));
    await assertFails(getDocs(collection(db, "usernames")));
    await assertFails(deleteDoc(doc(as("m1", "m1@example.com"), "usernames", "sara_k")));
    await assertSucceeds(deleteDoc(doc(admin(), "usernames", "sara_k")));
  });

  // ---------------------------------------------------------------- sign-up / users
  await test("email/password user (verified) creates the pending users doc", async () => {
    const u = { uid: "e1", email: "e1@example.com", displayName: null, photoURL: null };
    await assertSucceeds(setDoc(doc(as("e1", "e1@example.com", { provider: "password" }), "users", "e1"), newUserRecord(u, "password", NOW())));
  });
  await test("email/password user NOT verified cannot create the users doc", async () => {
    const u = { uid: "e2", email: "e2@example.com", displayName: null, photoURL: null };
    await assertFails(setDoc(doc(as("e2", "e2@example.com", { provider: "password", verified: false }), "users", "e2"), newUserRecord(u, "password", NOW())));
  });
  await test("Google user creates the pending users doc", async () => {
    const u = { uid: "g1", email: "g1@example.com", displayName: "G One", photoURL: "https://example.com/p.png" };
    await assertSucceeds(setDoc(doc(as("g1", "g1@example.com"), "users", "g1"), newUserRecord(u, "google", NOW())));
  });
  await test("creating the users doc as approved is denied", async () => {
    await assertFails(setDoc(doc(as("g2", "g2@example.com"), "users", "g2"), { ...newUserRecord({ uid: "g2", email: "g2@example.com", displayName: null, photoURL: null }, "google", NOW()), status: "approved" }));
  });
  await test("creating the users doc with a username (skipping the claim) is denied", async () => {
    await assertFails(setDoc(doc(as("g3", "g3@example.com"), "users", "g3"), { ...newUserRecord({ uid: "g3", email: "g3@example.com", displayName: null, photoURL: null }, "google", NOW()), username: "sneaky" }));
  });
  await test("payment proof update is still allowed", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertSucceeds(updateDoc(doc(as("p1", "p1@example.com"), "users", "p1"), { payment: paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: "B123456", proof: null }, NOW()) }));
  });
  const IMG = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDA==";
  await test("payment with a screenshot: payment_proofs/{uid} + users payment in one batch (lib/membership.ts)", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    const db = as("p1", "p1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(db, "payment_proofs", "p1"), proofImageDoc("p1", IMG, at));
    b.update(doc(db, "users", "p1"), { payment: paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: null, proof: IMG }, at) });
    await assertSucceeds(b.commit());
  });
  await test("first payment from a new account (users create + payment_proofs) is allowed", async () => {
    const db = as("n1", "n1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(db, "payment_proofs", "n1"), proofImageDoc("n1", IMG, at));
    b.set(doc(db, "users", "n1"), { uid: "n1", email: "n1@example.com", name: "", photo: "", status: "pending", requested_at: at,
      payment: paymentProof({ method: "mexc", months: 3, amount: 40, currency: "USDT", txid: "M1234567", proof: IMG }, at) });
    await assertSucceeds(b.commit());
  });
  for (const [label, bad] of [["an HTML data URL", "data:text/html;base64,PHNjcmlwdD4="], ["an SVG image", "data:image/svg+xml;base64,PHN2Zz4="],
    ["a javascript: link", "javascript:alert(1)"], ["a web address", "https://example.com/x.png"], ["base64 with markup", "data:image/png;base64,<script>"]] as const) {
    await test(`payment_proofs with ${label} is denied`, async () => {
      await seed({ "users/p1": pending("p1", "p1@example.com") });
      await assertFails(setDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p1"), proofImageDoc("p1", bad, NOW())));
    });
    await test(`legacy inline users.payment.proof with ${label} is denied`, async () => {
      await seed({ "users/p1": pending("p1", "p1@example.com") });
      const pay = { ...paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: null, proof: null }, NOW()), proof: bad };
      await assertFails(updateDoc(doc(as("p1", "p1@example.com"), "users", "p1"), { payment: pay }));
    });
  }
  await test("legacy inline users.payment.proof with a JPEG data URL is still allowed", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    const pay = { ...paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: null, proof: null }, NOW()), proof: IMG };
    await assertSucceeds(updateDoc(doc(as("p1", "p1@example.com"), "users", "p1"), { payment: pay }));
  });
  await test("a realistic ~600 KB JPEG proof is allowed (pattern check on a large string)", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertSucceeds(setDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p1"), proofImageDoc("p1", "data:image/jpeg;base64," + "/9j/".repeat(150_000), NOW())));
  });
  await test("payment proof image over 900 KB is denied", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertFails(setDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p1"), proofImageDoc("p1", "data:image/png;base64," + "A".repeat(900_000), NOW())));
  });
  await test("payment_proofs of another uid cannot be written", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertFails(setDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p2"), proofImageDoc("p2", IMG, NOW())));
  });
  await test("payment_proofs: own and admin reads allowed, other members denied", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com"), "users/m2": approved("m2", "m2@example.com"), "payment_proofs/p1": proofImageDoc("p1", IMG, NOW()) });
    const { getDoc, getDocs } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p1")));
    await assertSucceeds(getDoc(doc(admin(), "payment_proofs", "p1")));
    await assertFails(getDoc(doc(as("m2", "m2@example.com"), "payment_proofs", "p1")));
    await assertFails(getDocs(collection(as("m2", "m2@example.com"), "payment_proofs")));
  });
  // admin screenshot clean-up (lib/membership.ts: deleteProof, deleteCheckedProofs, accept / reject in one batch)
  await test("admin deletes a screenshot: payment_proofs/{uid} delete + users payment cleared in one batch", async () => {
    const pay = { ...paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: "B123456", proof: IMG }, NOW()), status: "accepted" };
    await seed({ "users/p1": approved("p1", "p1@example.com", { payment: pay }), "payment_proofs/p1": proofImageDoc("p1", IMG, NOW()) });
    const db = admin();
    const b = writeBatch(db);
    b.delete(doc(db, "payment_proofs", "p1"));
    b.update(doc(db, "users", "p1"), { payment: paymentWithoutProof(pay, NOW()) });
    await assertSucceeds(b.commit());
  });
  await test("admin clears a legacy inline screenshot (payment.proof -> null, has_proof false)", async () => {
    const pay = { ...paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: null, proof: null }, NOW()), proof: IMG, status: "rejected" };
    await seed({ "users/p1": pending("p1", "p1@example.com", { payment: pay }) });
    await assertSucceeds(updateDoc(doc(admin(), "users", "p1"), { payment: paymentWithoutProof(pay, NOW()) }));
  });
  await test("admin accepts a payment and deletes its screenshot in the same batch", async () => {
    const pay = paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: null, proof: IMG }, NOW());
    await seed({ "users/p1": pending("p1", "p1@example.com", { payment: pay }), "payment_proofs/p1": proofImageDoc("p1", IMG, NOW()) });
    const db = admin();
    const b = writeBatch(db);
    b.update(doc(db, "users", "p1"), { status: "approved", expires_at: NOW() + 30 * DAY, payment: { ...paymentWithoutProof(pay, NOW()), status: "accepted", decided_at: NOW() } });
    b.delete(doc(db, "payment_proofs", "p1"));
    await assertSucceeds(b.commit());
  });
  await test("members cannot delete screenshots (their own or anyone else's)", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com"), "users/m2": approved("m2", "m2@example.com"),
      "payment_proofs/p1": proofImageDoc("p1", IMG, NOW()) });
    await assertFails(deleteDoc(doc(as("p1", "p1@example.com"), "payment_proofs", "p1")));
    await assertFails(deleteDoc(doc(as("m2", "m2@example.com"), "payment_proofs", "p1")));
  });
  await test("a member cannot mark their own decided payment's screenshot as deleted (only 'submitted' updates)", async () => {
    const pay = { ...paymentProof({ method: "binance", months: 1, amount: 15, currency: "USDT", txid: "B123456", proof: null }, NOW()), status: "accepted" };
    await seed({ "users/p1": approved("p1", "p1@example.com", { payment: pay }) });
    await assertFails(updateDoc(doc(as("p1", "p1@example.com"), "users", "p1"), { payment: paymentWithoutProof(pay, NOW()) }));
  });
  await test("admin badge queries (status == pending, payment.status == submitted) are allowed for the admin only", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com"), "users/m1": approved("m1", "m1@example.com") });
    const { getDocs, query, where } = await import("firebase/firestore");
    await assertSucceeds(getDocs(query(collection(admin(), "users"), where("status", "==", "pending"))));
    await assertSucceeds(getDocs(query(collection(admin(), "users"), where("payment.status", "==", "submitted"))));
    await assertFails(getDocs(query(collection(as("m1", "m1@example.com"), "users"), where("status", "==", "pending"))));
  });
  await test("member editing status is denied", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertFails(updateDoc(doc(as("p1", "p1@example.com"), "users", "p1"), { status: "approved" }));
  });
  await test("member editing expires_at is denied", async () => {
    await seed({ "users/m1": approved("m1", "m1@example.com") });
    await assertFails(updateDoc(doc(as("m1", "m1@example.com"), "users", "m1"), { expires_at: NOW() + 999 * DAY }));
  });
  await test("username together with a status change is denied", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    const db = as("p1", "p1@example.com");
    const b = writeBatch(db);
    b.set(doc(db, "usernames", "p_one"), usernameClaim("p1", NOW()));
    b.update(doc(db, "users", "p1"), { ...usernameOnUser("p_one"), status: "approved" });
    await assertFails(b.commit());
  });
  await test("pending user sets a username (skippable screen for new sign-ups)", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertSucceeds(claim(as("p1", "p1@example.com"), "p1", "p_one"));
  });

  // ---------------------------------------------------------------- Community
  const community = { "users/m1": approved("m1", "m1@example.com", { username: "sara_k" }), "usernames/sara_k": { uid: "m1", created_at: NOW() },
    "users/m2": approved("m2", "m2@example.com", { username: "dreyes" }), "usernames/dreyes": { uid: "m2", created_at: NOW() },
    "users/p1": pending("p1", "p1@example.com", { username: "pend_one" }), "owner/profile": ownerProfile(ADMIN.uid, "hesper_ai") };
  await test("member creates a post", async () => {
    await seed(community);
    await assertSucceeds(post(as("m1", "m1@example.com"), "m1", "sara_k", "Hello everyone"));
  });
  await test("admin creates a post with the admin badge", async () => {
    await seed(community);
    await assertSucceeds(post(admin(), ADMIN.uid, "hesper_ai", "Welcome!", { admin: true }));
  });
  await test("member faking the admin badge is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "sara_k", "I am admin", { admin: true }));
  });
  await test("pending (non-member) post is denied", async () => {
    await seed(community);
    await assertFails(post(as("p1", "p1@example.com"), "p1", "pend_one", "let me in"));
  });
  await test("signed-in stranger without a users doc cannot post", async () => {
    await seed(community);
    await assertFails(post(as("x1", "x1@example.com"), "x1", "nobody", "hi"));
  });
  await test("expired member post is denied", async () => {
    await seed({ ...community, "users/old": approved("old", "old@example.com", { username: "old_one", expires_at: NOW() - DAY }) });
    await assertFails(post(as("old", "old@example.com"), "old", "old_one", "still here?"));
  });
  await test("member without a username cannot post", async () => {
    await seed({ ...community, "users/m3": approved("m3", "m3@example.com") });
    await assertFails(post(as("m3", "m3@example.com"), "m3", "", "no name"));
  });
  await test("post with someone else's username is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "dreyes", "impersonating"));
  });
  await test("post as another author_uid is denied", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const b = writeBatch(db);
    const at = NOW();
    b.set(doc(db, "posts", postId("m1", at)), postDoc("m2", "dreyes", "hi", at, false));
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("post with 0 characters is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "sara_k", ""));
  });
  await test("post with only spaces is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "sara_k", "    "));
  });
  await test("post with 500 characters is allowed", async () => {
    await seed(community);
    await assertSucceeds(post(as("m1", "m1@example.com"), "m1", "sara_k", "x".repeat(500)));
  });
  await test("post with 501 characters is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "sara_k", "x".repeat(501)));
  });
  await test("post with an old created_at is denied", async () => {
    await seed(community);
    await assertFails(post(as("m1", "m1@example.com"), "m1", "sara_k", "from the past", { at: NOW() - 10 * 60_000 }));
  });
  await test("post without the post_meta marker is denied", async () => {
    await seed(community);
    const at = NOW();
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "posts", postId("m1", at)), postDoc("m1", "sara_k", "no marker", at, false)));
  });
  await test("post with extra fields is denied", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(db, "posts", postId("m1", at)), { ...postDoc("m1", "sara_k", "hi", at, false), image: "https://x" });
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("second post within 30 s is denied (post_meta)", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    await assertSucceeds(post(db, "m1", "sara_k", "first"));
    await assertFails(post(db, "m1", "sara_k", "second, too soon", { at: NOW() + 5_000 }));
  });
  await test("two posts in one batch are denied (one post_meta step, post id = uid_created_at)", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(db, "posts", postId("m1", at)), postDoc("m1", "sara_k", "first", at, false));
    b.set(doc(db, "posts", postId("m1", at + 1)), postDoc("m1", "sara_k", "second", at + 1, false));
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("two posts with random ids and the same created_at in one batch are denied", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(collection(db, "posts")), postDoc("m1", "sara_k", "first", at, false));
    b.set(doc(collection(db, "posts")), postDoc("m1", "sara_k", "second", at, false));
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("post whose id is not uid_created_at is denied", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(db, "posts", postId("m2", at)), postDoc("m1", "sara_k", "wrong id", at, false));
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("second post 30 s later is allowed", async () => {
    await seed({ ...community, "post_meta/m1": { last: NOW() - 31_000 } });
    await assertSucceeds(post(as("m1", "m1@example.com"), "m1", "sara_k", "after the wait"));
  });
  await test("editing a post is denied", async () => {
    await seed({ ...community, "posts/a": postDoc("m1", "sara_k", "original", NOW(), false) });
    await assertFails(updateDoc(doc(as("m1", "m1@example.com"), "posts", "a"), { text: "edited" }));
  });
  await test("author deletes own post", async () => {
    await seed({ ...community, "posts/a": postDoc("m1", "sara_k", "mine", NOW(), false) });
    await assertSucceeds(deleteDoc(doc(as("m1", "m1@example.com"), "posts", "a")));
  });
  await test("other member deleting a post is denied", async () => {
    await seed({ ...community, "posts/a": postDoc("m1", "sara_k", "mine", NOW(), false) });
    await assertFails(deleteDoc(doc(as("m2", "m2@example.com"), "posts", "a")));
  });
  await test("admin deletes any post", async () => {
    await seed({ ...community, "posts/a": postDoc("m1", "sara_k", "mine", NOW(), false) });
    await assertSucceeds(deleteDoc(doc(admin(), "posts", "a")));
  });
  await test("posts readable by members and admin, not by pending users", async () => {
    await seed({ ...community, "posts/a": postDoc("m1", "sara_k", "mine", NOW(), false) });
    const { getDoc } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(as("m2", "m2@example.com"), "posts", "a")));
    await assertSucceeds(getDoc(doc(admin(), "posts", "a")));
    await assertFails(getDoc(doc(as("p1", "p1@example.com"), "posts", "a")));
  });

  // ---------------------------------------------------------------- regression: existing writes as before
  const member = { "users/m1": approved("m1", "m1@example.com") };
  await test("presence write (lib/presence.ts shape)", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(as("m1", "m1@example.com"), "presence", "m1"), { last_seen: NOW(), country: "AE", tz: "Asia/Dubai", device: "Android app" }, { merge: true }));
  });
  await test("jobs create: backtest", async () => {
    await seed(member);
    await assertSucceeds(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "backtest", params: { symbol: "BTC/USDT", timeframe: "4h" }, status: "queued", created_at: NOW(), by: "m1@example.com" }));
  });
  await test("jobs create: test_push to own uid", async () => {
    await seed(member);
    await assertSucceeds(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "test_push", params: { uid: "m1" }, status: "queued", created_at: NOW(), by: "m1@example.com" }));
  });
  await test("jobs create with a spoofed by (someone else's address) is denied", async () => {
    await seed(member);
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "backtest", params: { symbol: "BTC/USDT", timeframe: "4h" }, status: "queued", created_at: NOW(), by: "admin@example.com" }));
  });
  await test("jobs create without by is denied", async () => {
    await seed(member);
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "backtest", params: { symbol: "BTC/USDT", timeframe: "4h" }, status: "queued", created_at: NOW() }));
  });
  await test("jobs create: admin-only job type by a member is denied", async () => {
    await seed(member);
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "adjust_signal", params: { signal_id: "x", action: "close", note: "nope" }, status: "queued", created_at: NOW(), by: "m1@example.com" }));
  });
  await test("jobs create: admin queues an admin job signed with its own address", async () => {
    await assertSucceeds(addDoc(collection(admin(), "jobs"), { type: "adjust_signal", params: { signal_id: "x", action: "close", note: "taking profit" }, status: "queued", created_at: NOW(), by: ADMIN.email }));
  });
  await test("jobs read: the creator reads their own job, another member cannot, the admin can", async () => {
    await seed({ ...member, "users/m2": approved("m2", "m2@example.com"),
      "jobs/j1": { type: "backtest", params: {}, status: "done", created_at: NOW(), by: "m1@example.com", json: "{}" } });
    const { getDoc, getDocs } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(as("m1", "m1@example.com"), "jobs", "j1")));
    await assertFails(getDoc(doc(as("m2", "m2@example.com"), "jobs", "j1")));
    await assertFails(getDocs(collection(as("m2", "m2@example.com"), "jobs")));
    await assertSucceeds(getDoc(doc(admin(), "jobs", "j1")));
    await assertSucceeds(getDocs(collection(admin(), "jobs")));
  });
  await test("jobs: queue then watch own job (lib/api.ts queueJob flow)", async () => {
    await seed(member);
    const { getDoc } = await import("firebase/firestore");
    const db = as("m1", "m1@example.com");
    const ref = await addDoc(collection(db, "jobs"), { type: "replay", params: { symbol: "BTC/USDT" }, status: "queued", created_at: NOW(), by: "m1@example.com" });
    await assertSucceeds(getDoc(ref));
  });
  await test("jobs create: test_push to another uid is denied", async () => {
    await seed(member);
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "test_push", params: { uid: "m2" }, status: "queued", created_at: NOW(), by: "m1@example.com" }));
  });
  await test("paper/{uid}_futures write", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(as("m1", "m1@example.com"), "paper", "m1_futures"), { id: "acc1", starting_balance: 10000, wallet: 10000, created_at: NOW(), positions: {}, position_mode: "oneway", totals: { realized: 0, fees: 0, funding: 0, count: 0, wins: 0, liquidations: 0 } }));
  });
  // ---------------------------------------------------------------- v2.14 practice accounts: $1,000 start + "Add funds"
  const futAcc = (extra: any = {}) => ({ id: "acc1", ...newPaperFields(), wallet: 1000, created_at: NOW(), positions: {}, position_mode: "oneway",
    totals: { realized: 0, fees: 0, funding: 0, count: 0, wins: 0, liquidations: 0 }, ...extra });
  const spotAcc = (extra: any = {}) => ({ id: "sp1", ...newPaperFields(), cash: 1000, created_at: NOW(), positions: {}, totals: { realized: 0, fees: 0, slippage: 0, count: 0 }, ...extra });
  await test("paper: a new $1,000 account (futures and spot) is accepted", async () => {
    await seed(member);
    const db = as("m1", "m1@example.com");
    await assertSucceeds(setDoc(doc(db, "paper", "m1_futures"), futAcc()));
    await assertSucceeds(setDoc(doc(db, "paper", "m1_spot"), spotAcc()));
  });
  await test("paper: Add funds (the app's paperTopUp) is accepted, futures and spot, also on an older account", async () => {
    await seed({ ...member, "paper/m1_futures": futAcc({ wallet: 640.5 }), "paper/m1_spot": spotAcc(),
      "paper/m1_old": { id: "old", starting_balance: 10000, wallet: 9500, positions: {} } });
    const db = as("m1", "m1@example.com");
    await assertSucceeds(updateDoc(doc(db, "paper", "m1_futures"), paperTopUp(futAcc({ wallet: 640.5 }), 5000, "futures", NOW())));
    await assertSucceeds(updateDoc(doc(db, "paper", "m1_spot"), paperTopUp(spotAcc(), 1000, "spot", NOW())));
    await assertSucceeds(updateDoc(doc(db, "paper", "m1_old"), paperTopUp({ id: "old", starting_balance: 10000, wallet: 9500 }, 1234.56, "futures", NOW())));
  });
  await test("paper: a normal trade (balance changes, deposits untouched) is still accepted", async () => {
    await seed({ ...member, "paper/m1_futures": futAcc() });
    await assertSucceeds(updateDoc(doc(as("m1", "m1@example.com"), "paper", "m1_futures"), { wallet: 900, positions: { BTCUSDT: { qty: 1 } } }));
  });
  await test("paper: deposits never go down, never exceed $1,000,000 and must match the balance", async () => {
    await seed({ ...member, "paper/m1_futures": futAcc({ deposited: 6000, deposit_count: 1, wallet: 6000 }) });
    const db = as("m1", "m1@example.com");
    const ref = doc(db, "paper", "m1_futures");
    await assertFails(updateDoc(ref, { deposited: 5000, deposit_count: 2, wallet: 5000 }));                 // goes down
    await assertFails(updateDoc(ref, { deposited: 1_000_001, deposit_count: 2, wallet: 1_000_001 }));       // above the cap
    await assertFails(updateDoc(ref, { deposited: 7000, deposit_count: 2, wallet: 9000 }));                 // balance +3000 for a 1000 deposit
    await assertFails(updateDoc(ref, { deposited: 7000, deposit_count: 1, wallet: 7000 }));                 // count not raised
    await assertFails(updateDoc(ref, { deposited: 7000, deposit_count: 3, wallet: 7000 }));                 // two at once
    await assertFails(updateDoc(ref, { deposit_count: 5 }));                                                // count without a deposit
    await assertFails(updateDoc(ref, { starting_balance: 50_000 }));                                        // start rewritten
    await assertSucceeds(updateDoc(ref, { deposited: 7000, deposit_count: 2, wallet: 7000 }));
  });
  await test("paper: a reset may start a new $1,000 account but never a new account above $1,000,000 or with fake deposits", async () => {
    await seed({ ...member, "paper/m1_futures": futAcc({ deposited: 6000, deposit_count: 1, wallet: 6000 }) });
    const db = as("m1", "m1@example.com");
    await assertFails(setDoc(doc(db, "paper", "m1_futures"), futAcc({ id: "acc2", starting_balance: 2_000_000, deposited: 2_000_000, wallet: 2_000_000 })));
    await assertFails(setDoc(doc(db, "paper", "m1_futures"), futAcc({ id: "acc2", deposited: 9000 })));
    await assertFails(setDoc(doc(db, "paper", "m1_futures"), futAcc({ id: "acc2", starting_balance: -5, deposited: -5 })));
    await assertSucceeds(setDoc(doc(db, "paper", "m1_futures"), futAcc({ id: "acc2" })));
  });
  await test("paper of another uid is denied", async () => {
    await seed(member);
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "paper", "m2_futures"), { wallet: 1 }));
  });
  await test("alerts create", async () => {
    await seed(member);
    await assertSucceeds(addDoc(collection(as("m1", "m1@example.com"), "alerts"), { type: "PRICE_ABOVE", symbol: "BTC/USDT", timeframe: "4h", params: { price: 70000 }, cooldown_s: 3600, enabled: true, created_at: NOW(), owner_uid: "m1", owner_email: "m1@example.com" }));
  });
  // v2.13: the exact shape of frontend/src/lib/api.ts "POST /alerts"; anything else is refused (a malformed rule used to
  // stop the engine's configuration step every cycle)
  const goodAlert = (uid = "m1", extra: any = {}) => ({ type: "TRADE_SETUP", symbol: "BTC/USDT", timeframe: "4h",
    params: { side: "any", market: "futures", min_confidence: 0, confident_only: false, grade: "any" }, cooldown_s: 3600, enabled: true,
    created_at: NOW(), owner_uid: uid, owner_email: `${uid}@example.com`, ...extra });
  await test("alerts: the website's trade-setup alert is accepted", async () => {
    await seed(member);
    await assertSucceeds(addDoc(collection(as("m1", "m1@example.com"), "alerts"), goodAlert()));
  });
  await test("alerts: bad cooldown (text, fraction, NaN, too small, too big) is refused", async () => {
    await seed(member);
    const db = as("m1", "m1@example.com");
    for (const cd of ["3600", 3600.5, NaN, 0, 59, 31536001, null]) await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { cooldown_s: cd })));
  });
  await test("alerts: bad symbol / type / timeframe / extra keys / someone else's uid are refused", async () => {
    await seed(member);
    const db = as("m1", "m1@example.com");
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { symbol: 42 })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { symbol: "btc/usdt; drop" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { symbol: { x: 1 } })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "NOT_A_TYPE" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { timeframe: "7m" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { params: "x" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { surprise: true })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m2")));
  });
  // v2.16 smarter alerts: the Alerts page presets ("My signals: entry / TP / SL" on every coin and timeframe, "Market mood
  // change") and the single call-event types; other types / timeframes stay refused
  await test("alerts: v2.16 call-event and market-mood alerts are accepted", async () => {
    await seed(member);
    const db = as("m1", "m1@example.com");
    await assertSucceeds(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "SIGNAL_UPDATES", symbol: "ALL/USDT", timeframe: "all",
      params: { events: ["entry", "tp1", "tp2", "tp3", "closed"] }, cooldown_s: 60 })));
    await assertSucceeds(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "MOOD_CHANGE", symbol: "ALL/USDT", timeframe: "4h", params: {}, cooldown_s: 3600 })));
    for (const t of ["ENTRY_REACHED", "TP2_REACHED", "TP3_REACHED", "SIGNAL_CLOSED"])
      await assertSucceeds(addDoc(collection(db, "alerts"), goodAlert("m1", { type: t, symbol: "ETH/USDT", timeframe: "1h", params: {}, cooldown_s: 60 })));
  });
  await test("alerts: v2.16 types keep the same checks (owner, symbol, timeframe, cooldown)", async () => {
    await seed(member);
    const db = as("m1", "m1@example.com");
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m2", { type: "SIGNAL_UPDATES", symbol: "ALL/USDT", timeframe: "all" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "SIGNAL_UPDATES", symbol: "all coins", timeframe: "all" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "MOOD_CHANGE", symbol: "ALL/USDT", timeframe: "any" })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "TP2_REACHED", symbol: "BTC/USDT", cooldown_s: 30 })));
    await assertFails(addDoc(collection(db, "alerts"), goodAlert("m1", { type: "TP4_REACHED", symbol: "BTC/USDT" })));
  });
  await test("alerts: the owner switches a rule on/off; other changes are refused", async () => {
    await seed({ ...member, "alerts/a1": goodAlert("m1") });
    const db = as("m1", "m1@example.com");
    await assertSucceeds(updateDoc(doc(db, "alerts", "a1"), { enabled: false }));
    await assertFails(updateDoc(doc(db, "alerts", "a1"), { enabled: "no" }));
    await assertFails(updateDoc(doc(db, "alerts", "a1"), { cooldown_s: "soon" }));
    await assertFails(updateDoc(doc(db, "alerts", "a1"), { symbol: 7 }));
  });
  await test("push_tokens create", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(as("m1", "m1@example.com"), "push_tokens", "tok123"), { token: "tok123", uid: "m1", email: "m1@example.com", created_at: NOW(), ua: "test", app: "browser" }));
  });
  await test("pending user cannot write paper or alerts", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com") });
    await assertFails(setDoc(doc(as("p1", "p1@example.com"), "paper", "p1_futures"), { wallet: 1 }));
    await assertFails(addDoc(collection(as("p1", "p1@example.com"), "alerts"), { owner_uid: "p1", type: "x" }));
  });

  // ---------------------------------------------------------------- views/health_errors (admin only, v2.13)
  const healthDocs = { "views/health": { json: "{}", updated_at: NOW() }, "views/health_errors": { json: "{}", updated_at: NOW() } };
  const readView = async (db: Firestore, id: string) => { const { getDoc } = await import("firebase/firestore"); return getDoc(doc(db, "views", id)); };
  await test("health_errors: admin reads it", async () => {
    await seed(healthDocs);
    await assertSucceeds(readView(admin(), "health_errors"));
  });
  await test("health_errors: an active member cannot read it, but still reads views/health", async () => {
    await seed({ ...member, ...healthDocs });
    await assertFails(readView(as("m1", "m1@example.com"), "health_errors"));
    await assertSucceeds(readView(as("m1", "m1@example.com"), "health"));
  });
  await test("health_errors: pending and signed-out people cannot read it", async () => {
    await seed({ "users/p1": pending("p1", "p1@example.com"), ...healthDocs });
    await assertFails(readView(as("p1", "p1@example.com"), "health_errors"));
    await assertFails(readView(env.unauthenticatedContext().firestore() as unknown as Firestore, "health_errors"));
  });
  await test("admin/migrations: members cannot read or write it", async () => {
    await seed({ ...member, "admin/migrations": { flags: { fresh_start_v23: true } } });
    const { getDoc } = await import("firebase/firestore");
    await assertFails(getDoc(doc(as("m1", "m1@example.com"), "admin", "migrations")));
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "admin", "migrations"), { flags: {} }));
    await assertSucceeds(getDoc(doc(admin(), "admin", "migrations")));
  });

  // ---------------------------------------------------------------- views/scalping (admin scorecard) + config/scalping
  const scalpView = { "views/scalping": { json: "{}", updated_at: NOW() }, "views/track_record": { json: "{}", updated_at: NOW() } };
  const readScalp = async (db: Firestore) => { const { getDoc } = await import("firebase/firestore"); return getDoc(doc(db, "views", "scalping")); };
  await test("scalping: admin reads views/scalping (default visibility, no config doc)", async () => {
    await seed(scalpView);
    await assertSucceeds(readScalp(admin()));
  });
  await test("scalping: member denied while visibility is admin (no config doc, and visibility 'admin')", async () => {
    await seed({ ...member, ...scalpView });
    await assertFails(readScalp(as("m1", "m1@example.com")));
    await seed({ ...member, ...scalpView, "config/scalping": { visibility: "admin", updated_at: NOW(), by: ADMIN.email } });
    await assertFails(readScalp(as("m1", "m1@example.com")));
    const { getDoc } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(as("m1", "m1@example.com"), "views", "track_record")));     // other views unchanged
  });
  await test("scalping: active member allowed when visibility is 'members'", async () => {
    await seed({ ...member, ...scalpView, "config/scalping": { visibility: "members", updated_at: NOW(), by: ADMIN.email } });
    await assertSucceeds(readScalp(as("m1", "m1@example.com")));
  });
  await test("scalping: pending / expired accounts denied even when visibility is 'members'", async () => {
    await seed({ ...scalpView, "config/scalping": { visibility: "members", updated_at: NOW(), by: ADMIN.email },
      "users/p1": pending("p1", "p1@example.com"), "users/x1": approved("x1", "x1@example.com", { expires_at: NOW() - DAY }) });
    await assertFails(readScalp(as("p1", "p1@example.com")));
    await assertFails(readScalp(as("x1", "x1@example.com")));
  });
  await test("scalping: signed-out always denied (admin or members visibility)", async () => {
    await seed(scalpView);
    const anon = env.unauthenticatedContext().firestore() as unknown as Firestore;
    await assertFails(readScalp(anon));
    await seed({ ...scalpView, "config/scalping": { visibility: "members", updated_at: NOW(), by: ADMIN.email } });
    await assertFails(readScalp(anon));
  });
  await test("scalping: nobody writes views/scalping from the website", async () => {
    await assertFails(setDoc(doc(admin(), "views", "scalping"), { json: "{}" }));
  });
  await test("config/scalping: admin sets visibility; members and bad values denied", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(admin(), "config", "scalping"), { visibility: "members", updated_at: NOW(), by: ADMIN.email }));
    await assertSucceeds(setDoc(doc(admin(), "config", "scalping"), { visibility: "admin", updated_at: NOW(), by: ADMIN.email }));
    await assertFails(setDoc(doc(admin(), "config", "scalping"), { visibility: "public", updated_at: NOW(), by: ADMIN.email }));
    await assertFails(setDoc(doc(admin(), "config", "scalping"), { visibility: "members", extra: true }));
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "config", "scalping"), { visibility: "members", updated_at: NOW(), by: "m1@example.com" }));
  });

  // ---------------------------------------------------------------- views/hesper (Road to Rich, admin only)
  const hesperView = { "views/hesper": { json: "{}", updated_at: NOW() }, "views/bots": { json: "{}", updated_at: NOW() } };
  const readHesper = async (db: Firestore) => { const { getDoc } = await import("firebase/firestore"); return getDoc(doc(db, "views", "hesper")); };
  await test("hesper: admin reads views/hesper", async () => {
    await seed(hesperView);
    await assertSucceeds(readHesper(admin()));
  });
  await test("hesper: active member denied (other views still readable)", async () => {
    await seed({ ...member, ...hesperView });
    await assertFails(readHesper(as("m1", "m1@example.com")));
    const { getDoc } = await import("firebase/firestore");
    await assertSucceeds(getDoc(doc(as("m1", "m1@example.com"), "views", "bots")));
  });
  await test("hesper: pending, expired and signed-out denied", async () => {
    await seed({ ...hesperView, "users/p1": pending("p1", "p1@example.com"), "users/x1": approved("x1", "x1@example.com", { expires_at: NOW() - DAY }) });
    await assertFails(readHesper(as("p1", "p1@example.com")));
    await assertFails(readHesper(as("x1", "x1@example.com")));
    await assertFails(readHesper(env.unauthenticatedContext().firestore() as unknown as Firestore));
  });
  await test("hesper: active member allowed when config/hesper.visibility is 'members' (view only)", async () => {
    await seed({ ...member, ...hesperView, "config/hesper": { visibility: "admin", updated_at: NOW(), by: ADMIN.email } });
    await assertFails(readHesper(as("m1", "m1@example.com")));
    await seed({ ...member, ...hesperView, "config/hesper": { visibility: "members", updated_at: NOW(), by: ADMIN.email } });
    await assertSucceeds(readHesper(as("m1", "m1@example.com")));
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "views", "hesper"), { json: "{}" }));
  });
  await test("hesper: pending, expired and signed-out denied even when visibility is 'members'", async () => {
    await seed({ ...hesperView, "config/hesper": { visibility: "members", updated_at: NOW(), by: ADMIN.email },
      "users/p1": pending("p1", "p1@example.com"), "users/x1": approved("x1", "x1@example.com", { expires_at: NOW() - DAY }) });
    await assertFails(readHesper(as("p1", "p1@example.com")));
    await assertFails(readHesper(as("x1", "x1@example.com")));
    await assertFails(readHesper(env.unauthenticatedContext().firestore() as unknown as Firestore));
  });
  await test("config/hesper: admin sets visibility; members and bad values denied", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(admin(), "config", "hesper"), { visibility: "members", updated_at: NOW(), by: ADMIN.email }));
    await assertSucceeds(setDoc(doc(admin(), "config", "hesper"), { visibility: "admin", updated_at: NOW(), by: ADMIN.email }));
    await assertFails(setDoc(doc(admin(), "config", "hesper"), { visibility: "public", updated_at: NOW(), by: ADMIN.email }));
    await assertFails(setDoc(doc(admin(), "config", "hesper"), { visibility: "members", extra: true }));
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "config", "hesper"), { visibility: "members", updated_at: NOW(), by: "m1@example.com" }));
  });
  await test("hesper: nobody writes views/hesper from the website", async () => {
    await assertFails(setDoc(doc(admin(), "views", "hesper"), { json: "{}" }));
  });

  await env.cleanup();
  const failed = results.filter((r) => !r.ok);
  const summary = { at: new Date().toISOString(), sha: process.env.GITHUB_SHA ?? null, total: results.length, passed: results.length - failed.length, failed: failed.length, results };
  writeFileSync(new URL("./results.json", import.meta.url), JSON.stringify(summary, null, 2));
  console.log(`\nRULES TESTS: ${summary.passed}/${summary.total} passed${failed.length ? `; FAILED: ${failed.map((f) => f.name).join(" | ")}` : ""}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
