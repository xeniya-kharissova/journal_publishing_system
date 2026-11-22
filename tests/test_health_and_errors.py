"""Tests for health check, OpenAPI/Swagger UI, CORS, SQLite FK pragma, and error envelopes."""

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app


def test_health_endpoint_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "scholarly-journal-backend"
    assert body["version"]


def test_openapi_and_swagger_ui_are_live(client: TestClient) -> None:
    docs_response = client.get("/docs")
    assert docs_response.status_code == 200
    assert "text/html" in docs_response.headers["content-type"]

    schema_response = client.get("/openapi.json")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert "/health" in schema["paths"]
    assert "/api/v1/auth/register" in schema["paths"]
    assert "/api/v1/users/me" in schema["paths"]
    assert "/api/v1/admin/users" in schema["paths"]


def test_cors_allows_configured_frontend_origin(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_sqlite_foreign_key_enforcement_is_enabled(db_session: Session) -> None:
    result = db_session.execute(text("PRAGMA foreign_keys")).scalar()
    assert result == 1


def test_404_uses_structured_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/nonexistent-endpoint")
    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "not_found"


def test_405_uses_structured_error_envelope(client: TestClient) -> None:
    response = client.delete("/health")
    assert response.status_code == 405
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "method_not_allowed"


def test_422_validation_error_uses_structured_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "validation_error"
    assert isinstance(body["details"], list)
    assert len(body["details"]) > 0


def test_500_internal_error_uses_structured_error_envelope(test_settings: Settings) -> None:
    app = create_app(test_settings)

    @app.get("/_test/crash")
    def crash_route() -> None:
        raise RuntimeError("Simulated unhandled failure")

    with TestClient(app, raise_server_exceptions=False) as crash_client:
        response = crash_client.get("/_test/crash")

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == {"code", "message", "details"}
    assert body["code"] == "internal_server_error"
    assert body["details"] is None
