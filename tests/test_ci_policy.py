"""Regression checks for the acceptance barrier and independent approvals."""

import shutil
from pathlib import Path

import pytest

from scripts.check_acceptance import check
from scripts.check_acceptance import test_names as collect_test_names
from scripts.critical_review import approved, critical

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy_copy(tmp_path):
    for name in (
        "Makefile",
        "pyproject.toml",
        "tests/functional-coverage.json",
        ".github/workflows/ci.yml",
        ".github/workflows/critical-review.yml",
    ):
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    return tmp_path


def test_valid_ci_policy(policy_copy):
    assert check(policy_copy) == []


@pytest.mark.parametrize(
    "name,old,new",
    [
        ("Makefile", "--cov-fail-under=85", "--cov-fail-under=20"),
        ("Makefile", "\t$(MAKE) security\n", ""),
        ("pyproject.toml", "fail_under = 85", "fail_under = 20"),
        (".github/workflows/ci.yml", "needs: gate", "needs: build"),
        (".github/workflows/ci.yml", "if: always()", "if: success()"),
        (
            ".github/workflows/ci.yml",
            "runs-on: ubuntu-24.04",
            "continue-on-error: true\n    runs-on: ubuntu-24.04",
        ),
    ],
)
def test_weakened_ci_is_rejected(policy_copy, name, old, new):
    path = policy_copy / name
    path.write_text(path.read_text().replace(old, new))
    assert check(policy_copy)


def test_test_inventory_detects_removed_test():
    before = "def test_sale(): pass\ndef test_price(): pass\n"
    after = "def test_sale(): pass\n"
    assert collect_test_names(before) - collect_test_names(after) == {"test_price"}


@pytest.mark.parametrize(
    "name",
    [
        "tests/test_api.py",
        "Makefile",
        ".github/workflows/ci.yml",
        "scripts/check_acceptance.py",
    ],
)
def test_critical_paths(name):
    assert critical(name)


def test_self_approval_and_stale_approval_rejected():
    review = {
        "id": 1,
        "user": {"login": "owner"},
        "state": "APPROVED",
        "commit_id": "current",
    }
    assert not approved([review], {"owner"}, "owner", "current")
    assert not approved([review], {"owner"}, "contributor", "new-head")
    assert not approved([review], {"someone-else"}, "contributor", "current")
    assert approved([review], {"owner"}, "contributor", "current")


def test_requested_changes_block_previous_approval():
    reviews = [
        {
            "id": 1,
            "user": {"login": "owner"},
            "state": "APPROVED",
            "commit_id": "current",
        },
        {
            "id": 2,
            "user": {"login": "owner"},
            "state": "CHANGES_REQUESTED",
            "commit_id": "current",
        },
    ]
    assert not approved(reviews, {"owner"}, "contributor", "current")
