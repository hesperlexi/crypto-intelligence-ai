import { collection, deleteDoc, doc, onSnapshot, updateDoc } from "firebase/firestore";
import { countryName, flagUrl, ONLINE_MS } from "../lib/presence";
import { ReactNode, useCallback, useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Note } from "../components/ui";
import { useFocusTrap } from "../components/Shell";
import { db } from "../lib/firebase";
import { fmtTime } from "../lib/format";
import { daysLeft, fmtDate, grantMembership, markFree, MembershipConfig, planLabel, rejectPayment, saveMembershipConfig, useMembershipConfig } from "../lib/membership";
import { roleOf, useIsAdmin } from "../lib/session";
import { Limits, saveLimits, useLimits } from "../lib/limits";

type Filter = "todo" | "members" | "ending" | "expired" | "blocked" | "all";
type Act = (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void;

const todo = (u: any) => u.status === "pending" || u.payment?.status === "submitted";
const ending = (u: any) => roleOf(u) === "member" && u.expires_at && (daysLeft(u.expires_at) ?? 99) <= 7;
const MATCH: Record<Filter, (u: any) => boolean> = {
  todo, members: (u) => roleOf(u) === "member", ending, expired: (u) => roleOf(u) === "expired", blocked: (u) => u.status === "blocked", all: () => true,
};
const FILTERS: [Filter, string][] = [["todo", "To check"], ["members", "Active"], ["ending", "Ending ≤7 days"], ["expired", "Expired"], ["blocked", "Blocked"], ["all", "All"]];

/** Admin: check payment proofs, approve members for 1 / 3 / 6 / 12 months, extend, block, set prices and limits. */
export default function Users() {
  const admin = useIsAdmin();
  const cfg = useMembershipConfig();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("todo");
  const [q, setQ] = useState("");
  const [proofOf, setProofOf] = useState<string | null>(null);
  useEffect(() => (admin ? onSnapshot(collection(db, "users"), (q) => setRows(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => setErr(e.message)) : undefined), [admin]);
  const [states, setStates] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "user_state"), (q) => setStates(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [seen, setSeen] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "presence"), (q) => setSeen(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(id); }, []);
  if (!admin) return <Empty>Only the app owner can manage users.</Empty>;

  const all = rows ?? [];
  const last = (u: any) => seen[u.id]?.last_seen ?? 0;
  const needle = q.trim().toLowerCase();
  const list = all.filter(MATCH[filter])
    .filter((u) => !needle || `${u.name ?? ""} ${u.email ?? ""} ${u.username ?? ""} ${u.payment?.txid ?? ""}`.toLowerCase().includes(needle))
    .sort((a, b) => Number(todo(b)) - Number(todo(a)) || last(b) - last(a) || (b.payment?.submitted_at ?? b.requested_at ?? 0) - (a.payment?.submitted_at ?? a.requested_at ?? 0));
  const now = Date.now();
  const within = (ms: number) => all.filter((u) => now - last(u) < ms).length;
  const byCountry = Object.entries(all.reduce((m: Record<string, number>, u) => { const c = seen[u.id]?.country; if (c) m[c] = (m[c] ?? 0) + 1; return m; }, {}))
    .sort((a, b) => b[1] - a[1]);
  const count = (f: Filter) => all.filter(MATCH[f]).length;
  const free = all.filter((u) => u.free && MATCH.members(u)).length;
  const act: Act = async (fn, ok) => { try { const res = await fn(); setErr(null); setMsg(typeof ok === "function" ? ok(res) : ok); } catch (e: any) { setErr(e.message); setMsg(null); } };
  const income = all.flatMap((u) => u.history ?? []).reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0);
  const proofUser = proofOf ? all.find((u) => u.id === proofOf) : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="page-title">Users & memberships</h1>
          <p className="page-sub">Check payment proofs, approve and extend memberships, and see who is using the app.</p>
        </div>
        <span className="num text-xs text-mute">{all.length} accounts · {income} USDT received in total</span>
      </div>

      {/* summary */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SummaryTile label="Waiting to check" value={count("todo")} tone={count("todo") ? "accent" : undefined} sub="new requests and payment proofs" onClick={() => setFilter("todo")} active={filter === "todo"} />
        <SummaryTile label="Active members" value={count("members")} sub={free ? `${free} free` : "paying and free"} onClick={() => setFilter("members")} active={filter === "members"} />
        <SummaryTile label="Ending in 7 days" value={count("ending")} tone={count("ending") ? "warn" : undefined} sub="remind or extend" onClick={() => setFilter("ending")} active={filter === "ending"} />
        <SummaryTile label="Expired" value={count("expired")} tone={count("expired") ? "bear" : undefined} sub="locked out until renewal" onClick={() => setFilter("expired")} active={filter === "expired"} />
      </div>

      <Card title="Activity" right={<span className="text-[11px] text-mute">country from each device's time zone</span>}>
        <div className="grid grid-cols-3 gap-3 text-center">
          <ActivityNum n={within(ONLINE_MS)} label="online now" dot />
          <ActivityNum n={within(86_400_000)} label="active today" />
          <ActivityNum n={within(7 * 86_400_000)} label="active this week" />
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
        <p className="mt-3 text-[11px] text-mute">People appear after they open the app once with this version.</p>
      </Card>

      {/* search + status tabs */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="seg max-w-full overflow-x-auto" role="group" aria-label="Filter by status">
          {FILTERS.map(([k, l]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)} className="whitespace-nowrap">
              {l} <span className="num opacity-70">{k === "all" ? all.length : count(k)}</span>
            </button>
          ))}
        </div>
        <label className="sm:w-64">
          <span className="sr-only">Search users</span>
          <input className="input input-sm" type="search" placeholder="Search name, username, email or order ID" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </div>
      {err && <ErrorBox error={err} />}
      {msg && <p className="rounded-lg border border-bull/30 bg-bull/[0.08] px-3 py-2 text-sm text-bull" role="status">{msg}</p>}

      {rows == null ? <Card><Empty>Loading…</Empty></Card> : !list.length ? (
        <Card><Empty>{needle ? "No one matches this search." : filter === "todo" ? "Nothing to check. New payment proofs appear here, and you get a notification." : "No one here."}</Empty></Card>
      ) : (
        <>
          {/* computer: table */}
          <section className="panel relative z-10 hidden p-0 lg:block">
            <table className="grid-table">
              <thead>
                <tr><th>Member</th><th>Status</th><th>Plan / until</th><th>Payment</th><th>Last seen</th><th>Where / device</th><th className="text-right">Actions</th></tr>
              </thead>
              <tbody>
                {list.map((u) => <UserRow key={u.id} u={u} st={states[u.id]} pr={seen[u.id]} cfg={cfg} act={act} onProof={() => setProofOf(u.id)} />)}
              </tbody>
            </table>
          </section>
          {/* phone / tablet: cards */}
          <div className="relative z-10 grid gap-3 md:grid-cols-2 lg:hidden">
            {list.map((u) => <UserCard key={u.id} u={u} st={states[u.id]} pr={seen[u.id]} cfg={cfg} act={act} onProof={() => setProofOf(u.id)} />)}
          </div>
        </>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-2"><PricesCard cfg={cfg} act={act} /><LimitsCard act={act} total={all.length} /></div>
      <Note>Members pay with your Binance QR or by MEXC transfer to your UID, then upload a screenshot and/or the order ID. Check the payment arrived (Binance → Pay → History, or MEXC → Wallets → History) before approving. Approving adds the months after the current end date, so early renewals never lose days. When a membership ends, that person is locked out automatically until they renew; their paper accounts and alerts are kept. People approved before memberships existed have no end date until you give them a plan.</Note>
      {proofUser && <ProofViewer u={proofUser} cfg={cfg} act={act} onClose={() => setProofOf(null)} />}
    </div>
  );
}

function SummaryTile({ label, value, sub, tone, onClick, active }: { label: string; value: number; sub: string; tone?: "accent" | "warn" | "bear"; onClick: () => void; active: boolean }) {
  const cls = tone === "accent" ? "text-accent" : tone === "warn" ? "text-warn" : tone === "bear" ? "text-bear" : "text-text";
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`panel p-4 text-left transition-colors hover:border-accent/40 ${active ? "ring-1 ring-accent/50" : ""}`}>
      <div className="label">{label}</div>
      <div className={`num mt-1.5 text-2xl font-semibold leading-none ${cls}`}>{value}</div>
      <div className="mt-1.5 text-[11px] text-mute">{sub}</div>
    </button>
  );
}

function ActivityNum({ n, label, dot = false }: { n: number; label: string; dot?: boolean }) {
  return (
    <div>
      <div className="num flex items-center justify-center gap-1.5 text-2xl font-semibold">{dot && <span className="h-2.5 w-2.5 rounded-full bg-bull" aria-hidden="true" />}{n}</div>
      <div className="text-xs text-mute">{label}</div>
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

function Avatar({ u, size = 36 }: { u: any; size?: number }) {
  return u.photo
    ? <img src={u.photo} alt="" width={size} height={size} className="shrink-0 rounded-full" style={{ width: size, height: size }} referrerPolicy="no-referrer" />
    : <div className="flex shrink-0 items-center justify-center rounded-full bg-accent/15 font-semibold text-accent" style={{ width: size, height: size }}>{(u.name || u.email || "?")[0].toUpperCase()}</div>;
}

function StatusBadge({ u }: { u: any }) {
  const r = roleOf(u);
  const left = daysLeft(u.expires_at);
  if (r === "member") return <Badge tone={left != null && left <= 7 ? "warn" : "bull"}>{u.free ? "free · " : ""}{left == null ? "member" : `member · ${left}d left`}</Badge>;
  if (r === "expired") return <Badge tone="bear">expired</Badge>;
  if (r === "blocked") return <Badge tone="bear">blocked</Badge>;
  return <Badge tone="warn">waiting</Badge>;
}

function Seen({ pr }: { pr?: any }) {
  const a = activeText(pr?.last_seen);
  return <span className={`inline-flex items-center gap-1.5 ${a.on ? "text-bull" : "text-mute"}`}><span className={`h-1.5 w-1.5 rounded-full ${a.on ? "bg-bull" : "bg-glass/30"}`} aria-hidden="true" />{a.text}</span>;
}

function Where({ pr }: { pr?: any }) {
  if (!pr?.country && !pr?.device) return <span className="text-mute">—</span>;
  return (
    <span className="inline-flex flex-col gap-0.5 text-xs">
      {pr?.country && <span className="inline-flex items-center gap-1.5"><Flag cc={pr.country} />{countryName(pr.country)}</span>}
      {pr?.device && <span className="text-mute">{pr.device}</span>}
    </span>
  );
}

function paidLine(u: any): string | null {
  if (!u.history?.length) return null;
  if (u.free && !u.history.some((h: any) => Number(h.amount) > 0)) return "free (nothing paid)";
  return `${u.history.length} payment${u.history.length === 1 ? "" : "s"} · ${u.history.reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0)} USDT`;
}

/** The plan picker and every action for one person. Each button calls exactly the same function as before. */
function useUserActions(u: any, cfg: MembershipConfig, act: Act) {
  const p = u.payment;
  const r = roleOf(u);
  const [months, setMonths] = useState<number>(p?.months ?? 1);
  const price = cfg.plans.find((x) => x.months === months)?.price ?? null;
  const mismatch = p?.status === "submitted" && p.amount != null && price != null && Number(p.amount) !== price && p.months === months;
  const grantLabel = r === "member" ? `Extend +${planLabel(months)} (paid)` : p?.status === "submitted" ? `Accept · ${planLabel(months)}` : `Approve · paid · ${planLabel(months)}`;
  const grant = () => act(() => grantMembership(u.id, u, months, p?.status === "submitted" ? Number(p.amount) : price), (to: number) => `${u.email}: member until ${fmtDate(to)}.`);
  const grantFree = () => act(() => grantMembership(u.id, u, months, 0, true), (to: number) => `${u.email}: free member until ${fmtDate(to)}.`);
  const canMarkFree = !u.free && (u.history ?? []).some((h: any) => Number(h.amount) > 0);
  const doMarkFree = () => { if (window.confirm(`Mark ${u.email} as a free member? Their recorded payments become 0 USDT; their end date stays the same.`)) act(() => markFree(u.id, u), `${u.email} marked as free.`); };
  const reject = () => {
    const why = window.prompt("Why is the proof not accepted? (shown to the person)", "Payment not found in my Binance history");
    if (why !== null) act(() => rejectPayment(u.id, u, why), `Proof from ${u.email} rejected.`);
  };
  const block = () => { if (window.confirm(`Block ${u.email}? They lose access straight away.`)) act(() => updateDoc(doc(db, "users", u.id), { status: "blocked", changed_at: Date.now() }), `${u.email} blocked.`); };
  const unblock = () => act(() => updateDoc(doc(db, "users", u.id), { status: "pending", changed_at: Date.now() }), `${u.email} unblocked (waiting).`);
  const remove = () => { if (window.confirm(`Delete ${u.email}? They can request access again later.`)) act(() => deleteDoc(doc(db, "users", u.id)), `${u.email} deleted.`); };
  const picker = (
    <select className="input input-sm w-auto" value={months} onChange={(e) => setMonths(Number(e.target.value))} aria-label={`Plan for ${u.email}`}>
      {cfg.plans.map((x) => <option key={x.months} value={x.months}>{x.label} · ${x.price}</option>)}
    </select>
  );
  return { p, r, months, price, mismatch, grantLabel, grant, grantFree, canMarkFree, doMarkFree, reject, block, unblock, remove, picker };
}

/** "More" menu for the less common and destructive actions. */
function MoreMenu({ items }: { items: [string, () => void, boolean?][] }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return;
    const h = () => setOpen(false);
    const t = window.setTimeout(() => document.addEventListener("click", h), 0);
    return () => { window.clearTimeout(t); document.removeEventListener("click", h); };
  }, [open]);
  return (
    <div className="relative">
      <button type="button" className="btn btn-sm px-2" aria-haspopup="menu" aria-expanded={open} aria-label="More actions" onClick={() => setOpen((v) => !v)}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-52">
        <div role="menu" className="panel popover animate-in p-1" onKeyDown={(e) => e.key === "Escape" && close()}>
          {items.map(([label, fn, danger]) => (
            <button key={label} role="menuitem" type="button" onClick={() => { setOpen(false); fn(); }}
              className={`block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-glass/[0.06] ${danger ? "text-bear" : ""}`}>{label}</button>
          ))}
        </div>
        </div>
      )}
    </div>
  );
}

function moreItems(a: ReturnType<typeof useUserActions>, u: any): [string, () => void, boolean?][] {
  return [
    [`Free · ${planLabel(a.months)}`, a.grantFree],
    ...(a.canMarkFree ? [["Mark as free (nothing paid)", a.doMarkFree] as [string, () => void]] : []),
    ...(a.p?.status === "submitted" ? [["Reject proof…", a.reject, true] as [string, () => void, boolean]] : []),
    u.status !== "blocked" ? ["Block…", a.block, true] : ["Unblock", a.unblock],
    ["Delete…", a.remove, true],
  ];
}

function PaymentCell({ u, onProof }: { u: any; onProof: () => void }) {
  const p = u.payment;
  if (!p) return <span className="text-xs text-mute">{paidLine(u) ?? "—"}</span>;
  const tone = p.status === "submitted" ? "text-accent" : p.status === "accepted" ? "text-bull" : "text-bear";
  return (
    <div className="text-xs">
      <div className="num"><span className="font-semibold text-text">{p.amount} {p.currency}</span> · {planLabel(p.months)}</div>
      <div className="mt-0.5 flex items-center gap-2">
        <span className={tone}>{p.status === "submitted" ? "to check" : p.status}</span>
        <button type="button" className="text-accent hover:underline" onClick={onProof}>{p.proof ? "View proof" : "Details"}</button>
      </div>
    </div>
  );
}

/** Username and sign-in method (accounts made before 31 Oct 2026 have neither field: they used Google). */
function Ident({ u }: { u: any }) {
  const how = u.provider === "password" ? "Email & password" : "Google";
  return (
    <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-mute">
      {u.username ? <span className="truncate font-medium text-text/90">@{u.username}</span> : <span className="italic">no username yet</span>}
      <span className="rounded border border-glass/15 px-1 leading-4" title={`Signs in with ${how}`}>{u.provider === "password" ? "Email" : "Google"}</span>
    </div>
  );
}

function UserRow({ u, st, pr, cfg, act, onProof }: { u: any; st?: any; pr?: any; cfg: MembershipConfig; act: Act; onProof: () => void }) {
  const a = useUserActions(u, cfg, act);
  return (
    <tr className={a.p?.status === "submitted" ? "[&>td]:!bg-accent/[0.05]" : ""}>
      <td className="max-w-[16rem]">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar u={u} />
          <div className="min-w-0">
            <div className="truncate font-medium">{u.name || (u.username ? `@${u.username}` : u.email)}</div>
            <div className="truncate text-xs text-mute">{u.email}</div>
            <Ident u={u} />
            {st?.push_error && <div className="truncate text-[11px] text-bear" title={st.push_error.message}>notifications failing</div>}
          </div>
        </div>
      </td>
      <td><StatusBadge u={u} /></td>
      <td className="text-xs">
        {u.expires_at ? <div className="num">{fmtDate(u.expires_at)}</div> : roleOf(u) === "member" ? <div className="text-mute">no end date</div> : null}
        <div className="text-mute">{u.plan_months ? planLabel(u.plan_months) : `asked ${fmtDate(u.requested_at)}`}</div>
      </td>
      <td><PaymentCell u={u} onProof={onProof} /></td>
      <td className="text-xs"><Seen pr={pr} /></td>
      <td><Where pr={pr} /></td>
      <td>
        <div className="flex items-center justify-end gap-1.5">
          {a.picker}
          <button type="button" className="btn btn-sm btn-primary" onClick={a.grant}>{a.grantLabel}</button>
          <MoreMenu items={moreItems(a, u)} />
        </div>
        {a.mismatch && <div className="mt-1 text-right text-[11px] text-warn">Proof is {a.p.amount} {a.p.currency}; plan price is ${a.price}.</div>}
      </td>
    </tr>
  );
}

function UserCard({ u, st, pr, cfg, act, onProof }: { u: any; st?: any; pr?: any; cfg: MembershipConfig; act: Act; onProof: () => void }) {
  const a = useUserActions(u, cfg, act);
  const p = a.p;
  return (
    <div className={`panel p-4 ${p?.status === "submitted" ? "ring-1 ring-accent/50" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar u={u} size={40} />
          <div className="min-w-0">
            <div className="truncate font-medium">{u.name || (u.username ? `@${u.username}` : u.email)}</div>
            <div className="truncate text-xs text-mute">{u.email}</div>
            <Ident u={u} />
          </div>
        </div>
        <StatusBadge u={u} />
      </div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
        <Dt>Last seen</Dt><Dd><Seen pr={pr} /></Dd>
        {(pr?.country || pr?.device) && <><Dt>Where</Dt><Dd>{[pr?.country && countryName(pr.country), pr?.device].filter(Boolean).join(" · ")}</Dd></>}
        <Dt>Asked</Dt><Dd>{fmtTime(u.requested_at)}</Dd>
        {u.expires_at && <><Dt>Active until</Dt><Dd>{fmtDate(u.expires_at)}</Dd></>}
        {u.plan_months && <><Dt>Last plan</Dt><Dd>{planLabel(u.plan_months)}</Dd></>}
        <Dt>Notifications</Dt><Dd className={st?.push_error ? "text-bear" : st?.push_ok_at ? "text-bull" : "text-mute"}>{st?.push_error ? `failed ${fmtTime(st.push_error.at)}` : st?.push_ok_at ? `on since ${fmtDate(st.push_ok_at)}` : "not turned on"}</Dd>
        {paidLine(u) && <><Dt>Payments</Dt><Dd className="num">{paidLine(u)}</Dd></>}
      </dl>
      {st?.push_error && (
        <p className="mt-2 rounded-lg border border-bear/30 bg-bear/10 px-2 py-1.5 text-[11px] text-bear">
          Notification error ({st.push_error.app}, step: {st.push_error.stage}): {st.push_error.code ? `${st.push_error.code} · ` : ""}{st.push_error.message}
        </p>
      )}
      {p && (
        <button type="button" onClick={onProof} className={`mt-3 flex w-full items-center gap-3 rounded-xl border p-3 text-left ${p.status === "submitted" ? "border-accent/40 bg-accent/[0.06]" : "border-glass/10 bg-glass/[0.02]"}`}>
          {p.proof ? <img src={p.proof} alt="" className="h-14 w-10 shrink-0 rounded-md object-cover ring-1 ring-glass/20" /> : <span className="flex h-14 w-10 shrink-0 items-center justify-center rounded-md bg-glass/[0.05] text-[10px] text-mute">no image</span>}
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">{p.status === "submitted" ? "Payment proof to check" : p.status === "accepted" ? "Last payment · accepted" : "Last payment · rejected"}</span>
            <span className="num block text-xs text-accent">{p.amount} {p.currency} · {planLabel(p.months)} · {p.method === "mexc" ? "MEXC" : "Binance"}</span>
          </span>
          <span className="text-xs text-accent">Open</span>
        </button>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {a.picker}
        <button type="button" className="btn btn-sm btn-primary flex-1" onClick={a.grant}>{a.grantLabel}</button>
        <MoreMenu items={moreItems(a, u)} />
      </div>
      {a.mismatch && <p className="mt-2 text-xs text-warn">The proof is for {p.amount} {p.currency}; the current price of this plan is ${a.price}.</p>}
    </div>
  );
}

const Dt = ({ children }: { children: ReactNode }) => <dt className="text-mute">{children}</dt>;
const Dd = ({ children, className = "" }: { children: ReactNode; className?: string }) => <dd className={`min-w-0 truncate text-right ${className}`}>{children}</dd>;

/** Full-size payment proof with its details and the same accept / extend / reject actions. */
function ProofViewer({ u, cfg, act, onClose }: { u: any; cfg: MembershipConfig; act: Act; onClose: () => void }) {
  const a = useUserActions(u, cfg, act);
  const p = a.p ?? {};
  const ref = useFocusTrap(true, onClose);
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center bg-black/75 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={`Payment proof from ${u.email}`} onClick={(e) => e.stopPropagation()}
        className="panel popover animate-in flex max-h-[92dvh] w-full max-w-3xl flex-col overflow-hidden rounded-b-none sm:rounded-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-glass/[0.08] px-4 py-3">
          <div className="flex min-w-0 items-center gap-3"><Avatar u={u} /><div className="min-w-0"><div className="truncate font-medium">{u.name || u.email}</div><div className="truncate text-xs text-mute">{u.email}</div></div></div>
          <button type="button" className="btn btn-ghost btn-sm px-2" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 md:grid md:grid-cols-[minmax(0,1fr)_16rem] md:gap-4 md:space-y-0">
          <div className="flex min-h-[12rem] min-w-0 shrink-0 items-center justify-center rounded-xl bg-black/40 p-2">
            {p.proof ? <a href={p.proof} target="_blank" rel="noopener" title="Open the original" className="block max-w-full"><img src={p.proof} alt="Payment screenshot" className="mx-auto block max-h-[40dvh] max-w-full rounded-lg object-contain md:max-h-[64dvh]" /></a>
              : <p className="text-sm text-mute">No screenshot was uploaded. Check the order ID in your exchange history.</p>}
          </div>
          <div className="space-y-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <Dt>Status</Dt><Dd className={p.status === "submitted" ? "text-accent" : p.status === "accepted" ? "text-bull" : "text-bear"}>{p.status === "submitted" ? "to check" : p.status ?? "—"}</Dd>
              <Dt>Amount</Dt><Dd className="num font-semibold">{p.amount ?? "—"} {p.currency}</Dd>
              <Dt>Plan</Dt><Dd>{p.months ? planLabel(p.months) : "—"}</Dd>
              <Dt>Paid with</Dt><Dd>{p.method === "mexc" ? "MEXC" : "Binance"}</Dd>
              <Dt>Order ID</Dt><Dd className="num whitespace-normal break-all">{p.txid || "—"}</Dd>
              <Dt>Sent</Dt><Dd>{fmtTime(p.submitted_at)}</Dd>
              {p.reason && <><Dt>Reason</Dt><Dd className="whitespace-normal">{p.reason}</Dd></>}
              <Dt>Member</Dt><Dd><StatusBadge u={u} /></Dd>
            </dl>
            <div className="space-y-2 border-t border-glass/[0.08] pt-4">
              <label className="block text-xs text-mute">Plan to grant<div className="mt-1 [&>select]:w-full">{a.picker}</div></label>
              <button type="button" className="btn btn-primary w-full" onClick={() => { a.grant(); onClose(); }}>{a.grantLabel}</button>
              <div className="grid grid-cols-2 gap-2">
                <button type="button" className="btn btn-sm" onClick={() => { a.grantFree(); onClose(); }}>Free · {planLabel(a.months)}</button>
                {p.status === "submitted" ? <button type="button" className="btn btn-sm btn-danger" onClick={a.reject}>Reject proof…</button> : <span />}
              </div>
              {a.mismatch && <p className="text-xs text-warn">The proof is for {p.amount} {p.currency}; the current price of this plan is ${a.price}.</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PricesCard({ cfg, act }: { cfg: MembershipConfig; act: Act }) {
  const [draft, setDraft] = useState<MembershipConfig | null>(null);
  const c = draft ?? cfg;
  const setPrice = (m: number, v: string) => setDraft({ ...c, plans: c.plans.map((p) => (p.months === m ? { ...p, price: Number(v) || 0 } : p)) });
  return (
    <Card title="Membership prices, payment & support">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {c.plans.map((p) => (
          <label key={p.months} className="text-xs text-mute">{p.label} (USD)
            <input className="input num mt-1 text-right" inputMode="decimal" value={p.price} onChange={(e) => setPrice(p.months, e.target.value)} />
          </label>
        ))}
      </div>
      <label className="mt-4 block text-xs text-mute">Payment note shown to members
        <textarea className="input mt-1 min-h-[72px]" value={c.pay_note} onChange={(e) => setDraft({ ...c, pay_note: e.target.value })} />
      </label>
      <label className="mt-4 block text-xs text-mute">Support email members can contact
        <input className="input mt-1" type="email" inputMode="email" value={c.support_email} onChange={(e) => setDraft({ ...c, support_email: e.target.value.trim() })} />
      </label>
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-glass/[0.06] pt-4">
        <img src={c.qr_url} alt="Your Binance Pay QR" className="h-16 w-16 rounded-md bg-white object-contain p-0.5" />
        <span className="flex-1 text-xs text-mute">Your Binance Pay QR shown to members.</span>
        {draft && <button type="button" className="btn btn-ghost" onClick={() => setDraft(null)}>Discard</button>}
        <button type="button" className="btn btn-primary" disabled={!draft} onClick={() => act(async () => {
          if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(c.support_email)) throw new Error("Enter a valid support email address.");
          await saveMembershipConfig(c); setDraft(null);
        }, "Saved.")}>Save changes</button>
      </div>
    </Card>
  );
}

function LimitsCard({ act, total }: { act: Act; total: number }) {
  const cur = useLimits();
  const [draft, setDraft] = useState<Limits | null>(null);
  const l = draft ?? cur;
  const step = (k: keyof Limits, d: number, max: number) => setDraft({ ...l, [k]: Math.max(0, Math.min(max, Number(l[k]) + d)) });
  const field = (k: keyof Limits, label: string, help: string, max: number) => (
    <div className="rounded-xl border border-glass/[0.08] bg-glass/[0.02] p-3">
      <div className="flex items-baseline justify-between gap-2"><span className="text-sm font-medium">{label}</span><span className="num text-[11px] text-mute">0–{max}</span></div>
      <div className="mt-2 flex items-center gap-2">
        <button type="button" className="btn w-10 px-0 text-lg" aria-label={`Decrease ${label}`} onClick={() => step(k, -1, max)}>−</button>
        <input className="input num w-20 text-center" inputMode="numeric" aria-label={label} value={l[k]} onChange={(e) => setDraft({ ...l, [k]: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
        <button type="button" className="btn w-10 px-0 text-lg" aria-label={`Increase ${label}`} onClick={() => step(k, 1, max)}>+</button>
      </div>
      <p className="mt-2 text-xs text-mute">{help}</p>
    </div>
  );
  return (
    <Card title="Coin limits">
      <div className="grid gap-3 sm:grid-cols-2">
        {field("member_coin_limit", "Coins each member can add", "0 turns personal coins off. Lowering it keeps their first coins.", 50)}
        {field("member_coins_max", "Member coins in total", "On top of your own list. More coins = longer engine runs.", 200)}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-glass/[0.06] pt-4">
        <span className="flex-1 text-xs text-mute">Users: no limit · {total} signed up so far</span>
        {draft && <button type="button" className="btn btn-ghost" onClick={() => setDraft(null)}>Discard</button>}
        <button type="button" className="btn btn-primary" disabled={!draft} onClick={() => act(async () => { await saveLimits(l); setDraft(null); }, "Limits saved. The engine uses them on its next run.")}>Save limits</button>
      </div>
    </Card>
  );
}
