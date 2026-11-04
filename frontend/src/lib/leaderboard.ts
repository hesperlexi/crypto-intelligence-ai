// v2.16 practice leaderboard. The ENGINE ranks (backend/app/services/leaderboard.py); this file only holds the admin's
// two actions: "Award prize" (one free month + a winner badge, once per month and winner) and keeping a member out.
import { arrayRemove, arrayUnion, doc, runTransaction, setDoc } from "firebase/firestore";
import { db } from "./firebase";
import { addMonths } from "./membership";
import { getSession } from "./session";
import { BADGE_PREFIX, freeMonth, prizeAwarded } from "./writeShapes";

export interface LbRow { rank: number; username: string; return_pct: number; trades: number }
export interface LbView {
  month: string; label: string; since: number; generated_at: number; min_trades: number; rules: string; every_s: number;
  rows: LbRow[]; ranked: number; taking_part: number;
  last_winner: { month: string; label: string; winners: { username: string; return_pct: number; trades: number }[] } | null;
  badges: Record<string, string[]>;
}

/** "Oct 2026" from "2026-10". */
export const shortMonth = (key: string) => {
  const [y, m] = key.split("-").map(Number);
  return new Date(y, (m || 1) - 1, 1).toLocaleDateString("en-US", { month: "short", year: "numeric" });
};
export const badgeTitle = (months: string[]) => `Practice leaderboard winner: ${months.map(shortMonth).join(", ")}`;

/** Admin: one free month + badge for a month's winner. Refused when already given or when the person is not an
 *  approved member. Never income (history entry kind "prize", amount 0). */
export async function awardPrize(month: string, label: string, uid: string): Promise<string> {
  const by = getSession()?.email ?? null;
  return runTransaction(db, async (tx) => {
    const now = Date.now();
    const uref = doc(db, "users", uid), oref = doc(db, "owner", "leaderboard");
    const u = (await tx.get(uref)).data();
    const own = (await tx.get(oref)).data() ?? {};
    if (own.awarded?.[month]?.[uid]) throw new Error("This prize was already given.");
    const g = freeMonth(u, now, by, "prize", { prize_month: month, prize_label: label }, addMonths);
    if (!g) throw new Error("Not an approved member: no prize given.");
    tx.update(uref, { ...g.fields, history: arrayUnion(g.entry), badges: arrayUnion(`${BADGE_PREFIX}${month}`) });
    tx.set(oref, prizeAwarded(month, uid, now, by), { merge: true });
    return u?.username ? `@${u.username}` : u?.email ?? uid;
  });
}

/** Admin: keep a member out of the ranking (or let them back in). The engine reads it on its next hourly run. */
export async function setExcluded(uid: string, excluded: boolean) {
  await setDoc(doc(db, "owner", "leaderboard"), { excluded: excluded ? arrayUnion(uid) : arrayRemove(uid), updated_at: Date.now() }, { merge: true });
}
