// Large media files get a cache-busting ?v=<content hash>, computed from the file at build time (vite.config.ts
// __MEDIA_VERSIONS__), so browsers download a video again only when the video itself changed, not on every deploy.
declare const __MEDIA_VERSIONS__: Record<string, string> | undefined;
const V: Record<string, string> = typeof __MEDIA_VERSIONS__ !== "undefined" ? __MEDIA_VERSIONS__ : {};

/** "/demo.mp4" -> "/demo.mp4?v=<hash of the file>" (the bare path when no hash is known). */
export const mediaUrl = (path: string) => (V[path] ? `${path}?v=${V[path]}` : path);

/** The 70 s app demo (frontend/public/demo.mp4) is hidden until it is re-recorded: it showed the old menu and results
 *  deleted by the 3 Nov 2026 fresh start (owner decision 3 Nov 2026). Set to true when a new demo.mp4 is in place. */
export const SHOW_APP_DEMO = false;
