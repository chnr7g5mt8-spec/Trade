import pytest
from fastapi.testclient import TestClient

from app import main
from app.providers import SampleProvider


@pytest.fixture
def client(tmp_path, monkeypatch):
    web = tmp_path / "web"
    (web / "_expo" / "static" / "js").mkdir(parents=True)
    (web / "index.html").write_text("<html>app shell</html>")
    (web / "_expo" / "static" / "js" / "entry.js").write_text("console.log('bundle')")
    (tmp_path / "secret.txt").write_text("outside web dir")

    monkeypatch.setattr(main, "service", main.RatingService(SampleProvider()))
    routes = list(main.app.router.routes)
    main.mount_web_app(str(web))
    yield TestClient(main.app)
    main.app.router.routes[:] = routes  # don't leak the catch-all into other tests


def test_serves_index_at_root(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "app shell" in res.text


def test_serves_static_files(client):
    res = client.get("/_expo/static/js/entry.js")
    assert res.status_code == 200
    assert "bundle" in res.text
    assert "javascript" in res.headers["content-type"]


def test_app_routes_fall_back_to_index(client):
    res = client.get("/stock/AAPL")
    assert res.status_code == 200
    assert "app shell" in res.text
    assert res.headers["cache-control"] == "no-cache"


def test_api_still_takes_precedence(client):
    assert client.get("/api/rating/KO").json()["ticker"] == "KO"
    assert client.get("/health").json()["status"] == "ok"


def test_unknown_api_paths_are_404_not_the_app(client):
    res = client.get("/api/nope")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not found"}


def test_cannot_escape_web_dir(client):
    for path in ["/../secret.txt", "/%2e%2e/secret.txt", "/_expo/../../secret.txt"]:
        res = client.get(path)
        assert "outside web dir" not in res.text


def test_missing_index_fails_fast(tmp_path):
    with pytest.raises(RuntimeError, match="no index.html"):
        main.mount_web_app(str(tmp_path))
