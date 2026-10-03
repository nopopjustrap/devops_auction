from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def raw_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("SESSION_TTL_HOURS", "8")
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


# These gates report failures instead of silently accepting skipped checks.
_RESULTS = []


def pytest_addoption(parser):
    parser.addoption("--functional-coverage", action="store_true", default=False)


def pytest_runtest_logreport(report):
    _RESULTS.append(report)


def pytest_sessionfinish(session, exitstatus):
    import json
    from pathlib import Path

    if any(r.skipped or hasattr(r, "wasxfail") for r in _RESULTS):
        session.exitstatus = 1
    if not session.config.getoption("--functional-coverage"):
        return
    mapping = json.loads(
        (Path(__file__).parent / "functional-coverage.json").read_text()
    )
    passed = {r.nodeid.split("[")[0] for r in _RESULTS if r.when == "call" and r.passed}
    failed = {r.nodeid.split("[")[0] for r in _RESULTS if r.failed or r.skipped}
    covered = {
        key: bool(nodes) and all(n in passed and n not in failed for n in nodes)
        for key, nodes in mapping.items()
    }
    percent = 100 * sum(covered.values()) / len(covered)
    report = {
        "covered": sum(covered.values()),
        "total": len(covered),
        "percent": percent,
        "minimum": 40,
        "requirements": covered,
    }
    output = Path("reports/functional-coverage.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    if percent < 40:
        session.exitstatus = 1
