import { collection, deleteDoc, doc, onSnapshot, updateDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Note } from "../components/ui";
import { db } from "../lib/firebase";
import { fmtTime } from "../lib/format";
import { daysLeft, fmtDate, grantMembership, MembershipConfig, planLabel, rejectPayment, saveMembershipConfig, useMembershipConfig } from "../lib/membership";
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
  if (!admin) return <Empty>Only the app owner can manage users.</Empty>;

  const all = rows ?? [];
  const todo = (u: any) => u.status === "pending" || u.payment?.status === "submitted";
  const role = (u: any) => roleOf(u);
  const ending = (u: any) => role(u) === "member" && u.expires_at && (daysLeft(u.expires_at) ?? 99) <= 7;
  const match: Record<Filter, (u: any) => boolean> = {
    todo, members: (u) => role(u) === "member", ending, expired: (u) => role(u) === "expired", blocked: (u) => u.status === "blocked", all: () => true,
  };
  const list = all.filter(match[filter]).sort((a, b) => Number(todo(b)) - Number(todo(a)) || (b.payment?.submitted_at ?? b.requested_at ?? 0) - (a.payment?.submitted_at ?? a.requested_at ?? 0));
  const count = (f: Filter) => all.filter(match[f]).length;
  const act = async (fn: () => Promise<any>, ok: string | ((res: any) => string)) => { try { const res = await fn(); setErr(null); setMsg(typeof ok === "function" ? ok(res) : ok); } catch (e: any) { setErr(e.message); setMsg(null); } };
  const income = all.flatMap((u) => u.history ?? []).reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-xl font-semibold tracking-tight">Users & memberships</h1>
        <span className="num text-xs text-mute">{count("members")} active · ${income} received in total</span>
      </div>
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
          {list.map((u) => <UserCard key={u.id} u={u} cfg={cfg} act={act} onZoom={setZoom} />)}
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2"><PricesCard cfg={cfg} act={act} /><LimitsCard act={act} total={all.length} /></div>
      <Note>Members pay with your Binance QR and upload a screenshot and/or the Binance order ID. Check the payment arrived in your Binance app (Pay → History) before approving. Approving adds the months after the current end date, so early renewals never lose days. When a membership ends, that person is locked out automatically until they renew; their paper accounts and alerts are kept. People approved before memberships existed have no end date until you give them a plan.</Note>
      {zoom && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-4" onClick={() => setZoom(null)} role="dialog" aria-label="Payment proof">
          <img src={zoom} alt="Payment proof" className="max-h-full max-w-full rounded-xl" />
        </div>
      )}
    </div>
  );
}

function UserCard({ u, cfg, act, onZoom }: { u: any; cfg: MembershipConfig; act: (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void; onZoom: (s: string) => void }) {
  const p = u.payment;
  const r = roleOf(u);
  const [months, setMonths] = useState<number>(p?.months ?? 1);
  const price = cfg.plans.find((x) => x.months === months)?.price ?? null;
  const left = daysLeft(u.expires_at);
  const badge = r === "member" ? <Badge tone={left != null && left <= 7 ? "warn" : "bull"}>{left == null ? "member · no end date" : `member · ${left}d left`}</Badge>
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
          </div>
        </div>
        {badge}
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-mute">Asked</dt><dd className="text-right">{fmtTime(u.requested_at)}</dd>
        {u.expires_at && <><dt className="text-mute">Active until</dt><dd className="text-right">{fmtDate(u.expires_at)}</dd></>}
        {u.plan_months && <><dt className="text-mute">Last plan</dt><dd className="text-right">{planLabel(u.plan_months)}</dd></>}
        {u.history?.length > 0 && <><dt className="text-mute">Payments</dt><dd className="num text-right">{u.history.length} · ${u.history.reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0)}</dd></>}
      </dl>

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
          {r === "member" ? `Extend +${planLabel(months)}` : p?.status === "submitted" ? `Accept · ${planLabel(months)}` : `Approve · ${planLabel(months)}`}
        </button>
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
