// App-wide building blocks: error boundary, 404 page, route skeletons, owner-only guard, bottom-bar icons,
// focus trap for sheets.
import { Component, ErrorInfo, ReactNode, useEffect, useRef } from "react";
import { Link, Navigate } from "react-router-dom";
import { BRAND } from "../lib/brand";
import { useIsAdmin } from "../lib/session";
import { HeroLogo, LogoSpinner } from "./Logo";

/** Friendly page instead of a blank screen when something throws while rendering. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("App error", error, info.componentStack); }
  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });  // navigating away clears it
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-4 py-10">
        <div className="panel w-full max-w-md p-7 text-center">
          <HeroLogo size={72} className="mx-auto" />
          <h1 className="mt-4 text-xl font-semibold tracking-tight">Something went wrong</h1>
          <p className="mt-2 text-sm text-mute">This page could not be shown. Reloading usually fixes it. If it keeps happening, tell us what you were doing.</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <button type="button" className="btn btn-primary" onClick={() => location.reload()}>Reload</button>
            <a className="btn" href={`mailto:${BRAND.supportEmail}?subject=${encodeURIComponent("App error")}`}>Contact {BRAND.supportEmail}</a>
          </div>
        </div>
      </div>
    );
  }
}

export function NotFound() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center px-4 py-10">
      <div className="panel w-full max-w-md p-7 text-center">
        <HeroLogo size={72} className="mx-auto" />
        <p className="num mt-4 text-sm font-semibold text-accent">404</p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight">Page not found</h1>
        <p className="mt-2 text-sm text-mute">The link may be old or mistyped. Everything else is where you left it.</p>
        <Link to="/" className="btn btn-primary mt-5">Go to Home</Link>
      </div>
    </div>
  );
}

/** Shown while a page's code downloads: the page's rough shape instead of a blank area. */
export function RouteSkeleton() {
  return (
    <div className="space-y-3 py-2" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading</span>
      <div className="skeleton h-8 w-48 rounded-lg" />
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="skeleton h-24 rounded-xl" /><div className="skeleton h-24 rounded-xl" /><div className="skeleton hidden h-24 rounded-xl sm:block" />
      </div>
      <div className="skeleton h-64 rounded-xl" />
    </div>
  );
}

/** Full-screen loader before the session is known. */
export function BootLoader() {
  return <div className="flex min-h-full items-center justify-center py-20"><LogoSpinner size={84} /></div>;
}

/** Owner-only pages: members are sent home (same rule as Users). */
export function AdminOnly({ children }: { children: ReactNode }) {
  const admin = useIsAdmin();
  return admin ? <>{children}</> : <Navigate to="/" replace />;
}

/** Keeps keyboard focus inside a sheet, closes it on Escape, and returns focus where it was. */
export function useFocusTrap(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  // the latest onClose without re-running the effect: a parent that re-renders (live prices every second) used to pass
  // a new function each time, which re-ran the effect and moved focus back to the first button - nobody could type
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const onClose = () => closeRef.current();
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    const items = () => Array.from(el?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []);
    items()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); return; }
      if (e.key !== "Tab") return;
      const list = items();
      if (!list.length) return;
      const first = list[0], last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open]);
  return ref;
}

const NAV_ICON: Record<string, string> = {
  home: "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6h-6v6H4a1 1 0 01-1-1z",
  signals: "M3 17l6-6 4 4 8-8M15 7h6v6",
  trade: "M7 4v16M7 4l-3 3M7 4l3 3M17 20V4M17 20l-3-3M17 20l3-3",
  results: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  more: "M5 12h.01M12 12h.01M19 12h.01",
};
export function NavIcon({ name }: { name: keyof typeof NAV_ICON | string }) {
  const d = NAV_ICON[name] ?? NAV_ICON.more;
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={name === "more" ? 3.2 : 1.9} strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
  );
}
