import pytest

from app.sources.recorded import RecordedClient


@pytest.fixture
def client():
    return RecordedClient()


@pytest.fixture(autouse=True)
def no_retry_pauses(monkeypatch):
    """Tests needn't wait between the client's retries of Yahoo server errors."""
    from app.sources import yahoo

    monkeypatch.setattr(yahoo, "RETRY_WAITS", (0.0, 0.0))
