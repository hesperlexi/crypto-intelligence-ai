// V3.1 (owner, 24 Nov 2026: "give me an option on the shareables page to share with Telegram"): one button for every share
// image on the Share kit. First tap asks to confirm, second tap queues the image (lib/telegramShare: owner/telegram_drafts +
// job telegram_post); the engine posts it on its next run (within ~5 min) and the button reports the outcome.
import { useState } from "react";
import { postToTelegram } from "../lib/telegramShare";

export default function TelegramButton({ canvas, caption, kind, className = "btn" }: {
  canvas: () => Promise<HTMLCanvasElement | null>; caption: string; kind: string; className?: string;
}) {
  const [state, setState] = useState<"idle" | "confirm" | "busy" | "done" | "error">("idle");
  const [msg, setMsg] = useState("");
  const go = async () => {
    if (state === "idle" || state === "done" || state === "error") { setState("confirm"); setMsg(""); return; }
    if (state !== "confirm") return;
    setState("busy"); setMsg("Posting on the next engine run (within 5 min)…");
    try {
      const cv = await canvas();
      if (!cv) throw new Error("the image is not ready");
      await postToTelegram(cv, caption.slice(0, 1000), kind);
      setState("done"); setMsg("Posted to the Telegram channel.");
    } catch (e: any) { setState("error"); setMsg(`Not posted: ${e?.message ?? e}`); }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <button type="button" className={`${className} ${state === "confirm" ? "btn-primary" : ""}`} disabled={state === "busy"} onClick={go}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className="mr-1.5"><path d="M21.4 4.6 2.9 11.7c-1.3.5-1.2 1.2-.2 1.5l4.7 1.5 1.8 5.6c.2.7.4.9.9.9.4 0 .6-.2.9-.4l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.6c.3-1.3-.5-1.9-1.4-1.6zM8.9 14.2l9.4-5.9c.4-.3.8-.1.5.2l-7.9 7.1-.3 3.4z" /></svg>
        {state === "confirm" ? "Tap again to post" : state === "busy" ? "Posting…" : state === "done" ? "Posted ✓" : "Post to Telegram"}
      </button>
      {state === "confirm" && <button type="button" className="text-xs text-mute hover:text-text" onClick={() => setState("idle")}>Cancel</button>}
      {msg && <span role="status" className={`text-xs ${state === "error" ? "text-bear" : "text-mute"}`}>{msg}</span>}
    </span>
  );
}
