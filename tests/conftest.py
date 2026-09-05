from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Generator[TestClient, None, None]:
    application = create_app(str(tmp_path / "test.db"))
    with TestClient(application) as test_client:
        yield test_client
