"""Data shapes shared by the data providers, the scoring engine and the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

AssetType = Literal["stock", "fund", "crypto"]


class Quote(BaseModel):
    """Live price information common to every asset."""

    price: float | None = None
    currency: str | None = None
    price_time: int | None = None  # Unix seconds of the last regular-session trade
    market_state: str | None = None  # "open", "pre", "post" or "closed"
    extended_price: float | None = None  # pre-market or after-hours price, if more recent
    extended_session: str | None = None  # "pre" or "post"
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    price_history: list[float] = []  # ~1 year, downsampled for a sparkline


class DividendInfo(BaseModel):
    """A regular dividend: what each payment is and when the next is expected."""

    per_year: int  # 1, 2, 4 or 12
    amount: float  # a regular payment per share, in the listing's currency
    currency: str | None = None
    last_ex_date: int  # Unix seconds of the latest ex-dividend date
    next_ex_date: int | None = None  # estimated from the schedule


class StockData(BaseModel):
    """Raw inputs needed to rate a stock. Any metric may be missing (None)."""

    ticker: str
    name: str | None = None
    asset_type: AssetType = "stock"
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    quote: Quote = Quote()
    market_cap: float | None = None

    # Valuation
    pe_ratio: float | None = None
    forward_pe: float | None = None
    peg_ratio: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    ev_to_ebitda: float | None = None
    fcf_yield: float | None = None
    # Profitability (fractions, e.g. 0.25 == 25%)
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    # Growth
    revenue_growth: float | None = None  # latest quarter vs a year earlier
    earnings_growth: float | None = None  # latest quarter vs a year earlier
    revenue_cagr_3y: float | None = None
    # Financial health
    debt_to_equity: float | None = None  # ratio (1.5 == 1.5x)
    current_ratio: float | None = None
    quick_ratio: float | None = None
    interest_coverage: float | None = None
    # Earnings consistency (shares of recent years, 0..1)
    profitable_years: float | None = None
    revenue_up_years: float | None = None
    eps_up_years: float | None = None
    # Momentum
    return_1y: float | None = None
    return_3y: float | None = None  # annualised; funds only
    return_5y: float | None = None  # annualised; funds only
    price_vs_sma50: float | None = None
    price_vs_sma200: float | None = None
    # Risk
    volatility_1y: float | None = None
    max_drawdown_1y: float | None = None
    beta: float | None = None
    # Dividends
    dividend_yield: float | None = None
    payout_ratio: float | None = None
    dividend_growth_5y: float | None = None  # annualised growth of the yearly dividend
    dividend_streak: float | None = None  # consecutive years of higher dividends
    dividend: DividendInfo | None = None

    facts: list[Fact] = []
    notes: list[str] = []


class CryptoData(BaseModel):
    """Raw inputs needed to rate a cryptocurrency."""

    ticker: str  # Yahoo symbol, e.g. BTC-USD
    symbol: str  # e.g. BTC
    name: str | None = None
    quote: Quote = Quote()
    market_cap: float | None = None
    volume_24h: float | None = None
    turnover: float | None = None  # 24h volume / market cap
    circulating_supply: float | None = None
    max_supply: float | None = None
    supply_ratio: float | None = None  # circulating / max (or total) supply
    return_30d: float | None = None
    return_1y: float | None = None
    price_vs_sma50: float | None = None
    price_vs_sma200: float | None = None
    volatility_1y: float | None = None
    max_drawdown_1y: float | None = None
    from_all_time_high: float | None = None  # e.g. -0.35 == 35% below the high
    age_years: float | None = None
    is_stablecoin: bool = False
    facts: list[Fact] = []
    notes: list[str] = []


class Fact(BaseModel):
    label: str
    value: str


class MetricScore(BaseModel):
    key: str
    label: str
    value: float | None
    display: str
    score: float | None  # 0-100, None when the metric is unavailable
    benchmark: str | None = None  # e.g. "Industry median 28.4x"


class CategoryScore(BaseModel):
    key: str
    label: str
    description: str = ""  # what the category measures, in plain words
    weight: float
    score: float | None
    metrics: list[MetricScore]
    optional: bool = False


class PeerInfo(BaseModel):
    name: str
    level: str  # "industry" or "sector"
    companies: int


class Holding(BaseModel):
    symbol: str | None
    name: str
    weight: float  # share of the fund, 0..1


class Weight(BaseModel):
    name: str
    weight: float  # share of the fund, 0..1


class FundProfile(BaseModel):
    """What an ETF invests in."""

    summary: str | None = None
    holdings: list[Holding] = []  # largest first, up to 10
    sectors: list[Weight] = []  # stock sectors, largest first
    asset_mix: list[Weight] = []  # stocks, bonds, cash, ...
    as_of: str | None = None


class Outlook(BaseModel):
    """Analysts' forecasts for a stock, scored 0-100. Not part of the rating."""

    score: float | None
    analysts: int
    as_of: str | None  # when the forecasts were collected
    category: CategoryScore


class Rating(Quote):
    ticker: str  # the id used in URLs and the watchlist (e.g. "AAPL", "BTC-USD")
    symbol: str  # what to show (e.g. "AAPL", "BTC")
    asset_type: AssetType
    name: str | None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    score: float | None
    label: str
    coverage: float  # fraction of the core metrics that had data
    categories: list[CategoryScore]
    peer_group: PeerInfo | None = None
    facts: list[Fact] = []
    notes: list[str] = []
    source: str
    outlook: Outlook | None = None
    fund_profile: FundProfile | None = None
    dividend: DividendInfo | None = None
    profile: str | None = None  # investor profile the overall score is weighted for (None = balanced)


class NewsItem(BaseModel):
    title: str
    publisher: str | None = None
    link: str
    published: int | None = None  # Unix seconds
    thumbnail: str | None = None


class SearchResult(BaseModel):
    ticker: str
    symbol: str
    name: str
    asset_type: AssetType
    exchange: str | None = None


StockData.model_rebuild()
CryptoData.model_rebuild()
