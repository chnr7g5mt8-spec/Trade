import pytest

from app.providers import stocks
from app.providers.stocks import beta, build_quote, build_stock, major_currency
from app.sources.yahoo import Chart, Point
from tests.recordings import RECORDED_AT, chart, profile, timeseries


def fx_from_recordings(src, dst):
    rates = {("TWD", "USD"): chart("TWDUSD=X").meta["regularMarketPrice"],
             ("EUR", "GBP"): chart("EURGBP=X").meta["regularMarketPrice"]}
    return rates.get((src, dst))


def build(symbol, index="^GSPC", **kw):
    return build_stock(symbol, chart(symbol), timeseries(symbol), profile(symbol), index_chart=chart(index),
                       fx=fx_from_recordings, now=RECORDED_AT, **kw)


# --- real recorded companies --------------------------------------------------

def test_apple_matches_known_figures():
    d = build("AAPL")
    assert d.name == "Apple Inc." and d.industry == "Consumer Electronics" and d.sector == "Technology"
    assert d.market_cap == pytest.approx(4.91e12, rel=0.01)  # Yahoo shows $4.91T
    assert d.pe_ratio == pytest.approx(38.6, rel=0.01)  # Yahoo trailing P/E 38.6
    assert d.revenue_growth == pytest.approx(109.417 / 94.036 - 1, rel=1e-3)  # Jun-26 vs Jun-25 quarter
    assert d.earnings_growth == pytest.approx(2.02 / 1.57 - 1, rel=1e-3)
    assert d.revenue_cagr_3y == pytest.approx((416.161 / 394.328) ** (1 / 3) - 1, rel=1e-2)
    assert d.beta == pytest.approx(1.07, abs=0.05)  # Yahoo's 5-year monthly beta is 1.07
    assert d.profitable_years == 1.0
    assert d.dividend_yield == pytest.approx(0.0031, abs=0.0002)
    assert 0.10 < d.payout_ratio < 0.15
    # Apple stopped reporting interest expense after 2023; a stale figure is not used.
    assert d.interest_coverage is None
    assert d.quote.market_state == "closed"
    assert d.quote.currency == "USD"


def test_adr_valuation_uses_yahoos_ratios_and_converts_currency():
    d = build("TSM")
    # Statements are in TWD, the US listing trades in USD: P/E must come out normal, not 5x off.
    assert 20 < d.pe_ratio < 50
    assert d.fcf_yield is not None and 0 < d.fcf_yield < 0.1


def test_pence_quoted_stock_with_euro_financials():
    d = build("VOD.L", index="^FTSE")
    assert d.quote.currency == "GBp"
    assert d.pe_ratio == -1.0  # loss-making in the latest year
    assert d.fcf_yield is not None and 0 < d.fcf_yield < 0.4
    assert d.dividend_growth_5y < 0  # Vodafone cut its dividend


def test_bank_skips_measures_that_do_not_apply():
    d = build("JPM")
    for key in stocks.NOT_FOR_FINANCIALS:
        assert getattr(d, key) is None
    assert d.return_on_equity is not None and d.pe_ratio is not None
    assert any("Banks" in n for n in d.notes)


def test_japanese_stock_uses_its_own_index_for_beta():
    d = build("7203.T", index="^N225")
    assert d.quote.currency == "JPY"
    assert d.beta is not None and -1 < d.beta < 3


def test_fund_has_no_company_financials():
    d = build_stock("SPY", chart("SPY"), {}, profile("SPY"), now=RECORDED_AT)
    assert d.asset_type == "fund"
    assert d.pe_ratio is None and d.return_on_equity is None
    assert d.return_1y is not None and d.volatility_1y is not None
    # Long-run returns for comparing funds, annualised.
    assert 0.0 < d.return_5y < d.return_3y < 0.4


# --- rules on synthetic data --------------------------------------------------

DAY = 86400
T0 = 1_700_000_000


def make_chart(closes, start=T0, meta=None, dividends=()):
    ts = [start + i * DAY for i in range(len(closes))]
    return Chart(symbol="X", meta={"regularMarketPrice": closes[-1], "currency": "USD", **(meta or {})},
                 timestamps=ts, closes=list(closes), raw_closes=list(closes), dividends=list(dividends))


def P(as_of, value, period="3M", currency="USD"):
    return Point(as_of=as_of, value=value, currency=currency, period=period)


def test_ttm_prefers_current_trailing_then_sums_quarters():
    q = [P("2025-03-31", 1), P("2025-06-30", 2), P("2025-09-30", 3), P("2025-12-31", 4)]
    assert stocks._ttm({"quarterlyX": q}, "X").value == 10
    stale_trailing = {"quarterlyX": q, "trailingX": [P("2025-09-30", 99, "TTM")]}
    assert stocks._ttm(stale_trailing, "X").value == 10
    current = {"quarterlyX": q, "trailingX": [P("2025-12-31", 11, "TTM")]}
    assert stocks._ttm(current, "X").value == 11


def test_stale_annual_fallback_is_dropped():
    ts = {"annualX": [P("2022-12-31", 5, "12M")], "quarterlyY": [P("2025-06-30", 1)]}
    assert stocks._ttm(ts, "X") is None
    fresh = {"annualX": [P("2025-03-31", 5, "12M")], "quarterlyY": [P("2025-06-30", 1)]}
    assert stocks._ttm(fresh, "X").value == 5


def test_yoy_needs_a_year_between_points_and_a_positive_base():
    pts = [P("2024-06-30", 100), P("2024-09-30", 1), P("2024-12-31", 1), P("2025-03-31", 1), P("2025-06-30", 120)]
    assert stocks._yoy(pts) == pytest.approx(0.2)
    assert stocks._yoy([P("2025-03-31", 100), P("2025-06-30", 120)]) is None
    assert stocks._yoy([P("2024-06-30", -5), P("2025-06-30", 3)]) is None


def test_beta_of_a_stock_moving_twice_the_index():
    import math
    n = 6 * 260
    index = [100 * (1 + 0.05 * math.sin(i / 15)) for i in range(n)]
    stock = [100.0]
    for a, b in zip(index, index[1:]):
        stock.append(stock[-1] * (1 + 2 * (b / a - 1)))
    end = T0 + n * DAY
    b = beta(make_chart(stock), make_chart(index), now=end + 40 * DAY)
    assert b == pytest.approx(2.0, rel=0.05)
    assert beta(make_chart(stock[:400]), make_chart(index[:400]), now=end) is None  # under 3 years


def test_dividend_metrics():
    # Ten years of daily prices, dividends rising 10% a year, paid quarterly.
    n = 3650
    closes = [100.0] * n
    divs, amount = [], 0.5
    year_starts = {}
    for i in range(n):
        y = 2014 + i // 365
        year_starts.setdefault(y, i)
    for y, i in sorted(year_starts.items()):
        for k in range(4):
            if i + k * 90 < n:
                divs.append((T0 + (i + k * 90) * DAY, amount))
        amount *= 1.10
    c = make_chart(closes, dividends=divs)
    out = stocks._dividend_metrics(c, 100.0, now=c.timestamps[-1])
    assert out["dividend_yield"] > 0
    assert out["dividend_growth_5y"] == pytest.approx(0.10, abs=0.02)
    assert out["dividend_streak"] >= 7


def test_no_dividends():
    c = make_chart([100.0] * 400)
    assert stocks._dividend_metrics(c, 100.0, now=c.timestamps[-1]) == {
        "dividend_yield": None, "dividend_growth_5y": None, "dividend_streak": None}


def test_valuation_ratio_is_rolled_forward_by_price_move_and_ignored_when_stale():
    closes = [100.0] * 200 + [110.0]
    c = make_chart(closes)
    last_day = stocks.yahoo.iso_date(c.timestamps[-1])
    published = stocks.yahoo.iso_date(c.timestamps[150])
    ts = {"trailingPeRatio": [P(published, 20.0, "TTM", None)]}
    d = build_stock("X", c, ts, now=c.timestamps[-1] + 3600)
    assert d.pe_ratio == pytest.approx(22.0)  # price up 10% since Yahoo published 20x
    old = stocks.yahoo.iso_date(c.timestamps[0] - 200 * DAY)
    d = build_stock("X", c, {"trailingPeRatio": [P(old, 20.0, "TTM", None)]}, now=c.timestamps[-1])
    assert d.pe_ratio is None
    assert last_day  # sanity


def test_negative_equity():
    c = make_chart([100.0] * 300)
    ts = {"quarterlyStockholdersEquity": [P("2023-06-30", -50.0)], "quarterlyTotalDebt": [P("2023-06-30", 80.0)],
          "trailingNetIncomeCommonStockholders": [P("2023-06-30", 10.0, "TTM")]}
    d = build_stock("X", c, ts, now=c.timestamps[-1])
    assert d.debt_to_equity == -1.0
    assert d.return_on_equity is None
    assert any("negative" in n for n in d.notes)


def test_extended_hours_price_only_when_newer_and_market_not_open():
    regular = chart("AAPL")
    prepost = chart("AAPL_prepost")
    q = build_quote(regular, prepost, now=RECORDED_AT)
    assert q.extended_session == "post"
    assert q.extended_price == pytest.approx(prepost.closes[-1])
    open_time = regular.meta["currentTradingPeriod"]["regular"]["start"] + 60
    assert build_quote(regular, prepost, now=open_time).extended_price is None


def test_major_currency():
    assert major_currency("GBp") == ("GBP", 100)
    assert major_currency("USD") == ("USD", 1.0)
    assert major_currency(None) == (None, 1.0)


def test_unknown_industry_is_not_financial():
    assert stocks.is_financial("Banks—Regional") and stocks.is_financial("Insurance—Life")
    assert not stocks.is_financial("Software—Application") and not stocks.is_financial(None)


def _quarterly(years=10, start_amount=0.80, growth=0.03, fx=None, skip=()):
    """Ten years of daily prices at 50 and a quarterly dividend raised 3% each January.

    fx(t) is the home-to-listing exchange rate: amounts are paid in the listing's currency, as on a
    cross-listing. `skip` drops payments by index, as when a payment is missing from Yahoo's data.
    """
    n = int(years * 365.25)
    closes = [50.0] * n
    divs, i = [], 0
    for y in range(years):
        amount = start_amount * (1 + growth) ** y
        for q in range(4):
            t = T0 + int((y * 365.25 + 15 + q * 91.3) * DAY)
            if i not in skip:
                divs.append((t, amount * (fx(t) if fx else 1)))
            i += 1
    return make_chart(closes, dividends=divs)


def test_missing_payment_does_not_cut_the_yield():
    full = _quarterly()
    missing = _quarterly(skip={37})  # the 4th payment before the last one
    now = full.timestamps[-1]
    expected = 4 * 0.80 * 1.03 ** 9 / 50
    assert stocks._dividend_metrics(full, 50.0, now)["dividend_yield"] == pytest.approx(expected, rel=0.01)
    gap = stocks._dividend_metrics(missing, 50.0, now)
    assert gap["dividend_yield"] == pytest.approx(expected, rel=0.01)
    assert gap["dividend_streak"] == 8 and gap["dividend_growth_5y"] == pytest.approx(0.03, abs=0.005)


def test_stopped_dividend_has_no_scheduled_yield():
    c = _quarterly()
    later = c.timestamps[-1] + 300 * DAY  # no payment for 10 months
    assert stocks._dividend_metrics(c, 50.0, later)["dividend_yield"] is None


def test_cross_listed_dividends_are_compared_in_the_home_currency():
    import math

    # Home currency swings ±12% against the listing's: in listing currency the dividend seems to fall in some years.
    def rate(t):
        return 0.75 * (1 + 0.12 * math.sin((t - T0) / (365.25 * DAY) * 2.1))

    c = _quarterly(fx=rate)
    now = c.timestamps[-1]
    raw = stocks._dividend_metrics(c, 50.0, now)
    assert raw["dividend_streak"] < 8  # the exchange rate breaks the streak
    fx_chart = make_chart([1 / rate(T0 + i * DAY) for i in range(len(c.timestamps))])
    home = stocks._dividend_metrics(c, 50.0, now, stocks._converter(fx_chart))
    assert home["dividend_streak"] == 8
    assert home["dividend_growth_5y"] == pytest.approx(0.03, abs=0.003)
    assert home["dividend_yield"] == raw["dividend_yield"]  # yield stays in the listing's own currency


def test_home_currency_and_fx_history_only_when_currencies_differ():
    ts = {"annualTotalRevenue": [P("2025-12-31", 1, "12M", "CAD")],
          "annualTotalDebt": [P("2025-12-31", 1, "12M", "CAD")]}
    assert stocks.home_currency(ts) == "CAD"
    assert stocks.home_currency({}) is None

    class FakeClient:
        def __init__(self):
            self.calls = []

        def chart(self, symbol, range_="10y", interval="1d", prepost=False):
            self.calls.append(symbol)
            return make_chart([1.37, 1.38])

    client = FakeClient()
    provider = stocks.StockProvider(client)
    usd_listing = make_chart([46.6], dividends=[(T0, 0.7)])
    assert provider.dividend_fx(usd_listing, ts) is not None and client.calls == ["USDCAD=X"]
    assert provider.dividend_fx(make_chart([66.5], meta={"currency": "CAD"}, dividends=[(T0, 0.97)]), ts) is None
    assert provider.dividend_fx(make_chart([46.6]), ts) is None  # no dividends: nothing to convert


def test_pipelines_utilities_and_reits_pay_out_of_cash_flow():
    assert stocks.cash_flow_payout("Oil & Gas Midstream") and stocks.cash_flow_payout("Utilities—Regulated Electric")
    assert stocks.cash_flow_payout("REIT—Retail") and not stocks.cash_flow_payout("Oil & Gas Integrated")
    assert not stocks.cash_flow_payout(None)


def test_midstream_payout_uses_operating_cash_flow():
    c = _quarterly()
    ts = {"trailingCashDividendsPaid": [P("2025-12-31", -8e9, "TTM", "CAD")],
          "trailingNetIncomeCommonStockholders": [P("2025-12-31", 5.2e9, "TTM", "CAD")],
          "trailingOperatingCashFlow": [P("2025-12-31", 13e9, "TTM", "CAD")]}
    now = c.timestamps[-1]
    pipeline = build_stock("ENB", c, ts, {"industry": "Oil & Gas Midstream"}, now=now)
    assert pipeline.payout_ratio == pytest.approx(8 / 13)
    assert any("operating cash flow" in n for n in pipeline.notes)
    other = build_stock("XOM", c, ts, {"industry": "Oil & Gas Integrated"}, now=now)
    assert other.payout_ratio == pytest.approx(8 / 5.2)


def test_special_dividend_on_a_payment_day():
    c = _quarterly()
    t, a = c.dividends[-1]
    c.dividends.append((t, 2.5))  # a special dividend paid the same day as the regular one
    out = stocks._dividend_metrics(c, 50.0, c.timestamps[-1])
    assert stocks._payments_per_year([t for t, _ in c.dividends]) == 4
    assert out["dividend_yield"] == pytest.approx(4 * 0.80 * 1.03 ** 9 / 50, rel=0.01)  # the special isn't annualised
    assert stocks._payments_per_year([T0, T0]) is None and stocks._payments_per_year([T0]) is None
