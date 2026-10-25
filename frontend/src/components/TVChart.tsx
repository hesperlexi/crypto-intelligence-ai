// TradingView's free Advanced Chart widget: the full drawing tools and 100+ indicators, for members who want a
// pro chart next to the app's own AI chart. Loaded on demand; the attribution line is required by TradingView.
import { useEffect, useRef } from "react";
import { useAppearance } from "../lib/appearance";

const INTERVAL: Record<string, string> = { "1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240", "12h": "720", "1d": "D", "3d": "3D", "1w": "W" };

export default function TVChart({ symbol, market = "spot", tf = "1h", height = 520 }: { symbol: string; market?: "spot" | "futures"; tf?: string; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const { resolved } = useAppearance();
  const tvSymbol = `BINANCE:${symbol.replace("/", "").toUpperCase()}${market === "futures" ? ".P" : ""}`;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.innerHTML = '<div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>';
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    s.async = true;
    s.type = "text/javascript";
    s.innerHTML = JSON.stringify({
      autosize: true, symbol: tvSymbol, interval: INTERVAL[tf] ?? "60", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Etc/UTC",
      theme: resolved === "light" ? "light" : "dark", style: "1", locale: "en", allow_symbol_change: true,
      hide_side_toolbar: false, calendar: false, support_host: "https://www.tradingview.com",
      backgroundColor: resolved === "light" ? "rgba(255,255,255,1)" : "rgba(11,14,17,1)",
    });
    el.appendChild(s);
    return () => { el.innerHTML = ""; };
  }, [tvSymbol, tf, resolved]);
  return (
    <div>
      <div ref={box} className="tradingview-widget-container w-full overflow-hidden rounded-lg" style={{ height }} />
      <p className="mt-1 text-right text-[10px] text-mute">
        Chart by <a href={`https://www.tradingview.com/symbols/${tvSymbol.replace(":", "-")}/`} target="_blank" rel="noopener nofollow" className="text-accent hover:underline">TradingView</a>
      </p>
    </div>
  );
}
