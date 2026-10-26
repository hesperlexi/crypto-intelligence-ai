// Public Telegram channel: free signal each day, daily wins, weekly results.
export const TELEGRAM_URL = "https://t.me/crypappai";

const Icon = ({ size = 18 }: { size?: number }) => (
  <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><path d="M21.9 4.3 18.7 19.4c-.2 1.1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.3-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 13 1.4 11.5c-1-.3-1.1-1 .2-1.5L20.5 2.8c.9-.3 1.7.2 1.4 1.5z" /></svg>
);

export default function TelegramLink({ variant = "button", label = "Join @crypappai on Telegram" }: { variant?: "button" | "link"; label?: string }) {
  if (variant === "link") return <a href={TELEGRAM_URL} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-accent hover:underline"><Icon size={13} />Telegram</a>;
  return (
    <a href={TELEGRAM_URL} target="_blank" rel="noopener"
      className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#229ED9] px-5 py-3 text-base font-semibold text-white shadow-lg shadow-[#229ED9]/20 transition hover:brightness-110">
      <Icon />{label}
    </a>
  );
}
