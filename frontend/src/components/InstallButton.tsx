import { useEffect, useState } from "react";

/** "Install app" button. Chrome / Edge / Android give a native prompt; iPhone and iPad need Share → Add to Home Screen. */
export default function InstallButton({ compact = false }: { compact?: boolean }) {
  const [prompt, setPrompt] = useState<any>(null);
  const [installed, setInstalled] = useState(false);
  const [iosHelp, setIosHelp] = useState(false);
  const standalone = typeof window !== "undefined" && (window.matchMedia("(display-mode: standalone)").matches || (navigator as any).standalone === true);
  const ios = typeof navigator !== "undefined" && /iphone|ipad|ipod/i.test(navigator.userAgent);

  useEffect(() => {
    const onPrompt = (e: Event) => { e.preventDefault(); setPrompt(e); };
    const onInstalled = () => { setInstalled(true); setPrompt(null); };
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    return () => { window.removeEventListener("beforeinstallprompt", onPrompt); window.removeEventListener("appinstalled", onInstalled); };
  }, []);

  if (standalone || installed || (!prompt && !ios)) return null;
  const click = async () => {
    if (prompt) { prompt.prompt(); await prompt.userChoice.catch(() => null); setPrompt(null); }
    else setIosHelp((v) => !v);
  };
  return (
    <div className="relative">
      <button className={`btn btn-primary ${compact ? "px-2 py-1 text-xs" : "px-2.5 py-1 text-xs"}`} onClick={click} title="Install as an app">
        <span aria-hidden>⤓</span> Install app
      </button>
      {iosHelp && (
        <div className="panel absolute right-0 top-9 z-50 w-64 p-3 text-xs text-text">
          On iPhone / iPad: tap the <b>Share</b> button in Safari, then <b>Add to Home Screen</b>.
        </div>
      )}
    </div>
  );
}
