// Chart tools shared by the coin page and the Trade page (owner, 14 Nov 2026): EMA / VWAP / Bollinger overlays,
// Structure (support / resistance / liquidity / supply-demand + BOS / CHOCH markers) and the AI trade plan.
import type { Marker, PriceLine } from "../components/CandleChart";

export const OVERLAY_GROUPS: Record<string, string[]> = {
  EMA: ["ema_9", "ema_21", "ema_50", "ema_200"],
  VWAP: ["vwap"],
  Bollinger: ["bb_upper", "bb_mid", "bb_lower"],
};

export function structureLines(a: any): PriceLine[] {
  const out: PriceLine[] = [];
  if (!a || a.status !== "OK") return out;
  (a.levels?.zones?.resistance ?? []).slice(0, 3).forEach((z: any) => out.push({ price: z.mid, title: "Resistance", color: "rgba(246,70,93,0.75)", dashed: true }));
  (a.levels?.zones?.support ?? []).slice(0, 3).forEach((z: any) => out.push({ price: z.mid, title: "Support", color: "rgba(14,203,129,0.75)", dashed: true }));
  (a.levels?.liquidity ?? []).slice(0, 4).forEach((l: any) => out.push({ price: l.level, title: l.kind === "high" ? "Liquidity ↑" : "Liquidity ↓", color: "rgba(232,179,57,0.6)", dashed: true }));
  (a.levels?.supply_demand?.demand ?? []).slice(-1).forEach((z: any) => out.push({ price: z.high, title: "Demand", color: "rgba(14,203,129,0.45)" }));
  (a.levels?.supply_demand?.supply ?? []).slice(-1).forEach((z: any) => out.push({ price: z.low, title: "Supply", color: "rgba(246,70,93,0.45)" }));
  return out;
}

export function planLines(a: any): PriceLine[] {
  const s = a?.status === "OK" ? a.setup : null;
  if (!s?.valid) return [];
  return [
    { price: s.ideal_entry, title: "AI entry", color: "--accent" },
    { price: s.stop, title: "AI stop", color: "--bear" },
    ...(s.targets ?? []).map((t: any) => ({ price: t.price, title: `AI ${t.name}`, color: "--bull" })),
  ];
}

export function structureMarkers(a: any): Marker[] {
  if (!a || a.status !== "OK") return [];
  return (a.events ?? []).map((e: any) => ({ ts: e.ts, text: `${e.type}${e.direction > 0 ? " ↑" : " ↓"}`, up: e.direction > 0 }));
}
