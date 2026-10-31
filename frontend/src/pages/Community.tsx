// Community: members' posts (text only, 1-500 characters), newest first, 20 at a time.
// Stored in Firestore posts/{id}; the rules check the author, the username, the length and a 30-second pace
// (post_meta/{uid}). Links are shown as plain text on purpose (no clickable links between members).
import { collection, deleteDoc, doc, getDocs, limit, onSnapshot, orderBy, query, startAfter, writeBatch } from "firebase/firestore";
import { FormEvent, memo, useEffect, useMemo, useState } from "react";
import { Empty } from "../components/ui";
import { UsernameForm } from "../components/AuthPanel";
import { auth } from "../lib/firebase";
import { db } from "../lib/firebase";
import { ago, fmtTime } from "../lib/format";
import { useSession } from "../lib/session";

export const POST_MAX = 500;
const PAGE = 20;
const GAP_S = 30;
const LAST_KEY = "community-last-post";

interface Post { id: string; author_uid: string; username: string; text: string; created_at: number; admin?: boolean }
const toPost = (d: any): Post => ({ id: d.id, ...d.data() });

function useFeed() {
  const [live, setLive] = useState<Post[] | null>(null);          // newest page, live
  const [older, setOlder] = useState<Post[]>([]);                 // pages fetched with "Show older"
  const [more, setMore] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => onSnapshot(query(collection(db, "posts"), orderBy("created_at", "desc"), limit(PAGE)),
    (q) => { setLive(q.docs.map(toPost)); setErr(null); if (q.docs.length < PAGE) setMore(false); }, (e) => setErr(e.message)), []);
  const posts = useMemo(() => {
    const seen = new Set<string>();
    return [...(live ?? []), ...older].filter((p) => (seen.has(p.id) ? false : (seen.add(p.id), true)));
  }, [live, older]);
  const loadMore = async () => {
    const last = posts[posts.length - 1];
    if (!last) return;
    setLoading(true);
    try {
      const q = await getDocs(query(collection(db, "posts"), orderBy("created_at", "desc"), startAfter(last.created_at), limit(PAGE)));
      setOlder((o) => [...o, ...q.docs.map(toPost)]);
      if (q.docs.length < PAGE) setMore(false);
    } catch (e: any) { setErr(e.message); }
    setLoading(false);
  };
  const drop = (id: string) => setOlder((o) => o.filter((p) => p.id !== id));
  return { posts, loaded: live !== null, more, loadMore, loading, err, drop };
}

function waitLeft(): number {
  try { return Math.max(0, Math.ceil((Number(localStorage.getItem(LAST_KEY) ?? 0) + GAP_S * 1000 - Date.now()) / 1000)); } catch { return 0; }
}

function Composer({ uid, username, admin }: { uid: string; username: string; admin: boolean }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [wait, setWait] = useState(waitLeft());
  useEffect(() => { if (!wait) return; const t = window.setInterval(() => setWait(waitLeft()), 1000); return () => window.clearInterval(t); }, [wait]);
  const len = text.trim().length;
  const post = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    if (!len) return;
    if (text.length > POST_MAX) { setErr(`Posts can be at most ${POST_MAX} characters.`); return; }
    if (waitLeft()) { setWait(waitLeft()); return; }
    setBusy(true);
    const now = Date.now();
    try {
      // the post and the pace marker are written together: the rules accept the post only with a matching marker
      const b = writeBatch(db);
      b.set(doc(collection(db, "posts")), { author_uid: uid, username, text: text.trim(), created_at: now, ...(admin ? { admin: true } : {}) });
      b.set(doc(db, "post_meta", uid), { last: now });
      await b.commit();
      try { localStorage.setItem(LAST_KEY, String(now)); } catch { /* ignore */ }
      setWait(GAP_S); setText("");
    } catch (e2: any) {
      setErr(/permission|denied/i.test(String(e2?.code ?? e2?.message)) ? `Could not post. Please wait ${GAP_S} seconds between posts and try again.` : "Could not post. Check your connection and try again.");
    }
    setBusy(false);
  };
  return (
    <form className="panel p-3 sm:p-4" onSubmit={post}>
      <label htmlFor="community-text" className="sr-only">Write a post</label>
      <textarea id="community-text" className="input min-h-[88px] resize-y py-2.5 leading-relaxed" maxLength={POST_MAX} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Share an idea, a question or how a trade went… (text only)" onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void post(e as any); }} />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-mute">Posting as <span className="font-semibold text-text">@{username}</span>{admin && <AdminBadge />}</span>
        <span className="flex items-center gap-3">
          <span className={`num text-xs ${POST_MAX - text.length < 40 ? "text-warn" : "text-mute"}`} aria-live="polite">{text.length}/{POST_MAX}</span>
          <button type="submit" className="btn btn-primary px-4 py-1.5 text-sm" disabled={busy || !len || wait > 0}>{busy ? "Posting…" : wait > 0 ? `Wait ${wait} s` : "Post"}</button>
        </span>
      </div>
      {err && <p role="alert" className="mt-2 text-sm text-bear">{err}</p>}
    </form>
  );
}

const AdminBadge = () => <span className="ml-1.5 rounded border border-accent/60 bg-accent/15 px-1.5 py-0.5 align-middle text-[10px] font-bold uppercase tracking-wide text-accent" title="App owner">Admin</span>;

const PostItem = memo(function PostItem({ p, canDelete, onDeleted }: { p: Post; canDelete: boolean; onDeleted: (id: string) => void }) {
  const [busy, setBusy] = useState(false);
  const del = async () => {
    if (!window.confirm("Delete this post? This cannot be undone.")) return;
    setBusy(true);
    try { await deleteDoc(doc(db, "posts", p.id)); onDeleted(p.id); } catch { window.alert("Could not delete the post. Please try again."); }
    setBusy(false);
  };
  return (
    <li className="panel p-3 sm:p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-sm font-semibold text-accent" aria-hidden="true">{(p.username || "?")[0].toUpperCase()}</span>
          <div className="min-w-0 leading-tight">
            <div className="truncate text-sm font-semibold">@{p.username}{p.admin && <AdminBadge />}</div>
            <time className="text-[11px] text-mute" dateTime={new Date(p.created_at).toISOString()} title={fmtTime(p.created_at)}>{Date.now() - p.created_at < 60_000 ? "just now" : ago(p.created_at)}</time>
          </div>
        </div>
        {canDelete && <button className="btn shrink-0 px-2.5 py-1 text-xs text-mute hover:text-bear" onClick={del} disabled={busy} aria-label={`Delete post by ${p.username}`}>{busy ? "…" : "Delete"}</button>}
      </div>
      {/* plain text only: React escapes it, and links are not turned into anchors */}
      <p className="mt-2.5 whitespace-pre-wrap break-words text-sm leading-relaxed text-text/90">{p.text}</p>
    </li>
  );
});

export default function Community() {
  const s = useSession();
  const admin = s?.role === "admin";
  const feed = useFeed();
  const [, tick] = useState(0);
  useEffect(() => { const t = window.setInterval(() => tick((n) => n + 1), 60_000); return () => window.clearInterval(t); }, []);   // "time ago"
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="page-title">Community</h1>
        <p className="page-sub">Talk with other members. Be kind, no spam, no promotions. Nothing here is financial advice.</p>
      </div>
      {s && s.username ? <Composer uid={s.uid} username={s.username} admin={admin} />
        : s && auth.currentUser ? (
          <div className="panel p-3 sm:p-4">
            <p className="mb-3 text-sm"><span className="font-semibold">Choose a username to post.</span> <span className="text-mute">Other members see it next to your posts; it can't be changed later.</span></p>
            <UsernameForm user={auth.currentUser} admin={admin} compact />
          </div>
        ) : null}
      {feed.err && <p className="rounded-lg border border-bear/40 bg-bear/10 px-3 py-2 text-sm text-bear">Could not load posts. Please try again later.</p>}
      {!feed.loaded && !feed.err ? (
        <ul className="space-y-3" aria-busy="true">{[0, 1, 2].map((i) => <li key={i} className="skeleton h-24 rounded-2xl" />)}</ul>
      ) : feed.posts.length ? (
        <ul className="space-y-3">
          {feed.posts.map((p) => <PostItem key={p.id} p={p} canDelete={admin || p.author_uid === s?.uid} onDeleted={feed.drop} />)}
        </ul>
      ) : !feed.err ? <Empty>Be the first to post.</Empty> : null}
      {feed.loaded && feed.more && feed.posts.length >= PAGE && (
        <div className="text-center"><button className="btn px-4" onClick={feed.loadMore} disabled={feed.loading}>{feed.loading ? "Loading…" : "Show older posts"}</button></div>
      )}
    </div>
  );
}
