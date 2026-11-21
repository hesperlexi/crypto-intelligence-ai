// v2.63 (admin): post a share image drawn in the browser to the Telegram channel. The image goes into
// owner/telegram_drafts (owner-only) and job telegram_post sends it on the next engine run, then takes it off the list.
import { doc, runTransaction } from "firebase/firestore";
import { queueJob } from "./api";
import { db } from "./firebase";

const MAX_B64 = 700_000;            // keeps the drafts document well under Firestore's 1 MB limit

function jpeg(cv: HTMLCanvasElement): string {
  for (const q of [0.88, 0.8, 0.7, 0.6]) {
    const b64 = cv.toDataURL("image/jpeg", q).split(",")[1] ?? "";
    if (b64.length <= MAX_B64) return b64;
  }
  throw new Error("the image is too large to post");
}

/** Queue the canvas for the channel; resolves when it is posted (or throws with the reason). */
export async function postToTelegram(cv: HTMLCanvasElement, caption: string, kind: string): Promise<void> {
  const png = jpeg(cv);
  const id = `${kind}-${Date.now().toString(36)}`;
  const ref = doc(db, "owner", "telegram_drafts");
  await runTransaction(db, async (tx) => {
    const cur = await tx.get(ref);
    const items = ((cur.data()?.items ?? []) as any[]).filter((x) => !(x?.png && String(x.kind ?? "").startsWith("challenge")));
    tx.set(ref, { items: [...items, { id, kind, caption, created_at: Date.now(), png }], updated_at: Date.now() }, { merge: true });
  });
  const j = await queueJob("telegram_post", { id });
  const r: any = await j.done;
  if (r && r.sent === false) throw new Error(r.reason ?? "not posted");
}
