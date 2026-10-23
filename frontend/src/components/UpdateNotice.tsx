import { reloadNow, useUpdate } from "../lib/updater";

/** Shown only while a new version is being applied (or waiting because you are typing). */
export default function UpdateNotice() {
  const u = useUpdate();
  if (u.phase === "idle") return null;
  return (
    <div className="panel animate-in fixed left-1/2 top-16 z-[60] flex -translate-x-1/2 items-center gap-3 px-4 py-2.5 text-sm" role="status">
      {u.phase === "updating" ? (
        <><span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden />Updating to the latest version…</>
      ) : (
        <>A new version is ready.<button className="btn btn-primary px-2.5 py-1 text-xs" onClick={() => reloadNow(u.build)}>Update now</button></>
      )}
    </div>
  );
}
