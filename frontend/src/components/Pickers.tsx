import { useApi } from "../lib/api";
import { Tabs } from "./ui";

export const MODEL_TFS = ["1h", "4h", "12h", "1d", "3d", "1w"] as const;
export const ALL_TFS = ["1m", "5m", "15m", "30m", "1h", "4h", "12h", "1d", "3d", "1w"] as const;

export function useMeta() {
  return useApi<any>("/meta");
}

export function useSymbols(): string[] {
  const meta = useMeta();
  return (meta.data?.watchlist ?? []).map((w: any) => w.symbol);
}

export function SymbolSelect({ value, onChange, symbols, stacked = false }: { value: string; onChange: (s: string) => void; symbols: string[]; stacked?: boolean }) {
  if (stacked) {
    // form layout: label above a full-width select, like the other order-form fields
    return (
      <label className="block text-xs text-mute">Asset
        <select className="input mt-1 h-10 text-base" value={value} onChange={(e) => onChange(e.target.value)}>
          {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
    );
  }
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="label">Asset</span>
      <select className="input w-36" value={value} onChange={(e) => onChange(e.target.value)}>
        {symbols.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
    </label>
  );
}

export function TfTabs({ value, onChange, options = MODEL_TFS }: { value: string; onChange: (t: string) => void; options?: readonly string[] }) {
  return <Tabs value={value} options={options} onChange={onChange} label="Timeframe" />;
}
