// v2.61 "Ask AI" for members: a small button bottom-right that opens a chat panel (bottom sheet on phones). The assistant
// explains what is on the current page (lib/chat.ts sends that page's figures); it never gives buy / sell advice.
import { FormEvent, useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { askAI, CHAT_MEMBERS, chatReady, starters, Turn } from "../lib/chat";
import { useSession } from "../lib/session";

function Answer({ text }: { text: string }) {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const bullets = lines.filter((l) => /^[-*•]\s+/.test(l));
  return (
    <div className="space-y-1.5">
      {lines.filter((l) => !/^[-*•]\s+/.test(l)).map((l, i) => <p key={i}>{l.replace(/\*\*/g, "")}</p>)}
      {bullets.length > 0 && <ul className="list-disc space-y-1 pl-4">{bullets.map((l, i) => <li key={i}>{l.replace(/^[-*•]\s+/, "").replace(/\*\*/g, "")}</li>)}</ul>}
    </div>
  );
}

export default function AskAI() {
  const s = useSession();
  const loc = useLocation();
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [left, setLeft] = useState<number | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" }); }, [turns, busy]);
  useEffect(() => { if (open) window.setTimeout(() => input.current?.focus(), 60); }, [open]);
  useEffect(() => {
    if (!open) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);

  if (!s || !(s.role === "admin" || (s.role === "member" && CHAT_MEMBERS)) || !chatReady()) return null;

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setErr(null); setQ(""); setBusy(true);
    const history = turns;
    setTurns([...history, { role: "user", text: question }]);
    try {
      const r = await askAI(question, history, loc.pathname, loc.search);
      setTurns((t) => [...t, { role: "model", text: r.answer }]);
      if (r.left != null) setLeft(r.left);
    } catch (e: any) {
      setErr(e?.message ?? "Something went wrong.");
      if (e?.left != null) setLeft(e.left);
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); send(q); };

  return (
    <>
      {!open && (
        <button type="button" className="askai-fab" onClick={() => setOpen(true)} aria-label="Ask AI about this page">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 3l1.8 4.6L18 9l-4.2 1.6L12 15l-1.8-4.4L6 9l4.2-1.4z" /><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z" />
          </svg>
          <span>Ask AI</span>
        </button>
      )}
      {open && (
        <div className="askai-wrap" role="dialog" aria-modal="false" aria-label="Ask AI">
          <section className="askai-panel">
            <header className="askai-head">
              <div className="min-w-0">
                <div className="flex items-center gap-2 font-semibold"><span className="askai-dot" aria-hidden="true" />Ask AI</div>
                <p className="truncate text-xs text-mute">Explains what's on this page · not financial advice</p>
              </div>
              <div className="flex items-center gap-1">
                {turns.length > 0 && <button type="button" className="btn px-2.5 py-1 text-xs" onClick={() => { setTurns([]); setErr(null); }}>New chat</button>}
                <button type="button" className="askai-x tap" onClick={() => setOpen(false)} aria-label="Close">✕</button>
              </div>
            </header>
            <div ref={list} className="askai-list" aria-live="polite">
              {turns.length === 0 && (
                <div className="space-y-3">
                  <p className="text-sm text-mute">Ask about the signals, levels, results or news on this page. The answer uses only the figures you can see here.</p>
                  <div className="flex flex-col gap-2">
                    {starters(loc.pathname).map((t) => <button key={t} type="button" className="askai-starter" onClick={() => send(t)}>{t}</button>)}
                  </div>
                </div>
              )}
              {turns.map((t, i) => (
                <div key={i} className={t.role === "user" ? "askai-me" : "askai-ai"}>
                  {t.role === "user" ? t.text : <Answer text={t.text} />}
                </div>
              ))}
              {busy && <div className="askai-ai askai-typing" aria-label="Thinking"><span /><span /><span /></div>}
              {err && <div className="askai-err" role="alert">{err}</div>}
            </div>
            <form className="askai-form" onSubmit={submit}>
              <textarea ref={input} className="input min-h-[44px] flex-1 resize-none py-2.5" rows={1} maxLength={600} value={q}
                placeholder="Ask about this page…" aria-label="Your question" onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} />
              <button type="submit" className="btn btn-primary shrink-0 px-4" disabled={busy || !q.trim()}>Send</button>
            </form>
            {left != null && <p className="px-4 pb-2 text-xs text-mute">{left} question{left === 1 ? "" : "s"} left today</p>}
          </section>
        </div>
      )}
    </>
  );
}
