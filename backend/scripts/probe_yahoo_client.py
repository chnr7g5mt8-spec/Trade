"""Exercise app.sources.yahoo against real Yahoo Finance (run on GitHub Actions)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sources import yahoo  # noqa: E402

ANNUAL = ["TotalRevenue", "NetIncomeCommonStockholders", "DilutedEPS", "OperatingIncome", "GrossProfit",
          "EBIT", "EBITDA", "InterestExpense", "StockholdersEquity", "TotalDebt", "TotalAssets",
          "CurrentAssets", "CurrentLiabilities", "Inventory", "CashCashEquivalentsAndShortTermInvestments",
          "OrdinarySharesNumber", "FreeCashFlow", "CashDividendsPaid"]
VALUATION = ["MarketCap", "EnterpriseValue", "PeRatio", "ForwardPeRatio", "PegRatio", "PsRatio", "PbRatio",
             "EnterprisesValueEBITDARatio"]
TYPES = ([f"annual{k}" for k in ANNUAL] + [f"quarterly{k}" for k in ANNUAL] + [f"trailing{k}" for k in ANNUAL]
         + [f"trailing{k}" for k in VALUATION])

c = yahoo.Client()
for sym in ["AAPL", "TSM", "7203.T", "VOD.L", "SAP.DE", "0700.HK", "RELIANCE.NS", "JPM", "SPY", "BTC-USD",
            "NOSUCHTICKERX"]:
    print(f"\n===== {sym}", flush=True)
    try:
        ch = c.chart(sym, "10y")
        m = ch.meta
        print("chart:", len(ch.closes), "closes;", len(ch.dividends), "dividends; last", ch.closes[-1:],
              {k: m.get(k) for k in ["currency", "instrumentType", "exchangeName", "fullExchangeName", "longName",
                                     "shortName", "regularMarketPrice", "regularMarketTime", "timezone",
                                     "hasPrePostMarketData", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"]})
        print("trading period:", json.dumps(m.get("currentTradingPeriod"))[:400], "state:", yahoo.market_state(m))
        print("meta keys:", sorted(m))
    except yahoo.YahooError as e:
        print("chart error:", type(e).__name__, e)
    try:
        ts = c.timeseries(sym, TYPES)
        print("timeseries types returned:", len(ts))
        for k in sorted(ts):
            pts = ts[k]
            print(f"  {k}: {[(p.as_of, round(p.value, 4), p.currency, p.period) for p in pts[-5:]]}")
    except yahoo.YahooError as e:
        print("timeseries error:", type(e).__name__, e)
    try:
        res = c.search(sym, 5)
        print("search:", [{k: q.get(k) for k in ["symbol", "longname", "shortname", "quoteType", "exchange",
                                                 "exchDisp", "sector", "industry"]} for q in res[:3]])
    except yahoo.YahooError as e:
        print("search error:", type(e).__name__, e)
    time.sleep(1)

print("\n===== search queries")
for q in ["apple", "toyota", "vodafone", "nestle", "samsung", "reliance", "pepe"]:
    res = c.search(q, 8)
    print(q, [(x.get("symbol"), x.get("quoteType"), x.get("exchDisp")) for x in res])

print("\n===== chart 1d 5m prepost AAPL")
ch = c.chart("AAPL", "2d", "5m", prepost=True)
print(len(ch.closes), ch.timestamps[-3:], ch.closes[-3:], ch.meta.get("regularMarketTime"))
