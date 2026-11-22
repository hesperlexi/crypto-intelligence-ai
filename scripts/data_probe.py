"""Read-only: which free data sources can the engine's runner reach? Counts / samples only."""
import json, requests
out = {}
def get(u, **p):
    try:
        r = requests.get(u, params=p, timeout=15, headers={"User-Agent": "Mozilla/5.0 cia-probe"})
        return r.status_code, r
    except Exception as e:
        return 0, str(e)[:120]
s, r = get("https://www.deribit.com/api/v2/public/get_volatility_index_data", currency="BTC", resolution="3600", start_timestamp=1795000000000, end_timestamp=1795340000000)
out["deribit_dvol"] = [s, (r.json()["result"]["data"][-1] if s == 200 else str(r)[:80])]
s, r = get("https://www.deribit.com/api/v2/public/get_book_summary_by_currency", currency="BTC", kind="option")
out["deribit_options"] = [s, len(r.json()["result"]) if s == 200 else str(r)[:80]]
if s == 200: out["deribit_option_sample"] = {k: r.json()["result"][0].get(k) for k in ("instrument_name", "open_interest", "underlying_price")}
for sym in ("^spx", "dx.f", "xauusd", "^ndq", "us10y.b"):
    s, r = get("https://stooq.com/q/d/l/", s=sym, i="d")
    out[f"stooq_{sym}"] = [s, (r.text.strip().splitlines()[-1] if s == 200 else str(r)[:80])]
s, r = get("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC", range="5d", interval="1d")
out["yahoo"] = [s, (str(r.json()["chart"]["result"][0]["meta"].get("regularMarketPrice")) if s == 200 else str(getattr(r, "text", r))[:80])]
for u in ("https://api.llama.fi/emissions", "https://defillama-datasets.llama.fi/emissions/arbitrum", "https://api.llama.fi/emission/arbitrum"):
    s, r = get(u)
    out[u] = [s, (r.text[:160] if s else str(r)[:80])]
s, r = get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume", ccy="BTC", period="1H")
out["okx_oi"] = [s, (r.json().get("data", [[]])[0] if s == 200 else str(r)[:80])]
print(json.dumps(out, indent=1, default=str))
