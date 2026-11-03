// Result on margin (v2.6): ROI = price return (blended 50/25/25 exits) x the leverage the signal card suggested
// (engine/futures.signal_leverage: liquidation >= 1.5x the stop distance, max 10x). Losses multiply the same way,
// so a win stays a win and a loss a loss. Records carry `roi_pct` and `leverage`; older payloads may only have
// `return_pct`, which is then shown as a plain "price move" (never labelled ROI).
import { isNum } from "./format";

export interface Roi {
  /** The headline figure, in percent. */
  value: number;
  /** True when `value` is ROI on margin; false when it is only the price move. */
  onMargin: boolean;
  leverage: number | null;
  /** Price move in percent (the record's return_pct; after fees when `net`). */
  price: number;
  /** v2.13: `price` is the result after fees (round trip + funding). */
  net?: boolean;
}

export function roiOf(x: { roi_pct?: unknown; leverage?: unknown; return_pct?: unknown; net?: unknown } | null | undefined): Roi | null {
  if (!x || !isNum(x.return_pct)) return null;
  const lev = isNum(x.leverage) && x.leverage >= 1 ? x.leverage : null;
  const net = x.net === true;      // v2.13: closed record rows carry the result after fees (return_pct = net)
  if (isNum(x.roi_pct) && lev) return { value: x.roi_pct, onMargin: true, leverage: lev, price: x.return_pct, net };
  if (lev) return { value: x.return_pct * lev, onMargin: true, leverage: lev, price: x.return_pct, net };
  return { value: x.return_pct, onMargin: false, leverage: null, price: x.return_pct, net };
}

/** Small label under a result: "ROI on margin · +0.42% after fees" (net rows) or the older "price" wording. */
export const roiLabel = (r: Roi) => (r.onMargin ? `ROI on margin · ${r.net ? "" : "price "}${signedPct(r.price)}${r.net ? " after fees" : ""}` : r.net ? "after fees" : "price move");

export const signedPct = (v: number, d = 2) => `${v > 0 ? "+" : ""}${v.toFixed(d)}%`;
export const roiTone = (v: number) => (v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-mute");
