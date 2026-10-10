# Stock Rater

Rates any stock, fund or cryptocurrency from 0 to 100 and labels it
**Strong Buy / Buy / Hold / Sell / Strong Sell**. Stocks are compared with
companies in the same industry; coins with other coins.

Live app: https://stock-rater-n7st.onrender.com

> Educational project. Scores come from a rules-based model, not investment advice.

## What it covers

- **Stocks worldwide**: anything Yahoo Finance lists (New York, London,
  Tokyo, Frankfurt, Hong Kong, Mumbai, Toronto, Sydney, ...). Search by
  company name or symbol.
- **Crypto**: the 8,000+ coins Yahoo lists (e.g. `BTC-USD`).
- **Funds and ETFs** are shown with price trend, risk and dividends, but not
  rated (a fund holds many companies, so there is no single set of financials).

## How the rating works

### Stocks

| Category | Weight | Measures |
| --- | --- | --- |
| Valuation | 20% | P/E (trailing, forward), PEG, price/book, price/sales, EV/EBITDA, free cash flow yield |
| Profitability | 20% | Return on equity and on assets; gross, operating and net margin |
| Growth | 15% | Revenue and EPS growth vs a year earlier; 3-year revenue growth |
| Financial health | 15% | Debt/equity, current and quick ratio, interest coverage |
| Earnings consistency | 5% | Share of recent years that were profitable, and with rising revenue and EPS |
| Momentum | 15% | 1-year return; price vs 50- and 200-day averages |
| Risk | 10% | 1-year volatility, largest drop, 5-year beta vs the home market index |
| Dividends | dividend payers only | Yield, payout ratio, 5-year dividend growth, years of increases |

**Compared with peers.** Valuation, profitability, growth and leverage norms
differ a lot by industry (a P/E of 30 is ordinary for software and expensive
for a bank). Those measures score 70% on where the company ranks among up to
50 of the largest US-listed companies in its Yahoo industry (or its sector,
when the industry has fewer than 8 with data) and 30% on a fixed scale, so a
whole industry that is expensive doesn't look cheap. The peer data
(`backend/app/data/benchmarks.json`) is rebuilt monthly by a GitHub Action
from real Yahoo data, using exactly the code that rates individual stocks.

Banks, insurers and lenders skip cash-flow, liquidity and debt measures,
which don't apply to how they work.

### Crypto

| Category | Weight | Measures |
| --- | --- | --- |
| Market strength | 25% | Market cap (log scale), 24h volume relative to market cap |
| Momentum | 30% | 30-day and 1-year return; price vs 50- and 200-day averages |
| Risk | 35% | 1-year volatility, largest drop, distance below all-time high |
| Maturity & supply | 10% | Years of trading; share of maximum supply already issued |

Crypto scores compare coins with each other; even the best-rated coins are far
more volatile than most stocks. Stablecoins and gold-backed tokens aren't rated.

### Explore

The **Explore** page lists the top 20 in each of a few categories: top rated,
strong today and ahead (half rating, half analyst outlook), future outlook,
growth at a fair price (at least 50 on both growth and value), best value,
strongest growth, best dividends, lowest risk, strongest momentum, top
crypto, and the top rated in each sector. Rating thousands of companies
takes too long for a web request, so a GitHub Action
(`backend/scripts/build_explore.py`) rates every US-listed company worth over
$1B (including foreign companies' US listings) and every coin worth over $100M
each weekday after the US close, with the same code as a single rating, and
stores the lists in `backend/app/data/explore.json`. Category lists only
include stocks rated Hold or better, and every list needs at least 60% of the
measures to be available. Preferred shares, closed-end funds and wrapped or
staked copies of other coins are left out. Tapping an entry opens its live rating.

### Future outlook

US-listed stocks also get an **analyst outlook** score from 0 to 100, from
Wall Street analysts' forecasts: next year's EPS and sales growth, the average
price target vs today's price, and the buy/sell consensus (at least 3
analysts; Explore lists need 5). Yahoo serves forecasts only to logged-in
sessions, which Render can't get, so the daily Explore job collects them into
`backend/app/data/outlook.json`. The outlook is shown next to the rating but
kept out of it: analysts' forecasts are often too optimistic.

### Labels

Scores are whole numbers and the label comes from the score: 80+ Strong Buy,
65+ Buy, 45+ Hold, 30+ Sell, below 30 Strong Sell. Anything with less than 40%
of the measures available is shown but not rated.

### Track record

`backend/scripts/backtest.py` (run quarterly by a GitHub Action) re-rates the
~500 largest US companies at past quarter ends using only annual reports that
had been published by then and prices up to then, and compares the ratings
with the following 12 months' total returns. The results and their limits are
shown in the app under **How ratings work**. The main limit: Yahoo's free
financial history reaches back only 4-5 years, so the test covers about two
years of start dates.

## Data

Everything comes from Yahoo Finance through endpoints that don't need a login
"crumb" (Yahoo refuses those to some cloud hosts, including Render's):
price charts, financial statements and Yahoo's valuation ratios, search, and
the crypto screener. Prices update every minute while a market is trading
(including pre-market and after hours; crypto always) and every 15 minutes
otherwise. `/api/diagnostics` reports which data services work from the
server.

## Project layout

```
backend/   Python FastAPI API: data, scoring, peer benchmarks, backtest
mobile/    Expo (React Native + TypeScript) app; its web build is served by the backend
Dockerfile one container with both, deployed to Render (render.yaml)
.github/   CI, daily Explore rankings, monthly benchmarks, quarterly backtest, daily live check
```

## Running it locally

Backend (Python 3.11+):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`DATA_SOURCE=sample` replays recorded real Yahoo responses (in
`backend/app/data/recorded/`) instead of calling Yahoo: AAPL, MSFT, NVDA, TSM,
JPM, KO, XOM, O, VOD.L, 7203.T, SAP.DE, SPY, BTC, ETH, SOL and USDT.

Tests: `pytest` (and `LIVE=1 pytest tests/live` for checks against real Yahoo).

App:

```bash
cd mobile
npm install
npx expo start      # scan the QR code with Expo Go, or press w for the browser
```

The app looks for the backend on port 8000 of the computer running Expo; set
`EXPO_PUBLIC_API_URL` to use another server, e.g. the deployed one.
Checks: `npm run typecheck` and `npm run lint`.

Whole app in one container:

```bash
docker build -t stock-rater .
docker run -p 8000:8000 stock-rater                        # live data
docker run -p 8000:8000 -e DATA_SOURCE=sample stock-rater  # recorded data
```

## Deploying

`render.yaml` deploys the container to Render's free tier: in Render, choose
**New > Blueprint** and pick this repository. The free tier sleeps after about
15 minutes without visitors, so the first visit after that takes up to a
minute. Before publishing to app stores, host the backend on HTTPS (release
builds block plain `http://`).
