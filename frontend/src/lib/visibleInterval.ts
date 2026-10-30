// setInterval that stops while the tab is hidden (no timers firing in a background tab) and resumes,
// with one immediate run, when the tab becomes visible again. Returns a stop function.
export function visibleInterval(fn: () => void, ms: number): () => void {
  let id = 0;
  const start = () => { if (!id) id = window.setInterval(fn, ms); };
  const stop = () => { if (id) { window.clearInterval(id); id = 0; } };
  const onVis = () => {
    if (document.hidden) stop();
    else { start(); fn(); }
  };
  if (!document.hidden) start();
  document.addEventListener("visibilitychange", onVis);
  return () => { stop(); document.removeEventListener("visibilitychange", onVis); };
}
