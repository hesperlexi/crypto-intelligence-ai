// v2.9 sealed-signal proof (engine: services/proof.py). Each call's fingerprint (SHA-256 of its published levels + a
// secret salt) is posted to the public Telegram channel when it is published; the full text follows when it closes.
//   record row .proof = {hash, sealed_at?, text? (closed calls only)}
import { useState } from "react";
import { Pill } from "./SignalExtras";

async function sha256(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Small "Sealed" pill on a record row; opens the fingerprint (and the text once the call closed). */
export function SealPill({ proof }: { proof?: { hash: string; sealed_at?: number | null; text?: string } | null }) {
  const [open, setOpen] = useState(false);
  if (!proof?.hash) return null;
  const posted = proof.sealed_at && proof.sealed_at > 0;
  return (
    <>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="inline-flex">
        <Pill tone={posted ? "accent" : "mute"} title={posted ? "Fingerprint posted publicly when this signal was published" : "Fingerprint stored (not posted publicly)"}>🔒 Sealed</Pill>
      </button>
      {open && (
        <div className="mt-1 w-full space-y-1 rounded-lg border border-glass/[0.1] bg-glass/[0.03] p-2 text-[11px] text-mute">
          <div>Fingerprint{posted ? ` · posted ${new Date(proof.sealed_at!).toLocaleString()}` : ""}</div>
          <code className="block break-all text-text">{proof.hash}</code>
          {proof.text
            ? <><div>Sealed text (revealed after close)</div><code className="block break-all text-text">{proof.text}</code><VerifyNow text={proof.text} hash={proof.hash} /></>
            : <div>The text is revealed when the signal closes.</div>}
        </div>
      )}
    </>
  );
}

function VerifyNow({ text, hash }: { text: string; hash: string }) {
  const [ok, setOk] = useState<boolean | null>(null);
  return (
    <div className="flex items-center gap-2">
      <button type="button" className="btn btn-sm px-2 text-[11px]" onClick={async () => setOk((await sha256(text)) === hash)}>Check it</button>
      {ok != null && <span className={ok ? "text-bull" : "text-bear"}>{ok ? "✓ Matches the fingerprint" : "✗ Does not match"}</span>}
    </div>
  );
}

/** "How to verify" box with a SHA-256 checker (Results page, #verify). */
export function VerifyBox() {
  const [text, setText] = useState("");
  const [hash, setHash] = useState("");
  const [out, setOut] = useState<string | null>(null);
  const run = async () => {
    const h = await sha256(text.trim());
    setOut(hash.trim() ? (h === hash.trim().toLowerCase() ? "match" : "nomatch") : h);
  };
  return (
    <section id="verify" className="panel scroll-mt-24 p-0">
      <div className="card-head border-b border-glass/[0.06] px-4 py-2.5"><h2 className="label">🔒 Sealed signals · verify our record</h2></div>
      <div className="space-y-3 p-4 text-sm">
        <p className="text-mute">The moment a signal is published, its fingerprint (a SHA-256 code of its coin, direction, entry, stop-loss, targets, time and a secret salt) is posted to our public Telegram channel, time-stamped by Telegram. When the signal closes, the full text is posted too. If the text's SHA-256 equals the fingerprint posted earlier, the signal was not changed or added after the result was known.</p>
        <label className="block">
          <span className="text-xs text-mute">Sealed text (from the "Signal revealed" post or a record row)</span>
          <textarea className="input mt-1 min-h-[64px] w-full py-2 font-mono text-xs" value={text} onChange={(e) => { setText(e.target.value); setOut(null); }} placeholder="CIA-SEAL-1|…" />
        </label>
        <label className="block">
          <span className="text-xs text-mute">Fingerprint from the earlier "Sealed signal" post (optional)</span>
          <input className="input mt-1 w-full font-mono text-xs" value={hash} onChange={(e) => { setHash(e.target.value); setOut(null); }} placeholder="64 characters" />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn btn-primary" disabled={!text.trim()} onClick={run}>Verify</button>
          {out === "match" && <span className="font-semibold text-bull">✓ Matches: the signal was sealed before its result.</span>}
          {out === "nomatch" && <span className="font-semibold text-bear">✗ Does not match.</span>}
          {out && out !== "match" && out !== "nomatch" && <span className="break-all font-mono text-xs">SHA-256: {out}</span>}
        </div>
        <p className="text-[11px] text-mute">The check runs in your browser. Any SHA-256 tool gives the same result. Signals published before 31 Oct 2026 were not sealed.</p>
      </div>
    </section>
  );
}
