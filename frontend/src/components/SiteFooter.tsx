// Footer shared by the signed-out landing page, the public trust pages and the app shell.
import { Link } from "react-router-dom";
import { BRAND, footerText } from "../lib/brand";
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
  return (
    <footer className={`border-t border-glass/[0.06] px-4 py-4 text-center text-xs text-mute ${className}`}>
      <nav aria-label="Legal and information" className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
        {TRUST_LINKS.map(([to, label]) => <Link key={to} to={to} className="hover:text-text">{label}</Link>)}
        <a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className="hover:text-text">User manual (PDF)</a>
        <TelegramLink variant="link" />
      </nav>
      <p className="mt-2">
        {footerText().split(BRAND.supportEmail)[0]}
        <a href={`mailto:${BRAND.supportEmail}`} className="text-accent hover:underline">{BRAND.supportEmail}</a>
        {footerText().split(BRAND.supportEmail)[1]}
      </p>
      <p className="mt-1">Forecasts are probabilities, never certainties. No real orders are placed: practice trading and demo bots use virtual money.</p>
      <p className="mt-1">{COPYRIGHT}</p>
    </footer>
  );
}
