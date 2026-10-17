"""Select only a successfully published main commit; never deploy PR artifacts."""

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


def get(path):
    repository = os.environ["GITHUB_REPOSITORY"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def published(run):
    if (
        run["event"] != "push"
        or run["head_branch"] != "main"
        or run["conclusion"] != "success"
        or run["head_repository"]["full_name"] != os.environ["GITHUB_REPOSITORY"]
    ):
        return False
    jobs = get(f"actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
    return any(j["name"] == "publish" and j["conclusion"] == "success" for j in jobs)


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ["GITHUB_REF"] != "refs/heads/main":
        raise RuntimeError("CD can only execute from main")
    action = event.get("inputs", {}).get("action", "deploy")
    if action not in ("deploy", "rollback", "recover"):
        raise RuntimeError("Invalid delivery action")
    tag = event.get("inputs", {}).get("tag", "")
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_run":
        run = event["workflow_run"]
        if not published(run):
            raise RuntimeError("CI did not successfully publish a main image")
        if get("branches/main")["commit"]["sha"] != run["head_sha"]:
            raise RuntimeError("Stale automatic deployment: main has advanced")
        tag = "sha-" + run["head_sha"]
    elif action == "deploy":
        if not re.fullmatch(r"sha-[0-9a-f]{40}", tag):
            raise RuntimeError("Use sha-<full commit SHA>")
        query = urllib.parse.urlencode(
            {"head_sha": tag[4:], "event": "push", "per_page": 100}
        )
        runs = get("actions/workflows/ci.yml/runs?" + query)["workflow_runs"]
        if not any(published(run) for run in runs):
            raise RuntimeError("No successful CI publication for this main revision")
    else:
        if tag:
            raise RuntimeError("Do not specify a tag for rollback/recover")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write(f"action={action}\ntag={tag}\n")


if __name__ == "__main__":
    main()
