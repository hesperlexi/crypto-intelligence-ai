// TradingView's free Advanced Chart (drawing tools and 100+ indicators), for members who want a pro chart next to
// the app's own AI chart. Embedded as a plain iframe that fills its box exactly (the script widget sized itself
// inconsistently inside our panels). The attribution line is required by TradingView.
import { useMemo } from "react";
import { isLightTheme, useAppearance } from "../lib/appearance";

// toolbar colour = the theme's page background (index.css --ink)
const TOOLBAR: Record<string, string> = { gold: "0b0e13", obsidian: "050608", graphite: "1a1b1e", aurora: "080d1a", light: "f6f7f9" };
const INTERVAL: Record<string, string> = { "1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "12h": "720", "1d": "D", "3d": "3D", "1w": "W" };

export default function TVChart({ symbol, market = "spot", tf = "1h", height = 520, tvSymbolOverride }: { symbol: string; market?: "spot" | "futures"; tf?: string; height?: number; tvSymbolOverride?: string }) {
  const { resolved } = useAppearance();
  // gold (PAXG in the app) shows forex.com's spot gold price, XAU/USD; an index (e.g. CRYPTOCAP:BTC.D) is passed as is
  const tvSymbol = tvSymbolOverride ? tvSymbolOverride : symbol.startsWith("PAXG/") ? "FOREXCOM:XAUUSD" : `BINANCE:${symbol.replace("/", "").toUpperCase()}${market === "futures" ? ".P" : ""}`;
  const src = useMemo(() => {
    const dark = !isLightTheme(resolved);
    const q = new URLSearchParams({
      symbol: tvSymbol, interval: INTERVAL[tf] ?? "60", theme: dark ? "dark" : "light", style: "1", locale: "en",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Etc/UTC", hidesidetoolbar: "0", symboledit: "1",
      saveimage: "1", withdateranges: "1", hideideas: "1", studies: "[]", toolbarbg: TOOLBAR[resolved] ?? (dark ? "0b0e13" : "f1f3f6"),
      utm_source: location.hostname, utm_medium: "widget", utm_campaign: "chart",
    });
    return `https://s.tradingview.com/widgetembed/?${q.toString()}`;
  }, [tvSymbol, tf, resolved]);
  return (
    <div className="w-full">
      <iframe key={src} src={src} title={`TradingView chart ${tvSymbol}`} className="block w-full rounded-lg border-0" style={{ height }}
        allow="fullscreen" allowFullScreen loading="lazy" />
      <p className="mt-1 text-right text-[11px] text-mute">
        Chart by <a href={`https://www.tradingview.com/symbols/${tvSymbol.replace(":", "-")}/`} target="_blank" rel="noopener nofollow" className="text-accent hover:underline">TradingView</a>
      </p>
    </div>
  );
}
