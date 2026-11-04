// v2.16 Results → Leaderboard: this month's practice ranking (computed hourly by the engine, views/leaderboard),
// last month's winner, and for the admin the full list (admin/leaderboard) with "Award prize" and "Keep out".
import { useState } from "react";
import { Badge, Tile } from "./kit";
import { Card, Empty, ErrorBox, Info, Loading } from "./ui";
import { useApi } from "../lib/api";
import { awardPrize, badgeTitle, LbView, setExcluded, shortMonth } from "../lib/leaderboard";
import { ago, fmtTime } from "../lib/format";
import { useSession } from "../lib/session";

const pct = (x: number) => `${x > 0 ? "+" : ""}${x.toFixed(2)}%`;
const tone = (x: number) => (x > 0 ? "text-bull" : x < 0 ? "text-bear" : "text-mute");

function Medal({ months }: { months?: string[] }) {
  return months?.length ? <span role="img" aria-label={badgeTitle(months)} title={badgeTitle(months)}>🥇</span> : null;
}

export default function Leaderboard() {
  const s = useSession();
  const admin = s?.role === "admin";
  const lb = useApi<LbView>("/leaderboard");
  if (lb.error) return <ErrorBox error={lb.error} retry={lb.reload} />;
  if (!lb.data) return <Loading />;
  const v = lb.data;
  const me = s?.username ? v.rows.find((r) => r.username === s.username) : undefined;
  const lw = v.last_winner;
  return (
    <div className="space-y-4">
      <div className="metric-strip" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <Tile variant="strip" label={v.month.slice(0, 4)} value={shortMonth(v.month).split(" ")[0]} sub={`updated ${ago(v.generated_at)}`} />
        <Tile variant="strip" label="Ranked" value={v.ranked} sub={`${v.taking_part} taking part`} />
        <Tile variant="strip" label="You" value={me ? `#${me.rank}` : "—"} valueClass={me ? "text-accent" : "text-mute"}
          sub={me ? pct(me.return_pct) : admin ? "owner: not ranked" : s?.username ? "not ranked yet" : "set a username"} />
      </div>

      <p className="text-xs text-mute">
        {v.rules} <Info label="How the leaderboard works">
          Futures practice account only. Return = (equity now − equity at the month's start − money added) ÷ (equity at the
          start + money added), so Add funds never counts as profit. Open trades count at the current price. Updated about
          once an hour; the month ends at midnight Dubai time. Only usernames are shown: set one in Community to take part.
          Resetting the account during a month removes you from that month. #1 wins a 🥇 badge and 1 free month.
        </Info>
      </p>

      {lw && lw.winners.length > 0 && (
        <div className="panel flex items-center gap-3 p-3">
          <span className="text-2xl" aria-hidden="true">🥇</span>
          <div className="min-w-0 text-sm">
            <div className="font-semibold">{lw.label} winner{lw.winners.length > 1 ? "s" : ""}</div>
            <div className="truncate text-mute">{lw.winners.map((w) => `@${w.username} ${pct(w.return_pct)}`).join(" · ")}</div>
          </div>
        </div>
      )}

      <Card title={`${v.label} ranking`} className="[&>.card-body]:p-0">
        {!v.rows.length ? <Empty>No one has {v.min_trades} closed trades this month yet.</Empty> : (
          <ol className="divide-y divide-glass/[0.06]" aria-label={`${v.label} ranking`}>
            {v.rows.map((r) => {
              const mine = r.username === s?.username;
              return (
                <li key={r.username} className={`flex items-center gap-3 px-4 py-2.5 ${mine ? "bg-accent/[0.06]" : ""}`} aria-current={mine ? "true" : undefined}>
                  <span className={`num w-8 shrink-0 text-right text-sm font-semibold ${r.rank <= 3 ? "text-accent" : "text-mute"}`}>#{r.rank}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-1 text-sm font-medium"><span className="truncate">@{r.username}</span><span className="shrink-0"><Medal months={v.badges[r.username]} /></span>{mine && <Badge tone="accent" className="shrink-0">you</Badge>}</span>
                    <span className="num block text-xs text-mute">{r.trades} closed trades</span>
                  </span>
                  <span className={`num shrink-0 text-base font-semibold ${tone(r.return_pct)}`}>{pct(r.return_pct)}</span>
                </li>
              );
            })}
          </ol>
        )}
      </Card>
      {admin && <AdminPanel />}
    </div>
  );
}

/** Admin only: every entry (uid, deposits, flags), month winners with "Award prize", and keep-out switches. */
function AdminPanel() {
  const a = useApi<any>("/leaderboard/admin");
  const o = useApi<any>("/leaderboard/owner");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  let d: any = null;
  try { d = a.data?.json ? JSON.parse(a.data.json) : null; } catch { d = null; }
  const awarded = o.data?.awarded ?? {};
  const excluded: string[] = o.data?.excluded ?? [];
  const run = async (key: string, fn: () => Promise<string | void>, ok: (r: any) => string) => {
    setBusy(key); setErr(null);
    try { setMsg(ok(await fn())); } catch (e: any) { setErr(e.message); setMsg(null); }
    setBusy(null);
  };
  if (!d) return <Card title="Admin"><Empty>The engine publishes the admin details with its next hourly run.</Empty></Card>;
  const months = [...new Set<string>((d.winners ?? []).map((w: any) => w.month))];
  return (
    <div className="space-y-4">
      <Card title="Prizes (admin)">
        {!months.length ? <Empty>No month has ended yet. The winner appears here after midnight Dubai time on the 1st.</Empty> : (
          <ul className="divide-y divide-glass/[0.06] text-sm">
            {(d.winners as any[]).map((w) => {
              const done = awarded[w.month]?.[w.uid];
              return (
                <li key={`${w.month}-${w.uid}`} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="min-w-0"><span className="font-medium">{w.label}</span> · @{w.username} <span className={`num ${tone(w.return_pct)}`}>{pct(w.return_pct)}</span> <span className="num text-xs text-mute">· {w.trades} trades</span></span>
                  {done ? <Badge tone="bull">prize given {fmtTime(done.at)}</Badge>
                    : <button type="button" className="btn btn-sm btn-primary" disabled={busy != null}
                        onClick={() => window.confirm(`Give @${w.username} 1 free month and the 🥇 badge for ${w.label}?`)
                          && run(w.month + w.uid, () => awardPrize(w.month, w.label, w.uid), (who) => `Prize given to ${who}.`)}>Award prize</button>}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      {msg && <p className="rounded-lg border border-bull/30 bg-bull/[0.08] px-3 py-2 text-sm text-bull" role="status">{msg}</p>}
      {err && <ErrorBox error={err} />}
      <Card title={`Everyone taking part · ${d.label}`} className="[&>.card-body]:p-0">
        {!d.rows?.length ? <Empty>No practice accounts read yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-mute">
                {["#", "Member", "Return", "Trades", "Start", "Added", "Equity", "Check", ""].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-glass/[0.06]">
                {(d.rows as any[]).map((r) => (
                  <tr key={r.uid}>
                    <td className="num px-3 py-2 text-mute">{r.rank ?? "—"}</td>
                    <td className="px-3 py-2">@{r.username}</td>
                    <td className={`num px-3 py-2 ${tone(r.return_pct)}`}>{pct(r.return_pct)}</td>
                    <td className="num px-3 py-2">{r.trades}</td>
                    <td className="num px-3 py-2">${Math.round(r.start_equity).toLocaleString()}</td>
                    <td className="num px-3 py-2">${Math.round(r.deposits).toLocaleString()}</td>
                    <td className="num px-3 py-2">${Math.round(r.equity).toLocaleString()}</td>
                    <td className="px-3 py-2 text-xs">{r.flags?.length ? <span className="text-warn">{r.flags.join("; ")}</span> : <span className="text-mute">ok</span>}</td>
                    <td className="px-3 py-2 text-right">
                      <button type="button" className="btn btn-ghost btn-sm" disabled={busy != null}
                        onClick={() => run("x" + r.uid, () => setExcluded(r.uid, true), () => `@${r.username} is kept out from the next update.`)}>Keep out</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {excluded.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-t border-glass/[0.06] px-4 py-3 text-xs text-mute">
            Kept out: {excluded.map((uid) => (
              <button key={uid} type="button" className="chip" onClick={() => run("i" + uid, () => setExcluded(uid, false), () => "Back in from the next update.")}>{uid.slice(0, 8)} · let back in</button>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
