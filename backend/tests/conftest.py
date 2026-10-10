import pytest

from app.sources.recorded import RecordedClient


@pytest.fixture
def client():
    return RecordedClient()
