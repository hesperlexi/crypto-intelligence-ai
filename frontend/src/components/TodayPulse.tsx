// v2.44 Home "Today in 10 seconds": open signals as a health ring, today's closed results, the live result ticker and,
// for new members, the first-week guide. Real record data only (views/track_record, already loaded on Home).
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { isNum } from "../lib/format";
import { useLive } from "../lib/live";
import { useMyRecord } from "../lib/membership";
import { useSession, useIsAdmin } from "../lib/session";
import { TELEGRAM_URL } from "./TelegramLink";
import { healthOf } from "./Overview";
import { FirstWeek, ResultTicker, Ring, wasVisited } from "./Premium";

const DUBAI = 4 * 3_600_000;
const dayOf = (ms: number) => Math.floor((ms + DUBAI) / 86_400_000);
const CLOSED = new Set(["STOPPED", "TP1", "TP2", "TP3", "EXPIRED"]);

export function TodayPulse({ track }: { track: any }) {
  const { tickers } = useLive();
  const sigs: any[] = track?.live?.signals ?? [];
  const open = sigs.filter((x) => x.status === "OPEN");
  const health = open.map((x) => healthOf(x, tickers[x.symbol]?.last ?? undefined)[0]);
  const healthy = health.filter((h) => h === "Healthy").length;
  const watch = health.filter((h) => h === "Watch").length;
  const risk = health.filter((h) => h === "At risk").length;
  const today = useMemo(() => {
    const d = dayOf(Date.now());
    const c = sigs.filter((x) => CLOSED.has(x.status) && isNum(x.closed_at) && dayOf(x.closed_at) === d && isNum(x.return_pct));
    return { n: c.length, w: c.filter((x) => x.return_pct > 0).length, sum: c.reduce((a, x) => a + x.return_pct, 0) };
  }, [sigs]);
  if (!track) return null;
  return (
    <div className="today-pulse mt-5">
      <div className="grid gap-3 min-[420px]:grid-cols-2 lg:grid-cols-[auto_auto_minmax(0,1fr)] lg:items-center">
        <Link to="/results" className="tp-cell">
          <Ring value={open.length ? healthy / open.length : 0} size={64} stroke={7} tone={risk ? "--warn" : "--bull"} label={`${healthy} of ${open.length} open signals healthy`}>
            <span className="num text-base font-semibold">{open.length}</span>
          </Ring>
          <div className="min-w-0">
            <div className="text-xs text-mute">Open signals</div>
            <div className="text-sm font-medium">{open.length ? <><span className="text-bull">{healthy} healthy</span>{watch ? <> · <span className="text-warn">{watch} watch</span></> : null}{risk ? <> · <span className="text-bear">{risk} at risk</span></> : null}</> : "None open right now"}</div>
          </div>
        </Link>
        <Link to="/results" className="tp-cell">
          <div className={`tp-badge ${today.n ? (today.sum > 0 ? "is-up" : "is-down") : ""}`}>{today.n ? `${today.sum > 0 ? "+" : ""}${today.sum.toFixed(1)}%` : "—"}</div>
          <div className="min-w-0">
            <div className="text-xs text-mute">Closed today, after fees</div>
            <div className="text-sm font-medium">{today.n ? `${today.w} won · ${today.n - today.w} lost` : "Nothing closed yet today"}</div>
          </div>
        </Link>
        <div className="min-w-0 max-lg:col-span-full"><ResultTicker rows={sigs} /></div>
      </div>
    </div>
  );
}

export function FirstWeekGuide() {
  const s = useSession();
  const admin = useIsAdmin();
  const rec = useMyRecord();
  if (admin || !s || rec === undefined) return null;
  const since = rec?.approved_at ?? rec?.requested_at ?? null;
  const notif = typeof Notification !== "undefined" && Notification.permission === "granted";
  return (
    <FirstWeek uid={s.uid} createdAt={since} steps={[
      { k: "notify", title: "Turn on alerts", text: "Get a push for every new signal and each target hit.", to: "/alerts", done: notif },
      { k: "signals", title: "Read a signal card", text: "Entry, stop-loss, three targets and the grade.", to: "/signals", done: wasVisited("signals") },
      { k: "paper", title: "Try a practice trade", text: "Demo money only, $1,000 to start.", to: "/paper", done: wasVisited("paper") },
      { k: "telegram", title: "Join the Telegram channel", text: "Daily free call and results.", href: TELEGRAM_URL, done: wasVisited("telegram") },
    ]} />
  );
}
