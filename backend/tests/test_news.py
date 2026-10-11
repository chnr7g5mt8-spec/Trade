from fastapi.testclient import TestClient

from app import main
from app.benchmarks import EMPTY
from app.funds import FundStore
from app.providers.market import MarketData, to_news
from app.sources.recorded import RecordedClient


def story(title, t, related=None, link=None, thumb=True):
    s = {"uuid": title, "title": title, "publisher": "Reuters", "link": link or f"https://finance.yahoo.com/{t}",
         "providerPublishTime": t, "type": "STORY"}
    if related is not None:
        s["relatedTickers"] = related
    if thumb:
        s["thumbnail"] = {"resolutions": [{"url": "https://s.yimg.com/big.jpg", "width": 1000, "tag": "original"},
                                          {"url": "https://s.yimg.com/small.jpg", "width": 140, "tag": "140x140"}]}
    return s


def test_stories_about_the_ticker_come_first_newest_first():
    items = [story("Market wrap", 300, ["SPY"]), story("Enbridge raises dividend", 100, ["ENB", "ENB.TO"]),
             story("Enbridge pipeline approved", 200, ["ENB.TO"]), story("Old link", 400, ["ENB"], link="http://x")]
    out = to_news(items, "ENB.TO", "Enbridge Inc.")
    assert [n.title for n in out] == ["Enbridge pipeline approved", "Enbridge raises dividend"]
    assert out[0].thumbnail == "https://s.yimg.com/small.jpg" and out[0].published == 200
    # Untagged stories are used when none is tagged; duplicates and non-https links are dropped.
    untagged = [story("A", 1), story("A", 2), story("B", 3, thumb=False)]
    assert [(n.title, n.thumbnail) for n in to_news(untagged, "X")] == [("B", None), ("A", "https://s.yimg.com/small.jpg")]


def test_stories_mainly_about_the_company_come_before_passing_mentions():
    items = [story("Is AT&T ready for a Starlink world?", 300, ["T", "AAPL"]),
             story("Apple hires podcast startup team", 200, ["AAPL"]),
             story("Why Apple (AAPL) stock is trading lower", 100, ["NVDA", "AAPL"])]
    assert [n.title for n in to_news(items, "AAPL", "Apple Inc.")] == [
        "Apple hires podcast startup team", "Why Apple (AAPL) stock is trading lower", "Is AT&T ready for a Starlink world?"]


def test_keyword_and_base_symbol():
    from app.providers.market import base_symbol, keyword

    assert keyword("The Coca-Cola Company") == "Coca-Cola" and keyword("Enbridge Inc.") == "Enbridge"
    assert keyword("SPDR S&P 500 ETF Trust") == "SPDR" and keyword(None) is None and keyword("3M Co") is None
    assert base_symbol("ENB.TO") == "ENB" and base_symbol("btc-usd") == "BTC" and base_symbol("BRK-B") == "BRK-B"


def test_falls_back_to_plain_symbol_then_name():
    class Client(RecordedClient):
        def __init__(self):
            super().__init__()
            self.queries = []

        def news(self, query, count=10):
            self.queries.append(query)
            return [story("Enbridge raises its dividend", 1, ["ENB"])] if query == "Enbridge" else []

    client = Client()
    found = MarketData(client).news("ENB.TO", "Enbridge Inc.")
    assert client.queries == ["ENB.TO", "ENB", "Enbridge"] and found[0].title == "Enbridge raises its dividend"


def test_news_endpoint(monkeypatch):
    market = MarketData(RecordedClient())
    market.name = "sample"
    monkeypatch.setattr(main, "service", main.RatingService(market, benchmarks=EMPTY, funds=FundStore()))
    client = TestClient(main.app)
    res = client.get("/api/news/AAPL")
    titles = [n["title"] for n in res.json()]
    # Real recorded stories: those about Apple first, newest first; passing mentions after.
    assert titles[0].startswith("Apple discloses deal") and titles[-1].startswith("Solana")
    assert len(titles) == 7
    assert client.get("/api/news/bad$").status_code == 400
