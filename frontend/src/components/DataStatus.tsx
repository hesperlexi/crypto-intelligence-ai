// V3.4 Stage 5: one way to say how far a figure can be trusted, everywhere.
//   confirmed / live -> "Live"   delayed -> "Delayed"   unavailable / missing -> "Unavailable"   estimate -> "Estimate"
const MAP: Record<string, [string, string]> = {
  confirmed: ["Live", "v3-ok"], live: ["Live", "v3-ok"], ok: ["Live", "v3-ok"],
  delayed: ["Delayed", "v3-watch"], stale: ["Delayed", "v3-watch"],
  estimate: ["Estimate", "v3-muted"], estimated: ["Estimate", "v3-muted"],
  unavailable: ["Unavailable", "v3-act"], missing: ["Unavailable", "v3-act"],
};

export default function DataStatus({ status, title }: { status?: string | null; title?: string }) {
  const [label, cls] = MAP[String(status ?? "unavailable").toLowerCase()] ?? MAP.unavailable;
  return <span className={`v3-pill ${cls}`} title={title}>{label}</span>;
}

export function DataLegend() {
  return (
    <p className="flex flex-wrap items-center gap-2 text-xs text-mute">
      <DataStatus status="confirmed" /> measured from closed data
      <DataStatus status="delayed" /> real but late
      <DataStatus status="estimate" /> modelled, not measured
      <DataStatus status="unavailable" /> missing - never guessed
    </p>
  );
}
