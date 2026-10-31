import { collection, deleteDoc, doc, onSnapshot, updateDoc } from "firebase/firestore";
import { countryName, flagUrl, ONLINE_MS } from "../lib/presence";
import { KeyboardEvent as ReactKeyboardEvent, ReactNode, RefObject, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Badge, Card, Empty, ErrorBox, Note } from "../components/ui";
import { useFocusTrap } from "../components/Shell";
import { db } from "../lib/firebase";
import { fmtTime } from "../lib/format";
import { daysLeft, fmtDate, grantMembership, markFree, MembershipConfig, planLabel, rejectPayment, saveMembershipConfig, useMembershipConfig } from "../lib/membership";
import { roleOf, useIsAdmin } from "../lib/session";
import { Limits, saveLimits, useLimits } from "../lib/limits";

type Filter = "todo" | "members" | "free" | "ending" | "expired" | "blocked" | "all";
type Sort = "action" | "newest" | "expiry" | "active" | "name";
type Act = (fn: () => Promise<any>, ok: string | ((res: any) => string)) => void;

const todo = (u: any) => u.status === "pending" || u.payment?.status === "submitted";
const ending = (u: any) => roleOf(u) === "member" && u.expires_at && (daysLeft(u.expires_at) ?? 99) <= 7;
const MATCH: Record<Filter, (u: any) => boolean> = {
  todo, members: (u) => roleOf(u) === "member", free: (u) => !!u.free && roleOf(u) === "member", ending, expired: (u) => roleOf(u) === "expired",
  blocked: (u) => u.status === "blocked", all: () => true,
};
const FILTERS: [Filter, string][] = [["todo", "To check"], ["members", "Active"], ["free", "Free"], ["ending", "Ending ≤7 days"], ["expired", "Expired"], ["blocked", "Blocked"], ["all", "All"]];
const SORTS: [Sort, string][] = [["action", "Needs action first"], ["newest", "Newest sign-ups"], ["expiry", "Ending soonest"], ["active", "Last active"], ["name", "Name A–Z"]];
const PAGE = 25;

/** A free member (u.free, set by grantMembership(…, free = true) or markFree) sees no payment-proof tools, unless they
 *  have sent a new payment proof: then the normal paid flow (proof, accept, reject) is shown so it can be checked. */
const isFreeView = (u: any) => !!u.free && u.payment?.status !== "submitted";
const displayName = (u: any) => u.name || (u.username ? `@${u.username}` : u.email);

/** Admin: check payment proofs, approve members for 1 / 3 / 6 / 12 months, extend, block, set prices and limits. */
export default function Users() {
  const admin = useIsAdmin();
  const cfg = useMembershipConfig();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("todo");
  const [sort, setSort] = useState<Sort>("action");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [proofOf, setProofOf] = useState<string | null>(null);
  useEffect(() => (admin ? onSnapshot(collection(db, "users"), (q) => setRows(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => setErr(e.message)) : undefined), [admin]);
  const [states, setStates] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "user_state"), (q) => setStates(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [seen, setSeen] = useState<Record<string, any>>({});
  useEffect(() => (admin ? onSnapshot(collection(db, "presence"), (q) => setSeen(Object.fromEntries(q.docs.map((d) => [d.id, d.data()]))), () => {}) : undefined), [admin]);
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((n) => n + 1), 30_000); return () => window.clearInterval(id); }, []);
  useEffect(() => setLimit(PAGE), [filter, sort, q]);
  const stickyTop = useHeaderHeight();

  const all = rows ?? [];
  const last = useCallback((u: any) => seen[u.id]?.last_seen ?? 0, [seen]);
  const needle = q.trim().toLowerCase();
  const list = useMemo(() => {
    const asked = (u: any) => u.payment?.submitted_at ?? u.requested_at ?? 0;
    const cmp: Record<Sort, (a: any, b: any) => number> = {
      action: (a, b) => Number(todo(b)) - Number(todo(a)) || last(b) - last(a) || asked(b) - asked(a),
      newest: (a, b) => (b.requested_at ?? 0) - (a.requested_at ?? 0),
      expiry: (a, b) => (a.expires_at ?? Infinity) - (b.expires_at ?? Infinity) || last(b) - last(a),
      active: (a, b) => last(b) - last(a) || asked(b) - asked(a),
      name: (a, b) => String(displayName(a)).replace(/^@/, "").localeCompare(String(displayName(b)).replace(/^@/, ""), undefined, { sensitivity: "base" }),
    };
    return all.filter(MATCH[filter])
      .filter((u) => !needle || `${u.name ?? ""} ${u.email ?? ""} ${u.username ?? ""} ${u.payment?.txid ?? ""}`.toLowerCase().includes(needle))
      .sort(cmp[sort]);
  }, [all, filter, sort, needle, last]);
  if (!admin) return <Empty>Only the app owner can manage users.</Empty>;

  const now = Date.now();
  const within = (ms: number) => all.filter((u) => now - last(u) < ms).length;
  const byCountry = Object.entries(all.reduce((m: Record<string, number>, u) => { const c = seen[u.id]?.country; if (c) m[c] = (m[c] ?? 0) + 1; return m; }, {}))
    .sort((a, b) => b[1] - a[1]);
  const count = (f: Filter) => all.filter(MATCH[f]).length;
  const free = count("free");
  const act: Act = async (fn, ok) => { try { const res = await fn(); setErr(null); setMsg(typeof ok === "function" ? ok(res) : ok); } catch (e: any) { setErr(e.message); setMsg(null); } };
  const income = all.flatMap((u) => u.history ?? []).reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0);
  const proofUser = proofOf ? all.find((u) => u.id === proofOf) : null;
  const shown = list.slice(0, limit);
  const filterName = FILTERS.find(([k]) => k === filter)?.[1] ?? "";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="page-title">Users & memberships</h1>
          <p className="page-sub">Check payment proofs, approve and extend memberships, and see who is using the app.</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-mute">
          <span className="num rounded-md border border-glass/10 px-2 py-1"><span className="font-semibold text-text">{all.length}</span> accounts</span>
          <span className="num rounded-md border border-glass/10 px-2 py-1"><span className="font-semibold text-accent">{income}</span> USDT received</span>
        </div>
      </div>

      {/* summary: each tile is also a filter */}
      <div className="grid grid-cols-2 gap-2.5 sm:gap-3 lg:grid-cols-4">
        <SummaryTile label="Waiting to check" value={count("todo")} tone={count("todo") ? "accent" : undefined} sub="new requests and payment proofs" onClick={() => setFilter("todo")} active={filter === "todo"} />
        <SummaryTile label="Active members" value={count("members")} sub={`${count("members") - free} paying · ${free} free`} onClick={() => setFilter("members")} active={filter === "members"} />
        <SummaryTile label="Ending in 7 days" value={count("ending")} tone={count("ending") ? "warn" : undefined} sub="remind or extend" onClick={() => setFilter("ending")} active={filter === "ending"} />
        <SummaryTile label="Expired" value={count("expired")} tone={count("expired") ? "bear" : undefined} sub="locked out until renewal" onClick={() => setFilter("expired")} active={filter === "expired"} />
      </div>

      {/* activity: one compact strip */}
      <section className="panel flex flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:gap-6" aria-label="Activity">
        <div className="grid shrink-0 grid-cols-3 gap-2 text-center lg:flex lg:gap-6 lg:text-left">
          <ActivityNum n={within(ONLINE_MS)} label="online now" dot />
          <ActivityNum n={within(86_400_000)} label="active today" />
          <ActivityNum n={within(7 * 86_400_000)} label="this week" />
        </div>
        {byCountry.length > 0 && (
          <div className="-mx-4 flex min-w-0 flex-1 gap-1.5 overflow-x-auto border-t border-glass/[0.06] px-4 pt-3 lg:mx-0 lg:flex-wrap lg:justify-end lg:overflow-visible lg:border-0 lg:px-0 lg:pt-0"
            title="Country from each device's time zone. People appear after they open the app once with this version.">
            {byCountry.map(([c, n]) => (
              <span key={c} className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-glass/10 px-1.5 py-0.5 text-[11px]">
                <Flag cc={c} />{countryName(c)}<span className="num text-mute">{n}</span>
              </span>
            ))}
          </div>
        )}
      </section>

      {/* toolbar: status tabs, search, sort */}
      <div className="space-y-2">
        <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <div className="seg" role="group" aria-label="Filter by status">
            {FILTERS.map(([k, l]) => (
              <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)} className="whitespace-nowrap">
                {l} <span className="num opacity-70">{k === "all" ? all.length : count(k)}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <label className="relative min-w-0 flex-1 sm:max-w-sm">
            <span className="sr-only">Search users</span>
            <svg aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-mute" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
            <input className="input input-sm !pl-8" type="search" placeholder="Search name, username, email or order ID" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <label className="shrink-0">
            <span className="sr-only">Sort users</span>
            <select className="input input-sm w-auto" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </label>
          <span className="ml-auto hidden self-center text-xs text-mute sm:inline" aria-live="polite">
            <span className="num">{list.length}</span> {list.length === 1 ? "person" : "people"} · {filterName}
          </span>
        </div>
      </div>
      {err && <ErrorBox error={err} />}
      {msg && <p className="rounded-lg border border-bull/30 bg-bull/[0.08] px-3 py-2 text-sm text-bull" role="status">{msg}</p>}

      {rows == null ? <Card><Empty>Loading…</Empty></Card> : !list.length ? (
        <Card><Empty>{needle ? "No one matches this search." : filter === "todo" ? "Nothing to check. New payment proofs appear here, and you get a notification." : "No one here."}</Empty></Card>
      ) : (
        <>
          {/* computer: one aligned table with a header that stays in view */}
          <section className="panel hidden p-0 xl:block" aria-label="Users">
            <table className="grid-table [&_th:first-child]:rounded-tl-[var(--r-lg)] [&_th:last-child]:rounded-tr-[var(--r-lg)]">
              <thead>
                <tr>
                  {["Member", "Status", "Plan / until", "Last seen", "Payment"].map((h) => <th key={h} scope="col" style={{ top: stickyTop }}>{h}</th>)}
                  <th scope="col" className="text-right" style={{ top: stickyTop }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((u) => <UserRow key={u.id} u={u} st={states[u.id]} pr={seen[u.id]} cfg={cfg} act={act} onProof={() => setProofOf(u.id)} />)}
              </tbody>
            </table>
          </section>
          {/* phone / tablet: compact cards */}
          <div className="grid gap-2.5 md:grid-cols-2 xl:hidden">
            {shown.map((u) => <UserCard key={u.id} u={u} st={states[u.id]} pr={seen[u.id]} cfg={cfg} act={act} onProof={() => setProofOf(u.id)} />)}
          </div>
          <div className="flex flex-col items-center gap-2 pt-1 text-xs text-mute">
            <span aria-live="polite">Showing <span className="num text-text">{shown.length}</span> of <span className="num text-text">{list.length}</span></span>
            {list.length > shown.length && (
              <div className="flex gap-2">
                <button type="button" className="btn btn-sm" onClick={() => setLimit((n) => n + PAGE)}>Show {Math.min(PAGE, list.length - shown.length)} more</button>
                {list.length - shown.length > PAGE && <button type="button" className="btn btn-ghost btn-sm" onClick={() => setLimit(list.length)}>Show all</button>}
              </div>
            )}
          </div>
        </>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-2"><PricesCard cfg={cfg} act={act} /><LimitsCard act={act} total={all.length} /></div>
      <Note>Members pay with your Binance QR or by MEXC transfer to your UID, then upload a screenshot and/or the order ID. Check the payment arrived (Binance → Pay → History, or MEXC → Wallets → History) before approving. Approving adds the months after the current end date, so early renewals never lose days. When a membership ends, that person is locked out automatically until they renew; their paper accounts and alerts are kept. People approved before memberships existed have no end date until you give them a plan.</Note>
      {proofUser && <ProofViewer u={proofUser} cfg={cfg} act={act} onClose={() => setProofOf(null)} />}
    </div>
  );
}

/** Height of the app's sticky top bar, so the table header can stick just below it. */
function useHeaderHeight() {
  const [h, setH] = useState(0);
  useEffect(() => {
    const el = document.querySelector<HTMLElement>("header.glass-bar");
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setH(getComputedStyle(el).position === "sticky" ? el.getBoundingClientRect().height : 0));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return h;
}

function useIsPhone() {
  const query = "(max-width: 767px)";
  const [m, setM] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setM(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return m;
}

function SummaryTile({ label, value, sub, tone, onClick, active }: { label: string; value: number; sub: string; tone?: "accent" | "warn" | "bear"; onClick: () => void; active: boolean }) {
  const cls = tone === "accent" ? "text-accent" : tone === "warn" ? "text-warn" : tone === "bear" ? "text-bear" : "text-text";
  const dot = tone === "accent" ? "bg-accent" : tone === "warn" ? "bg-warn" : tone === "bear" ? "bg-bear" : "bg-glass/25";
  return (
    <button type="button" onClick={onClick} aria-pressed={active}
      className={`panel group p-3 text-left transition-colors hover:border-accent/40 sm:p-4 ${active ? "!border-accent/50 bg-accent/[0.05]" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="label truncate">{label}</span>
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      </div>
      <div className={`num mt-2 text-[26px] font-semibold leading-none sm:text-3xl ${cls}`}>{value}</div>
      <div className="mt-1.5 truncate text-[11px] text-mute">{sub}</div>
    </button>
  );
}

function ActivityNum({ n, label, dot = false }: { n: number; label: string; dot?: boolean }) {
  return (
    <div className="lg:flex lg:items-baseline lg:gap-1.5">
      <div className="num flex items-center justify-center gap-1.5 text-xl font-semibold lg:justify-start">{dot && <span className="h-2 w-2 rounded-full bg-bull shadow-[0_0_8px_rgb(var(--bull))]" aria-hidden="true" />}{n}</div>
      <div className="text-[11px] text-mute">{label}</div>
    </div>
  );
}

function Flag({ cc }: { cc?: string | null }) {
  const [bad, setBad] = useState(false);
  const url = flagUrl(cc);
  if (!url || bad) return <span className="inline-flex h-3.5 w-5 shrink-0 items-center justify-center rounded-sm bg-glass/10 text-[8px] text-mute" aria-hidden="true">{cc ?? "?"}</span>;
  return <img src={url} alt="" width={20} height={14} className="h-3.5 w-5 shrink-0 rounded-sm object-cover ring-1 ring-glass/15" onError={() => setBad(true)} />;
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
    ? <img src={u.photo} alt="" width={size} height={size} className="shrink-0 rounded-full ring-1 ring-glass/15" style={{ width: size, height: size }} referrerPolicy="no-referrer" />
    : <div className="flex shrink-0 items-center justify-center rounded-full bg-accent/[0.12] font-semibold text-accent ring-1 ring-accent/25" style={{ width: size, height: size, fontSize: size * 0.4 }}>{(u.name || u.username || u.email || "?")[0].toUpperCase()}</div>;
}

function StatusBadge({ u }: { u: any }) {
  const r = roleOf(u);
  const left = daysLeft(u.expires_at);
  if (r === "member") return <Badge tone={left != null && left <= 7 ? "warn" : "bull"}>{u.free ? "free member" : "member"}</Badge>;
  if (r === "expired") return <Badge tone="bear">{u.free ? "free · expired" : "expired"}</Badge>;
  if (r === "blocked") return <Badge tone="bear">blocked</Badge>;
  return <Badge tone={u.payment?.status === "submitted" ? "accent" : "warn"}>{u.payment?.status === "submitted" ? "proof to check" : "waiting"}</Badge>;
}

function Seen({ pr }: { pr?: any }) {
  const a = activeText(pr?.last_seen);
  return <span className={`inline-flex items-center gap-1.5 ${a.on ? "text-bull" : "text-mute"}`}><span className={`h-1.5 w-1.5 shrink-0 rounded-full ${a.on ? "bg-bull" : "bg-glass/30"}`} aria-hidden="true" />{a.text}</span>;
}

function Where({ pr }: { pr?: any }) {
  if (!pr?.country && !pr?.device) return null;
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-mute">
      {pr?.country && <Flag cc={pr.country} />}
      <span className="truncate">{[pr?.country && countryName(pr.country), pr?.device].filter(Boolean).join(" · ")}</span>
    </span>
  );
}

function paidLine(u: any): string | null {
  if (!u.history?.length) return null;
  if (u.free && !u.history.some((h: any) => Number(h.amount) > 0)) return "free (nothing paid)";
  return `${u.history.length} payment${u.history.length === 1 ? "" : "s"} · ${u.history.reduce((s: number, h: any) => s + (Number(h.amount) || 0), 0)} USDT`;
}

/** End date with a days-left bar (relative to the last plan's length). */
function Term({ u, wide = false, lead }: { u: any; wide?: boolean; lead?: string }) {
  const r = roleOf(u);
  const left = daysLeft(u.expires_at);
  if (!u.expires_at || left == null) {
    return r === "member" ? <span className="text-xs text-mute">member · no end date</span>
      : <span className="text-xs text-mute">asked {fmtDate(u.requested_at)}</span>;
  }
  const total = Math.max(1, (u.plan_months || 1) * 30.44);
  const pct = left <= 0 ? 0 : Math.max(4, Math.min(100, (left / total) * 100));
  const tone = left <= 0 ? "bg-bear" : left <= 7 ? "bg-warn" : "bg-bull";
  const txt = left <= 0 ? "text-bear" : left <= 7 ? "text-warn" : "text-text";
  return (
    <div className={`min-w-0 ${wide ? "w-full" : "w-44"}`}>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="num truncate">{lead && <span className="font-semibold text-bull">{lead} · </span>}{left <= 0 ? "ended " : "until "}{fmtDate(u.expires_at)}</span>
        <span className={`num shrink-0 font-semibold ${txt}`}>{left <= 0 ? `${-left}d ago` : `${left}d left`}</span>
      </div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-glass/10" role="presentation"><div className={`h-full rounded-full ${tone}`} style={{ width: `${pct}%` }} /></div>
      {u.plan_months ? <div className="mt-1 text-[11px] text-mute">{u.free && !lead ? "free · " : ""}{planLabel(u.plan_months)}</div> : null}
    </div>
  );
}

/** The plan picker and every action for one person. Each button calls exactly the same function as before. */
function useUserActions(u: any, cfg: MembershipConfig, act: Act) {
  const p = u.payment;
  const r = roleOf(u);
  const freeView = isFreeView(u);
  const [months, setMonths] = useState<number>(p?.months ?? 1);
  const price = cfg.plans.find((x) => x.months === months)?.price ?? null;
  const mismatch = p?.status === "submitted" && p.amount != null && price != null && Number(p.amount) !== price && p.months === months;
  const grantLabel = r === "member" ? `Extend +${planLabel(months)} (paid)` : p?.status === "submitted" ? `Accept · ${planLabel(months)}` : `Approve · paid · ${planLabel(months)}`;
  const shortLabel = r === "member" ? "Extend · paid" : p?.status === "submitted" ? "Accept" : "Approve · paid";
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
  const picker = (cls = "") => (
    <select className={`input input-sm ${cls || "w-auto"}`} value={months} onChange={(e) => setMonths(Number(e.target.value))} aria-label={`Plan length for ${u.email}`}>
      {cfg.plans.map((x) => <option key={x.months} value={x.months}>{freeView ? x.label : `${x.label} · $${x.price}`}</option>)}
    </select>
  );
  /** Primary button: free members get "Extend free", everyone else the paid accept / approve / extend. */
  const primary = (cls = "") => freeView
    ? <button type="button" className={`btn btn-sm btn-on ${cls}`} onClick={grantFree} aria-label={`Extend free by ${planLabel(months)} for ${u.email}`}>Extend free</button>
    : <button type="button" className={`btn btn-sm btn-primary ${cls}`} onClick={grant} title={grantLabel} aria-label={`${grantLabel} for ${u.email}`}>{shortLabel}</button>;
  const menu: MenuItem[] = freeView ? [
    u.status !== "blocked" ? { label: "Block…", hint: "They lose access straight away", onSelect: block, danger: true } : { label: "Unblock", hint: "Back to waiting", onSelect: unblock },
    { label: "Delete…", hint: "They can ask for access again later", onSelect: remove, danger: true },
  ] : [
    { label: `Free · ${planLabel(months)}`, hint: "Give time without payment", onSelect: grantFree },
    ...(canMarkFree ? [{ label: "Mark as free (nothing paid)", hint: "Recorded payments become 0 USDT", onSelect: doMarkFree }] : []),
    ...(p?.status === "submitted" ? [{ label: "Reject proof…", hint: "You write the reason they see", onSelect: reject, danger: true }] : []),
    u.status !== "blocked" ? { label: "Block…", hint: "They lose access straight away", onSelect: block, danger: true } : { label: "Unblock", hint: "Back to waiting", onSelect: unblock },
    { label: "Delete…", hint: "They can ask for access again later", onSelect: remove, danger: true },
  ];
  return { p, r, freeView, months, price, mismatch, grantLabel, grant, grantFree, reject, picker, primary, menu };
}

type MenuItem = { label: string; onSelect: () => void; danger?: boolean; hint?: string };

/** "More actions": a popover anchored to the button on computers (flips up near the bottom, never leaves the
 *  window) and a bottom sheet on phones. Both are portalled to <body>, so cards and table rows never clip them. */
function ActionMenu({ items, u }: { items: MenuItem[]; u: any }) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const phone = useIsPhone();
  const id = useId();
  const close = useCallback((refocus = true) => { setOpen(false); if (refocus) btn.current?.focus(); }, []);
  const pick = (it: MenuItem) => { close(); it.onSelect(); };
  return (
    <>
      <button ref={btn} type="button" className="btn btn-sm w-9 shrink-0 px-0" aria-haspopup={phone ? "dialog" : "menu"} aria-expanded={open} aria-controls={open ? id : undefined}
        aria-label={`More actions for ${u.email}`} onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => { if (!phone && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); setOpen(true); } }}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
      </button>
      {open && createPortal(
        phone ? <ActionSheet id={id} u={u} items={items} onPick={pick} onClose={() => close(false)} />
          : <ActionPopover id={id} anchor={btn} items={items} onPick={pick} onClose={close} />,
        document.body,
      )}
    </>
  );
}

function menuKeys(e: ReactKeyboardEvent<HTMLElement>) {
  const list = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
  const i = list.indexOf(document.activeElement as HTMLElement);
  const go = (n: number) => { e.preventDefault(); list[(n + list.length) % list.length]?.focus(); };
  if (e.key === "ArrowDown") go(i + 1);
  else if (e.key === "ArrowUp") go(i - 1);
  else if (e.key === "Home") go(0);
  else if (e.key === "End") go(list.length - 1);
}

function ActionPopover({ id, anchor, items, onPick, onClose }: { id: string; anchor: RefObject<HTMLButtonElement>; items: MenuItem[]; onPick: (it: MenuItem) => void; onClose: (refocus?: boolean) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; up: boolean; max: number } | null>(null);
  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.current?.getBoundingClientRect(), m = ref.current;
      if (!a || !m) return;
      const vw = document.documentElement.clientWidth, vh = window.innerHeight, gap = 6, pad = 8;
      if (a.bottom < 0 || a.top > vh) return onClose(false);   // the button scrolled out of view
      const h = m.scrollHeight, w = m.offsetWidth;
      const below = vh - a.bottom - gap - pad, above = a.top - gap - pad;
      const up = h > below && above > below;
      const max = Math.max(120, up ? above : below);
      const hh = Math.min(h, max);
      const top = Math.max(pad, Math.min(up ? a.top - gap - hh : a.bottom + gap, vh - pad - hh));
      const left = Math.max(pad, Math.min(a.right - w, vw - pad - w));
      setPos({ top, left, up, max });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [anchor, onClose]);
  // focus the first item once the menu is placed (a hidden element cannot take focus)
  const placed = pos != null;
  useEffect(() => { if (placed) ref.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true }); }, [placed]);
  useEffect(() => {
    const down = (e: PointerEvent) => { const t = e.target as Node; if (!ref.current?.contains(t) && !anchor.current?.contains(t)) onClose(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } };
    document.addEventListener("pointerdown", down);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", down); document.removeEventListener("keydown", esc); };
  }, [anchor, onClose]);
  return (
    <div ref={ref} id={id} role="menu" aria-label="More actions" tabIndex={-1}
      onKeyDown={(e) => { if (e.key === "Tab") onClose(false); else if (e.key !== "Escape") menuKeys(e); }}
      className="panel popover animate-in !fixed z-[70] w-60 overflow-y-auto p-1"
      style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, maxHeight: pos?.max, visibility: pos ? "visible" : "hidden", transformOrigin: pos?.up ? "bottom right" : "top right" }}>
      {items.map((it) => (
        <button key={it.label} role="menuitem" type="button" tabIndex={-1} onClick={() => onPick(it)}
          className={`block w-full rounded-md px-3 py-2 text-left text-sm outline-none hover:bg-glass/[0.06] focus-visible:bg-glass/[0.08] focus-visible:shadow-none ${it.danger ? "text-bear" : ""}`}>
          {it.label}
          {it.hint && <span className="block text-[11px] text-mute">{it.hint}</span>}
        </button>
      ))}
    </div>
  );
}

function ActionSheet({ id, u, items, onPick, onClose }: { id: string; u: any; items: MenuItem[]; onPick: (it: MenuItem) => void; onClose: () => void }) {
  const ref = useFocusTrap(true, onClose);
  const titleId = `${id}-title`;
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, []);
  return (
    <div className="fixed inset-0 z-[70]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/65 backdrop-blur-[2px]" aria-hidden="true" />
      <div ref={ref} id={id} role="dialog" aria-modal="true" aria-labelledby={titleId} onClick={(e) => e.stopPropagation()} className="absolute inset-x-0 bottom-0">
        <div className="panel popover sheet-in flex max-h-[85dvh] flex-col rounded-b-none rounded-t-2xl p-0">
          <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-glass/20" aria-hidden="true" />
          <div className="flex items-center gap-3 border-b border-glass/[0.06] px-4 pb-3 pt-2">
            <Avatar u={u} size={32} />
            <div className="min-w-0">
              <h2 id={titleId} className="truncate text-sm font-semibold">{displayName(u)}</h2>
              <p className="truncate text-xs text-mute">{u.email}</p>
            </div>
          </div>
          <div role="menu" aria-labelledby={titleId} className="min-h-0 flex-1 overflow-y-auto p-2" onKeyDown={menuKeys}>
            {items.map((it) => (
              <button key={it.label} role="menuitem" type="button" onClick={() => onPick(it)}
                className={`flex min-h-[52px] w-full flex-col justify-center rounded-lg px-3 py-2 text-left active:bg-glass/[0.08] ${it.danger ? "text-bear" : "text-text"}`}>
                <span className="text-[15px] font-medium">{it.label}</span>
                {it.hint && <span className="text-xs text-mute">{it.hint}</span>}
              </button>
            ))}
          </div>
          <div className="border-t border-glass/[0.06] px-3 pt-2 pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
            <button type="button" className="btn w-full" onClick={onClose}>Cancel</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PaymentCell({ u, onProof }: { u: any; onProof: () => void }) {
  const p = u.payment;
  if (isFreeView(u)) return <span className="text-xs text-mute">complimentary</span>;
  if (!p) return <span className="text-xs text-mute">{paidLine(u) ?? "—"}</span>;
  const tone = p.status === "submitted" ? "text-accent" : p.status === "accepted" ? "text-bull" : "text-bear";
  return (
    <div className="text-xs">
      <div className="num"><span className="font-semibold text-text">{p.amount} {p.currency}</span> <span className="text-mute">· {planLabel(p.months)}</span></div>
      <div className="mt-0.5 flex items-center gap-2">
        <span className={tone}>{p.status === "submitted" ? "to check" : p.status}</span>
        <button type="button" className="text-accent underline-offset-2 hover:underline" onClick={onProof} aria-label={`${p.proof ? "View proof" : "Payment details"} from ${u.email}`}>{p.proof ? "View proof" : "Details"}</button>
      </div>
    </div>
  );
}

/** Username and sign-in method (accounts made before 31 Oct 2026 have neither field: they used Google). */
function Ident({ u }: { u: any }) {
  const how = u.provider === "password" ? "Email & password" : "Google";
  return (
    <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-mute">
      {u.username ? <span className="truncate font-medium text-text/85">@{u.username}</span> : <span className="truncate italic">no username</span>}
      <span className="shrink-0 rounded border border-glass/15 px-1 leading-4" title={`Signs in with ${how}`}>{u.provider === "password" ? "Email" : "Google"}</span>
    </div>
  );
}

function UserRow({ u, st, pr, cfg, act, onProof }: { u: any; st?: any; pr?: any; cfg: MembershipConfig; act: Act; onProof: () => void }) {
  const a = useUserActions(u, cfg, act);
  const check = a.p?.status === "submitted";
  return (
    <tr className={check ? "[&>td:first-child]:shadow-[inset_2px_0_0_rgb(var(--accent))] [&>td]:!bg-accent/[0.045]" : ""}>
      <td className="w-[25%] max-w-0">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar u={u} />
          <div className="min-w-0">
            <div className="truncate font-medium">{displayName(u)}</div>
            <div className="truncate text-xs text-mute">{u.email}</div>
            <Ident u={u} />
            {st?.push_error && <div className="truncate text-[11px] text-bear" title={st.push_error.message}>notifications failing</div>}
          </div>
        </div>
      </td>
      <td><StatusBadge u={u} /></td>
      <td><Term u={u} /></td>
      <td className="max-w-[13rem]">
        <div className="text-xs"><Seen pr={pr} /></div>
        <div className="mt-0.5"><Where pr={pr} /></div>
      </td>
      <td><PaymentCell u={u} onProof={onProof} /></td>
      <td>
        <div className="flex items-center justify-end gap-1.5">
          {a.picker("w-[9.5rem]")}
          {a.primary("min-w-[6.5rem]")}
          <ActionMenu items={a.menu} u={u} />
        </div>
        {a.mismatch && <div className="mt-1 text-right text-[11px] text-warn">Proof is {a.p.amount} {a.p.currency}; plan price is ${a.price}.</div>}
      </td>
    </tr>
  );
}

function UserCard({ u, st, pr, cfg, act, onProof }: { u: any; st?: any; pr?: any; cfg: MembershipConfig; act: Act; onProof: () => void }) {
  const a = useUserActions(u, cfg, act);
  const p = a.p;
  const check = p?.status === "submitted";
  return (
    <article className={`panel flex flex-col p-3.5 ${check ? "!border-accent/45" : ""}`} aria-label={displayName(u)}>
      <div className="flex items-start gap-3">
        <Avatar u={u} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="truncate font-medium leading-tight">{displayName(u)}</div>
            <StatusBadge u={u} />
          </div>
          <div className="truncate text-xs text-mute">{u.email}</div>
          <Ident u={u} />
        </div>
      </div>

      <div className="mt-3 space-y-2 rounded-lg border border-glass/[0.06] bg-glass/[0.02] px-3 py-2.5">
        <Term u={u} wide lead={a.freeView && roleOf(u) === "member" ? "Free member" : undefined} />
        <div className="flex min-w-0 items-center justify-between gap-3 text-[11px]">
          <Seen pr={pr} />
          <Where pr={pr} />
        </div>
      </div>

      {st?.push_error && (
        <p className="mt-2 rounded-lg border border-bear/30 bg-bear/10 px-2 py-1.5 text-[11px] text-bear">
          Notifications failing ({st.push_error.app}, {st.push_error.stage}): {st.push_error.code ? `${st.push_error.code} · ` : ""}{st.push_error.message}
        </p>
      )}
      {p && !a.freeView && (
        <button type="button" onClick={onProof} className={`mt-2 flex w-full items-center gap-3 rounded-lg border p-2 text-left ${check ? "border-accent/40 bg-accent/[0.06]" : "border-glass/10 bg-glass/[0.02]"}`}
          aria-label={`${check ? "Check payment proof" : "Last payment"} from ${u.email}`}>
          {p.proof ? <img src={p.proof} alt="" className="h-11 w-8 shrink-0 rounded object-cover ring-1 ring-glass/20" /> : <span className="flex h-11 w-8 shrink-0 items-center justify-center rounded bg-glass/[0.05] text-[9px] leading-tight text-mute">no<br />image</span>}
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{check ? "Payment proof to check" : p.status === "accepted" ? "Last payment · accepted" : "Last payment · rejected"}</span>
            <span className="num block truncate text-xs text-mute"><span className={check ? "text-accent" : ""}>{p.amount} {p.currency}</span> · {planLabel(p.months)} · {p.method === "mexc" ? "MEXC" : "Binance"}</span>
          </span>
          <svg aria-hidden="true" className="shrink-0 text-mute" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"><path d="M9 6l6 6-6 6" /></svg>
        </button>
      )}

      <details className="group mt-2 text-xs">
        <summary className="cursor-pointer list-none text-mute marker:hidden hover:text-text [&::-webkit-details-marker]:hidden">
          <span className="inline-flex items-center gap-1">Details<svg aria-hidden="true" className="transition-transform group-open:rotate-90" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M9 6l6 6-6 6" /></svg></span>
        </summary>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
          <Dt>Asked</Dt><Dd>{fmtTime(u.requested_at)}</Dd>
          {u.plan_months && <><Dt>Last plan</Dt><Dd>{planLabel(u.plan_months)}</Dd></>}
          <Dt>Notifications</Dt><Dd className={st?.push_error ? "text-bear" : st?.push_ok_at ? "text-bull" : "text-mute"}>{st?.push_error ? `failed ${fmtTime(st.push_error.at)}` : st?.push_ok_at ? `on since ${fmtDate(st.push_ok_at)}` : "not turned on"}</Dd>
          {paidLine(u) && <><Dt>Payments</Dt><Dd className="num">{paidLine(u)}</Dd></>}
        </dl>
      </details>

      <div className="mt-auto flex items-center gap-2 pt-3">
        {a.picker("w-auto max-w-[44%] shrink")}
        {a.primary("min-w-0 flex-1")}
        <ActionMenu items={a.menu} u={u} />
      </div>
      {a.mismatch && <p className="mt-2 text-xs text-warn">The proof is for {p.amount} {p.currency}; the current price of this plan is ${a.price}.</p>}
    </article>
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
              <label className="block text-xs text-mute">Plan to grant<div className="mt-1 [&>select]:w-full">{a.picker()}</div></label>
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
