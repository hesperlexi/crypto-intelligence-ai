import { collection, deleteDoc, doc, onSnapshot, updateDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { Badge, Card, Empty, ErrorBox, Note } from "../components/ui";
import { db } from "../lib/firebase";
import { fmtTime } from "../lib/format";
import { getSession, useIsAdmin } from "../lib/session";

/** Admin: approve, block or remove the people who asked for access. */
export default function Users() {
  const admin = useIsAdmin();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "pending" | "approved" | "blocked">("all");
  useEffect(() => (admin ? onSnapshot(collection(db, "users"), (q) => setRows(q.docs.map((d) => ({ id: d.id, ...d.data() }))), (e) => setErr(e.message)) : undefined), [admin]);
  if (!admin) return <Empty>Only the app owner can manage users.</Empty>;

  const order: Record<string, number> = { pending: 0, approved: 1, blocked: 2 };
  const list = (rows ?? []).filter((r) => filter === "all" || r.status === filter)
    .sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3) || (b.requested_at ?? 0) - (a.requested_at ?? 0));
  const count = (s: string) => (rows ?? []).filter((r) => r.status === s).length;
  const act = async (fn: () => Promise<any>) => { try { await fn(); setErr(null); } catch (e: any) { setErr(e.message); } };
  const set = (id: string, status: string) => act(() => updateDoc(doc(db, "users", id), {
    status, ...(status === "approved" ? { approved_at: Date.now(), approved_by: getSession()?.email ?? null } : { changed_at: Date.now() }) }));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold tracking-tight">Users</h1>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter">
        {([["all", "All"], ["pending", `Waiting (${count("pending")})`], ["approved", `Members (${count("approved")})`], ["blocked", `Blocked (${count("blocked")})`]] as const).map(([k, l]) => (
          <button key={k} className={`btn px-3 py-1 text-xs ${filter === k ? "btn-on" : ""}`} aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>
      {err && <ErrorBox error={err} />}
      <Card title="Access requests and members">
        {rows == null ? <Empty>Loading…</Empty> : !list.length ? <Empty>{filter === "pending" ? "No one is waiting for approval." : "No users here yet. Share the app link; new sign-ins appear here."}</Empty> : (
          <ul className="divide-y divide-glass/[0.06]">
            {list.map((u) => (
              <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div className="flex min-w-0 items-center gap-3">
                  {u.photo ? <img src={u.photo} alt="" className="h-9 w-9 rounded-full" referrerPolicy="no-referrer" /> : <div className="h-9 w-9 rounded-full bg-raised" />}
                  <div className="min-w-0">
                    <div className="truncate font-medium">{u.name || u.email}</div>
                    <div className="truncate text-xs text-mute">{u.email} · asked {fmtTime(u.requested_at)}{u.approved_at ? ` · approved ${fmtTime(u.approved_at)}` : ""}</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={u.status === "approved" ? "bull" : u.status === "blocked" ? "bear" : "warn"}>{u.status === "approved" ? "member" : u.status === "pending" ? "waiting" : u.status}</Badge>
                  {u.status !== "approved" && <button className="btn btn-primary px-3 py-1 text-xs" onClick={() => set(u.id, "approved")}>Approve</button>}
                  {u.status !== "blocked" && <button className="btn px-3 py-1 text-xs hover:text-bear" onClick={() => set(u.id, "blocked")}>{u.status === "approved" ? "Remove access" : "Decline"}</button>}
                  <button className="btn px-3 py-1 text-xs text-mute" title="Delete the record: they can ask again" onClick={() => { if (window.confirm(`Delete ${u.email}? They can request access again later.`)) act(() => deleteDoc(doc(db, "users", u.id))); }}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <Note>Members see all predictions, Futures, Accuracy and the demo bots, can run backtests and replays, and get their own paper trading accounts, alerts and notifications. Only you (accounts in ADMIN_EMAILS) can change the coin list, bots, engine settings and users. Removing access takes effect immediately.</Note>
      </Card>
    </div>
  );
}
