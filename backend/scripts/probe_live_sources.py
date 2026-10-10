"""One-off probe of the real data sources, run on GitHub Actions.

Prints what Yahoo Finance and CoinGecko actually return so the app is built
against real responses. Not part of the app.
"""
import json
import sys
import time
import urllib.request

import yfinance as yf


def section(title):
    print(f"\n===== {title} =====", flush=True)


def show(obj, limit=3000):
    print(json.dumps(obj, default=str, indent=1)[:limit], flush=True)


section("yahoo info AAPL")
info = yf.Ticker("AAPL").info
keys = ["regularMarketPrice", "currentPrice", "regularMarketTime", "marketState", "postMarketPrice",
        "postMarketTime", "preMarketPrice", "currency", "financialCurrency", "sector", "industry",
        "sectorKey", "industryKey", "trailingPE", "forwardPE", "trailingPegRatio", "priceToBook",
        "enterpriseToEbitda", "priceToSalesTrailing12Months", "returnOnEquity", "returnOnAssets",
        "grossMargins", "profitMargins", "operatingMargins", "revenueGrowth", "earningsGrowth",
        "debtToEquity", "currentRatio", "quickRatio", "freeCashflow", "marketCap", "beta",
        "dividendRate", "dividendYield", "trailingAnnualDividendRate", "trailingAnnualDividendYield",
        "payoutRatio", "fiveYearAvgDividendYield", "quoteType", "exchange", "fullExchangeName"]
show({k: info.get(k) for k in keys})
print("total info keys:", len(info))

section("yahoo info for global stocks")
for sym in ["7203.T", "VOD.L", "SAP.DE", "SHOP.TO", "TSM", "RELIANCE.NS", "0700.HK"]:
    try:
        i = yf.Ticker(sym).info
        show({sym: {k: i.get(k) for k in ["shortName", "currency", "financialCurrency", "regularMarketPrice",
                                          "marketCap", "freeCashflow", "trailingPE", "industry", "sector",
                                          "marketState", "dividendRate", "dividendYield"]}})
    except Exception as e:
        print(sym, "ERROR", repr(e))
    time.sleep(1)

section("yahoo ETF info SPY")
i = yf.Ticker("SPY").info
show({k: i.get(k) for k in ["quoteType", "shortName", "regularMarketPrice", "trailingPE", "sector", "industry", "category"]})

section("yahoo income_stmt AAPL")
inc = yf.Ticker("AAPL").income_stmt
print(inc.columns.tolist())
print([r for r in inc.index.tolist()][:80])

section("yahoo balance_sheet AAPL rows")
bs = yf.Ticker("AAPL").balance_sheet
print(bs.columns.tolist())
print(bs.index.tolist()[:80])

section("yahoo history 5y with actions")
h = yf.Ticker("KO").history(period="5y", auto_adjust=True)
print(h.columns.tolist(), len(h), h.index[0], h.index[-1])
print(h[h["Dividends"] > 0].tail(6)["Dividends"].to_dict())

section("yahoo search")
for q in ["apple", "toyota", "bitcoin", "vodafone", "SAP"]:
    s = yf.Search(q, max_results=8, news_count=0, lists_count=0)
    show({q: [{k: x.get(k) for k in ["symbol", "shortname", "longname", "quoteType", "exchange", "exchDisp", "typeDisp", "sector", "industry"]} for x in s.quotes]}, 2500)

section("yahoo screener industries map sample")
from yfinance.const import EQUITY_SCREENER_EQ_MAP as M
ind = M["industry"]
print(type(ind), len(ind))
print({k: list(v)[:5] for k, v in list(ind.items())[:3]})

section("yahoo screener: technology / Software - Infrastructure")
from yfinance import EquityQuery
try:
    sw = [x for x in ind.get("Technology", []) if "Infrastructure" in x]
    print("matching industry names:", sw)
    q = EquityQuery("and", [EquityQuery("eq", ["industry", sw[0]]), EquityQuery("gt", ["intradaymarketcap", 1_000_000_000]),
                            EquityQuery("is-in", ["region", "us", "gb", "de", "jp", "ca"])])
    r = yf.screen(q, size=50, sortField="intradaymarketcap", sortAsc=False)
    quotes = r.get("quotes", [])
    print("count", len(quotes), "total", r.get("total"))
    show([{k: x.get(k) for k in ["symbol", "shortName", "marketCap", "region", "exchange", "trailingPE"]} for x in quotes[:10]])
    print("quote keys:", sorted(quotes[0].keys()) if quotes else None)
except Exception as e:
    print("screener ERROR", repr(e))

section("yahoo sector/industry objects")
try:
    sec = yf.Sector("technology")
    print(sec.industries.head(20).to_dict() if sec.industries is not None else None)
except Exception as e:
    print("sector ERROR", repr(e))


def get(url):
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "stock-rater-probe"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:
        return None, repr(e)


section("coingecko keyless")
cg = "https://api.coingecko.com/api/v3"
for path in ["/ping",
             "/coins/markets?vs_currency=usd&ids=bitcoin,tether&price_change_percentage=24h,7d,30d,1y",
             "/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1",
             "/coins/bitcoin/market_chart?vs_currency=usd&days=365&interval=daily",
             "/search?query=pepe",
             "/coins/list"]:
    status, body = get(cg + path)
    if isinstance(body, list):
        print(path, status, "list len", len(body)); show(body[:2], 2500)
    elif isinstance(body, dict):
        print(path, status, "keys", list(body.keys())[:10])
        if "prices" in body:
            print("prices len", len(body["prices"]), body["prices"][:2])
        else:
            show(body, 1500)
    else:
        print(path, status, body)
    time.sleep(3)

section("deployed site")
site = "https://stock-rater-n7st.onrender.com"
for path in ["/health", "/api/rating/AAPL", "/api/ratings?tickers=AAPL,MSFT,KO"]:
    for attempt in range(4):  # free tier may be asleep
        status, body = get(site + path)
        if status:
            break
        time.sleep(20)
    if isinstance(body, dict):
        show({k: body.get(k) for k in ["status", "source", "ticker", "name", "price", "price_time", "market_state",
                                       "score", "label", "coverage", "detail"]})
    elif isinstance(body, list):
        show([{k: x.get(k) for k in ["ticker", "price", "price_time", "market_state", "score", "source"]} for x in body])
    else:
        print(path, status, body)
sys.exit(0)
