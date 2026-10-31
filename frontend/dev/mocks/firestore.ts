// DEV PREVIEW ONLY. In-memory stand-in for "firebase/firestore" (aliased by dev/vite.preview.config.ts).
// Never imported by the production build: frontend/vite.config.ts has no alias to this folder.
import { seed } from "../seed";

type Data = Record<string, any>;
const store = new Map<string, Data>();
const listeners = new Set<() => void>();
let seeded = false;
function ensure() {
  if (seeded) return;
  seeded = true;
  for (const [k, v] of Object.entries(seed())) store.set(k, v);
}
const notify = () => queueMicrotask(() => listeners.forEach((f) => f()));

export interface Ref { kind: "doc"; path: string; id: string }
export interface Coll { kind: "coll"; path: string; filters: [string, string, any][]; order?: [string, "asc" | "desc"]; max?: number; after?: any }
type Clause = [string, string, any] | { __order: [string, "asc" | "desc"] } | { __limit: number } | { __after: any };

export const getFirestore = () => ({ mock: true });
export function doc(dbOrColl: any, ...parts: string[]): Ref {
  if (dbOrColl?.kind === "coll") parts = [...dbOrColl.path.split("/"), ...(parts.length ? parts : [Math.random().toString(36).slice(2, 12)])];
  const path = parts.join("/");
  return { kind: "doc", path, id: parts[parts.length - 1] };
}
export function collection(_db: any, ...parts: string[]): Coll { return { kind: "coll", path: parts.join("/"), filters: [] }; }
export function where(field: string, op: string, value: any) { return [field, op, value] as [string, string, any]; }
export const orderBy = (f: string, dir: "asc" | "desc" = "asc") => ({ __order: [f, dir] as [string, "asc" | "desc"] });
export const limit = (n: number) => ({ __limit: n });
export const startAfter = (v: any) => ({ __after: v });
export function query(c: Coll, ...w: Clause[]): Coll {
  const out: Coll = { ...c, filters: [...c.filters] };
  for (const x of w) {
    if (Array.isArray(x)) out.filters.push(x);
    else if ("__order" in x) out.order = x.__order;
    else if ("__limit" in x) out.max = x.__limit;
    else if ("__after" in x) out.after = x.__after;
  }
  return out;
}
export const arrayUnion = (...items: any[]) => ({ __arrayUnion: items });

function snap(ref: Ref) {
  ensure();
  const d = store.get(ref.path);
  return { id: ref.id, ref, exists: () => d !== undefined, data: () => (d === undefined ? undefined : structuredClone(d)) };
}
function docsOf(c: Coll) {
  ensure();
  const pre = c.path + "/";
  const out: any[] = [];
  for (const [k, v] of store) {
    if (!k.startsWith(pre) || k.slice(pre.length).includes("/")) continue;
    if (c.filters.every(([f, op, val]) => op === "==" ? f.split(".").reduce((o: any, k) => o?.[k], v) === val : true)) {
      const id = k.slice(pre.length);
      out.push({ id, ref: doc(null, ...k.split("/")), data: () => structuredClone(v), exists: () => true, _v: v });
    }
  }
  let docs = out;
  if (c.order) {
    const [f, dir] = c.order, k = dir === "desc" ? -1 : 1;
    docs.sort((a, b) => k * ((a._v[f] ?? 0) - (b._v[f] ?? 0)));
    if (c.after !== undefined) docs = docs.filter((d) => (dir === "desc" ? d._v[f] < c.after : d._v[f] > c.after));
  }
  if (c.max) docs = docs.slice(0, c.max);
  return { docs, size: docs.length, empty: !docs.length };
}

export function onSnapshot(target: Ref | Coll, cb: (s: any) => void, _err?: (e: Error) => void) {
  const fire = () => cb(target.kind === "doc" ? snap(target) : docsOf(target));
  setTimeout(fire, 30);
  listeners.add(fire);
  return () => { listeners.delete(fire); };
}
export async function getDoc(ref: Ref) {
  if (ref.path === "admin/probe" && sessionStorage.getItem("preview-as") !== "admin") throw new Error("permission-denied");
  return snap(ref);
}
export async function getDocs(c: Coll) { return docsOf(c); }

function merge(cur: Data, patch: Data): Data {
  const out = { ...cur };
  for (const [k, v] of Object.entries(patch)) {
    if (v && typeof v === "object" && "__arrayUnion" in v) out[k] = [...(cur[k] ?? []), ...v.__arrayUnion];
    else out[k] = v;
  }
  return out;
}
export async function setDoc(ref: Ref, data: Data, opts?: { merge?: boolean }) {
  ensure();
  store.set(ref.path, opts?.merge ? merge(store.get(ref.path) ?? {}, data) : merge({}, data));
  notify();
}
export async function updateDoc(ref: Ref, data: Data) {
  ensure();
  if (!store.has(ref.path)) throw new Error("not-found");
  store.set(ref.path, merge(store.get(ref.path)!, data));
  notify();
}
export async function deleteDoc(ref: Ref) { ensure(); store.delete(ref.path); notify(); }
export async function addDoc(c: Coll, data: Data) {
  const id = Math.random().toString(36).slice(2, 12);
  const ref = doc(null, ...c.path.split("/"), id);
  await setDoc(ref, data);
  return ref;
}
export function writeBatch(_db: any) {
  const ops: (() => Promise<void>)[] = [];
  const b = {
    set: (r: Ref, d: Data, o?: { merge?: boolean }) => { ops.push(() => setDoc(r, d, o)); return b; },
    update: (r: Ref, d: Data) => { ops.push(() => updateDoc(r, d)); return b; },
    delete: (r: Ref) => { ops.push(() => deleteDoc(r)); return b; },
    commit: async () => { for (const op of ops) await op(); },
  };
  return b;
}
export async function runTransaction(_db: any, fn: (tx: any) => Promise<any>) {
  const tx = {
    get: async (r: Ref) => snap(r),
    update: (r: Ref, d: Data) => { void updateDoc(r, d); },
    set: (r: Ref, d: Data) => { void setDoc(r, d); },
  };
  return fn(tx);
}
