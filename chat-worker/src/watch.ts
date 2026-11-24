// Cloudflare price-alert watcher (owner, 24 Nov 2026: "yes, build it").
//
// The engine runs on GitHub Actions and has gaps (7 h on 23 Nov). Its own fast watch (backend/app/watch.py) can only
// warn while the engine runs, so this watcher runs on Cloudflare every minute instead, day and night, free plan.
//
// * The engine prepares the "armed" alerts (POST /watch/arm, X-Edge-Key): one per level of every open call (pending
//   entry, TP1-3 not hit yet, the stop in force) and of the Hesper / Last Stand trades - coin, price source, level,
//   direction, the finished notification text, and the phone tokens of the people who asked for that event (their alert
//   rules, exactly as the engine's own push). Nothing here decides who gets what.
// * Every minute (cron): one price request (Binance spot; MEXC futures for futures-only coins), and for each armed alert
//   the price has reached and that was not sent yet: one Firebase Cloud Messaging send per phone, with the SAME tag as
//   the engine's later confirmed push, so the phone replaces it instead of showing two.
// * The FCM key is a send-only service account (secret FCM_SENDER_KEY: role "Firebase Cloud Messaging API Admin"); the
//   main Firebase key never leaves GitHub. Phone tokens are kept only inside the Durable Object, never served to apps.
// * GET /watch/status (X-Edge-Key) tells the engine what was sent (so its own watch skips those) and which phones were
//   refused (the engine removes those tokens).

export type Armed = {
  key: string; symbol: string; src: "spot" | "mexc"; pair: string; side: 1 | -1; level: number; profit: boolean;
  msg: { title: string; body: string; url: string; tag: string }; tokens: string[];
};

const KEEP_SENT_MS = 7 * 86_400_000;
const MAX_SENDS = 40;            // free plan: at most 50 outgoing requests per run (prices + token + sends)

type Sql = SqlStorage;
function kvGet(sql: Sql, k: string): string | null {
  return (sql.exec("SELECT v FROM wkv WHERE k = ?", k).toArray()[0] as any)?.v ?? null;
}
function kvPut(sql: Sql, k: string, v: string) {
  sql.exec("INSERT INTO wkv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", k, v);
}
export function watchInit(sql: Sql) {
  sql.exec("CREATE TABLE IF NOT EXISTS wkv (k TEXT PRIMARY KEY, v TEXT NOT NULL)");
  sql.exec("CREATE TABLE IF NOT EXISTS wsent (key TEXT PRIMARY KEY, at INTEGER NOT NULL)");
  sql.exec("CREATE TABLE IF NOT EXISTS wtok (key TEXT NOT NULL, tok TEXT NOT NULL, at INTEGER NOT NULL, PRIMARY KEY (key, tok))");
}

const reached = (a: Armed, p: number) => {
  const d = (p - a.level) * a.side;
  return a.profit ? d >= 0 : d <= 0;
};

async function prices(list: Armed[]): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  const spot = [...new Set(list.filter((a) => a.src === "spot").map((a) => a.pair))];
  const mexc = [...new Set(list.filter((a) => a.src === "mexc").map((a) => a.pair))];
  if (spot.length) {
    try {
      const r = await fetch(`https://data-api.binance.vision/api/v3/ticker/price?symbols=${encodeURIComponent(JSON.stringify(spot))}`);
      if (r.ok) for (const x of (await r.json()) as any[]) out[`spot:${x.symbol}`] = Number(x.price);
    } catch { /* next minute */ }
  }
  for (const c of mexc.slice(0, 5)) {
    try {
      const r = await fetch(`https://contract.mexc.com/api/v1/contract/ticker?symbol=${encodeURIComponent(c)}`);
      const d: any = r.ok ? await r.json() : null;
      if (d?.data?.lastPrice) out[`mexc:${c}`] = Number(d.data.lastPrice);
    } catch { /* next minute */ }
  }
  return out;
}

// ---- Google OAuth for FCM (RS256 JWT signed with the send-only service account) ----------------------------------
const b64url = (b: ArrayBuffer | Uint8Array | string) => {
  const bytes = typeof b === "string" ? new TextEncoder().encode(b) : new Uint8Array(b as ArrayBuffer);
  let s = "";
  for (const x of bytes) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
async function accessToken(sql: Sql, keyJson: string): Promise<{ token: string; project: string } | null> {
  let sa: any;
  try { sa = JSON.parse(keyJson); } catch { return null; }
  if (!sa?.private_key || !sa?.client_email) return null;
  const cached = JSON.parse(kvGet(sql, "fcm_token") ?? "null");
  if (cached && cached.exp > Date.now() + 120_000) return { token: cached.t, project: sa.project_id };
  const pem = String(sa.private_key).replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const now = Math.floor(Date.now() / 1000);
  const head = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claim = b64url(JSON.stringify({ iss: sa.client_email, scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token", iat: now, exp: now + 3600 }));
  const sig = b64url(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${head}.${claim}`)));
  const r = await fetch("https://oauth2.googleapis.com/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=${head}.${claim}.${sig}` });
  const d: any = r.ok ? await r.json() : null;
  if (!d?.access_token) return null;
  kvPut(sql, "fcm_token", JSON.stringify({ t: d.access_token, exp: Date.now() + (Number(d.expires_in) || 3600) * 1000 }));
  return { token: d.access_token, project: sa.project_id };
}

/** One pass (cron, every minute). */
export async function watchRun(sql: Sql, keyJson: string | undefined): Promise<Record<string, unknown>> {
  const now = Date.now();
  const list: Armed[] = JSON.parse(kvGet(sql, "armed") ?? "[]");
  const armedAt = Number(kvGet(sql, "armed_at") ?? 0);
  const st: any = { at: now, armed: list.length, armed_at: armedAt, sent: 0, due: 0, error: keyJson ? null : "FCM_SENDER_KEY not set" };
  // hourly self-check: a dry-run send (validate_only: nothing reaches the phone) proves the key and its permission
  const check = JSON.parse(kvGet(sql, "fcm_check") ?? "null");
  const probe = kvGet(sql, "probe_token");
  if (keyJson && probe && (!check || now - check.at > 3_600_000)) {
    const res: any = { at: now, ok: false };
    try {
      const auth = await accessToken(sql, keyJson);
      if (!auth) res.why = "no access token";
      else {
        const r = await fetch(`https://fcm.googleapis.com/v1/projects/${auth.project}/messages:send`, {
          method: "POST", headers: { Authorization: `Bearer ${auth.token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ validate_only: true, message: { token: probe, data: { title: "check", body: "check" } } }) });
        res.ok = r.ok; res.status = r.status;
        if (!r.ok) res.why = (await r.text()).slice(0, 160).replace(/ya29\.[\w.-]+/g, "[token]");
      }
    } catch (e) { res.why = String(e).slice(0, 120); }
    kvPut(sql, "fcm_check", JSON.stringify(res));
  }
  st.fcm_check = JSON.parse(kvGet(sql, "fcm_check") ?? "null");
  // armed list older than 6 h = the engine is gone for long; the levels may be out of date (closed calls) -> stop
  if (!list.length || now - armedAt > 6 * 3_600_000) { kvPut(sql, "status", JSON.stringify({ ...st, idle: true })); return st; }
  const px = await prices(list);
  st.priced = Object.keys(px).length;
  const due = list.filter((a) => {
    const p = px[`${a.src}:${a.pair}`];
    return isFinite(p) && reached(a, p) && !sql.exec("SELECT 1 FROM wsent WHERE key = ?", a.key).toArray().length;
  });
  st.due = due.length;
  if (due.length) {
    const auth = keyJson ? await accessToken(sql, keyJson) : null;
    if (!auth) st.error = keyJson ? "could not get a notification token" : "FCM_SENDER_KEY not set";
    else {
      const bad: string[] = JSON.parse(kvGet(sql, "bad_tokens") ?? "[]");
      let budget = MAX_SENDS;
      for (const a of due) {
        if (budget <= 0) break;                      // the rest go out next minute
        const done = new Set(sql.exec("SELECT tok FROM wtok WHERE key = ?", a.key).toArray().map((r: any) => r.tok));
        const left = a.tokens.filter((t) => !bad.includes(t) && !done.has(t));
        for (const t of left.slice(0, budget)) {
          budget--;
          try {
            const r = await fetch(`https://fcm.googleapis.com/v1/projects/${auth.project}/messages:send`, {
              method: "POST", headers: { Authorization: `Bearer ${auth.token}`, "Content-Type": "application/json" },
              body: JSON.stringify({ message: { token: t, data: a.msg, webpush: { headers: { Urgency: "high", TTL: "86400" } } } }),
            });
            if (r.ok) { st.sent++; sql.exec("INSERT INTO wtok (key, tok, at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING", a.key, t, now); }
            else if (r.status === 404 || r.status === 400) { const e = await r.text(); if (/UNREGISTERED|INVALID_ARGUMENT|not a valid FCM/i.test(e)) bad.push(t); else st.error = `send ${r.status}`; }
            else st.error = `send ${r.status}`;
          } catch (e) { st.error = String(e).slice(0, 120); }
        }
        const still = a.tokens.filter((t) => !bad.includes(t) && !done.has(t) && !sql.exec("SELECT 1 FROM wtok WHERE key = ? AND tok = ?", a.key, t).toArray().length);
        if (!still.length) sql.exec("INSERT INTO wsent (key, at) VALUES (?, ?) ON CONFLICT(key) DO NOTHING", a.key, now);
      }
      kvPut(sql, "bad_tokens", JSON.stringify(bad.slice(-200)));
    }
  }
  sql.exec("DELETE FROM wsent WHERE at < ?", now - KEEP_SENT_MS);
  sql.exec("DELETE FROM wtok WHERE at < ?", now - KEEP_SENT_MS);
  const total = Number(kvGet(sql, "sent_total") ?? 0) + st.sent;
  kvPut(sql, "sent_total", String(total));
  st.sent_total = total;
  kvPut(sql, "status", JSON.stringify(st));
  return st;
}

export function watchArm(sql: Sql, body: any): number {
  const list: Armed[] = (Array.isArray(body?.armed) ? body.armed : []).filter((a: any) =>
    a && typeof a.key === "string" && typeof a.pair === "string" && isFinite(Number(a.level)) && (a.side === 1 || a.side === -1)
    && a.msg && typeof a.msg.tag === "string" && Array.isArray(a.tokens)).slice(0, 2000);
  kvPut(sql, "armed", JSON.stringify(list));
  kvPut(sql, "engine_diag", JSON.stringify(body?.diag ?? null).slice(0, 2000));
  if (typeof body?.probe_token === "string") kvPut(sql, "probe_token", body.probe_token);
  kvPut(sql, "armed_at", String(Date.now()));
  return list.length;
}

export function watchStatus(sql: Sql, since: number) {
  const st = JSON.parse(kvGet(sql, "status") ?? "{}");
  const sent = sql.exec("SELECT key, at FROM wsent WHERE at >= ?", since).toArray().map((r: any) => [r.key, r.at]);
  return { ...st, sent_keys: sent, bad_tokens: JSON.parse(kvGet(sql, "bad_tokens") ?? "[]"), engine_diag: JSON.parse(kvGet(sql, "engine_diag") ?? "null") };
}
