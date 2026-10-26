import gc

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import create_app


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(test_engine, monkeypatch):
    from app.services import auth_service

    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setattr(auth_service, "BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password-123")
    monkeypatch.setattr(auth_service, "PASSWORD_ITERATIONS", 100_000)
    app = create_app(test_engine)
    with TestClient(app) as test_client:
        test_client.headers.update({"Origin": "http://localhost:5173"})
        response = test_client.post(
            "/api/auth/login",
            json={
                "email": "admin@example.test",
                "password": "test-admin-password-123",
            },
        )
        assert response.status_code == 200
        yield test_client
    gc.collect()
