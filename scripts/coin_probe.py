"""Read-only: Binance spot (engine record) vs Binance USD-M futures (website live price) for every watchlist coin, from
Binance's public daily archives (data.binance.vision). Aggregate gaps only."""
import io, json, os, sys, zipfile, datetime as dt
import requests
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
wl = [x.get("symbol") for x in (fs.document("config/watchlist").get().to_dict() or {}).get("symbols", [])]
DAYS = [(dt.date.today() - dt.timedelta(days=i)).isoformat() for i in (1, 2, 3)]


def load(kind, sym, day):
    base = "futures/um" if kind == "fut" else "spot"
    url = f"https://data.binance.vision/data/{base}/daily/klines/{sym}/1m/{sym}-1m-{day}.zip"
    r = requests.get(url, timeout=30)
    if r.status_code != 200:
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    out = {}
    for line in z.read(z.namelist()[0]).decode().splitlines():
        p = line.split(",")
        if not p[0].isdigit():
            continue
        t = int(p[0])
        t = t // 1000 if t > 10**14 else t          # spot archives use microseconds since 2025
        out[t] = (float(p[2]), float(p[3]), float(p[4]))
    return out


def q(v, f):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(f * len(v)))], 3) if v else None


res = {"days": DAYS, "coins": {}}
for s in wl:
    sym = s.replace("/", "")
    gaps, hi15, lo15, miss = [], [], [], 0
    fut_seen = spot_seen = 0
    for day in DAYS:
        f, sp = load("fut", sym, day), load("spot", sym, day)
        fut_seen += f is not None
        spot_seen += sp is not None
        if not f or not sp:
            continue
        common = sorted(set(f) & set(sp))
        for t in common:
            gaps.append(abs(f[t][2] / sp[t][2] - 1) * 100)
        # 15-minute highs / lows: what a target check sees
        buckets = {}
        for t in common:
            b = t // 900_000
            fh, fl, _ = f[t]; sh, sl, _ = sp[t]
            x = buckets.setdefault(b, [0, 1e18, 0, 1e18])
            x[0], x[1], x[2], x[3] = max(x[0], fh), min(x[1], fl), max(x[2], sh), min(x[3], sl)
        for x in buckets.values():
            hi15.append(abs(x[0] / x[2] - 1) * 100)
            lo15.append(abs(x[1] / x[3] - 1) * 100)
    res["coins"][s] = {"futures_days": fut_seen, "spot_days": spot_seen, "minutes": len(gaps),
                       "close_gap_pct": {"median": q(gaps, .5), "p95": q(gaps, .95), "max": q(gaps, 1)},
                       "15m_high_gap_pct": {"median": q(hi15, .5), "p95": q(hi15, .95), "max": q(hi15, 1)},
                       "15m_low_gap_pct": {"median": q(lo15, .5), "p95": q(lo15, .95), "max": q(lo15, 1)}}
print(json.dumps(res, indent=1))
