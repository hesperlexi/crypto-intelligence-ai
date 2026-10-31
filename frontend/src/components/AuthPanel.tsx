// Sign-in UI: Google or email + password (sign in / create account / forgot password), the "check your inbox"
// screen for new email accounts, and the one-time username picker. Passwords are only passed to Firebase Auth.
import { signInWithPopup, signOut, User } from "firebase/auth";
import { FormEvent, ReactNode, useCallback, useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { auth, googleProvider } from "../lib/firebase";
import { authMessage, checkPassword, claimUsername, MIN_PASSWORD, refreshVerified, resendVerification, resendWait, resetPassword, signInEmail, signUp, usernameProblem, usernameTaken } from "../lib/account";
import { BRAND } from "../lib/brand";
import { APP_VERSION, COPYRIGHT } from "../lib/version";
import { HeroLogo } from "./Logo";
import { useFocusTrap } from "./Shell";

export type AuthMode = "signin" | "signup" | "reset";

export function GoogleIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 48 48" className="mr-2 inline-block align-[-3px]"><path fill="currentColor" d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z" /></svg>;
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return <label className="block text-left text-xs text-mute">{label}<div className="mt-1">{children}</div>{hint && <div className="mt-1 text-[11px]">{hint}</div>}</label>;
}

/** Google + email forms. Used in the sign-in dialog on the landing page. */
export function AuthForms({ initial = "signin", onDone }: { initial?: AuthMode; onDone?: () => void }) {
  const [mode, setMode] = useState<AuthMode>(initial);
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState<null | "google" | "email">(null);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const ids = useId();
  useEffect(() => { setErr(null); setInfo(null); }, [mode]);

  const google = async () => {
    setBusy("google"); setErr(null);
    try { await signInWithPopup(auth, googleProvider); onDone?.(); } catch (e) { setErr(authMessage(e)); }
    setBusy(null);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null); setInfo(null);
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) { setErr("Enter a valid email address."); return; }
    if (mode === "signup") {
      const bad = checkPassword(pw);
      if (bad) { setErr(bad); return; }
      if (pw !== pw2) { setErr("The two passwords are not the same."); return; }
    } else if (mode === "signin" && !pw) { setErr("Enter your password."); return; }
    setBusy("email");
    try {
      if (mode === "signup") { await signUp(email, pw); onDone?.(); }
      else if (mode === "signin") { await signInEmail(email, pw); onDone?.(); }
      else { await resetPassword(email); setInfo(`If an account exists for ${email.trim()}, a reset link is on its way. Check your inbox (and spam).`); }
    } catch (e2) {
      // a reset request never says whether the address has an account
      if (mode === "reset" && /user-not-found/.test(String((e2 as any)?.code))) setInfo(`If an account exists for ${email.trim()}, a reset link is on its way. Check your inbox (and spam).`);
      else setErr(authMessage(e2));
    }
    setPw(""); setPw2("");          // never keep a typed password around after a try
    setBusy(null);
  };

  const tab = (k: AuthMode, l: string) => (
    <button type="button" role="tab" aria-selected={mode === k} onClick={() => setMode(k)}
      className={`-mb-px flex-1 border-b-2 pb-2 text-sm ${mode === k ? "border-accent font-semibold text-text" : "border-transparent text-mute hover:text-text"}`}>{l}</button>
  );
  return (
    <div className="text-left">
      {mode !== "reset" && (
        <>
          <button type="button" className="btn btn-primary w-full py-2.5" onClick={google} disabled={!!busy}><GoogleIcon />{busy === "google" ? "Opening Google…" : "Continue with Google"}</button>
          <div className="my-4 flex items-center gap-3 text-[11px] uppercase tracking-wider text-mute"><span className="h-px flex-1 bg-glass/10" />or with email<span className="h-px flex-1 bg-glass/10" /></div>
          <div className="mb-4 flex gap-4 border-b border-glass/[0.08]" role="tablist">{tab("signin", "Sign in")}{tab("signup", "Create account")}</div>
        </>
      )}
      {mode === "reset" && (
        <div className="mb-4">
          <h3 className="font-display text-lg font-bold">Reset your password</h3>
          <p className="mt-1 text-sm text-mute">Enter the email you signed up with. We'll send you a link to choose a new password.</p>
        </div>
      )}
      <form className="space-y-3" onSubmit={submit} noValidate>
        <Field label="Email"><input id={`${ids}e`} className="input" type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required /></Field>
        {mode !== "reset" && (
          <Field label="Password" hint={mode === "signup" ? <span className={pw && pw.length < MIN_PASSWORD ? "text-warn" : "text-mute"}>At least {MIN_PASSWORD} characters.</span> : undefined}>
            <div className="relative">
              <input className="input pr-16" type={show ? "text" : "password"} autoComplete={mode === "signup" ? "new-password" : "current-password"} value={pw} onChange={(e) => setPw(e.target.value)} required minLength={mode === "signup" ? MIN_PASSWORD : undefined} />
              <button type="button" className="absolute inset-y-0 right-2 my-auto h-7 rounded px-2 text-xs text-mute hover:text-text" onClick={() => setShow((v) => !v)} aria-pressed={show}>{show ? "Hide" : "Show"}</button>
            </div>
          </Field>
        )}
        {mode === "signup" && <Field label="Repeat password"><input className="input" type={show ? "text" : "password"} autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required /></Field>}
        {err && <p role="alert" className="rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">{err}</p>}
        {info && <p role="status" className="rounded-lg border border-bull/40 bg-bull/10 px-3 py-2 text-sm text-bull">{info}</p>}
        <button type="submit" className="btn w-full py-2.5 font-semibold" disabled={!!busy}>
          {busy === "email" ? "Please wait…" : mode === "signup" ? "Create account" : mode === "signin" ? "Sign in" : "Send reset link"}
        </button>
      </form>
      <div className="mt-3 flex justify-between text-xs">
        {mode === "signin" ? <button type="button" className="text-accent hover:underline" onClick={() => setMode("reset")}>Forgot password?</button>
          : mode === "reset" ? <button type="button" className="text-accent hover:underline" onClick={() => setMode("signin")}>← Back to sign in</button> : <span />}
        {mode === "signup" && <span className="text-mute">We'll email you a link to confirm the address.</span>}
      </div>
    </div>
  );
}

/** Modal with the sign-in forms (landing page "Sign in" / "Create account" buttons). */
export function AuthDialog({ mode, onClose }: { mode: AuthMode; onClose: () => void }) {
  const close = useCallback(() => onClose(), [onClose]);
  const ref = useFocusTrap(true, close);
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end justify-center sm:items-center sm:p-4" onClick={close}>
      <div className="absolute inset-0 bg-ink/70 backdrop-blur-sm" />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={mode === "signup" ? "Create an account" : "Sign in"} onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-md">
        <div className="panel animate-in max-h-[92dvh] overflow-y-auto rounded-b-none p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] sm:rounded-2xl sm:p-6">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="font-display text-xl font-bold">Welcome to Crypto Intelligence <span className="text-accent">AI</span></h2>
              <p className="mt-1 text-sm text-mute">Sign in or create a free account, then choose a plan.</p>
            </div>
            <button className="btn h-9 w-9 shrink-0 p-0" aria-label="Close" onClick={close}>✕</button>
          </div>
          <AuthForms initial={mode} onDone={close} />
          <p className="mt-4 text-center text-[11px] text-mute">By continuing you agree to the <a className="text-accent hover:underline" href="/terms">Terms of Use</a> and the <a className="text-accent hover:underline" href="/risk">Risk disclosure</a>.</p>
        </div>
      </div>
    </div>,
    document.body,
  );
}

function CenterCard({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-full items-start justify-center px-3 py-8 sm:items-center sm:px-4">
      <div className="panel w-full max-w-md p-6 text-center sm:p-7">
        <HeroLogo size={88} title="Crypto Intelligence AI logo" className="mx-auto mb-4" />
        {children}
        <p className="mt-6 text-[11px] text-mute">{COPYRIGHT} · v{APP_VERSION} · <a className="hover:text-text" href={`mailto:${BRAND.supportEmail}`}>{BRAND.supportEmail}</a></p>
      </div>
    </div>
  );
}

/** New email account: confirm the address before anything else (the database only opens to verified accounts). */
export function VerifyEmailScreen({ user, onVerified }: { user: User; onVerified: () => void }) {
  const [wait, setWait] = useState(resendWait());
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { const t = window.setInterval(() => setWait(resendWait()), 1000); return () => window.clearInterval(t); }, []);
  const resend = async () => {
    setMsg(null);
    try { await resendVerification(user); setWait(resendWait()); setMsg({ ok: true, text: "Sent again. It can take a minute to arrive; check the spam folder too." }); }
    catch (e) { setMsg({ ok: false, text: (e as any)?.code ? authMessage(e) : String((e as Error).message) }); }
  };
  const check = async () => {
    setBusy(true); setMsg(null);
    try {
      if (await refreshVerified(user)) onVerified();
      else setMsg({ ok: false, text: "Not confirmed yet. Open the link in the email we sent, then tap this button again." });
    } catch (e) { setMsg({ ok: false, text: authMessage(e) }); }
    setBusy(false);
  };
  return (
    <CenterCard>
      <h1 className="text-xl font-semibold tracking-tight">Check your inbox</h1>
      <p className="mt-2 text-sm text-mute">We sent a confirmation link to <span className="text-text [overflow-wrap:anywhere]">{user.email}</span>. Open it to confirm your email address, then come back here.</p>
      <button className="btn btn-primary mt-5 w-full py-2.5" onClick={check} disabled={busy}>{busy ? "Checking…" : "I've confirmed my email"}</button>
      <button className="btn mt-2 w-full" onClick={resend} disabled={wait > 0}>{wait > 0 ? `Resend email in ${wait} s` : "Resend email"}</button>
      {msg && <p role={msg.ok ? "status" : "alert"} className={`mt-3 text-sm ${msg.ok ? "text-bull" : "text-warn"}`}>{msg.text}</p>}
      <p className="mt-4 text-xs text-mute">Wrong address? <button className="text-accent hover:underline" onClick={() => signOut(auth)}>Use another account</button></p>
    </CenterCard>
  );
}

/** One-time username picker (any sign-in method, once the email is confirmed). */
export function UsernameScreen({ user, admin }: { user: User; admin: boolean }) {
  const [name, setName] = useState(() => (user.displayName ?? user.email?.split("@")[0] ?? "").toLowerCase().replace(/[^a-z0-9_]/g, "").slice(0, 20));
  const [state, setState] = useState<null | "checking" | "free" | "taken">(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const n = name.trim().toLowerCase();
  const problem = n ? usernameProblem(n, admin) : null;
  useEffect(() => {
    setState(null);
    if (!n || problem) return;
    let live = true;
    const t = window.setTimeout(() => { setState("checking"); usernameTaken(n).then((x) => live && setState(x ? "taken" : "free")).catch(() => live && setState(null)); }, 400);
    return () => { live = false; window.clearTimeout(t); };
  }, [n, problem]);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null); setBusy(true);
    try { await claimUsername(user, n, { admin }); } catch (e2) { setErr((e2 as Error).message); }
    setBusy(false);
  };
  return (
    <CenterCard>
      <h1 className="text-xl font-semibold tracking-tight">Choose your username</h1>
      <p className="mt-2 text-sm text-mute">Other members see it next to your posts in Community. It can't be changed later, and your email stays private.</p>
      <form className="mt-5 text-left" onSubmit={save} noValidate>
        <label className="block text-xs text-mute">Username
          <div className="mt-1 flex items-center rounded-lg border border-glass/[0.14] bg-ink/50 focus-within:border-accent/70 focus-within:shadow-[0_0_0_3px_rgb(var(--accent)/0.15)]">
            <span className="pl-3 text-mute">@</span>
            <input className="min-w-0 flex-1 bg-transparent px-1.5 py-2.5 text-sm text-text outline-none focus-visible:outline-none" value={name} maxLength={20} autoCapitalize="none" autoCorrect="off" spellCheck={false}
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/\s/g, "_"))} aria-describedby="uname-help" aria-invalid={!!problem || state === "taken"} />
          </div>
        </label>
        <p id="uname-help" className={`mt-1.5 text-xs ${problem || state === "taken" ? "text-warn" : state === "free" ? "text-bull" : "text-mute"}`} aria-live="polite">
          {problem ?? (state === "taken" ? "That username is taken." : state === "free" ? "Available." : state === "checking" ? "Checking…" : "3-20 characters: letters a-z, numbers and _.")}
        </p>
        {err && <p role="alert" className="mt-2 rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">{err}</p>}
        <button type="submit" className="btn btn-primary mt-4 w-full py-2.5" disabled={busy || !n || !!problem || state === "taken" || state === "checking"}>{busy ? "Saving…" : "Save username"}</button>
      </form>
      <p className="mt-4 text-xs text-mute">Signed in as <span className="text-text [overflow-wrap:anywhere]">{user.email}</span> · <button className="text-accent hover:underline" onClick={() => signOut(auth)}>Sign out</button></p>
    </CenterCard>
  );
}
