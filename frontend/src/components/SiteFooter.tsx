// Footer shared by the signed-out landing page, the public trust pages and the app shell.
// Two centred lines: the links, then a smaller muted line with copyright, version, site, contact and disclaimer.
// Inside the signed-in app shell (`links={false}`) only the muted line is shown.
// Separators are CSS (`.foot-dots-sm` / `.foot-dots-lg` in index.css), drawn only from the width where that row fits on
// one line; narrower, the items wrap centred with even gaps, so no "·" is ever left hanging at a line end.
import { Link } from "react-router-dom";
import { BRAND } from "../lib/brand";
import { BUILD_ID, COPYRIGHT } from "../lib/version";
import { TELEGRAM_URL } from "./TelegramLink";

export const TRUST_LINKS: [string, string][] = [
  ["/about", "About"],
  ["/contact", "Contact"],
  ["/terms", "Terms"],
  ["/verify", "Verify"],
  ["/risk", "Risk disclosure"],
];

const HOST = BRAND.url.replace(/^https?:\/\/(www\.)?/, "");
const OWNER = COPYRIGHT.split(".")[0];               // "© 2026 Hesper"
const link = "rounded-sm transition-colors hover:text-text focus-visible:text-text focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-accent/60";

export default function SiteFooter({ className = "", width = "max-w-6xl", links = true }: { className?: string; width?: string; links?: boolean }) {
  return (
    <footer className={`foot border-t px-4 pt-5 ${className || "pb-6"}`}>
      <div className={`mx-auto flex ${width} flex-col items-center gap-2.5 text-center`}>
        {links && <nav aria-label="Legal and information">
          <ul className="foot-row foot-dots-sm text-[13px] text-mute">
            {TRUST_LINKS.map(([to, label]) => <li key={to}><Link to={to} className={link}>{label}</Link></li>)}
            <li><a href={`/manual.pdf?v=${BUILD_ID}`} target="_blank" rel="noopener" className={link}>Manual (PDF)</a></li>
            <li><a href={TELEGRAM_URL} target="_blank" rel="noopener" className={link}>Telegram</a></li>
          </ul>
        </nav>}
        <ul className="foot-row foot-dots-lg text-[11.5px] text-mute/80">
          <li className="foot-grp"><span>{OWNER}</span><span>{BRAND.name} v{BRAND.version}</span></li>
          {links && <li className="foot-grp"><a href={BRAND.url} className={link}>{HOST}</a><a href={`mailto:${BRAND.supportEmail}`} className="text-accent hover:underline">{BRAND.supportEmail}</a></li>}
          <li>Analysis only, not financial advice.</li>
        </ul>
      </div>
    </footer>
  );
}
