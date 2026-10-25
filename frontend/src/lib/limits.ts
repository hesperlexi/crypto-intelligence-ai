// Limits the admin can change: how many coins each member may add, and how many member coins in total.
import { doc, onSnapshot, setDoc } from "firebase/firestore";
import { useEffect, useState } from "react";
import { db } from "./firebase";

export interface Limits { member_coin_limit: number; member_coins_max: number }
export const DEFAULT_LIMITS: Limits = { member_coin_limit: 5, member_coins_max: 25 };

export function useLimits(): Limits {
  const [l, setL] = useState<Limits>(DEFAULT_LIMITS);
  useEffect(() => onSnapshot(doc(db, "config", "limits"), (s) => setL({ ...DEFAULT_LIMITS, ...(s.data() ?? {}) } as Limits), () => setL(DEFAULT_LIMITS)), []);
  return l;
}

export async function saveLimits(l: Limits) {
  const per = Math.round(Number(l.member_coin_limit)), total = Math.round(Number(l.member_coins_max));
  if (!(per >= 0 && per <= 50)) throw new Error("Coins per member must be between 0 and 50.");
  if (!(total >= 0 && total <= 200)) throw new Error("Total member coins must be between 0 and 200.");
  await setDoc(doc(db, "config", "limits"), { member_coin_limit: per, member_coins_max: total, updated_at: Date.now() });
}
