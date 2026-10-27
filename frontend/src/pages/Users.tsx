import { collection, deleteDoc, doc, onSnapshot, updateDoc } from "firebase/firestore";
import { countryName, flagUrl, ONLINE_MS } from "../lib/presence";
import { useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Note } from "../components/ui";
import { db } from "../lib/firebase";
import { fmtTime } from "../lib/format";
import { daysLeft, fmtDate, grantMembership, markFree, MembershipConfig, planLabel, rejectPayment, saveMembershipConfig, useMembershipConfig } from "../lib/membership";
import { roleOf, useIsAdmin } from "../lib/session";
import { Limits, saveLimits, useLimits } from "../lib/limits";

type Filter = "todo" | "members" | "ending" | "expired" | "blocked" | "all";

/** Admin: check payment proofs, approve members for 1 / 3 / 6 / 12 months, extend, block, set prices. */
export default function Users() {
  const admin = useIsAdmin();
  const cfg = useMembershipConfig();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("todo");
  const [zoom, setZoom] = useState<string | null>(null);
  useEffect(() => (admin ? onSnapshot(collection(db, "users"), (q) => setRows(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => setErr(e.message)) : undefined), [admin]);
  const [states, setStates] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "user_state"), (q) => setStates(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [seen, setSeen] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "presence"), (q) => setSeen(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(id); }, []);
  if (!admin) return <Empty>Only the app owner can manage users.</Empty>;

  const all = rows ?? [];
  const todo = (u: any) => u.status === "pending" || u.payment?.status === "submitted";
  const role = (u: any) => roleOf(u);
  const ending = (u: any) => role(u) === "member" && u.expires_at && (daysLeft(u.expires_at) ?? 99) <= 7;
  const match: Record<Filter, (u: any) => boolean> = {
    todo, members: (u) => role(u) === "member", ending, expired: (u) => role(u) === "expired", blocked: (u) => u.status === "blocked", all: () => true,
  };
  const last = (u: any) => seen[u.id]?.last_seen ?? 0;
  const list = all.filter(match[filter]).sort((a, b) => Number(todo(b)) - Number(todo(a)) || last(b) - last(a) || (b.payment?.submitted_at ?? b.requested_at ?? 0) - (a.payment?.submitted_at ?? a.requested_at ?? 0));
  const now = Date.now();
  const within = (ms: number) => all.filter((u) => now - last(u) < ms).length;
  const byCountry = Object.entries(all.reduce((m: Record<string, number>, u) => { const c = seen[u.id]?.country; if (c) m[c] = (m[c] ?? 0) + 1; return m; }, {}))
    .sort((a, b) => b[1] - a[1]);
  const count = (f: Filter) => all.filter(match[f]).length;
  const act = async (fn: () => Promise<any>, ok: string | ((res: any) => string)) => { try { const res = await fn(); setErr(null); setMsg(typeof ok === "function" ? ok(res) : ok); } catch (e: any) { setErr(e.message); setMsg(null); } };
  const income = all.flatMap((u) => u.history ?? []).reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-semibold tracking-tight">Users & memberships</h1>
        <span className="num text-xs text-mute">{count("members")} active{all.filter((u) => u.free && match.members(u)).length ? ` (${all.filter((u) => u.free && match.members(u)).length} free)` : ""} · {income} USDT received in total</span>
      </div>
      <Card title="Activity">
        <div className="grid grid-cols-3 gap-3 text-center">
          <div><div className="num flex items-center justify-center gap-1.5 text-2xl font-semibold"><span className="h-2.5 w-2.5 rounded-full bg-bull" aria-hidden="true" />{within(ONLINE_MS)}</div><div className="text-xs text-mute">online now</div></div>
          <div><div className="num text-2xl font-semibold">{within(86_400_000)}</div><div className="text-xs text-mute">active today</div></div>
          <div><div className="num text-2xl font-semibold">{within(7 * 86_400_000)}</div><div className="text-xs text-mute">active this week</div></div>
        </div>
        {byCountry.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2 border-t border-glass/[0.06] pt-3">
            {byCountry.map(([c, n]) => (
              <span key={c} className="inline-flex items-center gap-1.5 rounded-lg border border-glass/10 px-2 py-1 text-xs">
                <Flag cc={c} />{countryName(c)}<span className="num text-mute">{n}</span>
              </span>
            ))}
          </div>
        )}
        <p className="mt-3 text-[11px] text-mute">Country is estimated from each device's time zone. People appear after they open the app once with this version.</p>
      </Card>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter">
        {([["todo", `To check (${count("todo")})`], ["members", `Active (${count("members")})`], ["ending", `Ending ≤7 days (${count("ending")})`],
          ["expired", `Expired (${count("expired")})`], ["blocked", `Blocked (${count("blocked")})`], ["all", `All (${all.length})`]] as const).map(([k, l]) => (
          <button key={k} className={`btn px-3 py-1 text-xs ${filter === k ? "btn-on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>
      {err && <ErrorBox error={err} />}
      {msg && <p className="text-sm text-bull">{msg}</p>}
      {rows == null ? <Empty>Loading…</Empty> : !list.length ? (
        <Card><Empty>{filter === "todo" ? "Nothing to check. New payment proofs appear here, and you get a notification." : "No one here."}</Empty></Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {list.map((u) => <UserCard key={u.id} u={u} st={states[u.id]} pr={seen[u.id]} cfg={cfg} act={act} onZoom={setZoom} />)}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2"><PricesCard cfg={cfg} act={act} /><LimitsCard act={act} total={all.length} /></div>
      <Note>Members pay with your Binance QR or by MEXC transfer to your UID, then upload a screenshot and/or the order ID. Check the payment arrived (Binance → Pay → History, or MEXC → Wallets → History) before approving. Approving adds the months after the current end date, so early renewals never lose days. When a membership ends, that person is locked out automatically until they renew; their paper accounts and alerts are kept. People approved before memberships existed have no end date until you give them a plan.</Note>
      {zoom && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4" onClick={() => setZoom(null)} role="dialog" aria-label="Payment proof">
          <img src={zoom} alt="Payment proof" className="max-h-full max-w-full rounded-xl" />
        </div>
      )}
    </div>
  );
}

function Flag({ cc }: { cc?: string | null }) {
  const [bad, setBad] = useState(false);
  const url = flagUrl(cc);
  if (!url || bad) return <span className="inline-flex h-3.5 w-5 items-center justify-center rounded-sm bg-glass/10 text-[8px] text-mute" aria-hidden="true">{cc ?? "?"}</span>;
  return <img src={url} alt="" width={20} height={14} className="h-3.5 w-5 rounded-sm object-cover ring-1 ring-glass/15" onError={() => setBad(true)} />;
}

function activeText(ts?: number): { text: string; on: boolean } {
  if (!ts) return { text: "not seen yet", on: false };
  const d = Date.now() - ts;
  if (d < ONLINE_MS) return { text: "online now", on: true };
  const m = Math.round(d / 60_000), h = Math.round(d / 3_600_000), days = Math.round(d / 86_400_000);
  return { text: m < 60 ? `${m} min ago` : h < 24 ? `${h} h ago` : days < 30 ? `${days} d ago` : fmtDate(ts), on: false };
}

function UserCard({ u, st, pr, cfg, act, onZoom }: { u: any; st?: any; pr?: any; cfg: MembershipConfig; act: (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void; onZoom: (s: string) => void }) {
  const p = u.payment;
  const r = roleOf(u);
  const [months, setMonths] = useState<number>(p?.months ?? 1);
  const price = cfg.plans.find((x) => x.months === months)?.price ?? null;
  const left = daysLeft(u.expires_at);
  const badge = r === "member" ? <Badge tone={left != null && left <= 7 ? "warn" : "bull"}>{u.free ? "free · " : ""}{left == null ? "member · no end date" : `member · ${left}d left`}</Badge>
    : r === "expired" ? <Badge tone="bear">expired</Badge> : r === "blocked" ? <Badge tone="bear">blocked</Badge> : <Badge tone="warn">waiting</Badge>;
  const paid = p?.status === "submitted" && p.amount != null && price != null && Number(p.amount) !== price && p.months === months;

  return (
    <div className={`panel p-4 ${p?.status === "submitted" ? "ring-1 ring-accent/50" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {u.photo ? <img src={u.photo} alt="" className="h-10 w-10 rounded-full" referrerPolicy="no-referrer" /> : <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accent/15 font-semibold text-accent">{(u.name || u.email || "?")[0].toUpperCase()}</div>}
          <div className="min-w-0">
            <div className="truncate font-medium">{u.name || u.email}</div>
            <div className="truncate text-xs text-mute">{u.email}</div>
            {(() => { const a = activeText(pr?.last_seen); return (
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px]">
                <span className={`inline-flex items-center gap-1 ${a.on ? "text-bull" : "text-mute"}`}><span className={`h-1.5 w-1.5 rounded-full ${a.on ? "bg-bull" : "bg-glass/30"}`} aria-hidden="true" />{a.text}</span>
                {pr?.country && <span className="inline-flex items-center gap-1 text-mute"><Flag cc={pr.country} />{countryName(pr.country)}</span>}
                {pr?.device && <span className="text-mute">· {pr.device}</span>}
              </div>); })()}
          </div>
        </div>
        {badge}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-mute">Asked</dt><dd className="text-right">{fmtTime(u.requested_at)}</dd>
        {u.expires_at && <><dt className="text-mute">Active until</dt><dd className="text-right">{fmtDate(u.expires_at)}</dd></>}
        {u.plan_months && <><dt className="text-mute">Last plan</dt><dd className="text-right">{planLabel(u.plan_months)}</dd></>}
        <dt className="text-mute">Notifications</dt><dd className={`text-right ${st?.push_error ? "text-bear" : st?.push_ok_at ? "text-bull" : "text-mute"}`}>{st?.push_error ? `failed ${fmtTime(st.push_error.at)}` : st?.push_ok_at ? `on since ${fmtDate(st.push_ok_at)}` : "not turned on"}</dd>
        {u.history?.length > 0 && <><dt className="text-mute">Payments</dt><dd className="num text-right">{u.free && !u.history.some((h: any) => Number(h.amount) > 0) ? "free (nothing paid)" : `${u.history.length} · ${u.history.reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0)} USDT`}</dd></>}
      </dl>

      {st?.push_error && (
        <p className="mt-2 rounded-lg border border-bear/30 bg-bear/10 px-2 py-1.5 text-[11px] text-bear">
          Notification error ({st.push_error.app}, step: {st.push_error.stage}): {st.push_error.code ? `${st.push_error.code} · ` : ""}{st.push_error.message}
        </p>
      )}
      {p && (
        <div className={`mt-3 rounded-xl border p-3 ${p.status === "submitted" ? "border-accent/40 bg-accent/[0.06]" : "border-glass/10 bg-glass/[0.02]"}`}>
          <div className="flex items-center justify-between gap-2 text-sm">
            <span className="font-semibold">{p.status === "submitted" ? "Payment proof to check" : p.status === "accepted" ? "Last payment · accepted" : "Last payment · rejected"}</span>
            <span className="num text-accent">{p.amount} {p.currency} · {planLabel(p.months)}</span>
          </div>
          <div className="mt-2 flex gap-3">
            {p.proof ? <button onClick={() => onZoom(p.proof)} className="shrink-0" title="Open full size"><img src={p.proof} alt="Payment screenshot" className="h-24 w-16 rounded-md object-cover ring-1 ring-glass/20" /></button>
              : <div className="flex h-24 w-16 shrink-0 items-center justify-center rounded-md bg-glass/[0.04] text-center text-[10px] text-mute">no screenshot</div>}
            <dl className="grid min-w-0 flex-1 grid-cols-[auto_1fr] content-start gap-x-3 gap-y-1 text-xs">
              <dt className="text-mute">Paid with</dt><dd className="text-right">{p.method === "mexc" ? "MEXC" : "Binance"}</dd>
              <dt className="text-mute">Order ID</dt><dd className="num truncate text-right">{p.txid || "—"}</dd>
              <dt className="text-mute">Sent</dt><dd className="text-right">{fmtTime(p.submitted_at)}</dd>
              {p.reason && <><dt className="text-mute">Reason</dt><dd className="truncate text-right">{p.reason}</dd></>}
            </dl>
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select className="input w-auto py-1 text-xs" value={months} onChange={(e) => setMonths(Number(e.target.value))} aria-label="Plan">
          {cfg.plans.map((x) => <option key={x.months} value={x.months}>{x.label} · ${x.price}</option>)}
        </select>
        <button className="btn btn-primary px-3 py-1 text-xs" onClick={() => act(
          () => grantMembership(u.id, u, months, p?.status === "submitted" ? Number(p.amount) : price),
          (to: number) => `${u.email}: member until ${fmtDate(to)}.`)}>
          {r === "member" ? `Extend +${planLabel(months)} (paid)` : p?.status === "submitted" ? `Accept · ${planLabel(months)}` : `Approve · paid · ${planLabel(months)}`}
        </button>
        <button className="btn px-3 py-1 text-xs" title="Complimentary access (testers): recorded as 0 USDT, not counted as income" onClick={() => act(
          () => grantMembership(u.id, u, months, 0, true),
          (to: number) => `${u.email}: free member until ${fmtDate(to)}.`)}>
          Free · {planLabel(months)}
        </button>
        {!u.free && (u.history ?? []).some((h: any) => Number(h.amount) > 0) && <button className="btn px-3 py-1 text-xs" title="Nothing was actually paid: set their recorded payments to 0 USDT (dates stay the same)" onClick={() => {
          if (window.confirm(`Mark ${u.email} as a free member? Their recorded payments become 0 USDT; their end date stays the same.`)) act(() => markFree(u.id, u), `${u.email} marked as free.`);
        }}>Mark as free (nothing paid)</button>}
        {p?.status === "submitted" && <button className="btn px-3 py-1 text-xs hover:text-bear" onClick={() => {
          const why = window.prompt("Why is the proof not accepted? (shown to the person)", "Payment not found in my Binance history");
          if (why !== null) act(() => rejectPayment(u.id, u, why), `Proof from ${u.email} rejected.`);
        }}>Reject proof</button>}
        {u.status !== "blocked" ? <button className="btn px-3 py-1 text-xs hover:text-bear" onClick={() => act(() => updateDoc(doc(db, "users", u.id), { status: "blocked", changed_at: Date.now() }), `${u.email} blocked.`)}>Block</button>
          : <button className="btn px-3 py-1 text-xs" onClick={() => act(() => updateDoc(doc(db, "users", u.id), { status: "pending", changed_at: Date.now() }), `${u.email} unblocked (waiting).`)}>Unblock</button>}
        <button className="btn px-3 py-1 text-xs text-mute" title="Delete the record: they can ask again" onClick={() => { if (window.confirm(`Delete ${u.email}? They can request access again later.`)) act(() => deleteDoc(doc(db, "users", u.id)), `${u.email} deleted.`); }}>Delete</button>
      </div>
      {paid && <p className="mt-2 text-xs text-warn">The proof is for {p.amount} {p.currency}; the current price of this plan is ${price}.</p>}
    </div>
  );
}

function PricesCard({ cfg, act }: { cfg: MembershipConfig; act: (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void }) {
  const [draft, setDraft] = useState<MembershipConfig | null>(null);
  const c = draft ?? cfg;
  const setPrice = (m: number, v: string) => setDraft({ ...c, plans: c.plans.map((p) => (p.months === m ? { ...p, price: Number(v) || 0 } : p)) });
  return (
    <Card title="Membership prices, payment & support">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {c.plans.map((p) => (
          <label key={p.months} className="text-xs text-mute">{p.label} (USD)
            <input className="input num mt-1" inputMode="decimal" value={p.price} onChange={(e) => setPrice(p.months, e.target.value)} />
          </label>
        ))}
      </div>
      <label className="mt-3 block text-xs text-mute">Payment note shown to members
        <textarea className="input mt-1 min-h-[60px]" value={c.pay_note} onChange={(e) => setDraft({ ...c, pay_note: e.target.value })} />
      </label>
      <label className="mt-3 block text-xs text-mute">Support email members can contact
        <input className="input mt-1" type="email" inputMode="email" value={c.support_email} onChange={(e) => setDraft({ ...c, support_email: e.target.value.trim() })} />
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn btn-primary" disabled={!draft} onClick={() => act(async () => {
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.support_email)) throw new Error("Enter a valid support email address.");
          await saveMembershipConfig(c); setDraft(null);
        }, "Saved.")}>Save</button>
        <img src={c.qr_url} alt="Your Binance Pay QR" className="h-16 rounded-md bg-white p-0.5" />
        <span className="text-xs text-mute">Your Binance Pay QR shown to members.</span>
      </div>
    </Card>
  );
}

function LimitsCard({ act, total }: { act: (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void; total: number }) {
  const cur = useLimits();
  const [draft, setDraft] = useState<Limits | null>(null);
  const l = draft ?? cur;
  const step = (k: keyof Limits, d: number, max: number) => setDraft({ ...l, [k]: Math.max(0, Math.min(max, Number(l[k]) + d)) });
  const field = (k: keyof Limits, label: string, help: string, max: number) => (
    <div>
      <div className="text-xs text-mute">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <button className="btn h-10 w-10 justify-center p-0 text-lg" aria-label={`Decrease ${label}`} onClick={() => step(k, -1, max)}>−</button>
        <input className="input num w-20 text-center" inputMode="numeric" aria-label={label} value={l[k]} onChange={(e) => setDraft({ ...l, [k]: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
        <button className="btn h-10 w-10 justify-center p-0 text-lg" aria-label={`Increase ${label}`} onClick={() => step(k, 1, max)}>+</button>
      </div>
      <p className="mt-1 text-xs text-mute">{help}</p>
    </div>
  );
  return (
    <Card title="Limits">
      <div className="grid gap-4 sm:grid-cols-2">
        {field("member_coin_limit", "Coins each member can add", "0 turns personal coins off. Lowering it keeps their first coins.", 50)}
        {field("member_coins_max", "Member coins in total", "On top of your own list. More coins = longer engine runs.", 200)}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button className="btn btn-primary" disabled={!draft} onClick={() => act(async () => { await saveLimits(l); setDraft(null); }, "Limits saved. The engine uses them on its next run.")}>Save limits</button>
        <span className="text-xs text-mute">Users: no limit · {total} signed up so far</span>
      </div>
    </Card>
  );
}
