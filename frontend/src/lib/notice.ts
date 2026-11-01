// Small app-wide notices + "waiting for the engine" markers (admin Adjust / Close now). Saving queues an engine job and
// the dialog closes at once; the answer arrives later as a notice, so the admin can keep working.
import { useSyncExternalStore } from "react";

export type Notice = { id: number; text: string; tone: "ok" | "bad" | "info" };
let notices: Notice[] = [];
const pending = new Map<string, string>();         // signal id -> "close" | "adjust"
const subs = new Set<() => void>();
let seq = 0;
let snap = { notices, pending: new Map(pending) };
const emit = () => { snap = { notices, pending: new Map(pending) }; subs.forEach((f) => f()); };

export function notify(text: string, tone: Notice["tone"] = "info", ms = 9000) {
  const n = { id: ++seq, text, tone };
  notices = [...notices, n].slice(-4);
  emit();
  if (ms) window.setTimeout(() => dismiss(n.id), ms);
}
export function dismiss(id: number) { notices = notices.filter((n) => n.id !== id); emit(); }
export function setPending(signalId: string, what: string | null) {
  if (what) pending.set(signalId, what); else pending.delete(signalId);
  emit();
}
export function useNotices() {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => snap);
}

/** Run an engine job in the background: mark it pending, notify when it is applied or refused. */
export function track<T>(signalId: string, what: string, done: Promise<T>, ok: (r: T) => string) {
  setPending(signalId, what);
  notify(what === "close" ? "Saved: the engine closes it on its next run (within about 5 minutes). Keep working; you'll get a notice."
    : "Saved: the engine applies the change on its next run (within about 5 minutes). Keep working; you'll get a notice.", "info", 8000);
  done.then((r) => notify(ok(r), "ok", 12000))
    .catch((e: any) => notify(`Not applied: ${e?.message ?? "the engine refused it"}`, "bad", 15000))
    .finally(() => setPending(signalId, null));
}
