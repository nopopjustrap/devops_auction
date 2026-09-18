from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def raw_client(tmp_path) -> Generator[TestClient, None, None]:
    application = create_app(str(tmp_path / "test.db"))
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def client(raw_client: TestClient) -> Generator[TestClient, None, None]:
    credentials = {"username": "operator", "password": "student123"}
    register = raw_client.post("/api/v1/auth/register", json=credentials)
    assert register.status_code == 201
    login = raw_client.post("/api/v1/auth/login", json=credentials)
    assert login.status_code == 200
    yield raw_client
