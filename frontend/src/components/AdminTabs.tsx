// v2.60 (owner, 18 Nov 2026): the admin pages in two families instead of six menu entries.
//   Control room = Health · Trade Guardian · Performance Lab      Share kit = Weekly report · Achievements
// Every page keeps its own address (pushes and old links still open it); this strip moves between them.
import { NavLink } from "react-router-dom";
import { HUB_ALIASES } from "../lib/hubs";

export const ADMIN_FAMILIES = {
  control: [["/health", "Health"], ["/guardian", "Trade Guardian"], ["/lab", "Performance Lab"]],
  share: [["/report", "Weekly report"], ["/achievements", "Achievements"]],
} as const;
/** Sidebar / menu: an entry is lit on every page of its family. */
// V3.4: the six destinations light on every page of their family (lib/hubs); Share kit keeps its own pair
export const ADMIN_ALIASES: Record<string, readonly string[]> = {
  ...HUB_ALIASES,
  "/report": ["/achievements"],
};

export default function AdminTabs({ family }: { family: keyof typeof ADMIN_FAMILIES }) {
  return (
    <nav className="obs-tabs flex overflow-x-auto" aria-label={family === "control" ? "Control room" : "Share kit"}>
      {ADMIN_FAMILIES[family].map(([to, label]) => (
        <NavLink key={to} to={to} className={({ isActive }) => `obs-tab inline-flex items-center ${isActive ? "is-on" : ""}`}>{label}</NavLink>
      ))}
    </nav>
  );
}
