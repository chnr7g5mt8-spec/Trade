import json

from fastapi.testclient import TestClient

from app import history, main
from app.models import Rating


def r(ticker, score):
    return Rating(ticker=ticker, symbol=ticker, asset_type="stock", name=ticker, score=score, label="x",
                  coverage=1.0, categories=[], source="t")


def test_record_and_read(tmp_path):
    history.record([r("AAPL", 62.0), r("KO", 64.0)], "2026-10-12", tmp_path)
    history.record([r("AAPL", 63.0), r("MSFT", 68.0), r("KO", None)], "2026-10-13", tmp_path)
    history.record([r("AAPL", 61.0)], "2026-10-12", tmp_path)  # a re-run replaces that day
    history.record([r("AAPL", 60.0)], "2026-11-02", tmp_path)
    data = json.loads((tmp_path / "2026-10.json").read_text())
    # The re-run of the 12th has no KO score, so KO (unrated on the 13th too) is dropped.
    assert data == {"dates": ["2026-10-12", "2026-10-13"], "scores": {"AAPL": [61, 63], "MSFT": [None, 68]}}
    h = history.History(tmp_path)
    assert h.get("AAPL") == [("2026-10-12", 61), ("2026-10-13", 63), ("2026-11-02", 60)]
    assert h.get("MSFT") == [("2026-10-13", 68)] and h.get("NOPE") == []
    assert history.History(tmp_path / "missing").get("AAPL") == []


def test_days_are_kept_in_order_when_recorded_late(tmp_path):
    history.record([r("A", 50.0)], "2026-10-14", tmp_path)
    history.record([r("A", 40.0), r("B", 70.0)], "2026-10-13", tmp_path)
    data = json.loads((tmp_path / "2026-10.json").read_text())
    assert data["dates"] == ["2026-10-13", "2026-10-14"]
    assert data["scores"] == {"A": [40, 50], "B": [70, None]}


def test_old_months_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MONTHS_KEPT", 2)
    for month in ("2026-08", "2026-09", "2026-10"):
        history.record([r("A", 50.0)], f"{month}-01", tmp_path)
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["2026-09.json", "2026-10.json"]


def test_endpoint(tmp_path, monkeypatch):
    history.record([r("AAPL", 62.0)], "2026-10-12", tmp_path)
    monkeypatch.setattr(main, "score_history", history.History(tmp_path))
    client = TestClient(main.app)
    assert client.get("/api/history/aapl").json() == {"ticker": "AAPL", "points": [{"date": "2026-10-12", "score": 62}]}
    assert client.get("/api/history/KO").json()["points"] == []
