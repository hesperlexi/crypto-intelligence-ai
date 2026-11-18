// Crypto Intelligence AI — member chat (v2.61, owner 18 Nov 2026). A Cloudflare Worker on the free plan.
//
// POST /chat  { question, page, context, history }   Authorization: Bearer <Firebase ID token>
//   1. The Firebase ID token is verified here (RS256 against Google's public keys, audience = the project).
//   2. Membership is checked by reading users/{uid} through the Firestore REST API WITH THE MEMBER'S OWN TOKEN (the
//      rules already let a person read their own record), cached 30 min in KV, so most questions cost no Firestore read.
//      Admins = ADMIN_EMAILS. Pending / expired / blocked accounts are refused.
//   3. Daily caps in KV: per person (MEMBER_DAILY / ADMIN_DAILY) and for everyone together (GLOBAL_DAILY), Dubai day.
//   4. Gemini answers ONLY from `context` = the figures already on the member's screen, sent by the app. It has no
//      other data, never gives financial advice, never invents numbers. Advisory text only; it changes nothing.
// GET /health → {ok}. Nothing is stored except the counters and the membership cache (no questions, no answers).

export interface Env {
  KV: KVNamespace;
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
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
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
async function roleOf(claims: any, token: string, env: Env): Promise<"admin" | "member" | null> {
  const email = String(claims.email ?? "").toLowerCase();
  if (email && claims.email_verified && env.ADMIN_EMAILS.toLowerCase().split(/[,\s;]+/).filter(Boolean).includes(email)) return "admin";
  if (claims.firebase?.sign_in_provider === "password" && !claims.email_verified) return null;
  const ck = `role:${claims.sub}`;
  const cached = await env.KV.get(ck);
  if (cached) return cached === "member" ? "member" : null;
  const r = await fetch(`https://firestore.googleapis.com/v1/projects/${env.FIREBASE_PROJECT}/databases/(default)/documents/users/${claims.sub}`,
    { headers: { Authorization: `Bearer ${token}` } });
  let role: "member" | "none" = "none";
  if (r.ok) {
    const f = ((await r.json()) as any).fields ?? {};
    const status = f.status?.stringValue;
    const exp = Number(f.expires_at?.integerValue ?? f.expires_at?.doubleValue ?? 0);
    if (status === "approved" && (!exp || exp > Date.now())) role = "member";
  }
  if (role !== "member") await note(env, `not a member: users read ${r.status}`);
  await env.KV.put(ck, role, { expirationTtl: 1800 });
  return role === "member" ? "member" : null;
}

const dubaiDay = () => new Date(Date.now() + 4 * 3600_000).toISOString().slice(0, 10);

/** Counts one question; false when the person's or everyone's daily limit is reached. */
async function spend(uid: string, admin: boolean, env: Env): Promise<{ ok: boolean; left: number; why?: string }> {
  const day = dubaiDay();
  const mine = `n:${day}:${uid}`, all = `n:${day}:all`;
  const [m, a] = await Promise.all([env.KV.get(mine), env.KV.get(all)]);
  const cap = Number(admin ? env.ADMIN_DAILY : env.MEMBER_DAILY) || 20;
  const n = Number(m ?? 0), g = Number(a ?? 0);
  if (n >= cap) return { ok: false, left: 0, why: `You've used today's ${cap} questions. The count resets at midnight (Dubai time).` };
  if (g >= (Number(env.GLOBAL_DAILY) || 400)) return { ok: false, left: cap - n, why: "The assistant is resting for today (daily limit for everyone reached). Please try again tomorrow." };
  await Promise.all([env.KV.put(mine, String(n + 1), { expirationTtl: 172800 }), env.KV.put(all, String(g + 1), { expirationTtl: 172800 })]);
  return { ok: true, left: cap - n - 1 };
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
    if (![404, 429, 500, 503].includes(r.status)) { if (r.ok) await env.KV.put("diag:model", m, { expirationTtl: 86400 }); return r; }
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

export default {
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
    if (url.pathname !== "/chat" || req.method !== "POST") return json({ error: "Not found" }, 404, h);
    if (!env.GEMINI_API_KEY) return json({ error: "The assistant is not set up yet." }, 503, h);

    const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
    const claims = token ? await verify(token, env.FIREBASE_PROJECT) : null;
    if (!claims) { if (token) await note(env, "token not accepted"); return json({ error: "Please sign in again." }, 401, h); }
    const role = await roleOf(claims, token, env);
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
