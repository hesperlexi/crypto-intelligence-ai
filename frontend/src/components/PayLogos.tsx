// Payment-method marks shown on the plan picker (exchange logos, used only to identify the payment option).
export function BinanceLogo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path fill="#F0B90B" d="M16.624 13.92l2.718 2.716-7.353 7.353-7.353-7.352 2.717-2.717 4.636 4.66 4.635-4.66zm4.637-4.636L24 12l-2.715 2.716L18.568 12l2.693-2.716zm-9.272.001l2.716 2.691-2.716 2.718L9.272 12l2.717-2.715zm-9.273-.001L5.409 12l-2.692 2.692L0 12l2.716-2.716zM11.989.012l7.353 7.329-2.718 2.715-4.635-4.635-4.636 4.66-2.717-2.716L11.989.012z" />
    </svg>
  );
}

export function MexcLogo({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path fill="#1972E2" d="M4.2 20.4 11.1 8.9a2.4 2.4 0 0 1 4.1 0l2.8 4.7-5.2 8.9a2.4 2.4 0 0 1-2.1 1.2H6.3a2.4 2.4 0 0 1-2.1-3.3z" />
      <path fill="#3BD1F7" d="M15.9 22.6 21 14.1a2.4 2.4 0 0 1 4.1 0l3.3 5.5a2.7 2.7 0 0 1-2.3 4.1h-9.5c-.7 0-1-.6-.7-1.1z" />
    </svg>
  );
}
