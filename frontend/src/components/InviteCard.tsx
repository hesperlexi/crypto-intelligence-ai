// v2.16 Settings → Invite friends: the member's personal link, copy / share, and how many friends joined and paid.
// Counts: `referral_stats` on the member's own record (written by the engine, which can see who used the link);
// free months: the member's own history entries of kind "referral" (shown at once after the admin's approval).
import { useState } from "react";
import { Tile } from "./kit";
import { Card } from "./ui";
import { useMyRecord } from "../lib/membership";
import { createMyCode, inviteLink } from "../lib/referral";
import { getSession, useSession } from "../lib/session";

export default function InviteCard() {
  const me = useMyRecord();
  const role = useSession()?.role;
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const code: string | undefined = me?.ref_code;
  const link = code ? inviteLink(code) : null;
  const months = (me?.history ?? []).filter((h: any) => h?.kind === "referral").length;
  const st = me?.referral_stats ?? {};
  const create = async () => {
    const uid = getSession()?.uid;
    if (!uid) return;
    setBusy(true); setErr(null);
    try { await createMyCode(uid); } catch (e: any) { setErr(e.message ?? "Could not make your link. Please try again."); }
    setBusy(false);
  };
  const copy = async () => {
    if (!link) return;
    try { await navigator.clipboard.writeText(link); setMsg("Link copied."); } catch { setMsg("Select the link and copy it."); }
  };
  const share = async () => {
    if (!link) return;
    try { await navigator.share({ title: "Crypto Intelligence AI", text: "Join me on Crypto Intelligence AI:", url: link }); } catch { /* closed */ }
  };
  if (role !== "member") return null;                     // active members only (the rules allow codes only for them)
  return (
    <Card title="Invite friends">
      <p className="text-sm text-mute">Get 1 free month when a friend you invite joins and their first payment is approved.</p>
      {me === undefined ? <div className="skeleton mt-3 h-10 rounded-lg" /> : !link ? (
        <button type="button" className="btn btn-primary mt-3" onClick={create} disabled={busy || !me}>{busy ? "Making your link…" : "Get my invite link"}</button>
      ) : (
        <div className="mt-3 space-y-2">
          <label className="block">
            <span className="sr-only">Your invite link</span>
            <input className="input num w-full" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
          </label>
          <div className="flex gap-2">
            <button type="button" className="btn flex-1" onClick={copy}>Copy link</button>
            {typeof navigator !== "undefined" && "share" in navigator && <button type="button" className="btn flex-1" onClick={share}>Share</button>}
          </div>
          <p className="text-xs text-mute">Your code: <span className="num font-semibold text-text">{code}</span></p>
        </div>
      )}
      {msg && <p className="mt-2 text-xs text-bull" role="status">{msg}</p>}
      {err && <p className="mt-2 text-xs text-bear" role="alert">{err}</p>}
      <div className="metric-strip mt-3" style={{ gridTemplateColumns: "repeat(3, minmax(0, 1fr))" }}>
        <Tile variant="strip" label="Joined" value={st.joined ?? 0} />
        <Tile variant="strip" label="Paid" value={Math.max(st.paid ?? 0, months)} />
        <Tile variant="strip" label="Free months" value={months} valueClass={months ? "text-accent" : ""} />
      </div>
    </Card>
  );
}
