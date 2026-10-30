// Footer shared by the signed-out landing page, the public trust pages and the app shell.
import { Link } from "react-router-dom";
import { BRAND, SITE_HOST } from "../lib/brand";
import { BUILD_ID, COPYRIGHT } from "../lib/version";
import TelegramLink from "./TelegramLink";

export const TRUST_LINKS: [string, string][] = [
  ["/about", "About"],
  ["/contact", "Contact"],
  ["/privacy", "Privacy"],
  ["/terms", "Terms"],
  ["/risk", "Risk disclosure"],
];

export default function SiteFooter({ className = "" }: { className?: string }) {
  // Two lines: links with the copyright in the right corner, then one line of brand, contact and disclaimer.
  return (
    <footer className={`border-t border-glass/[0.06] px-4 py-3 text-xs text-mute ${className}`}>
      <div className="mx-auto flex max-w-7xl flex-col gap-1.5">
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 md:justify-between">
          <nav aria-label="Legal and information" className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            {TRUST_LINKS.map(([to, label]) => <Link key={to} to={to} className="hover:text-text">{label}</Link>)}
            <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="hover:text-text">Manual (PDF)</a>
            <TelegramLink variant="link" />
          </nav>
          <span className="whitespace-nowrap">{COPYRIGHT}</span>
        </div>
        <p className="text-center md:text-left">
          {BRAND.name} v{BRAND.version} · <a href={BRAND.url} className="hover:text-text">{SITE_HOST}</a> ·{" "}
          <a href={`mailto:${BRAND.supportEmail}`} className="text-accent hover:underline">{BRAND.supportEmail}</a> ·
          Analysis only, not financial advice; forecasts are never certainties and practice trading uses virtual money.
        </p>
      </div>
    </footer>
  );
}
