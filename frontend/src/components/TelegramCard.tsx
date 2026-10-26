// Owner only: connect the public Telegram channel. The token lives in owner/telegram (members cannot read it).
import { doc, onSnapshot, setDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { queueJob } from "../lib/api";
import { db } from "../lib/firebase";
import { ago } from "../lib/format";
import { Card, Note } from "./ui";

const DEF = { enabled: false, token: "", channel: "@crypappai", post_wins: true, post_weekly: true, post_teaser: true };

export default function TelegramCard() {
  const [s, setS] = useState(DEF);
  const [st, setSt] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [show, setShow] = useState(false);
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
        <p className="text-xs text-mute">Daily wins, Monday results and one free signal a day. Setup: @BotFather → /newbot → copy token; add the bot as channel admin.</p>
        <label className="block"><span className="text-xs text-mute">Bot token (private)</span>
          <div className="mt-1 flex gap-2"><input className="input flex-1" type={show ? "text" : "password"} autoComplete="off" value={s.token} onChange={(e) => setS({ ...s, token: e.target.value.trim() })} placeholder="123456789:AA…" />
            <button className="btn px-3 text-xs" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"}</button></div></label>
        <label className="block"><span className="text-xs text-mute">Channel</span>
          <input className="input mt-1" value={s.channel} onChange={(e) => setS({ ...s, channel: e.target.value.trim() })} placeholder="@yourchannel" /></label>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {([["post_wins", "Wins of the day"], ["post_weekly", "Weekly results"], ["post_teaser", "Daily free signal"]] as const).map(([k, l]) => (
            <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={(s as any)[k]} onChange={(e) => setS({ ...s, [k]: e.target.checked })} />{l}</label>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={`btn ${s.enabled ? "" : "btn-primary"}`} disabled={!ready} onClick={() => save({ ...s, enabled: !s.enabled }, s.enabled ? "Autopilot paused." : "Autopilot on.")}>{s.enabled ? "Pause autopilot" : "Turn on autopilot"}</button>
          <button className="btn" onClick={() => save()}>Save</button>
          <button className="btn" disabled={!ready} onClick={test}>Send test post</button>
        </div>
        {msg && <p className="text-xs text-accent">{msg}</p>}
        {st && <Note>{st.ok ? "Connected." : `Last problem: ${(st.errors ?? []).join("; ")}`}{st.last_post_at ? ` Last post ${ago(st.last_post_at)}.` : ""}</Note>}
      </div>
    </Card>
  );
}
