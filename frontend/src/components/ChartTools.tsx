// Chart tools on every live chart (owner, 14 Nov 2026): EMA / VWAP / Bollinger drawn from the candles on screen and
// Structure / Trade plan from the engine's analysis of the coin (timeframes the engine does not analyse use the nearest:
// 1m / 5m -> 15m, 1w -> 3d). The choice is remembered on this device for all charts.
import { useMemo, useState } from "react";
import type { Candle, Marker, PriceLine } from "./CandleChart";
import { useApi } from "../lib/api";
import { OVERLAY_GROUPS, planLines, structureLines, structureMarkers } from "../lib/chartLevels";
import { slug } from "../lib/format";
import { overlays as taOverlays } from "../lib/ta";

const KEY = "cia-chart-tools";
export const TOOL_NAMES = ["EMA", "VWAP", "Bollinger", "Structure", "Trade plan"] as const;
const AN_TFS = ["15m", "1h", "4h", "12h", "1d", "3d"];
const INTRADAY = ["1m", "5m", "15m", "1h"];

export function analysisTf(tf: string): string {
  return AN_TFS.includes(tf) ? tf : tf === "1w" ? "3d" : "15m";
}

function load(): string[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) ?? localStorage.getItem("cia-trade-chart-tools") ?? "null"); if (Array.isArray(v)) return v; } catch { /* ignore */ }
  return ["EMA", "Structure", "Trade plan"];
}

/** State + derived chart inputs. Pass `on={false}` (e.g. the TradingView chart is showing) to skip the analysis read. */
/** `fixed`: use this analysis (Replay: what was known then) instead of reading the live one. */
export function useChartTools(symbol: string, tf: string, candles: Candle[], on = true, fixed?: any) {
  const [tools, setTools] = useState<string[]>(load);
  const flip = (g: string) => setTools((cur) => {
    const n = cur.includes(g) ? cur.filter((x) => x !== g) : [...cur, g];
    try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* ignore */ }
    return n;
  });
  const aTf = analysisTf(tf);
  const wantAn = on && fixed === undefined && (tools.includes("Structure") || tools.includes("Trade plan"));
  const live = useApi<any>(wantAn ? `/analysis/${slug(symbol)}?timeframe=${aTf}` : null, 120000);
  const an = fixed === undefined ? live : { data: fixed };
  const overlays = useMemo(() => (on && candles.length && tools.some((g) => OVERLAY_GROUPS[g]) ? taOverlays(candles as any, INTRADAY.includes(tf)) : null), [candles, tf, tools, on]);
  const show = useMemo(() => tools.flatMap((g) => OVERLAY_GROUPS[g] ?? []), [tools]);
  const markers = useMemo<Marker[]>(() => (tools.includes("Structure") ? structureMarkers(an.data) : []), [an.data, tools]);
  const lines = useMemo<PriceLine[]>(() => [
    ...(tools.includes("Structure") ? structureLines(an.data) : []),
    ...(tools.includes("Trade plan") ? planLines(an.data) : []),
  ], [an.data, tools]);
  return { tools, flip, aTf, overlays, show, markers, lines, analysis: an.data };
}

export function ToolChips({ tools, flip, aTf }: { tools: string[]; flip: (g: string) => void; aTf: string }) {
  return (
    <span className="flex flex-wrap items-center gap-1" role="group" aria-label="Chart tools">
      {TOOL_NAMES.map((g) => (
        <button key={g} type="button" className="chip text-xs" aria-pressed={tools.includes(g)} onClick={() => flip(g)}
          title={g === "Trade plan" || g === "Structure" ? `From the ${aTf.toUpperCase()} AI analysis` : undefined}>{g}</button>
      ))}
    </span>
  );
}
