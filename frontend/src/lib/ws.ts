// WebSocket race: open the same stream on several hosts at once and keep the first that delivers data.
// A host that is slow or blocked on this network (some mobile carriers block port 9443) no longer costs seconds.
export interface Race { close(): void; host(): string | null }

export function raceSocket(urls: string[], onMessage: (data: any) => void, onDown: () => void): Race {
  let winner: WebSocket | null = null, closed = false;
  const socks = urls.map((u) => {
    let s: WebSocket | null = null;
    try { s = new WebSocket(u); } catch { return null; }
    s.onmessage = (ev) => {
      if (closed) return;
      if (!winner) {
        winner = s;
        for (const o of socks) if (o && o !== s) { try { o.close(); } catch { /* ignore */ } }
      }
      if (winner !== s) return;
      try { onMessage(JSON.parse(ev.data)); } catch { /* ignore malformed */ }
    };
    s.onclose = () => {
      if (closed) return;
      if (winner === s || (!winner && socks.every((o) => !o || o.readyState >= WebSocket.CLOSING))) { closed = true; onDown(); }
    };
    s.onerror = () => { try { s?.close(); } catch { /* ignore */ } };
    return s;
  });
  if (socks.every((s) => !s)) setTimeout(onDown, 0);
  return {
    close() { closed = true; for (const s of socks) { try { s?.close(); } catch { /* ignore */ } } },
    host() { return winner ? new URL(winner.url).host : null; },
  };
}

/** Binance server time minus this device's clock (ms), so feed delay is measured on the exchange's clock. */
const offsets: Record<string, number> = {};
export async function clockOffset(futures: boolean): Promise<number> {
  const k = futures ? "f" : "s";
  if (k in offsets) return offsets[k];
  const url = futures ? "https://fapi.binance.com/fapi/v1/time" : "https://api.binance.com/api/v3/time";
  try {
    const t0 = Date.now();
    const r = await (await fetch(url, { cache: "no-store" })).json();
    const t1 = Date.now();
    offsets[k] = Number(r.serverTime) - (t0 + t1) / 2;
  } catch { offsets[k] = 0; }
  return offsets[k];
}
