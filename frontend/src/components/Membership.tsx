import { useState } from "react";
import { compressImage, daysLeft, fmtDate, PayMethod, Plan, planLabel, submitPayment, supportLink, useMembershipConfig, useMyRecord } from "../lib/membership";
import { BinanceLogo, MexcLogo } from "./PayLogos";
import { Badge, Card } from "./ui";

/** Choose a plan → pay with Binance (QR) or MEXC (UID transfer) → upload proof. Used on the access screen and in Settings. */
export function PaymentPanel({ record, compact = false }: { record: any; compact?: boolean }) {
  const cfg = useMembershipConfig();
  const [months, setMonths] = useState<number>(record?.payment?.months ?? 1);
  const [txid, setTxid] = useState("");
  const [proof, setProof] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const plan: Plan = cfg.plans.find((p) => p.months === months) ?? cfg.plans[0];
  const monthly = cfg.plans.find((p) => p.months === 1)?.price;
  const pay = record?.payment;
  const [again, setAgain] = useState(false);
  const [method, setMethod] = useState<PayMethod>(record?.payment?.method ?? "binance");
  const [copied, setCopied] = useState(false);
  const exch = method === "mexc" ? "MEXC" : "Binance";
  const copyUid = () => { navigator.clipboard?.writeText(cfg.mexc_uid).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {}); };

  const pick = async (f?: File) => {
    if (!f) return;
    try { setProof(await compressImage(f)); setMsg(null); } catch (e: any) { setMsg({ ok: false, text: e.message }); }
  };
  const send = async () => {
    setBusy(true);
    try {
      await submitPayment(plan, txid, proof, cfg.currency, method);
      setMsg({ ok: true, text: "Proof sent. You will get access as soon as the owner checks the payment." });
      setAgain(false); setProof(null); setTxid("");
    } catch (e: any) { setMsg({ ok: false, text: e.message }); }
    setBusy(false);
  };

  if (pay?.status === "submitted" && !again) {
    return (
      <div className="rounded-2xl border border-accent/40 bg-accent/[0.07] p-4 text-left">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">Payment proof sent</span><Badge tone="warn">waiting for check</Badge>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-y-1.5 text-sm">
          <dt className="text-mute">Plan</dt><dd className="text-right">{planLabel(pay.months)}</dd>
          <dt className="text-mute">Amount</dt><dd className="num text-right">{pay.amount} {pay.currency}</dd>
          <dt className="text-mute">Paid with</dt><dd className="text-right">{pay.method === "mexc" ? "MEXC" : "Binance"}</dd>
          {pay.txid && <><dt className="text-mute">Order / Tx ID</dt><dd className="num truncate text-right">{pay.txid}</dd></>}
          <dt className="text-mute">Sent</dt><dd className="text-right">{fmtDate(pay.submitted_at)}</dd>
        </dl>
        <p className="mt-3 text-xs text-mute">This screen opens the app by itself once the owner approves. Usually within a few hours.</p>
        <button className="btn mt-3 w-full text-xs" onClick={() => setAgain(true)}>Send a different proof</button>
        {msg && <p className={`mt-2 text-xs ${msg.ok ? "text-bull" : "text-bear"}`}>{msg.text}</p>}
      </div>
    );
  }

  return (
    <div className="text-left">
      {pay?.status === "rejected" && (
        <div className="mb-3 rounded-xl border border-bear/40 bg-bear/10 p-3 text-sm">
          <span className="font-semibold text-bear">Your last payment proof was not accepted.</span>
          {pay.reason && <span className="text-mute"> Reason: {pay.reason}</span>} Please check and send it again.
        </div>
      )}
      <div className="text-xs font-medium uppercase tracking-[0.12em] text-mute">1 · Choose a plan</div>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {cfg.plans.map((p) => {
          const on = p.months === plan.months;
          const save = monthly && p.months > 1 ? Math.round((1 - p.price / (monthly * p.months)) * 100) : 0;
          return (
            <button key={p.months} type="button" onClick={() => setMonths(p.months)} aria-pressed={on}
              className={`relative rounded-xl border p-3 text-left transition ${on ? "border-accent bg-accent/[0.12] shadow-[0_0_0_1px_rgb(var(--accent)/0.6),0_8px_24px_rgb(var(--accent)/0.15)]" : "border-glass/10 bg-glass/[0.03] hover:border-accent/40"}`}>
              <div className="text-xs text-mute">{p.label}</div>
              <div className="num mt-0.5 text-xl font-semibold">${p.price}</div>
              <div className="num text-[11px] text-mute">${(p.price / p.months).toFixed(2)} / month</div>
              {save > 0 && <span className="absolute right-2 top-2 rounded-full bg-bull/15 px-1.5 py-0.5 text-[10px] font-semibold text-bull">−{save}%</span>}
            </button>
          );
        })}
      </div>

      <div className="mt-5 text-xs font-medium uppercase tracking-[0.12em] text-mute">2 · Choose how to pay</div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {([["binance", "Binance", BinanceLogo, "Binance Pay · QR"], ["mexc", "MEXC", MexcLogo, "Transfer to UID"]] as const).map(([id, name, Logo, sub]) => {
          const on = method === id;
          return (
            <button key={id} type="button" onClick={() => setMethod(id)} aria-pressed={on}
              className={`flex items-center gap-3 rounded-xl border p-3 text-left transition ${on ? "border-accent bg-accent/[0.12] shadow-[0_0_0_1px_rgb(var(--accent)/0.6)]" : "border-glass/10 bg-glass/[0.03] hover:border-accent/40"}`}>
              <Logo />
              <span><span className="block font-semibold">{name}</span><span className="block text-[11px] text-mute">{sub}</span></span>
            </button>
          );
        })}
      </div>

      <div className="mt-5 text-xs font-medium uppercase tracking-[0.12em] text-mute">3 · Pay with {exch}</div>
      {method === "binance" ? (
        <>
          <div className={`mt-2 grid items-center gap-4 ${compact ? "" : "sm:grid-cols-[220px_1fr]"}`}>
            <a href={cfg.qr_url} target="_blank" rel="noopener" className="mx-auto block w-full max-w-[220px] overflow-hidden rounded-2xl bg-white p-1.5 shadow-[0_8px_30px_rgb(var(--accent)/0.18)]">
              <img src={cfg.qr_url} alt="Binance Pay QR code for Hesper" className="w-full rounded-xl" />
            </a>
            <ol className="list-decimal space-y-1.5 pl-5 text-sm text-mute marker:text-accent">
              <li>Open the <span className="text-text">Binance app</span> → <span className="text-text">Pay</span> → <span className="text-text">Scan</span>, and scan the QR code (or tap it to open it full size).</li>
              <li>Send exactly <span className="num font-semibold text-accent">{plan.price} {cfg.currency}</span> for <span className="text-text">{plan.label}</span>.</li>
              <li>Take a screenshot of the <span className="text-text">payment successful</span> screen showing the amount and the order ID.</li>
            </ol>
          </div>
          {cfg.pay_note && <p className="mt-2 text-xs text-mute">{cfg.pay_note}</p>}
        </>
      ) : (
        <div className="mt-2 space-y-3">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-accent/40 bg-accent/[0.06] p-3">
            <div><div className="text-xs text-mute">MEXC UID</div><div className="num text-xl font-semibold tracking-wider">{cfg.mexc_uid}</div></div>
            <button type="button" className="btn text-xs" onClick={copyUid}>{copied ? "Copied ✓" : "Copy UID"}</button>
          </div>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-mute marker:text-accent">
            <li>Open the <span className="text-text">MEXC app</span> → <span className="text-text">Wallets</span> → <span className="text-text">Withdraw</span> → choose <span className="text-text">USDT</span>.</li>
            <li>Pick <span className="text-text">Internal transfer (MEXC user)</span> and paste the UID <span className="num text-text">{cfg.mexc_uid}</span>.</li>
            <li>Send exactly <span className="num font-semibold text-accent">{plan.price} {cfg.currency}</span> for <span className="text-text">{plan.label}</span> and confirm.</li>
            <li>Take a screenshot of the <span className="text-text">transfer successful</span> screen showing the amount and the order ID.</li>
          </ol>
        </div>
      )}

      <div className="mt-5 text-xs font-medium uppercase tracking-[0.12em] text-mute">4 · Send the proof</div>
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <label className="flex min-h-[96px] cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-accent/40 bg-accent/[0.04] p-3 text-center text-sm hover:bg-accent/[0.08]">
          {proof ? <img src={proof} alt="Payment screenshot" className="max-h-40 rounded-lg" /> : <><span className="text-accent">＋ Upload screenshot</span><span className="text-xs text-mute">PNG or JPG from your gallery</span></>}
          <input type="file" accept="image/*" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        </label>
        <label className="text-xs text-mute">{exch} order ID / transaction ID (recommended)
          <input className="input num mt-1" placeholder="e.g. 3184 5512 0098 7766" value={txid} onChange={(e) => setTxid(e.target.value)} />
          <span className="mt-1 block">{method === "mexc" ? "Found under MEXC → Wallets → History → the transfer." : "Found under Binance → Pay → History → the payment."}</span>
        </label>
      </div>
      <button className="btn btn-primary mt-4 w-full py-2.5" disabled={busy} onClick={send}>
        {busy ? "Sending…" : `Send proof · ${plan.label} · $${plan.price}`}
      </button>
      {msg && <p className={`mt-2 text-sm ${msg.ok ? "text-bull" : "text-bear"}`}>{msg.text}</p>}
    </div>
  );
}

/** Settings card for members: when the membership ends and how to renew. */
export function MembershipCard() {
  const r = useMyRecord();
  const [open, setOpen] = useState(false);
  if (!r) return null;
  const left = daysLeft(r.expires_at);
  const tone = left == null ? "bull" : left <= 3 ? "bear" : left <= 7 ? "warn" : "bull";
  return (
    <Card title="Membership" right={<Badge tone={tone as any}>{left == null ? "no end date" : left > 0 ? `${left} days left` : "ended"}</Badge>}>
      <dl className="grid grid-cols-2 gap-y-1.5 text-sm">
        <dt className="text-mute">Plan</dt><dd className="text-right">{r.plan_months ? planLabel(r.plan_months) : "—"}</dd>
        <dt className="text-mute">Active until</dt><dd className="text-right">{r.expires_at ? fmtDate(r.expires_at) : "no end date"}</dd>
        <dt className="text-mute">Member since</dt><dd className="text-right">{fmtDate(r.approved_at)}</dd>
      </dl>
      {r.payment?.status === "submitted" && <p className="mt-3 text-xs text-warn">Renewal proof sent on {fmtDate(r.payment.submitted_at)} · waiting for the owner.</p>}
      {r.expires_at && <button className="btn btn-primary mt-3 w-full" onClick={() => setOpen(!open)}>{open ? "Hide" : "Renew / extend"}</button>}
      {open && <div className="mt-4 border-t border-glass/[0.06] pt-4"><PaymentPanel record={r} compact /></div>}

    </Card>
  );
}

/** Thin banner in the app when a membership ends within a week. */
export function RenewBanner() {
  const r = useMyRecord();
  const left = daysLeft(r?.expires_at);
  if (left == null || left > 7 || r?.payment?.status === "submitted") return null;
  return (
    <a href="/settings" className="block border-b border-warn/30 bg-warn/10 px-4 py-2 text-center text-sm text-warn hover:bg-warn/15">
      Your membership ends {left <= 1 ? "within a day" : `in ${left} days`} ({fmtDate(r.expires_at)}). Tap to renew in Settings.
    </a>
  );
}

/** "Need help?" card: email the app owner (address set on the Users page). */
export function ContactCard() {
  const { support_email } = useMembershipConfig();
  const [copied, setCopied] = useState(false);
  return (
    <Card title="Help & support">
      <p className="text-sm text-mute">Questions or problems? Email us.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <a className="btn btn-primary" href={supportLink(support_email)}>Email support</a>
        <button className="btn" onClick={async () => { try { await navigator.clipboard.writeText(support_email); setCopied(true); window.setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ } }}>{copied ? "Copied" : "Copy address"}</button>
      </div>
      <p className="num mt-2 break-all text-sm text-accent">{support_email}</p>
    </Card>
  );
}

/** One-line support link for small places (access screen, menus). */
export function SupportLink({ className = "", label = "Contact support" }: { className?: string; label?: string }) {
  const { support_email } = useMembershipConfig();
  return <a className={className} href={supportLink(support_email)}>{label}</a>;
}
