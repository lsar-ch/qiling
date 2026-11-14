from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app


def test_frontend_html_is_not_cached() -> None:
    with TestClient(create_app(load_settings())) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
