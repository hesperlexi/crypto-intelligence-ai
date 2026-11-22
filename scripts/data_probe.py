"""Read-only: structure of DefiLlama's free emissions datasets + which of our coins have one."""
import json, requests
out = {}
def get(u):
    try:
        r = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0 cia-probe"}); return r.status_code, r
    except Exception as e: return 0, str(e)[:100]
s, r = get("https://defillama-datasets.llama.fi/emissions/arbitrum")
if s == 200:
    j = r.json()
    out["top_keys"] = list(j.keys())
    for k, v in j.items():
        if isinstance(v, dict): out[f"keys:{k}"] = {kk: (str(vv)[:160]) for kk, vv in list(v.items())[:12]}
        elif isinstance(v, list): out[f"list:{k}"] = str(v[:2])[:400]
        else: out[f"val:{k}"] = str(v)[:160]
slugs = ["sui", "aptos", "avalanche", "ethena", "polkadot", "cardano", "chainlink", "near", "uniswap", "aave", "sei", "hbar", "hedera",
         "pepe", "gala", "bonk", "ethereum-classic", "tron", "dogecoin", "solana", "xrp", "litecoin", "binance-coin", "bnb", "worldcoin", "pyth-network", "jupiter", "starknet", "optimism", "celestia", "hyperliquid", "ondo-finance", "pudgy-penguins", "zcash", "rare"]
have = {}
for sl in slugs:
    s, r = get(f"https://defillama-datasets.llama.fi/emissions/{sl}")
    have[sl] = s
out["slugs"] = have
s, r = get("https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=1mo&interval=1d")
out["yahoo_dxy"] = [s, str(r.json()["chart"]["result"][0]["meta"].get("regularMarketPrice")) if s == 200 else ""]
s, r = get("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d")
out["yahoo_tnx"] = [s, str(r.json()["chart"]["result"][0]["meta"].get("regularMarketPrice")) if s == 200 else ""]
print(json.dumps(out, indent=1, default=str))
