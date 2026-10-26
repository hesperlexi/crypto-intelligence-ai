// Owner only: connect the public Telegram channel. The token lives in owner/telegram (members cannot read it).
import { doc, onSnapshot, runTransaction, setDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { queueJob } from "../lib/api";
import { db } from "../lib/firebase";
import { ago } from "../lib/format";
import { Card, Note } from "./ui";

const DEF = { enabled: false, token: "", channel: "@crypappai", post_wins: true, post_weekly: true, post_teaser: true, post_each_win: true, approve_first: true };
type Draft = { id: string; kind: string; caption: string; created_at: number; png?: string | null };
const KIND: Record<string, string> = { win: "Best win", wins: "Wins of the day", weekly: "Weekly results", teaser: "Free signal" };
const plain = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">");

export default function TelegramCard() {
  const [s, setS] = useState(DEF);
  const [st, setSt] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [busy, setBusy] = useState<Record<string, string>>({});
  useEffect(() => onSnapshot(doc(db, "owner", "telegram_drafts"), (d) => setDrafts((d.data()?.items ?? []) as Draft[]), () => {}), []);
  const skip = async (id: string) => {
    try {
      await runTransaction(db, async (tx) => {
        const ref = doc(db, "owner", "telegram_drafts"); const cur = await tx.get(ref);
        tx.update(ref, { items: ((cur.data()?.items ?? []) as Draft[]).filter((x) => x.id !== id), updated_at: Date.now() });
      });
    } catch (e: any) { setMsg(e.message); }
  };
  const approve = async (id: string) => {
    setBusy((b) => ({ ...b, [id]: "Posting on the next engine run (within 5 min)…" }));
    try { const j = await queueJob("telegram_post", { id }); await j.done; setMsg("Posted to the channel."); }
    catch (e: any) { setMsg(e.message); setBusy((b) => { const n = { ...b }; delete n[id]; return n; }); }
  };
  useEffect(() => onSnapshot(doc(db, "owner", "telegram"), (d) => setS({ ...DEF, ...(d.data() ?? {}) }), () => {}), []);
  useEffect(() => onSnapshot(doc(db, "owner", "telegram_status"), (d) => setSt(d.data() ?? null), () => {}), []);
  const save = async (next = s, note = "Saved. The engine uses it from its next run.") => {
    try { await setDoc(doc(db, "owner", "telegram"), { ...next, updated_at: Date.now() }); setMsg(note); } catch (e: any) { setMsg(e.message); }
  };
  const test = async () => {
    try { await save(s, "Saved."); const j = await queueJob("test_telegram", {}); setMsg("Test post queued: it is sent on the next engine run (a few minutes)."); await j.done; setMsg("Test post sent to the channel."); }
    catch (e: any) { setMsg(e.message); }
  };
  const ready = s.token && s.channel;
  return (
    <Card title="Telegram channel autopilot" right={<span className={`text-xs font-semibold ${s.enabled && ready ? "text-bull" : "text-mute"}`}>{s.enabled && ready ? "ON" : "OFF"}</span>}>
      <div className="space-y-3 text-sm">
        <p className="text-xs text-mute">Picture cards: best wins, daily wins, Monday results and one free signal a day. With "Ask me before posting" each card waits here for Post or Skip. Setup: @BotFather → /newbot → copy token; add the bot as channel admin.</p>
        <label className="block"><span className="text-xs text-mute">Bot token (private)</span>
          <div className="mt-1 flex gap-2"><input className="input flex-1" type={show ? "text" : "password"} autoComplete="off" value={s.token} onChange={(e) => setS({ ...s, token: e.target.value.trim() })} placeholder="123456789:AA…" />
            <button className="btn px-3 text-xs" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button></div></label>
        <label className="block"><span className="text-xs text-mute">Channel</span>
          <input className="input mt-1" value={s.channel} onChange={(e) => setS({ ...s, channel: e.target.value.trim() })} placeholder="@yourchannel" /></label>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {([["approve_first", "Ask me before posting"], ["post_each_win", "Best wins (target 2 or 3)"], ["post_wins", "Wins of the day"], ["post_weekly", "Weekly results"], ["post_teaser", "Daily free signal"]] as const).map(([k, l]) => (
            <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={(s as any)[k]} onChange={(e) => setS({ ...s, [k]: e.target.checked })} />{l}</label>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={`btn ${s.enabled ? "" : "btn-primary"}`} disabled={!ready} onClick={() => save({ ...s, enabled: !s.enabled }, s.enabled ? "Autopilot paused." : "Autopilot on.")}>{s.enabled ? "Pause autopilot" : "Turn on autopilot"}</button>
          <button className="btn" onClick={() => save()}>Save</button>
          <button className="btn" disabled={!ready} onClick={test}>Send test post</button>
        </div>
        {msg && <p className="text-xs text-accent">{msg}</p>}
        {drafts.length > 0 && (
          <div className="space-y-3 border-t border-line pt-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-mute">Waiting for your approval ({drafts.length})</div>
            {drafts.map((d) => (
              <div key={d.id} className="rounded-lg border border-line p-2">
                <div className="mb-1 flex items-center justify-between text-xs text-mute"><span className="font-semibold text-text">{KIND[d.kind] ?? d.kind}</span><span>{ago(d.created_at)}</span></div>
                {d.png && <img src={`data:image/png;base64,${d.png}`} alt="" className="w-full rounded" loading="lazy" />}
                <p className="mt-2 whitespace-pre-line text-xs text-mute">{plain(d.caption)}</p>
                {busy[d.id] ? <p className="mt-2 text-xs text-accent">{busy[d.id]}</p> : (
                  <div className="mt-2 flex gap-2">
                    <button className="btn btn-primary flex-1" disabled={!ready} onClick={() => approve(d.id)}>Post</button>
                    <button className="btn flex-1" onClick={() => skip(d.id)}>Skip</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {st && <Note>{st.ok ? "Connected." : `Last problem: ${(st.errors ?? []).join("; ")}`}{st.last_post_at ? ` Last post ${ago(st.last_post_at)}.` : ""}</Note>}
      </div>
    </Card>
  );
}
