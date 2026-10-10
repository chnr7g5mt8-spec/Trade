"""Record real Yahoo Finance responses for tests and the offline demo mode.

Run on GitHub Actions, where Yahoo is reachable; the workflow commits the
files under backend/app/data/recorded/. Tests and DATA_SOURCE=sample replay
them through the same code path as live data.
"""
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import yahoo  # noqa: E402

# Same list as app.providers.stocks.TIMESERIES_TYPES (a test keeps them in sync);
# repeated here so this script runs against the deployed code as well.
_ITEMS = ["TotalRevenue", "NetIncomeCommonStockholders", "DilutedEPS", "OperatingIncome", "GrossProfit", "EBIT",
          "InterestExpense", "StockholdersEquity", "TotalDebt", "TotalAssets", "CurrentAssets", "CurrentLiabilities",
          "Inventory", "OrdinarySharesNumber", "FreeCashFlow", "CashDividendsPaid", "OperatingCashFlow"]
_VALUATION = ["MarketCap", "EnterpriseValue", "PeRatio", "ForwardPeRatio", "PegRatio", "PsRatio", "PbRatio",
              "EnterprisesValueEBITDARatio"]
TIMESERIES_TYPES = ([f"annual{k}" for k in _ITEMS] + [f"quarterly{k}" for k in _ITEMS]
                    + [f"trailing{k}" for k in _ITEMS] + [f"trailing{k}" for k in _VALUATION])

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "recorded"
c = yahoo.Client()


STOCKS = ["AAPL", "MSFT", "NVDA", "TSM", "JPM", "KO", "XOM", "O", "VOD.L", "7203.T", "SAP.DE"]
FUNDS = ["SPY"]
CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "USDT-USD"]
INDEXES = ["^GSPC", "^N225", "^FTSE", "^GDAXI"]
FX = ["EURGBP=X", "TWDUSD=X"]


def save(name: str, data) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(data, separators=(",", ":")).encode(), mtime=0))
    print("saved", name, path.stat().st_size, "bytes", flush=True)


def raw(path: str, params: dict) -> dict:
    return c._get(path, params)  # the exact payload the app will parse


def chart(sym: str, range_: str = "10y", interval: str = "1d", prepost: bool = False) -> dict:
    return raw(f"/v8/finance/chart/{sym}", {"range": range_, "interval": interval,
                                           "includePrePost": str(prepost).lower(), "events": "div,split",
                                           "includeAdjustedClose": "true"})


def search(q: str) -> dict:
    return raw("/v1/finance/search", {"q": q, "quotesCount": 15, "newsCount": 0, "listsCount": 0,
                                      "enableFuzzyQuery": "false", "quotesQueryId": "tss_match_phrase_query"})


for path in OUT.glob("*.json.gz"):
    path.unlink()  # start clean so removed symbols don't linger

now = int(time.time())
for sym in STOCKS + FUNDS + INDEXES:
    save(f"chart_{sym}.json.gz", chart(sym))
    if sym in STOCKS:
        merged = {"timeseries": {"result": []}}
        for i in range(0, len(TIMESERIES_TYPES), 40):
            part = raw(f"/ws/fundamentals-timeseries/v1/finance/timeseries/{sym}", {
                "symbol": sym, "type": ",".join(TIMESERIES_TYPES[i:i + 40]),
                "period1": now - 6 * 366 * 86400, "period2": now + 86400})
            merged["timeseries"]["result"].extend((part.get("timeseries") or {}).get("result") or [])
        save(f"timeseries_{sym}.json.gz", merged)
    if sym not in INDEXES:
        save(f"search_{sym}.json.gz", search(sym))
    time.sleep(1)

for sym in CRYPTO:
    save(f"chart_{sym}.json.gz", chart(sym))
    save(f"search_{sym}.json.gz", search(sym))
for fx in FX:
    save(f"chart_{fx}.json.gz", chart(fx, "5d"))
save("chart_AAPL_prepost.json.gz", chart("AAPL", "2d", "5m", prepost=True))
for q in ["apple", "toyota", "bitcoin", "bank"]:
    save(f"search_{q}.json.gz", search(q))
save("screener_crypto.json.gz", raw(yahoo.SCREENER_URL, {
    "scrIds": "all_cryptocurrencies_us", "count": 250, "start": 0, "formatted": "false"}))
