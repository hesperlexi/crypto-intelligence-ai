export const DASH = "—";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Price with decimals adapted to magnitude (BTC 2dp, DOGE 5dp, ...). */
export function fmtPrice(v: unknown): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  const d = a >= 1000 ? 2 : a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : 6;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function pricePrecision(v: number): number {
  const a = Math.abs(v);
  return a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.1 ? 4 : a >= 0.01 ? 5 : 6;
}

/** `v` is a fraction (0.0123 -> +1.23%). */
export function fmtPct(v: unknown, digits = 2, signed = true): string {
  if (!isNum(v)) return DASH;
  const p = v * 100;
  return `${signed && p > 0 ? "+" : ""}${p.toFixed(digits)}%`;
}

/** `v` is already in percent units. */
export function fmtPctRaw(v: unknown, digits = 2, signed = true): string {
  if (!isNum(v)) return DASH;
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

/** Probability / share 0-1 -> "72%". */
export function fmtProb(v: unknown, digits = 0): string {
  return isNum(v) ? `${(v * 100).toFixed(digits)}%` : DASH;
}

export function fmtNum(v: unknown, digits = 2): string {
  return isNum(v) ? v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : DASH;
}

export function fmtCompact(v: unknown): string {
  if (!isNum(v)) return DASH;
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 }).format(v);
}

export function fmtTime(ms: unknown): string {
  if (!isNum(ms)) return DASH;
  return new Date(ms).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fmtDate(ms: unknown): string {
  if (!isNum(ms)) return DASH;
  return new Date(ms).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function ago(ms: unknown): string {
  if (!isNum(ms)) return DASH;
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} sec ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function tone(v: unknown): string {
  if (!isNum(v) || v === 0) return "text-mute";
  return v > 0 ? "text-bull" : "text-bear";
}

/** "BTC/USDT" -> "BTC-USDT" for URLs. */
export function slug(symbol: string): string {
  return symbol.replace("/", "-");
}

export function base(symbol: string): string {
  return symbol.split("/")[0];
}

export function toLocalInput(ms: number): string {
  const d = new Date(ms - new Date().getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
}
