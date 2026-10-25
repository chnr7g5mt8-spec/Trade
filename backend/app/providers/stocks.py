"""Stock (and fund) data from Yahoo's crumb-free endpoints.

`build_stock` is a pure function from raw Yahoo payloads to `StockData`, so
it can be tested against recorded real responses. `StockProvider` fetches
those payloads, with caching sized to how often each kind of data changes.
"""

from __future__ import annotations

import bisect
import logging
import math
import time
from datetime import date, datetime, timezone
from typing import Callable

from .. import stats
from ..models import DividendInfo, Fact, Quote, StockData
from ..sources import yahoo
from ..sources.yahoo import Chart, Point
from .cache import TTLCache

log = logging.getLogger(__name__)

_STATEMENT_ITEMS = [
    "TotalRevenue", "NetIncomeCommonStockholders", "DilutedEPS", "OperatingIncome", "GrossProfit", "EBIT",
    "InterestExpense", "StockholdersEquity", "TotalDebt", "TotalAssets", "CurrentAssets", "CurrentLiabilities",
    "Inventory", "OrdinarySharesNumber", "FreeCashFlow", "CashDividendsPaid", "OperatingCashFlow",
]
_VALUATION_ITEMS = ["MarketCap", "EnterpriseValue", "PeRatio", "ForwardPeRatio", "PegRatio", "PsRatio", "PbRatio",
                    "EnterprisesValueEBITDARatio"]
TIMESERIES_TYPES = ([f"annual{k}" for k in _STATEMENT_ITEMS] + [f"quarterly{k}" for k in _STATEMENT_ITEMS]
                    + [f"trailing{k}" for k in _STATEMENT_ITEMS] + [f"trailing{k}" for k in _VALUATION_ITEMS])

# Yahoo refreshes its valuation ratios every few weeks; older ones (e.g. a P/E
# last published before the company turned loss-making) are ignored.
VALUATION_MAX_AGE_DAYS = 90
FUND_TYPES = {"ETF", "MUTUALFUND"}

# Quote currencies in minor units (pence, cents) and their major currency.
MINOR_UNITS = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}

# Benchmark index used for beta, by exchange; anything else uses the S&P 500.
INDEX_FOR_EXCHANGE = {
    "JPX": "^N225", "LSE": "^FTSE", "GER": "^GDAXI", "FRA": "^GDAXI", "PAR": "^FCHI", "AMS": "^AEX",
    "HKG": "^HSI", "NSI": "^NSEI", "BSE": "^BSESN", "TOR": "^GSPTSE", "ASX": "^AXJO", "KSC": "^KS11",
    "TAI": "^TWII", "EBS": "^SSMI", "MIL": "FTSEMIB.MI", "MCE": "^IBEX", "STO": "^OMX", "SAO": "^BVSP",
}
DEFAULT_INDEX = "^GSPC"

# Cash flow, liquidity and leverage measures don't describe how banks, insurers
# and lenders work (deposits and float are their raw material), so they're skipped.
# Pipelines, utilities and REITs own huge, long-lived assets whose depreciation
# makes accounting profit look small next to the cash they produce, so their
# dividends are measured against operating cash flow, as those industries do.
CASH_FLOW_PAYOUT_INDUSTRIES = ("oil & gas midstream", "utilities", "reit")


def cash_flow_payout(industry: str | None) -> bool:
    name = (industry or "").lower()
    return any(name.startswith(prefix) for prefix in CASH_FLOW_PAYOUT_INDUSTRIES)


FINANCIAL_INDUSTRY_WORDS = ("bank", "insurance", "capital markets", "credit services", "mortgage")
NOT_FOR_FINANCIALS = ("ev_to_ebitda", "fcf_yield", "gross_margin", "operating_margin", "debt_to_equity",
                      "current_ratio", "quick_ratio", "interest_coverage")


def is_financial(industry: str | None) -> bool:
    return any(w in (industry or "").lower() for w in FINANCIAL_INDUSTRY_WORDS)


FxRate = Callable[[str, str], "float | None"]  # (from_currency, to_currency) -> rate


def major_currency(code: str | None) -> tuple[str | None, float]:
    """('GBp') -> ('GBP', 100): the major currency and how many quote units make one."""
    if code in MINOR_UNITS:
        return MINOR_UNITS[code]
    return code, 1.0


def _market_cap_from_shares(ts: dict[str, list[Point]], price: float | None,
                            quote_currency: str | None) -> tuple[float | None, str | None]:
    """Shares outstanding x price, in the reporting currency.

    Only for listings quoted in the company's own currency: a depositary
    receipt in another currency can stand for several shares (one TSM ADR is
    five shares), so shares x price would be wrong there.
    """
    shares = _balance(ts, "OrdinarySharesNumber")
    major, units = major_currency(quote_currency)
    home = home_currency(ts)
    if not shares or shares.value <= 0 or not price or not home or home != major:
        return None, None
    return shares.value * price / units, home


def home_currency(ts: dict[str, list[Point]]) -> str | None:
    """The currency the company reports in, from its latest annual figures."""
    seen = [pts[-1].currency for k, pts in ts.items() if k.startswith("annual") and pts and pts[-1].currency]
    return max(set(seen), key=seen.count) if seen else None


def _converter(fx_history: Chart | None) -> Callable[[int, float], float] | None:
    """Converts a payment at time t with the exchange rate of that day (or the last one before it)."""
    if not fx_history or not fx_history.timestamps:
        return None
    times, rates = fx_history.timestamps, fx_history.raw_closes or fx_history.closes

    def convert(t: int, amount: float) -> float:
        i = max(0, bisect.bisect_right(times, t) - 1)
        return amount * rates[i]
    return convert


# --- helpers over timeseries -------------------------------------------------

def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _latest(ts: dict[str, list[Point]], key: str) -> Point | None:
    pts = ts.get(key)
    return pts[-1] if pts else None


def _ttm(ts: dict[str, list[Point]], item: str) -> Point | None:
    """Trailing twelve months: Yahoo's own TTM figure if current, else the sum of the last 4 quarters."""
    trailing = _latest(ts, "trailing" + item)
    quarters = ts.get("quarterly" + item) or []
    if trailing and (not quarters or trailing.as_of >= quarters[-1].as_of):
        return trailing
    if len(quarters) >= 4 and 250 <= _days_between(quarters[-4].as_of, quarters[-1].as_of) <= 300:
        last4 = quarters[-4:]
        return Point(as_of=last4[-1].as_of, value=sum(p.value for p in last4), currency=last4[-1].currency,
                     period="TTM")
    fallback = trailing or _latest(ts, "annual" + item)
    # Don't fall back to a figure much older than the company's latest report
    # (e.g. a line item the company stopped reporting years ago).
    newest = max((pts[-1].as_of for pts in ts.values() if pts and pts[-1].period != "TTM"), default=None)
    if fallback and newest and _days_between(fallback.as_of, newest) > 400:
        return None
    return fallback


def _balance(ts: dict[str, list[Point]], item: str) -> Point | None:
    """Most recent balance-sheet value (quarterly if available, else annual)."""
    q, a = _latest(ts, "quarterly" + item), _latest(ts, "annual" + item)
    if q and a:
        return q if q.as_of >= a.as_of else a
    return q or a


def _yoy(points: list[Point]) -> float | None:
    """Latest period vs the same period a year earlier (needs ~1 year between them)."""
    if len(points) < 2:
        return None
    latest = points[-1]
    for p in reversed(points[:-1]):
        days = _days_between(p.as_of, latest.as_of)
        if 330 <= days <= 400:
            return latest.value / p.value - 1 if p.value > 0 else None
        if days > 400:
            break
    return None


def _ratio(a: Point | float | None, b: Point | float | None) -> float | None:
    av = a.value if isinstance(a, Point) else a
    bv = b.value if isinstance(b, Point) else b
    if av is None or bv is None or bv == 0:
        return None
    return av / bv


# --- price helpers -----------------------------------------------------------

def _close_on(chart: Chart, iso: str) -> float | None:
    """Actual traded close on the given date, or the last one before it."""
    cutoff = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() + 86400
    best = None
    for t, c in zip(chart.timestamps, chart.raw_closes or chart.closes):
        if t < cutoff:
            best = c
        else:
            break
    return best


def _last_year(chart: Chart) -> tuple[list[int], list[float]]:
    if not chart.timestamps:
        return [], []
    start = chart.timestamps[-1] - 365 * 86400
    pairs = [(t, c) for t, c in zip(chart.timestamps, chart.closes) if t >= start]
    return [t for t, _ in pairs], [c for _, c in pairs]


def annualized_return(chart: Chart, years: int) -> float | None:
    """Total return per year over the last `years`, from dividend-adjusted closes."""
    if not chart.timestamps or not chart.closes:
        return None
    start = chart.timestamps[-1] - years * 365.25 * 86400
    if chart.timestamps[0] > start + 7 * 86400:
        return None  # not enough history
    then = next((c for t, c in zip(chart.timestamps, chart.closes) if t >= start), None)
    if not then or then <= 0:
        return None
    return (chart.closes[-1] / then) ** (1 / years) - 1


def _month_end_closes(chart: Chart) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, c in zip(chart.timestamps, chart.closes):
        out[datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")] = c  # last close of each month wins
    return out


def beta(stock: Chart, index: Chart | None, months: int = 60, now: float | None = None) -> float | None:
    """Sensitivity of the stock's monthly returns to its market index over 5 years
    (the convention Yahoo and most finance sites use). Needs at least 3 years."""
    if index is None:
        return None
    s, m = _month_end_closes(stock), _month_end_closes(index)
    common = sorted(set(s) & set(m))
    # Drop the current, incomplete month.
    current = datetime.fromtimestamp(time.time() if now is None else now, tz=timezone.utc).strftime("%Y-%m")
    if common and common[-1] == current:
        common = common[:-1]
    common = common[-(months + 1):]
    pairs = [(m[b] / m[a] - 1, s[b] / s[a] - 1) for a, b in zip(common, common[1:]) if m[a] > 0 and s[a] > 0]
    if len(pairs) < 36:
        return None
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var


def build_quote(chart: Chart, prepost: Chart | None = None, now: float | None = None) -> Quote:
    now = time.time() if now is None else now
    meta = chart.meta
    price = stats.num(meta.get("regularMarketPrice")) or (chart.closes[-1] if chart.closes else None)
    price_time = stats.epoch(meta.get("regularMarketTime"))
    state = yahoo.market_state(meta, now)
    if meta.get("instrumentType") == "CRYPTOCURRENCY":
        state = "open"  # trades around the clock
    extended_price = extended_session = None
    if prepost and prepost.timestamps and state != "open":
        last_t, last_c = prepost.timestamps[-1], prepost.closes[-1]
        if price_time is None or last_t > price_time:
            extended_price, extended_session = last_c, ("pre" if state == "pre" else "post")
    _, year = _last_year(chart)
    return Quote(
        price=price, currency=meta.get("currency"), price_time=price_time, market_state=state,
        extended_price=extended_price, extended_session=extended_session,
        fifty_two_week_high=stats.num(meta.get("fiftyTwoWeekHigh")) or (max(year) if year else None),
        fifty_two_week_low=stats.num(meta.get("fiftyTwoWeekLow")) or (min(year) if year else None),
        price_history=stats.downsample(year),
    )


PAYMENTS_PER_YEAR = (1, 2, 4, 12)


def _payments_per_year(times: list[int]) -> int | None:
    """Annual, semi-annual, quarterly or monthly, from the usual gap between recent payments."""
    # Payments on the same day (a regular and a special dividend) count as one date.
    dates = sorted(set(t // 86400 for t in times))[-9:]
    gaps = sorted(b - a for a, b in zip(dates, dates[1:]))
    if not gaps:
        return None
    per_year = 365.25 / gaps[len(gaps) // 2]
    best = min(PAYMENTS_PER_YEAR, key=lambda n: abs(math.log(per_year / n)))
    return best if abs(math.log(per_year / best)) < 0.35 else None


def _annual_rate(amounts: list[float], per_year: int) -> float:
    """The regular payment times payments a year. The median ignores one-off specials and a missing payment."""
    xs = sorted(amounts)
    return xs[len(xs) // 2] * per_year if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2 * per_year


def dividend_schedule(chart: Chart, now: float) -> DividendInfo | None:
    """The regular payment and the next expected ex-dividend date, when the company pays on a schedule."""
    if not chart.dividends:
        return None
    times = [t for t, _ in chart.dividends]
    per_year = _payments_per_year(times)
    if not per_year:
        return None
    gap = 365.25 * 86400 / per_year
    if now - times[-1] >= 1.6 * gap:
        return None  # payments have stopped (or paused)
    amount = _annual_rate([a for _, a in chart.dividends[-per_year:]], per_year) / per_year
    nxt = times[-1] + gap
    while nxt < now:
        nxt += gap
    return DividendInfo(per_year=per_year, amount=amount, currency=chart.currency, last_ex_date=int(times[-1]),
                        next_ex_date=int(nxt))


def _dividend_metrics(chart: Chart, price: float | None, now: float,
                      to_home: Callable[[int, float], float] | None = None) -> dict[str, float | None]:
    """Yield, 5-year growth and streak of increases.

    `to_home` converts a payment (time, amount) into the company's own
    currency: a foreign company's dividends in another listing's currency go
    up and down with the exchange rate, which says nothing about its dividend.
    """
    out: dict[str, float | None] = {"dividend_yield": None, "dividend_growth_5y": None, "dividend_streak": None}
    if not chart.dividends or not price:
        return out
    times = [t for t, _ in chart.dividends]
    per_year = _payments_per_year(times)
    last_year = [a for t, a in chart.dividends if t >= now - 365 * 86400]
    if per_year and now - times[-1] < 1.6 * 365.25 * 86400 / per_year:
        # On schedule: the regular rate, so a payment missing from the data doesn't cut the yield.
        recent = [a for _, a in chart.dividends[-per_year:]]
        out["dividend_yield"] = _annual_rate(recent, per_year) / price
    elif sum(last_year) > 0:
        out["dividend_yield"] = sum(last_year) / price

    this_year = datetime.fromtimestamp(now, tz=timezone.utc).year
    by_year: dict[int, list[float]] = {}
    for t, a in chart.dividends:
        y = datetime.fromtimestamp(t, tz=timezone.utc).year
        if y < this_year:
            by_year.setdefault(y, []).append(to_home(t, a) if to_home else a)
    first_year = datetime.fromtimestamp(chart.timestamps[0], tz=timezone.utc).year if chart.timestamps else this_year
    # Only whole calendar years covered by the price history count.
    years = list(range(first_year + 1, this_year))

    def rate(y: int) -> float:
        paid = by_year.get(y, [])
        if not paid:
            return 0.0
        # The regular rate when the schedule is known (robust to a missing or special payment), else the total.
        return _annual_rate(paid, per_year) if per_year and len(paid) >= per_year / 2 else sum(paid)

    totals = [rate(y) for y in years]
    if len(totals) >= 6 and totals[-1] > 0 and totals[-6] > 0:
        out["dividend_growth_5y"] = (totals[-1] / totals[-6]) ** (1 / 5) - 1
    if totals and totals[-1] > 0:
        streak = 0
        for i in range(len(totals) - 1, 0, -1):
            if totals[i] > totals[i - 1] * 1.001:
                streak += 1
            else:
                break
        out["dividend_streak"] = float(streak)
    return out


def build_stock(ticker: str, chart: Chart, ts: dict[str, list[Point]], profile: dict | None = None,
                index_chart: Chart | None = None, prepost: Chart | None = None, fx: FxRate | None = None,
                now: float | None = None, dividend_fx: Chart | None = None) -> StockData:
    """`dividend_fx`: daily rate from the quote currency to the company's own one, for companies whose
    dividends are paid in another currency than this listing trades in (e.g. Enbridge in New York)."""
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    meta = chart.meta
    profile = profile or {}
    quote = build_quote(chart, prepost, now)
    price = quote.price
    instrument = meta.get("instrumentType")
    asset_type = "fund" if instrument in FUND_TYPES else "stock"
    notes: list[str] = []

    data: dict = dict(
        ticker=ticker,
        name=profile.get("longname") or profile.get("shortname") or meta.get("longName") or meta.get("shortName"),
        asset_type=asset_type,
        exchange=profile.get("exchDisp") or meta.get("fullExchangeName") or meta.get("exchangeName"),
        sector=profile.get("sector") or None,
        industry=profile.get("industry") or None,
        quote=quote,
    )

    # Momentum and risk come from prices, for stocks and funds alike.
    _, year = _last_year(chart)
    data.update(stats.momentum(year))
    data["volatility_1y"] = stats.annualized_volatility(year, 252)
    data["max_drawdown_1y"] = stats.max_drawdown(year)
    data["beta"] = beta(chart, index_chart, now=now)
    data.update(_dividend_metrics(chart, price, now, _converter(dividend_fx)))
    data["dividend"] = dividend_schedule(chart, now)

    if asset_type == "fund":
        data["return_3y"] = annualized_return(chart, 3)
        data["return_5y"] = annualized_return(chart, 5)
        return StockData(**data, notes=notes, facts=_facts(data, None, None))

    # --- valuation: Yahoo's ratios, rolled forward by the price move since they were published
    def fresh(key: str) -> tuple[Point, float] | None:
        p = _latest(ts, "trailing" + key)
        if not p or _days_between(p.as_of, today) > VALUATION_MAX_AGE_DAYS or not price:
            return None
        then = _close_on(chart, p.as_of)
        return (p, price / then) if then else None

    for key, field in (("PeRatio", "pe_ratio"), ("ForwardPeRatio", "forward_pe"), ("PegRatio", "peg_ratio"),
                       ("PbRatio", "price_to_book"), ("PsRatio", "price_to_sales")):
        f = fresh(key)
        if f:
            data[field] = f[0].value * f[1]

    market_cap = cap_currency = None
    f = fresh("MarketCap")
    if f:
        market_cap, cap_currency = f[0].value * f[1], f[0].currency
        ev = fresh("EnterpriseValue")
        ratio = fresh("EnterprisesValueEBITDARatio")
        if ev and ratio and ev[0].value > 0:
            ev_now = ev[0].value + market_cap - f[0].value  # debt and cash unchanged; equity repriced
            data["ev_to_ebitda"] = ratio[0].value * ev_now / ev[0].value
    computed = False
    if market_cap is None:
        # Yahoo's ratios can be months old for some listings (ENB.TO's were); work the market cap out
        # from the shares outstanding and today's price instead.
        market_cap, cap_currency = _market_cap_from_shares(ts, price, chart.currency)
        computed = market_cap is not None
    data["market_cap"] = market_cap

    ni = _ttm(ts, "NetIncomeCommonStockholders")
    if data.get("pe_ratio") is None and ni is not None and ni.value <= 0:
        data["pe_ratio"] = -1.0  # loss-making: scored 0 and shown as such

    fcf = _ttm(ts, "FreeCashFlow")
    if fcf and market_cap and cap_currency:
        rate = 1.0 if fcf.currency == cap_currency else (fx(fcf.currency, cap_currency) if fx and fcf.currency else None)
        if rate:
            data["fcf_yield"] = fcf.value * rate / market_cap

    # --- profitability (all figures in the company's reporting currency)
    revenue = _ttm(ts, "TotalRevenue")
    equity = _balance(ts, "StockholdersEquity")
    assets = _balance(ts, "TotalAssets")
    if equity and equity.value <= 0:
        notes.append("Shareholder equity is negative, so equity-based ratios aren't meaningful.")
    else:
        data["return_on_equity"] = _ratio(ni, equity)
    data["return_on_assets"] = _ratio(ni, assets)
    if computed:
        # The same ratios Yahoo publishes, from the latest results and today's price.
        if data.get("pe_ratio") is None and ni and ni.value > 0:
            data["pe_ratio"] = market_cap / ni.value
        if data.get("price_to_sales") is None and revenue and revenue.value > 0:
            data["price_to_sales"] = market_cap / revenue.value
        if data.get("price_to_book") is None and equity and equity.value > 0:
            data["price_to_book"] = market_cap / equity.value
    if revenue and revenue.value > 0:
        data["gross_margin"] = _ratio(_ttm(ts, "GrossProfit"), revenue)
        data["operating_margin"] = _ratio(_ttm(ts, "OperatingIncome"), revenue)
        data["net_margin"] = _ratio(ni, revenue)

    # --- growth
    data["revenue_growth"] = _yoy(ts.get("quarterlyTotalRevenue") or []) or _yoy(ts.get("annualTotalRevenue") or [])
    data["earnings_growth"] = _yoy(ts.get("quarterlyDilutedEPS") or []) or _yoy(ts.get("annualDilutedEPS") or [])
    annual_rev = ts.get("annualTotalRevenue") or []
    if len(annual_rev) >= 4 and annual_rev[-4].value > 0 and annual_rev[-1].value > 0:
        span = _days_between(annual_rev[-4].as_of, annual_rev[-1].as_of) / 365.25
        if 2.5 <= span <= 3.5:
            data["revenue_cagr_3y"] = (annual_rev[-1].value / annual_rev[-4].value) ** (1 / span) - 1

    # --- financial health
    debt = _balance(ts, "TotalDebt")
    if equity and debt:
        data["debt_to_equity"] = -1.0 if equity.value <= 0 else debt.value / equity.value
    ca, cl = _balance(ts, "CurrentAssets"), _balance(ts, "CurrentLiabilities")
    if ca and cl and cl.value > 0:
        data["current_ratio"] = ca.value / cl.value
        inv = _balance(ts, "Inventory")
        data["quick_ratio"] = (ca.value - (inv.value if inv else 0.0)) / cl.value
    ebit, interest = _ttm(ts, "EBIT"), _ttm(ts, "InterestExpense")
    if ebit and interest and interest.value > 0:
        data["interest_coverage"] = ebit.value / interest.value

    # --- consistency over the reported years
    def share(points: list[Point], test) -> float | None:
        return sum(1 for p in points if test(p)) / len(points) if len(points) >= 3 else None

    annual_ni = ts.get("annualNetIncomeCommonStockholders") or []
    data["profitable_years"] = share(annual_ni, lambda p: p.value > 0)
    if len(annual_rev) >= 3:
        data["revenue_up_years"] = sum(b.value > a.value for a, b in zip(annual_rev, annual_rev[1:])) / (len(annual_rev) - 1)
    eps = ts.get("annualDilutedEPS") or []
    if len(eps) >= 3:
        data["eps_up_years"] = sum(b.value > a.value for a, b in zip(eps, eps[1:])) / (len(eps) - 1)

    # --- dividends: payout from cash actually paid vs earnings
    paid = _ttm(ts, "CashDividendsPaid")
    ocf = _ttm(ts, "OperatingCashFlow")
    if data.get("dividend_yield") and paid and cash_flow_payout(data.get("industry")) and ocf and ocf.value > 0:
        data["payout_ratio"] = abs(paid.value) / ocf.value
        notes.append("Its payout ratio is measured against operating cash flow, as is usual for pipelines, "
                     "utilities and REITs: depreciation on their large assets makes accounting profit look small.")
    elif data.get("dividend_yield") and paid and ni and ni.value > 0:
        data["payout_ratio"] = abs(paid.value) / ni.value

    if is_financial(data.get("industry")):
        for key in NOT_FOR_FINANCIALS:
            data.pop(key, None)
        notes.append("Banks, insurers and lenders are rated without cash-flow, liquidity and debt measures, "
                     "which don't apply to how they work.")
    if not ts:
        notes.append("Yahoo has no financial statements for this company, so only price-based measures are shown.")
    return StockData(**data, notes=notes, facts=_facts(data, market_cap, cap_currency))


def _facts(data: dict, market_cap: float | None, cap_currency: str | None) -> list[Fact]:
    facts = []
    if market_cap:
        facts.append(Fact(label="Market cap", value=_compact(market_cap, cap_currency)))
    if data.get("exchange"):
        facts.append(Fact(label="Exchange", value=data["exchange"]))
    if data.get("industry"):
        facts.append(Fact(label="Industry", value=data["industry"]))
    if data.get("dividend_yield"):
        facts.append(Fact(label="Dividend yield", value=f"{data['dividend_yield'] * 100:.2f}%"))
    return facts


def _compact(v: float, currency: str | None) -> str:
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= size:
            amount = f"{v / size:.2f}{unit}"
            break
    else:
        amount = f"{v:,.0f}"
    return f"${amount}" if currency in (None, "USD") else f"{amount} {currency}"


# --- live fetching -----------------------------------------------------------

class StockProvider:
    """Fetches and caches the Yahoo payloads behind `build_stock`."""

    name = "yahoo"
    CHART_TTL = 60  # prices; the rating service applies its own market-aware cache on top
    FUNDAMENTALS_TTL = 6 * 3600  # statements change quarterly
    PROFILE_TTL = 7 * 86400
    INDEX_TTL = 6 * 3600
    FX_TTL = 3600

    def __init__(self, client: yahoo.Client | None = None):
        self.client = client or yahoo.Client()
        self._charts = TTLCache(self.CHART_TTL)
        self._fundamentals = TTLCache(self.FUNDAMENTALS_TTL)
        self._profiles = TTLCache(self.PROFILE_TTL)
        self._index = TTLCache(self.INDEX_TTL)
        self._fx = TTLCache(self.FX_TTL)

    def profile(self, ticker: str) -> dict:
        def load() -> dict:
            try:
                for q in self.client.search(ticker, 10):
                    if q.get("symbol", "").upper() == ticker.upper():
                        return q
            except yahoo.YahooError as exc:
                log.warning("profile lookup for %s failed: %s", ticker, exc)
            return {}
        return self._profiles.get(ticker, load)

    def fx(self, src: str, dst: str) -> float | None:
        def load() -> float | None:
            try:
                return stats.num(self.client.chart(f"{src}{dst}=X", "5d").meta.get("regularMarketPrice"))
            except yahoo.YahooError as exc:
                log.warning("fx %s->%s failed: %s", src, dst, exc)
                return None
        return self._fx.get(f"{src}{dst}", load)

    def index_chart(self, exchange_code: str | None) -> Chart | None:
        symbol = INDEX_FOR_EXCHANGE.get(exchange_code or "", DEFAULT_INDEX)
        def load() -> Chart | None:
            try:
                return self.client.chart(symbol, "10y")
            except yahoo.YahooError as exc:
                log.warning("index chart %s failed: %s", symbol, exc)
                return None
        return self._index.get(symbol, load)

    def dividend_fx(self, chart: Chart, ts: dict[str, list[Point]]) -> Chart | None:
        """Daily exchange rates into the company's own currency, when its dividends are paid in another one."""
        quote_ccy, _ = major_currency(chart.currency)
        home = home_currency(ts)
        if not chart.dividends or not quote_ccy or not home or home == quote_ccy:
            return None
        symbol = f"{quote_ccy}{home}=X"

        def load() -> Chart | None:
            try:
                return self.client.chart(symbol, "10y")
            except yahoo.YahooError as exc:
                log.warning("fx history %s failed: %s", symbol, exc)
                return None
        return self._index.get(symbol, load)

    def chart(self, ticker: str) -> Chart:
        return self._charts.get(ticker, lambda: self.client.chart(ticker, "10y"))

    def fetch(self, ticker: str) -> StockData:
        chart = self.chart(ticker)  # raises YahooNotFound for unknown symbols
        meta = chart.meta
        ts: dict = {}
        if meta.get("instrumentType") not in FUND_TYPES:
            ts = self._fundamentals.get(ticker, lambda: self.client.timeseries(ticker, TIMESERIES_TYPES))
        prepost = None
        state = yahoo.market_state(meta)
        if meta.get("hasPrePostMarketData") and state != "open":
            try:
                prepost = self.client.chart(ticker, "2d", "5m", prepost=True)
            except yahoo.YahooError:
                prepost = None
        return build_stock(ticker, chart, ts, profile=self.profile(ticker),
                           index_chart=self.index_chart(meta.get("exchangeName")), prepost=prepost, fx=self.fx,
                           dividend_fx=self.dividend_fx(chart, ts))
