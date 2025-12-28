import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.middlewares import RateLimitingMiddleware, RequestLoggingMiddleware, clients
from app import settings


@pytest.fixture
def app_factory():
    def _make(middleware_cls):
        app = FastAPI()

        @app.get("/test")
        async def test():
            return JSONResponse({"ok": True})

        app.add_middleware(middleware_cls)
        return app

    return _make


@pytest.fixture(autouse=True)
def clear_rate_limit_clients():
    yield
    clients.clear()


def test_rate_limiting_middleware(app_factory, monkeypatch):
    monkeypatch.setattr(settings, "rate_limiting", True)
    monkeypatch.setattr(settings, "rate_limit_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_duration_in_seconds", 60)

    app = app_factory(RateLimitingMiddleware)
    client = TestClient(app)

    assert client.get("/test").status_code == 200
    assert client.get("/test").status_code == 200

    r = client.get("/test")
    assert r.status_code == 429
    assert "X-RateLimit-Limit" in r.headers


def test_request_logging_middleware_adds_header(app_factory, monkeypatch):
    monkeypatch.setattr(settings, "debug", True)

    app = app_factory(RequestLoggingMiddleware)
    client = TestClient(app)

    r = client.get("/test")
    assert r.status_code == 200
    assert "X-Process-Time" in r.headers
