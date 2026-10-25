import pytest

from app.sources import yahoo
from tests.recordings import RECORDED_AT, chart, timeseries


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_parse_chart_real_payload():
    c = chart("AAPL")
    assert c.currency == "USD"
    assert len(c.closes) == len(c.timestamps) == len(c.raw_closes) > 2400
    assert c.timestamps == sorted(c.timestamps)
    assert all(p > 0 for p in c.closes)
    assert c.dividends and all(a > 0 for _, a in c.dividends)
    # Adjusted closes sit below actual ones in the past (dividends paid since).
    assert c.closes[0] < c.raw_closes[0]
    assert c.raw_closes[-1] == pytest.approx(c.meta["regularMarketPrice"], rel=1e-6)


def test_parse_timeseries_real_payload():
    ts = timeseries("AAPL")
    rev = ts["annualTotalRevenue"]
    assert [p.as_of for p in rev] == sorted(p.as_of for p in rev)
    assert rev[-1].currency == "USD" and rev[-1].period == "12M"
    assert ts["trailingPeRatio"][-1].value > 0


def test_market_state_from_trading_periods():
    meta = chart("AAPL").meta
    periods = meta["currentTradingPeriod"]
    assert yahoo.market_state(meta, periods["regular"]["start"] + 60) == "open"
    assert yahoo.market_state(meta, periods["pre"]["start"] + 60) == "pre"
    assert yahoo.market_state(meta, periods["post"]["start"] + 60) == "post"
    assert yahoo.market_state(meta, RECORDED_AT) == "closed"
    assert yahoo.market_state({}, RECORDED_AT) is None


@pytest.mark.parametrize("status, body, error", [
    (429, {}, yahoo.YahooRateLimited),
    (404, {"chart": {"error": {"description": "No data found"}}}, yahoo.YahooNotFound),
    (500, {"finance": {"error": {"description": "Internal"}}}, yahoo.YahooError),
    (200, ValueError("not json"), yahoo.YahooError),
])
def test_http_errors(status, body, error):
    c = yahoo.Client(session=FakeSession(FakeResponse(status, body)))
    with pytest.raises(error):
        c.chart("AAPL")


def test_network_error_is_yahoo_error():
    c = yahoo.Client(session=FakeSession(ConnectionError("down")))
    with pytest.raises(yahoo.YahooError, match="network error"):
        c.search("apple")


def test_chart_with_empty_result_is_not_found():
    c = yahoo.Client(session=FakeSession(FakeResponse(200, {"chart": {"result": [], "error": None}})))
    with pytest.raises(yahoo.YahooNotFound):
        c.chart("NOPE")


def test_timeseries_splits_long_type_lists():
    session = FakeSession(FakeResponse(200, {"timeseries": {"result": []}}))
    yahoo.Client(session=session).timeseries("KO", [f"annualX{i}" for i in range(85)])
    assert len(session.calls) == 3
    assert all(len(p["type"].split(",")) <= 40 for _, p in session.calls)


def test_screener_uses_absolute_url():
    session = FakeSession(FakeResponse(200, {"finance": {"result": [{"quotes": [{"symbol": "BTC-USD"}], "total": 9}]}}))
    quotes, total = yahoo.Client(session=session).screener("all_cryptocurrencies_us", 5)
    assert session.calls[0][0] == yahoo.SCREENER_URL
    assert quotes == [{"symbol": "BTC-USD"}] and total == 9


def test_capture_script_requests_the_same_series_as_the_app():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ast

    src = (Path(__file__).resolve().parents[1] / "scripts" / "capture_fixtures.py").read_text()
    ns: dict = {}
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets[0].id in ("_ITEMS", "_VALUATION", "TIMESERIES_TYPES"):
            exec(compile(ast.Module([node], []), "capture", "exec"), ns)
    from app.providers.stocks import TIMESERIES_TYPES

    assert ns["TIMESERIES_TYPES"] == TIMESERIES_TYPES


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("not JSON")
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_server_errors_and_dropped_connections_are_retried(monkeypatch):
    from app.sources import yahoo

    monkeypatch.setattr(yahoo.time, "sleep", lambda s: None)
    session = _Session([_Response(500), ConnectionError("reset"), _Response(200, {"ok": 1})])
    assert yahoo.Client(session=session)._get("/x", {}) == {"ok": 1} and session.calls == 3

    always = _Session([_Response(503)] * 3)
    with pytest.raises(yahoo.YahooError, match="503"):
        yahoo.Client(session=always)._get("/x", {})
    assert always.calls == 3

    # Not retried: rate limits and unknown symbols.
    limited = _Session([_Response(429)])
    with pytest.raises(yahoo.YahooRateLimited):
        yahoo.Client(session=limited)._get("/x", {})
    missing = _Session([_Response(404)])
    with pytest.raises(yahoo.YahooNotFound):
        yahoo.Client(session=missing)._get("/x", {})
    assert limited.calls == missing.calls == 1
