"""Fail on weakened acceptance policy; server-side review protects this checker."""

import ast
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

STAGES = {
    "policy",
    "style",
    "tests",
    "migrations",
    "backup",
    "security",
    "dependencies",
    "secrets",
}
TARGETS = {
    "policy-check",
    "quality",
    "security",
    "test",
    "mutation-check",
    "migration-check",
    "backup-check",
    "backup-demo",
    "dependencies-check",
    "secrets-check",
    "container-build",
    "container-check",
    "container-scan",
    "delivery-check",
}


def test_names(source):
    return {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def check(root=Path("."), base=None):
    errors = []
    make = (root / "Makefile").read_text()
    recipe = re.search(r"(?ms)^verify:\n(.*?)(?=^[^\t\n#]|\Z)", make)
    if not recipe or any(f"$(MAKE) {target}" not in recipe[1] for target in TARGETS):
        errors.append("verify must call every required Make target")
    if "--cov-fail-under=85" not in make or "--cov-branch" not in make:
        errors.append("Coverage gate must remain branch-aware and at least 85%")
    config = tomllib.loads((root / "pyproject.toml").read_text())
    if config["tool"]["coverage"]["report"]["fail_under"] < 85:
        errors.append("Coverage threshold below 85%")
    mapping = json.loads((root / "tests/functional-coverage.json").read_text())
    if len(mapping) < 14:
        errors.append("Functional requirement inventory has been reduced")
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    if set(jobs["checks"]["strategy"]["matrix"]["stage"]) != STAGES:
        errors.append("CI check stages changed")
    if set(jobs["gate"]["needs"]) != {"checks", "build", "container", "delivery"}:
        errors.append("ci-gate must depend on all required jobs")
    if jobs["gate"].get("if") != "always()":
        errors.append("ci-gate must run after failed/skipped jobs")
    if jobs["build"]["needs"] != "checks" or jobs["container"]["needs"] != "build":
        errors.append("Build/container dependencies changed")
    if jobs.get("delivery", {}).get("needs") != "build":
        errors.append("Delivery rehearsal must depend on the tested build")
    publish = jobs["publish"]
    if publish["needs"] != "gate" or publish.get("if") != (
        "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    ):
        errors.append("Publishing must be gated and restricted to main pushes")
    cd_path = root / ".github/workflows/cd.yml"
    if not cd_path.exists():
        errors.append("CD workflow missing")
    else:
        cd = yaml.safe_load(cd_path.read_text())
        triggers = cd.get("on", cd.get(True, {}))
        if set(triggers) != {"workflow_run", "workflow_dispatch"}:
            errors.append("CD triggers must exclude PR code")
        if cd.get("concurrency") != {
            "group": "auction-staging-delivery",
            "cancel-in-progress": False,
        }:
            errors.append(
                "CD must serialize deployments without cancelling active work"
            )
        deploy = cd.get("jobs", {}).get("deploy", {})
        if deploy.get("environment") != "staging":
            errors.append("Deployment must use the staging environment")
        steps = deploy.get("steps", [])
        ids = [step.get("id") for step in steps]
        network = next((step for step in steps if step.get("id") == "tailnet"), {})
        if (
            not network.get("uses", "").startswith("tailscale/github-action@")
            or "if" in network
            or network.get("with", {}).get("tags") != "tag:auction-ci"
            or any(name not in ids for name in ("release", "tailnet", "delivery"))
            or not ids.index("release") < ids.index("tailnet") < ids.index("delivery")
        ):
            errors.append(
                "CD must connect the restricted tailnet after release validation and before SSH"
            )
        condition = deploy.get("if", "")
        if any(
            value not in condition
            for value in (
                "refs/heads/main",
                "conclusion == 'success'",
                "event == 'push'",
                "head_repository.full_name == github.repository",
            )
        ):
            errors.append("CD must require a successful main push of this repository")
    for path in (root / ".github/workflows").glob("*.yml"):
        text = path.read_text()
        if "continue-on-error:" in text:
            errors.append(f"Error suppression forbidden: {path}")
        for action in re.findall(r"uses:\s+([^\s]+)", text):
            if not re.search(r"@[0-9a-f]{40}$", action):
                errors.append(f"Action not pinned to commit: {action}")
    if base and not set(base) == {"0"}:
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ValueError("BASE_REF must be a full commit SHA")
        files = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", base, "tests"], cwd=root, text=True
        ).splitlines()
        for name in files:
            if not name.endswith(".py"):
                continue
            old = subprocess.check_output(
                ["git", "show", f"{base}:{name}"], cwd=root, text=True
            )
            new_path = root / name
            missing = test_names(old) - (
                test_names(new_path.read_text()) if new_path.exists() else set()
            )
            if missing:
                errors.append(
                    f"Removed/renamed tests require acceptance redesign: {name}: {sorted(missing)}"
                )
    return errors


def main():
    errors = check(base=os.environ.get("BASE_REF"))
    Path("reports").mkdir(exist_ok=True)
    Path("reports/acceptance.json").write_text(
        json.dumps({"errors": errors}, indent=2) + "\n"
    )
    print("\n".join(errors) if errors else "Acceptance policy passed")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
