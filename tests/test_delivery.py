"""Release acceptance must reject wrong versions and broken business behavior."""

import importlib.util
from pathlib import Path

import pytest

from app import services
from app.version import release_version
from scripts.release_check import ReleaseError, verify


class ClientAdapter:
    def __init__(self, client):
        self.client = client

    def request(self, method, path, data=None, expected=200):
        response = self.client.request(method, path, json=data)
        if response.status_code != expected:
            raise ReleaseError(f"{path}: HTTP {response.status_code}")
        return response.json() if response.content else None


def test_version_is_public_and_not_runtime_override(raw_client, monkeypatch):
    monkeypatch.setenv("VCS_REF", "fake-revision")
    response = raw_client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "0.3.0", "revision": "development"}


def test_baked_revision(monkeypatch, tmp_path):
    file = tmp_path / "build_info.json"
    file.write_text('{"revision": "' + "a" * 40 + '"}')
    monkeypatch.setattr(Path, "with_name", lambda *args: file)
    assert release_version()["revision"] == "a" * 40


def test_release_acceptance_performs_sale(client):
    result = verify(ClientAdapter(client), "development", "operator", "student123")
    assert result["status"] == "accepted"
    assert result["auction_id"] > 0


def test_release_rejects_wrong_version(client):
    with pytest.raises(ReleaseError, match="revision"):
        verify(ClientAdapter(client), "a" * 40, "operator", "student123")


def test_healthy_application_with_broken_sale_is_rejected(client, monkeypatch):
    def broken(*args):
        raise services.DomainError(409, "BROKEN", "demonstration")

    monkeypatch.setattr(services, "create_sale", broken)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    with pytest.raises(ReleaseError, match="sales"):
        verify(ClientAdapter(client), "development", "operator", "student123")


def test_wrong_commission_is_rejected(client, monkeypatch):
    original = services.create_sale

    def broken(*args):
        sale = original(*args)
        sale["commission"] = "0.00"
        return sale

    monkeypatch.setattr(services, "create_sale", broken)
    with pytest.raises(ReleaseError, match="commission"):
        verify(ClientAdapter(client), "development", "operator", "student123")


@pytest.fixture
def deploy_module(monkeypatch):
    # Server bundles use adjacent stdlib-only modules, without installing the app.
    import scripts.release_check as release_check

    monkeypatch.setitem(__import__("sys").modules, "release_check", release_check)
    spec = importlib.util.spec_from_file_location("delivery", "scripts/deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_config_rejected_before_docker(deploy_module, tmp_path):
    path = tmp_path / "staging.env"
    path.write_text("APP_NAME=Staging\n")
    path.chmod(0o600)
    with pytest.raises(ReleaseError, match="IMAGE_REPOSITORY"):
        deploy_module.Deployment(tmp_path).deploy("sha-" + "a" * 40)


def test_world_readable_config_rejected(deploy_module, tmp_path):
    path = tmp_path / "staging.env"
    path.touch(mode=0o644)
    with pytest.raises(ReleaseError, match="600"):
        deploy_module.config(path)


def test_invalid_tag_cannot_be_a_command(deploy_module, tmp_path):
    with pytest.raises(ReleaseError, match="Tag"):
        deploy_module.Deployment(tmp_path).deploy("latest; echo unwanted")


def test_rollback_without_previous_release_fails(deploy_module, tmp_path):
    with pytest.raises(ReleaseError, match="No previous"):
        deploy_module.Deployment(tmp_path).rollback()


def test_host_lock_blocks_concurrent_operation(tmp_path):
    import fcntl
    import subprocess
    import sys

    with (tmp_path / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = subprocess.run(
            [sys.executable, "scripts/deploy.py", "status", "--root", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    assert result.returncode == 1
    assert "Another deployment is running" in result.stdout


def test_publish_selector_rejects_pr_and_failed_publication(monkeypatch):
    from scripts import select_release

    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    run = {
        "id": 1,
        "event": "pull_request",
        "head_branch": "main",
        "conclusion": "success",
        "head_repository": {"full_name": "owner/repo"},
    }
    assert not select_release.published(run)
    run["event"] = "push"
    monkeypatch.setattr(
        select_release,
        "get",
        lambda _: {"jobs": [{"name": "publish", "conclusion": "skipped"}]},
    )
    assert not select_release.published(run)
    monkeypatch.setattr(
        select_release,
        "get",
        lambda _: {"jobs": [{"name": "publish", "conclusion": "success"}]},
    )
    assert select_release.published(run)
    run["head_repository"]["full_name"] = "another/repo"
    assert not select_release.published(run)
