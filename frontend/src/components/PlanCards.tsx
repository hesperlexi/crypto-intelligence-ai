// v2.44 premium plan cards (Landing + Membership). Gold-foil frame on the best-value plan; savings worked out from the
// real monthly price; no invented "most popular" claims.
type Plan = { months: number; price: number; label: string };

const INCLUDED = ["Every signal: entry, stop-loss, 3 targets", "AI forecasts and coin reports", "Phone alerts for every call",
  "Practice trading and demo bots", "Full track record, losses included"];

export default function PlanCards({ plans, selected, onPick, cta, compact = false, disabled = false }: {
  plans: Plan[]; selected?: number; onPick: (months: number) => void; cta?: (p: Plan) => string; compact?: boolean; disabled?: boolean;
}) {
  const monthly = plans.find((p) => p.months === 1)?.price ?? plans[0]?.price;
  const bestMonths = Math.max(...plans.map((p) => p.months));
  return (
    <div className={`grid gap-3 ${compact ? "grid-cols-2 sm:grid-cols-4" : "sm:grid-cols-2 lg:grid-cols-4"}`}>
      {plans.map((p) => {
        const best = p.months === bestMonths && plans.length > 1;
        const on = selected === p.months;
        const save = monthly && p.months > 1 ? Math.round((1 - p.price / (monthly * p.months)) * 100) : 0;
        const per = p.price / p.months;
        const Tag = cta ? "div" : "button";
        return (
          <Tag key={p.months} {...(cta ? {} : { type: "button", onClick: () => onPick(p.months), "aria-pressed": on })}
            className={`plan-card ${best ? "is-best" : ""} ${on ? "is-on" : ""} ${compact ? "p-3" : "p-5"} text-left`}>
            {best && <span className="plan-ribbon">Best value</span>}
            <div className={`${best ? "text-accent" : "text-mute"} text-sm font-medium`}>{p.label}</div>
            <div className="num mt-2 flex items-baseline gap-1.5">
              <span className={`font-display font-semibold tracking-tight ${compact ? "text-2xl" : "text-4xl"} ${best ? "foil-text" : ""}`}>{p.price}</span>
              <span className="text-sm text-mute">USDT</span>
            </div>
            <div className="num mt-1 text-xs text-mute">{per.toFixed(2)} USDT a month</div>
            {save > 0 ? <div className="plan-save">Save {save}%</div> : <div className="plan-save is-none">Monthly</div>}
            {!compact && (
              <ul className="mt-4 space-y-1.5 text-sm">
                {INCLUDED.map((t) => <li key={t} className="flex gap-2"><span className="text-accent" aria-hidden="true">✓</span><span className="text-text/85">{t}</span></li>)}
              </ul>
            )}
            {cta && <button type="button" className={`btn mt-5 w-full ${best ? "btn-primary" : ""}`} onClick={() => onPick(p.months)} disabled={disabled}>{cta(p)}</button>}
          </Tag>
        );
      })}
    </div>
  );
}
