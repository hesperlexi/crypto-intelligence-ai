// Firestore security rules tests, run inside the Firestore emulator by .github/workflows/rules-test.yml:
//   firebase emulators:exec --only firestore --project demo-test "npm test"
// The rules file is ./firestore.rules (copied by the workflow from ../../firestore.rules, rendered from firestore.rules.template with ADMIN_EMAILS=admin@example.com).
// Account / username / Community / payment documents are built with the website's own builders
// (frontend/src/lib/writeShapes.ts), so these tests check the exact shapes the app sends.
import { assertFails, assertSucceeds, initializeTestEnvironment, RulesTestEnvironment } from "@firebase/rules-unit-testing";
import { addDoc, collection, deleteDoc, doc, Firestore, setDoc, updateDoc, writeBatch } from "firebase/firestore";
import { readFileSync, writeFileSync } from "node:fs";
import { newUserRecord, ownerProfile, paymentProof, postDoc, postMeta, usernameClaim, usernameOnUser } from "../../frontend/src/lib/writeShapes";

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
  b.set(doc(collection(db, "posts")), postDoc(uid, username, text, at, !!opts.admin));
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
    b.set(doc(collection(db, "posts")), postDoc("m2", "dreyes", "hi", NOW(), false));
    b.set(doc(db, "post_meta", "m1"), postMeta(NOW()));
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
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "posts"), postDoc("m1", "sara_k", "no marker", NOW(), false)));
  });
  await test("post with extra fields is denied", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    const at = NOW();
    const b = writeBatch(db);
    b.set(doc(collection(db, "posts")), { ...postDoc("m1", "sara_k", "hi", at, false), image: "https://x" });
    b.set(doc(db, "post_meta", "m1"), postMeta(at));
    await assertFails(b.commit());
  });
  await test("second post within 30 s is denied (post_meta)", async () => {
    await seed(community);
    const db = as("m1", "m1@example.com");
    await assertSucceeds(post(db, "m1", "sara_k", "first"));
    await assertFails(post(db, "m1", "sara_k", "second, too soon", { at: NOW() + 5_000 }));
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
  await test("jobs create: test_push to another uid is denied", async () => {
    await seed(member);
    await assertFails(addDoc(collection(as("m1", "m1@example.com"), "jobs"), { type: "test_push", params: { uid: "m2" }, status: "queued", created_at: NOW(), by: "m1@example.com" }));
  });
  await test("paper/{uid}_futures write", async () => {
    await seed(member);
    await assertSucceeds(setDoc(doc(as("m1", "m1@example.com"), "paper", "m1_futures"), { id: "acc1", starting_balance: 10000, wallet: 10000, created_at: NOW(), positions: {}, position_mode: "oneway", totals: { realized: 0, fees: 0, funding: 0, count: 0, wins: 0, liquidations: 0 } }));
  });
  await test("paper of another uid is denied", async () => {
    await seed(member);
    await assertFails(setDoc(doc(as("m1", "m1@example.com"), "paper", "m2_futures"), { wallet: 1 }));
  });
  await test("alerts create", async () => {
    await seed(member);
    await assertSucceeds(addDoc(collection(as("m1", "m1@example.com"), "alerts"), { type: "price_above", symbol: "BTC/USDT", timeframe: "4h", params: { price: 70000 }, cooldown_s: 3600, enabled: true, created_at: NOW(), owner_uid: "m1", owner_email: "m1@example.com" }));
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

  await env.cleanup();
  const failed = results.filter((r) => !r.ok);
  const summary = { at: new Date().toISOString(), sha: process.env.GITHUB_SHA ?? null, total: results.length, passed: results.length - failed.length, failed: failed.length, results };
  writeFileSync(new URL("./results.json", import.meta.url), JSON.stringify(summary, null, 2));
  console.log(`\nRULES TESTS: ${summary.passed}/${summary.total} passed${failed.length ? `; FAILED: ${failed.map((f) => f.name).join(" | ")}` : ""}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
