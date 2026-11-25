// Crypto Intelligence AI — member chat (v2.61, owner 18 Nov 2026). A Cloudflare Worker on the free plan.
//
// POST /chat  { question, page, context, history }   Authorization: Bearer <Firebase ID token>
//   1. The Firebase ID token is verified here (RS256 against Google's public keys, audience = the project).
//   2. Membership is checked by reading users/{uid} through the Firestore REST API WITH THE MEMBER'S OWN TOKEN (the
//      rules already let a person read their own record), cached in memory + the Durable Object (v2.68), so most questions cost no Firestore read.
//      Admins = ADMIN_EMAILS. Pending / expired / blocked accounts are refused.
//   3. Daily caps in the Durable Object (v2.68; KV allows only 1,000 writes a day): per person (MEMBER_DAILY / ADMIN_DAILY) and for everyone together (GLOBAL_DAILY), Dubai day.
//   4. Gemini answers ONLY from `context` = the figures already on the member's screen, sent by the app. It has no
//      other data, never gives financial advice, never invents numbers. Advisory text only; it changes nothing.
// GET /health → {ok}. Nothing is stored except the counters and the membership cache (no questions, no answers).

import { memberOf, watchArm, watchInit, watchRun, watchStatus } from "./watch";

export interface Env {
  KV: KVNamespace;
  VIEWS: DurableObjectNamespace;
  EDGE_KEY: string;
  FCM_SENDER_KEY?: string;
  GEMINI_API_KEY: string;
  GEMINI_MODEL: string;
  FIREBASE_PROJECT: string;
  ALLOWED_ORIGINS: string;
  ADMIN_EMAILS: string;
  MEMBER_DAILY: string;
  ADMIN_DAILY: string;
  GLOBAL_DAILY: string;
}

const JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com";
const MAX_Q = 600;            // characters in a question
const MAX_CONTEXT = 14000;    // characters of page data
const MAX_TURNS = 6;          // earlier messages kept

let jwks: { keys: any[]; at: number } | null = null;

const SYSTEM = `You are Cintel, the assistant inside "Crypto Intelligence AI", a crypto analysis app for its members.
Rules (always):
- Answer ONLY from the PAGE DATA in the message. It is what the member sees on screen right now. If the answer is not
  in it, say you can't see that on this page and suggest where in the app it is (Signals, Results, News, Radar, coin page).
- Never invent numbers, prices, levels, dates or results. Copy figures exactly as given.
- No financial advice: never tell the member to buy, sell, enter, hold or size a trade, and never promise profit.
  You may explain what a signal, level, grade or figure means and how the app's rules work.
- No predictions of your own about where a price will go.
- The app never places real orders; its trading is practice with virtual money.
- Plain, friendly English, short: at most 6 sentences or 6 bullet points. No headings.
- If asked about something unrelated to the app or crypto markets, say briefly that you only help with this app.`;

function cors(origin: string | null, env: Env): Record<string, string> {
  const ok = origin && (env.ALLOWED_ORIGINS.split(",").map((s) => s.trim()).includes(origin) || /^http:\/\/localhost:\d+$/.test(origin));
  return {
    "Access-Control-Allow-Origin": ok ? origin! : "https://cryptointelai.com",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Firebase-AppCheck",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

const json = (body: unknown, status: number, h: Record<string, string>) =>
  new Response(JSON.stringify(body), { status, headers: { ...h, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });

function b64url(s: string): Uint8Array {
  const p = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  const bin = atob(p);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function keyFor(kid: string): Promise<CryptoKey | null> {
  if (!jwks || Date.now() - jwks.at > 3600_000 || !jwks.keys.some((k) => k.kid === kid)) {
    const r = await fetch(JWKS_URL);
    if (!r.ok) return null;
    jwks = { keys: ((await r.json()) as any).keys ?? [], at: Date.now() };
  }
  const jwk = jwks.keys.find((k) => k.kid === kid);
  if (!jwk) return null;
  return crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
}

/** Verifies a Firebase ID token; returns its claims or null. */
async function verify(token: string, project: string): Promise<any | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const head = JSON.parse(new TextDecoder().decode(b64url(parts[0])));
    const claims = JSON.parse(new TextDecoder().decode(b64url(parts[1])));
    if (head.alg !== "RS256" || !head.kid) return null;
    const key = await keyFor(head.kid);
    if (!key) return null;
    const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64url(parts[2]), new TextEncoder().encode(`${parts[0]}.${parts[1]}`));
    const now = Date.now() / 1000;
    if (!ok || claims.aud !== project || claims.iss !== `https://securetoken.google.com/${project}` || !claims.sub
      || claims.exp < now || claims.iat > now + 300) return null;
    return claims;
  } catch { return null; }
}

/** member | admin | null — from the person's own users/{uid} record (read with their token), cached 30 min. */
async function roleOf(claims: any, token: string, env: Env, appCheck: string | null): Promise<"admin" | "member" | null> {
  const email = String(claims.email ?? "").toLowerCase();
  if (email && claims.email_verified && env.ADMIN_EMAILS.toLowerCase().split(/[,\s;]+/).filter(Boolean).includes(email)) return "admin";
  if (claims.firebase?.sign_in_provider === "password" && !claims.email_verified) return null;
  const ck = `role:${claims.sub}`;
  const hit = ROLES.get(claims.sub);
  if (hit && hit.until > Date.now()) return hit.role === "member" ? "member" : null;
  // v3.1: the engine's member list first (no Firestore read; works while Firestore is over its daily quota)
  try {
    const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
    const m = await (await stub.fetch(`https://do/watch/member?u=${encodeURIComponent(claims.sub)}`)).text();
    if (m === "member") { ROLES.set(claims.sub, { role: "member", until: Date.now() + 300_000 }); return "member"; }   // not listed: ask as before (a member approved minutes ago)
  } catch { /* fall through */ }
  const cached = await store(env, "get", { k: ck });
  if (cached) { await keepRole(claims.sub, cached, env, false); return cached === "member" ? "member" : null; }
  const r = await fetch(`https://firestore.googleapis.com/v1/projects/${env.FIREBASE_PROJECT}/databases/(default)/documents/users/${claims.sub}`,
    { headers: { Authorization: `Bearer ${token}`, ...(appCheck ? { "X-Firebase-AppCheck": appCheck } : {}) } });
  let role: "member" | "none" = "none";
  let exp = 0;
  if (r.ok) {
    const f = ((await r.json()) as any).fields ?? {};
    const status = f.status?.stringValue;
    exp = Number(f.expires_at?.integerValue ?? f.expires_at?.doubleValue ?? 0);
    if (status === "approved" && (!exp || exp > Date.now())) role = "member";
  } else if (r.status === 429 || r.status >= 500) {
    // v3.1 (25 Nov 2026): Firestore over its daily quota (or down) says nothing about membership - use the last
    // confirmed answer (kept 14 days, never past the membership's end) and cache nothing, so members keep live data
    const last = await store(env, "get", { k: `role_last:${claims.sub}` });
    const [lr, lexp] = String(last ?? "").split("|");
    await note(env, `users read ${r.status}: using last known role (${lr || "none"})`);
    if (lr === "member" && (!Number(lexp) || Number(lexp) > Date.now())) { ROLES.set(claims.sub, { role: "member", until: Date.now() + 120_000 }); return "member"; }
    return null;
  }
  if (role !== "member") await note(env, `not a member: users read ${r.status}`);
  await keepRole(claims.sub, role, env, true);
  if (role === "member") { try { await store(env, "put", { k: `role_last:${claims.sub}`, v: `member|${exp || 0}`, ttl: 14 * 86400 }); } catch { /* best effort */ } }
  return role === "member" ? "member" : null;
}

// v2.67: role cache in memory first (KV: 1,000 writes a day on the free plan; one per person per 2 h is kept)
const ROLES = new Map<string, { role: string; until: number }>();
async function keepRole(uid: string, role: string, env: Env, write: boolean) {
  ROLES.set(uid, { role, until: Date.now() + 300_000 });
  if (write) { try { await store(env, "put", { k: `role:${uid}`, v: role, ttl: 7200 }); } catch { /* memory still works */ } }   // v2.68: in the Durable Object, not KV
}

const dubaiDay = () => new Date(Date.now() + 4 * 3600_000).toISOString().slice(0, 10);

/** Counts one question; false when the person's or everyone's daily limit is reached. */
async function spend(uid: string, admin: boolean, env: Env): Promise<{ ok: boolean; left: number; why?: string }> {
  // v2.68: the daily counters live in the Durable Object (100,000 writes a day on the free plan; KV allows only 1,000)
  const day = dubaiDay();
  const cap = Number(admin ? env.ADMIN_DAILY : env.MEMBER_DAILY) || 20;
  const gcap = Number(env.GLOBAL_DAILY) || 400;
  const r = JSON.parse((await store(env, "spend", { mine: `n:${day}:${uid}`, all: `n:${day}:all`, cap, gcap })) ?? "{}");
  if (r.why === "mine") return { ok: false, left: 0, why: `You've used today's ${cap} questions. The count resets at midnight (Dubai time).` };
  if (r.why === "all") return { ok: false, left: Math.max(0, cap - (r.n ?? 0)), why: "The assistant is resting for today (daily limit for everyone reached). Please try again tomorrow." };
  return { ok: true, left: Math.max(0, cap - (r.n ?? 0)) };
}

/** Small key-value notes kept in the Durable Object (roles, chat counters). */
async function store(env: Env, op: "get" | "put" | "spend", body: Record<string, unknown>): Promise<string | null> {
  const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
  const r = await stub.fetch(`https://do/kv/${op}`, { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`store ${op} ${r.status}`);
  const t = await r.text();
  return op === "get" ? (t || null) : t;
}

/** Calls the first model in GEMINI_MODEL (comma list) that exists for this key; remembers the working one 1 day.
 *  Google retires model names for new keys (18 Nov 2026: gemini-2.5-flash refused), so a 404 moves to the next name. */
async function gemini(env: Env, body: unknown): Promise<Response> {
  const names = [(await env.KV.get("diag:model")) ?? "", ...env.GEMINI_MODEL.split(",").map((x) => x.trim())].filter(Boolean);
  let last: Response | null = null;
  for (const m of [...new Set(names)]) {
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent`, {
      method: "POST", headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY }, body: JSON.stringify(body),
    });
    // gone (404), busy (503 / 500) or out of free quota (429): try the next name
    if (![404, 429, 500, 503].includes(r.status)) { if (r.ok && m !== names[0]) await env.KV.put("diag:model", m, { expirationTtl: 86400 }); return r; }
    last = r;
  }
  return last ?? new Response("no model", { status: 404 });
}

/** Last problem (no keys, no questions) for /diag, kept 1 day. */
async function note(env: Env, what: string) {
  try { await env.KV.put("diag:last", JSON.stringify({ at: new Date().toISOString(), what: what.replace(/AIza[\w-]{20,}/g, "[key]") }), { expirationTtl: 86400 }); } catch { /* ignore */ }
}

const clip = (s: unknown, n: number) => String(s ?? "").slice(0, n);

async function ask(env: Env, question: string, page: string, context: string, history: { role: string; text: string }[]) {
  const turns = history.slice(-MAX_TURNS).map((t) => ({ role: t.role === "model" ? "model" : "user", parts: [{ text: clip(t.text, 1500) }] }));
  const body = {
    systemInstruction: { parts: [{ text: SYSTEM }] },
    contents: [...turns, { role: "user", parts: [{ text: `PAGE: ${clip(page, 80)}\nPAGE DATA (JSON):\n${clip(context, MAX_CONTEXT)}\n\nQUESTION: ${question}` }] }],
    generationConfig: { temperature: 0.2, maxOutputTokens: 2048 },
  };
  const r = await gemini(env, body);
  if (!r.ok) { await note(env, `gemini ${r.status}: ${(await r.text()).slice(0, 300)}`); return null; }
  const d: any = await r.json();
  const text = (d.candidates?.[0]?.content?.parts ?? []).map((p: any) => p.text ?? "").join("").trim();
  if (!text) await note(env, `gemini empty: ${JSON.stringify(d).slice(0, 300)}`);
  return text || null;
}

/** Engine-only routes of the price-alert watcher (same X-Edge-Key as /ingest), handled inside the Durable Object. */
async function engineOnly(req: Request, env: Env, path: string): Promise<Response> {
  const key = req.headers.get("X-Edge-Key") ?? "";
  if (!env.EDGE_KEY || key.length < 32 || key !== env.EDGE_KEY) return new Response(JSON.stringify({ error: "forbidden" }), { status: 403 });
  const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
  return stub.fetch(`https://do${path}`, { method: req.method, body: req.method === "POST" ? await req.text() : undefined });
}

export default {
  // price-alert watcher: every minute (wrangler.toml crons), inside the Durable Object that holds the armed alerts
  async scheduled(_ev: ScheduledEvent, env: Env, ctx: ExecutionContext) {
    const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
    ctx.waitUntil(stub.fetch("https://do/watch/run", { method: "POST" }).then(() => undefined).catch(() => undefined));
  },
  async fetch(req: Request, env: Env): Promise<Response> {
    const h = cors(req.headers.get("Origin"), env);
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    if (url.pathname === "/health") return json({ ok: true, ready: !!env.GEMINI_API_KEY }, 200, h);
    if (url.pathname === "/diag") {
      // a tiny Gemini call at most every 10 min + the last recorded problem; no keys or questions are ever shown
      let gem = await env.KV.get("diag:gemini4");
      if (!gem && env.GEMINI_API_KEY) {
        const r = await gemini(env, { contents: [{ role: "user", parts: [{ text: "Reply with OK" }] }], generationConfig: { maxOutputTokens: 256 } });
        gem = `${r.status} ${(await env.KV.get("diag:model")) ?? ""} ${r.ok ? "" : (await r.text()).slice(0, 200).replace(/AIza[\w-]{20,}/g, "[key]")}`;
        await env.KV.put("diag:gemini4", gem, { expirationTtl: 600 });
      }
      let models = await env.KV.get("diag:models");
      if (!models && env.GEMINI_API_KEY) {
        const r = await fetch("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", { headers: { "x-goog-api-key": env.GEMINI_API_KEY } });
        const d: any = r.ok ? await r.json() : {};
        models = String((d.models ?? []).filter((m: any) => (m.supportedGenerationMethods ?? []).includes("generateContent")).map((m: any) => String(m.name).replace("models/", "")).filter((n: string) => /flash/.test(n)).join(",") || `list ${r.status}`);
        await env.KV.put("diag:models", models ?? "", { expirationTtl: 600 });
      }
      return json({ models, gemini: gem, admins: env.ADMIN_EMAILS.split(/[,\s;]+/).filter(Boolean).length, last: JSON.parse((await env.KV.get("diag:last")) ?? "null") }, 200, h);
    }
    if (url.pathname === "/ingest" && req.method === "POST") return ingest(req, env);
    if (url.pathname === "/watch/arm" && req.method === "POST") return engineOnly(req, env, "/watch/arm");
    if (url.pathname === "/watch/status" && req.method === "GET") return engineOnly(req, env, `/watch/status?since=${encodeURIComponent(url.searchParams.get("since") ?? "0")}`);
    if (url.pathname === "/v" && req.method === "GET") return views(req, url, env, h);
    if (url.pathname === "/px" && req.method === "GET") return mexcPrices(url, h);
    if (url.pathname === "/kl" && req.method === "GET") return mexcKlines(url, h);
    if (url.pathname === "/edge-health") return edgeHealth(env, h);
    if (url.pathname !== "/chat" || req.method !== "POST") return json({ error: "Not found" }, 404, h);
    if (!env.GEMINI_API_KEY) return json({ error: "The assistant is not set up yet." }, 503, h);

    const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const claims = token ? await verify(token, env.FIREBASE_PROJECT) : null;
    if (!claims) { if (token) await note(env, "token not accepted"); return json({ error: "Please sign in again." }, 401, h); }
    const role = await roleOf(claims, token, env, req.headers.get("X-Firebase-AppCheck"));
    if (!role) return json({ error: "The assistant is for active members." }, 403, h);

    let b: any;
    try { b = await req.json(); } catch { return json({ error: "Bad request." }, 400, h); }
    const question = clip(b?.question, MAX_Q).trim();
    if (!question) return json({ error: "Type a question first." }, 400, h);
    const context = typeof b?.context === "string" ? b.context : JSON.stringify(b?.context ?? {});
    const history = Array.isArray(b?.history) ? b.history.filter((t: any) => t && typeof t.text === "string") : [];

    const s = await spend(claims.sub, role === "admin", env);
    if (!s.ok) return json({ error: s.why, left: s.left }, 429, h);
    const answer = await ask(env, question, clip(b?.page, 80), context, history);
    if (!answer) return json({ error: "The assistant could not answer just now. Please try again in a minute.", left: s.left }, 502, h);
    return json({ answer, left: s.left }, 200, h);
  },
};

// ======================================================================================================================
// v2.67 EDGE VIEWS (owner, 22 Nov 2026: "reduce the load on Firebase, connect Cloudflare free").
// The engine sends every changed member view here (POST /ingest, key derived from its Firebase key); they are kept in a
// Durable Object with SQLite storage (free plan: 100k writes / 5M reads a day). Members' apps read them with GET /v
// (signed-in, active members only - same check as the chat), served from Cloudflare's cache for 20 s, so 1 or 1,000
// members cost the same. Firestore keeps a slower copy as the fallback; the app falls back to it on any problem.
// Only views every active member may read are accepted (never admin-only or per-person documents).
const EDGE_RE = /^(health|meta|track_record|market_context|context|radar|news|coin_reports|leaderboard|bots|signals|cross_asset_1d|models_status|weekly_report|performance|wins_today|replay_ranges|(dashboard|futures)_(15m|1h|4h|12h|1d|3d)|(analysis|perf|models)_[A-Z0-9]{2,24}_(15m|1h|4h|12h|1d|3d|1w))$/;
const EDGE_TTL_S = 20;
const MAX_NAMES = 40;

async function ingest(req: Request, env: Env): Promise<Response> {
  // the body is passed to the Durable Object unread (the free plan allows 10 ms of CPU per request; the engine sends
  // small chunks of at most ~0.5 MB); rows = [{name, json, at, etag}]
  const key = req.headers.get("X-Edge-Key") ?? "";
  if (!env.EDGE_KEY || key.length < 32 || key !== env.EDGE_KEY) return new Response(JSON.stringify({ error: "forbidden" }), { status: 403 });
  const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
  const r = await stub.fetch("https://do/put", { method: "POST", body: req.body });
  return new Response(await r.text(), { status: r.status, headers: { "Content-Type": "application/json" } });
}

/** GET /v?n=a,b,c&e=etagA,etagB,etagC  ->  { "views": { a: {etag, at, data} | {same: 1} | {none: 1} }, "at": ms }.
 *  Built by joining text (no JSON parsing of the views, to stay inside the free plan's CPU time). The Cache API does
 *  nothing on workers.dev, so each Worker instance keeps the views it served in memory for EDGE_TTL_S; misses are
 *  fetched from the Durable Object in ONE call. */
const MEM = new Map<string, { etag: string; at: number; body: string; until: number }>();
async function views(req: Request, url: URL, env: Env, h: Record<string, string>): Promise<Response> {
  // the engine checks the read path with its own key (same views, no member data involved)
  const engineProbe = !!env.EDGE_KEY && (req.headers.get("X-Edge-Key") ?? "") === env.EDGE_KEY;
  if (!engineProbe) {
    const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const claims = token ? await verifyCached(token, env.FIREBASE_PROJECT) : null;
    if (!claims) return json({ error: "sign in" }, 401, h);
    const role = await roleOf(claims, token, env, req.headers.get("X-Firebase-AppCheck"));
    if (!role) return json({ error: "members only" }, 403, h);
  }
  const raw = (url.searchParams.get("n") ?? "").split(","), et = (url.searchParams.get("e") ?? "").split(",");
  const tags = new Map(raw.map((x, i) => [x.trim(), et[i] ?? ""]));
  const names = [...new Set(raw.map((x) => x.trim()).filter((x) => EDGE_RE.test(x)))].slice(0, MAX_NAMES);
  const now = Date.now();
  const miss = names.filter((n) => !((MEM.get(n)?.until ?? 0) > now));
  if (miss.length) {
    const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
    const d = await stub.fetch(`https://do/get?n=${encodeURIComponent(miss.join(","))}`);
    const text = d.ok ? await d.text() : "";
    const got = new Set<string>();
    for (const rec of text.split("\u0000")) {
      if (!rec) continue;
      const i1 = rec.indexOf("\u0001"), i2 = rec.indexOf("\u0001", i1 + 1), i3 = rec.indexOf("\u0001", i2 + 1);
      if (i1 < 0 || i2 < 0 || i3 < 0) continue;
      const n = rec.slice(0, i1);
      MEM.set(n, { etag: rec.slice(i1 + 1, i2), at: Number(rec.slice(i2 + 1, i3)) || 0, body: rec.slice(i3 + 1), until: now + EDGE_TTL_S * 1000 });
      got.add(n);
    }
    if (d.ok) for (const n of miss) if (!got.has(n)) MEM.set(n, { etag: "", at: 0, body: "", until: now + EDGE_TTL_S * 1000 });
    if (MEM.size > 600) for (const [k, v] of MEM) if (v.until < now) MEM.delete(k);
  }
  const parts: string[] = [];
  for (const n of names) {
    const m = MEM.get(n);
    if (!m || !m.body || !m.etag) parts.push(`${JSON.stringify(n)}:{"none":1}`);
    else if (tags.get(n) === m.etag) parts.push(`${JSON.stringify(n)}:{"same":1}`);
    else parts.push(`${JSON.stringify(n)}:{"etag":${JSON.stringify(m.etag)},"at":${m.at},"data":${m.body}}`);
  }
  return new Response(`{"views":{${parts.join(",")}},"at":${now}}`, { status: 200, headers: { ...h, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

// v3.1 (owner, 25 Nov 2026: "why is Anthropic price not live?"): coins traded only as MEXC perpetuals (not listed on
// Binance, e.g. ANTHROPIC) had no live price in the browser. Public prices, cached 5 s per coin in this isolate, at
// most 6 coins per request; the app asks every 10 s only for such coins and only while on screen.
const PX = new Map<string, { at: number; v: any }>();
const MEXC_NAME: Record<string, string> = { MSTR: "MSTRSTOCK_USDT", XAG: "SILVER_USDT" };
async function mexcPrices(url: URL, h: Record<string, string>): Promise<Response> {
  const bases = [...new Set((url.searchParams.get("s") ?? "").toUpperCase().split(",").map((x) => x.trim()).filter((x) => /^[A-Z0-9]{1,20}$/.test(x)))].slice(0, 6);
  const out: Record<string, unknown> = {};
  await Promise.all(bases.map(async (b) => {
    const hit = PX.get(b);
    if (hit && Date.now() - hit.at < 5000) { out[b] = hit.v; return; }
    try {
      const r = await fetch(`https://contract.mexc.com/api/v1/contract/ticker?symbol=${MEXC_NAME[b] ?? `${b}_USDT`}`);
      const d: any = r.ok ? await r.json() : null;
      const t = d?.data;
      if (t && Number(t.lastPrice) > 0) {
        const v = { last: Number(t.lastPrice), change: Number(t.riseFallRate) * 100, qv: Number(t.amount24) || null, ts: Number(t.timestamp) || Date.now() };
        PX.set(b, { at: Date.now(), v }); out[b] = v;
      }
    } catch { /* that coin is left out */ }
  }));
  return new Response(JSON.stringify({ px: out, at: Date.now() }), { status: 200, headers: { ...h, "Content-Type": "application/json", "Cache-Control": "no-store" } });
}

// v3.1 (owner, 25 Nov 2026: "the chart of Anthropic is wrong"): candles of MEXC-only coins for the app's charts, in
// Binance's kline shape [openMs, o, h, l, c, v]. 12h / 3d are built from 4h / 1d (epoch-aligned, like the engine).
const KL = new Map<string, { at: number; v: string }>();
const MEXC_TF: Record<string, [string, number, number]> = {        // app tf -> MEXC interval, its ms, candles per app candle
  "1m": ["Min1", 60e3, 1], "5m": ["Min5", 300e3, 1], "15m": ["Min15", 900e3, 1], "30m": ["Min30", 1800e3, 1],
  "1h": ["Min60", 3600e3, 1], "4h": ["Hour4", 14400e3, 1], "12h": ["Hour4", 14400e3, 3], "1d": ["Day1", 86400e3, 1],
  "3d": ["Day1", 86400e3, 3], "1w": ["Week1", 604800e3, 1],
};
async function mexcKlines(url: URL, h: Record<string, string>): Promise<Response> {
  const b = (url.searchParams.get("s") ?? "").toUpperCase();
  const tf = url.searchParams.get("tf") ?? "1h";
  const limit = Math.max(10, Math.min(1000, Number(url.searchParams.get("limit")) || 500));
  const m = MEXC_TF[tf];
  if (!/^[A-Z0-9]{1,20}$/.test(b) || !m) return json({ error: "bad request" }, 400, h);
  const key = `${b}|${tf}|${limit}`;
  const hit = KL.get(key);
  const hdr = { ...h, "Content-Type": "application/json", "Cache-Control": "no-store" };
  if (hit && Date.now() - hit.at < 20_000) return new Response(hit.v, { status: 200, headers: hdr });
  const [iv, ms, k] = m;
  const end = Math.floor(Date.now() / 1000);
  const start = end - Math.ceil((limit * k + 2 * k) * ms / 1000);
  try {
    const r = await fetch(`https://contract.mexc.com/api/v1/contract/kline/${MEXC_NAME[b] ?? `${b}_USDT`}?interval=${iv}&start=${start}&end=${end}`);
    const d: any = r.ok ? await r.json() : null;
    const t = d?.data?.time ?? [];
    let rows: number[][] = t.map((x: number, i: number) => {
      const o = +d.data.open[i], c = +d.data.close[i];
      return [x * 1000, o, Math.max(+d.data.high[i], o, c), Math.min(+d.data.low[i], o, c), c, +(d.data.vol?.[i] ?? 0)];
    });
    if (k > 1) {                               // 12h from 4h, 3d from 1d: epoch-aligned buckets
      const span = ms * k, g = new Map<number, number[]>();
      for (const x of rows) {
        const s0 = x[0] - (x[0] % span), cur = g.get(s0);
        if (!cur) g.set(s0, [s0, x[1], x[2], x[3], x[4], x[5]]);
        else { cur[2] = Math.max(cur[2], x[2]); cur[3] = Math.min(cur[3], x[3]); cur[4] = x[4]; cur[5] += x[5]; }
      }
      rows = [...g.values()].sort((p, q) => p[0] - q[0]);
    }
    const v = JSON.stringify(rows.slice(-limit));
    if (rows.length) KL.set(key, { at: Date.now(), v });
    if (KL.size > 300) for (const [kk, vv] of KL) if (Date.now() - vv.at > 60_000) KL.delete(kk);
    return new Response(v, { status: rows.length ? 200 : 502, headers: hdr });
  } catch {
    return json({ error: "MEXC not reachable" }, 502, h);
  }
}

async function edgeHealth(env: Env, h: Record<string, string>): Promise<Response> {
  try {
    const stub = env.VIEWS.get(env.VIEWS.idFromName("views"));
    const r = await stub.fetch("https://do/stats");
    return json({ ok: r.ok, ...(r.ok ? ((await r.json()) as object) : {}) }, 200, h);
  } catch (e) { return json({ ok: false, error: String(e).slice(0, 200) }, 200, h); }
}

const TOKENS = new Map<string, { claims: any; until: number }>();
async function verifyCached(token: string, project: string) {
  const t = TOKENS.get(token);
  if (t && t.until > Date.now() && t.claims.exp * 1000 > Date.now()) return t.claims;
  const c = await verify(token, project);
  if (c) { if (TOKENS.size > 2000) TOKENS.clear(); TOKENS.set(token, { claims: c, until: Date.now() + 300_000 }); }
  return c;
}

/** One Durable Object holds every edge view (SQLite storage: one row per view). */
export class ViewStore {
  sql: SqlStorage;
  env: Env;
  constructor(readonly state: DurableObjectState, env: Env) {
    this.env = env;
    this.sql = state.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS views (name TEXT PRIMARY KEY, json TEXT NOT NULL, at INTEGER NOT NULL, etag TEXT NOT NULL)");
  }
  async fetch(req: Request): Promise<Response> {
    const u = new URL(req.url);
    if (u.pathname.startsWith("/watch/")) {
      watchInit(this.sql);
      if (u.pathname === "/watch/run") return Response.json(await watchRun(this.sql, this.env.FCM_SENDER_KEY));
      if (u.pathname === "/watch/arm") return Response.json({ ok: true, armed: watchArm(this.sql, await req.json().catch(() => null)) });
      if (u.pathname === "/watch/status") return Response.json(watchStatus(this.sql, Number(u.searchParams.get("since")) || 0));
      if (u.pathname === "/watch/member") return new Response(memberOf(this.sql, String(u.searchParams.get("u") ?? "")));
      return new Response("not found", { status: 404 });
    }
    if (u.pathname.startsWith("/kv/")) {
      this.sql.exec("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, exp INTEGER NOT NULL)");
      const b: any = await req.json();
      const now = Date.now();
      const get = (k: string) => (this.sql.exec("SELECT v FROM kv WHERE k = ? AND exp > ?", k, now).toArray()[0] as any)?.v ?? null;
      const put = (k: string, v: string, ttl: number) => this.sql.exec("INSERT INTO kv (k, v, exp) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v, exp = excluded.exp", k, v, now + ttl * 1000);
      if (u.pathname === "/kv/get") return new Response(get(String(b.k)) ?? "");
      if (u.pathname === "/kv/put") { put(String(b.k), String(b.v), Number(b.ttl) || 3600); return new Response("ok"); }
      if (u.pathname === "/kv/spend") {
        const n = Number(get(String(b.mine)) ?? 0), g = Number(get(String(b.all)) ?? 0);
        if (n >= Number(b.cap)) return Response.json({ ok: false, why: "mine", n });
        if (g >= Number(b.gcap)) return Response.json({ ok: false, why: "all", n });
        put(String(b.mine), String(n + 1), 172800); put(String(b.all), String(g + 1), 172800);
        if (Math.random() < 0.02) this.sql.exec("DELETE FROM kv WHERE exp < ?", now);
        return Response.json({ ok: true, n: n + 1 });
      }
      return new Response("not found", { status: 404 });
    }
    if (u.pathname === "/put") {
      const rows: { name: string; json: string; at: number; etag: string }[] = await req.json();
      let n = 0;
      for (const r of Array.isArray(rows) ? rows : []) {
        if (!r || !EDGE_RE.test(r.name) || typeof r.json !== "string" || !r.etag) continue;
        this.sql.exec("INSERT INTO views (name, json, at, etag) VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET json = excluded.json, at = excluded.at, etag = excluded.etag",
          r.name, r.json, Number(r.at) || Date.now(), String(r.etag).slice(0, 40));
        n++;
      }
      this.sql.exec("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)");
      this.sql.exec("INSERT INTO meta (k, v) VALUES ('last_put', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", Date.now());
      return Response.json({ ok: true, stored: n });
    }
    if (u.pathname === "/get") {
      // records "name \u0001 etag \u0001 at \u0001 json", separated by \u0000 (neither can appear raw in JSON text)
      const out: string[] = [];
      for (const n of (u.searchParams.get("n") ?? "").split(",").slice(0, MAX_NAMES)) {
        const row = this.sql.exec("SELECT json, at, etag FROM views WHERE name = ?", n).toArray()[0] as any;
        if (row) out.push(`${n}\u0001${row.etag}\u0001${row.at}\u0001${row.json}`);
      }
      return new Response(out.join("\u0000"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    }
    if (u.pathname === "/stats") {
      const row = this.sql.exec("SELECT COUNT(*) AS n, MAX(at) AS newest FROM views").toArray()[0] as any;
      this.sql.exec("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)");
      const lp = this.sql.exec("SELECT v FROM meta WHERE k = 'last_put'").toArray()[0] as any;
      return Response.json({ views: row?.n ?? 0, newest: row?.newest ?? null, last_put: lp?.v ?? null });
    }
    return new Response("not found", { status: 404 });
  }
}
