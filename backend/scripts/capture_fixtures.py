"""Record real Yahoo Finance (and CoinGecko) responses as test fixtures.

Run on GitHub Actions (where both services are reachable); the workflow
commits the files under backend/tests/fixtures/. Tests then exercise the
parsers against genuine payloads instead of hand-written ones.
"""
import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import yahoo  # noqa: E402

# Same list as app.providers.stocks.TIMESERIES_TYPES (a test keeps them in sync);
# repeated here so this script runs against the deployed code as well.
_ITEMS = ["TotalRevenue", "NetIncomeCommonStockholders", "DilutedEPS", "OperatingIncome", "GrossProfit", "EBIT",
          "InterestExpense", "StockholdersEquity", "TotalDebt", "TotalAssets", "CurrentAssets", "CurrentLiabilities",
          "Inventory", "OrdinarySharesNumber", "FreeCashFlow", "CashDividendsPaid"]
_VALUATION = ["MarketCap", "EnterpriseValue", "PeRatio", "ForwardPeRatio", "PegRatio", "PsRatio", "PbRatio",
              "EnterprisesValueEBITDARatio"]
TIMESERIES_TYPES = ([f"annual{k}" for k in _ITEMS] + [f"quarterly{k}" for k in _ITEMS]
                    + [f"trailing{k}" for k in _ITEMS] + [f"trailing{k}" for k in _VALUATION])

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
c = yahoo.Client()


def save(name: str, data) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
    print("saved", path.relative_to(OUT), path.stat().st_size, "bytes", flush=True)


def raw(path: str, params: dict) -> dict:
    return c._get(path, params)  # the exact payload the app will parse


now = int(time.time())
for sym in ["AAPL", "TSM", "JPM", "KO", "VOD.L", "7203.T", "SPY", "BTC-USD", "ETH-USD", "USDT-USD", "^GSPC",
            "^N225", "^FTSE"]:
    save(f"yahoo/chart_{sym}.json.gz", raw(f"/v8/finance/chart/{sym}", {
        "range": "10y", "interval": "1d", "includePrePost": "false", "events": "div,split",
        "includeAdjustedClose": "true"}))
    if not sym.startswith("^") and sym not in ("SPY", "BTC-USD", "ETH-USD", "USDT-USD"):
        merged = {"timeseries": {"result": []}}
        for i in range(0, len(TIMESERIES_TYPES), 40):
            part = raw(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}", {
                "symbol": sym, "type": ",".join(TIMESERIES_TYPES[i:i + 40]),
                "period1": now - 6 * 366 * 86400, "period2": now + 86400})
            merged["timeseries"]["result"].extend((part.get("timeseries") or {}).get("result") or [])
        save(f"yahoo/timeseries_{sym}.json.gz", merged)
    time.sleep(1)

save("yahoo/chart_AAPL_prepost.json.gz", raw("/v8/finance/chart/AAPL", {
    "range": "2d", "interval": "5m", "includePrePost": "true", "events": "div,split", "includeAdjustedClose": "true"}))
for q in ["apple", "toyota", "bitcoin", "AAPL", "SPY"]:
    save(f"yahoo/search_{q}.json.gz", raw("/v1/finance/search", {
        "q": q, "quotesCount": 10, "newsCount": 0, "listsCount": 0, "enableFuzzyQuery": "false",
        "quotesQueryId": "tss_match_phrase_query"}))
save("yahoo/screener_crypto.json.gz", raw(yahoo.SCREENER_URL, {
    "scrIds": "all_cryptocurrencies_us", "count": 50, "start": 0, "formatted": "false"}))
for fx in ["EURGBP=X", "TWDUSD=X"]:
    save(f"yahoo/chart_{fx}.json.gz", raw(f"/v8/finance/chart/{fx}", {"range": "5d", "interval": "1d"}))


def cg(path: str):
    req = urllib.request.Request("https://api.coingecko.com/api/v3" + path, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


save("coingecko/markets_top.json.gz", cg("/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=50&page=1"
                                         "&price_change_percentage=24h,7d,30d,1y"))
