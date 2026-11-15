// v2.38: mounts heavy children (charts) only once they come near the screen. A page with many charts (Demo bots: one
// per bot) created ~40 canvases at once, which blanked or crashed the page on low-memory phones.
import { type ReactNode, useEffect, useRef, useState } from "react";

export default function LazyMount({ children, height, margin = "300px" }: { children: ReactNode; height: number; margin?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (on || !ref.current) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setOn(true); io.disconnect(); } }, { rootMargin: margin });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [on, margin]);
  return <div ref={ref} style={on ? undefined : { minHeight: height }}>{on ? children : null}</div>;
}
