// V3.4 Stage 5: the tab strip of a destination (lib/hubs), shown above every page of that family.
import { NavLink, useLocation } from "react-router-dom";
import { activeTab, hubOf, visibleTabs } from "../lib/hubs";

export default function HubTabs({ admin, counts = {} }: { admin: boolean; counts?: Record<string, number> }) {
  const loc = useLocation();
  const hub = hubOf(loc.pathname);
  if (!hub) return null;
  const tabs = visibleTabs(hub, admin);
  if (tabs.length < 2) return null;
  const on = activeTab(hub, loc.pathname);
  return (
    <nav className="hub-tabs" aria-label={`${hub.label} sections`}>
      <span className="hub-name">{hub.label}</span>
      <div className="hub-strip">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} aria-current={on?.to === t.to ? "page" : undefined}
            className={`hub-tab ${on?.to === t.to ? "is-on" : ""} ${t.admin ? "is-admin" : ""}`}>
            {t.label}
            {!!counts[t.to] && <span className="hub-count num" aria-label={`${counts[t.to]} new`}>{counts[t.to]}</span>}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
