from fastapi.testclient import TestClient

from gateway.api import _constant_time_equal
from gateway.config import Settings
from gateway.main import create_app


def test_liveness_and_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "test-request"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request"


def test_constant_time_key_comparison() -> None:
    assert _constant_time_equal("same", "same")
    assert not _constant_time_equal("one", "two")


def test_api_keys_parse_from_comma_separated_environment(monkeypatch) -> None:
    monkeypatch.setenv("API_KEYS", "one,two")
    assert Settings().api_keys == ("one", "two")
