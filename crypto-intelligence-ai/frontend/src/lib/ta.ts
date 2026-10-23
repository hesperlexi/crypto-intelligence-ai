// Chart overlays computed in the browser from the candles shown (display only; the engine computes its own).
export type Candle = [number, number, number, number, number, number];

export function ema(v: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  const k = 2 / (n + 1);
  let prev: number | null = null;
  v.forEach((x, i) => {
    prev = prev === null ? x : x * k + prev * (1 - k);
    out.push(i >= n - 1 ? prev : null);
  });
  return out;
}

export function sma(v: number[], n: number): (number | null)[] {
  let s = 0;
  return v.map((x, i) => {
    s += x;
    if (i >= n) s -= v[i - n];
    return i >= n - 1 ? s / n : null;
  });
}

export function bollinger(v: number[], n = 20, k = 2) {
  const mid = sma(v, n);
  const up: (number | null)[] = [];
  const lo: (number | null)[] = [];
  v.forEach((_, i) => {
    const m = mid[i];
    if (m === null) {
      up.push(null);
      lo.push(null);
      return;
    }
    let ss = 0;
    for (let j = i - n + 1; j <= i; j++) ss += (v[j] - m) ** 2;
    const sd = Math.sqrt(ss / n);
    up.push(m + k * sd);
    lo.push(m - k * sd);
  });
  return { mid, up, lo };
}

/** VWAP anchored at each UTC day (intraday) or rolling 20 bars (daily and above). */
export function vwap(c: Candle[], intraday: boolean): (number | null)[] {
  const out: (number | null)[] = [];
  let pv = 0, vv = 0, day = -1;
  c.forEach((x, i) => {
    const tp = (x[2] + x[3] + x[4]) / 3;
    if (intraday) {
      const d = Math.floor(x[0] / 86_400_000);
      if (d !== day) { day = d; pv = 0; vv = 0; }
      pv += tp * x[5]; vv += x[5];
      out.push(vv > 0 ? pv / vv : tp);
    } else {
      if (i < 19) { out.push(null); return; }
      let a = 0, b = 0;
      for (let j = i - 19; j <= i; j++) { const t = (c[j][2] + c[j][3] + c[j][4]) / 3; a += t * c[j][5]; b += c[j][5]; }
      out.push(b > 0 ? a / b : null);
    }
  });
  return out;
}

export function overlays(c: Candle[], intraday: boolean) {
  const close = c.map((x) => x[4]);
  const bb = bollinger(close);
  return {
    ts: c.map((x) => x[0]),
    ema_9: ema(close, 9), ema_21: ema(close, 21), ema_50: ema(close, 50), ema_200: ema(close, 200),
    vwap: vwap(c, intraday), bb_upper: bb.up, bb_mid: bb.mid, bb_lower: bb.lo,
  };
}
