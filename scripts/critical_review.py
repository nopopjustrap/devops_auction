"""Trusted-base PR metadata check. Never import or execute pull-request code."""

import json
import os
import urllib.request
from pathlib import Path

PREFIXES = ("tests/", "scripts/", "migrations/", ".github/", ".ci/", "requirements")
FILES = {
    "Makefile",
    "pyproject.toml",
    "pytest.ini",
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    ".gitleaks.toml",
    "CONTRIBUTING.md",
}


def critical(path):
    return path in FILES or path.startswith(PREFIXES)


def approved(reviews, owners, author, sha):
    latest = {}
    for review in sorted(reviews, key=lambda item: item["id"]):
        login = review["user"]["login"]
        if login in owners and review["state"] != "COMMENTED":
            latest[login] = review
    if any(r["state"] == "CHANGES_REQUESTED" for r in latest.values()):
        return False
    return any(
        login != author and r["state"] == "APPROVED" and r["commit_id"] == sha
        for login, r in latest.items()
    )


def main():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    number = int(event["pull_request"]["number"])
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]

    def get(path):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def pages(path):
        result = []
        for page in range(1, 31):
            batch = get(f"{path}?per_page=100&page={page}")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise RuntimeError("Too many records to safely evaluate approval")

    pr = get(f"pulls/{number}")
    if pr["head"]["sha"] != event["pull_request"]["head"]["sha"]:
        raise RuntimeError("PR head moved; rerun the latest event")
    changed = pages(f"pulls/{number}/files")
    if len(changed) != pr["changed_files"]:
        raise RuntimeError("Incomplete changed-file list")
    protected = sorted(
        {
            name
            for item in changed
            for name in (item["filename"], item.get("previous_filename", ""))
            if critical(name)
        }
    )
    if not protected:
        print("No critical files changed")
        return 0
    print("Critical changes require independent owner approval:")
    print("\n".join(protected))
    owners = {
        word[1:]
        for line in Path(".github/CODEOWNERS").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
        for word in line.split()[1:]
        if word.startswith("@")
    }
    reviews = pages(f"pulls/{number}/reviews")
    if not approved(reviews, owners, pr["user"]["login"], pr["head"]["sha"]):
        print("BLOCKED: independent CODEOWNER approval of the current head is missing")
        return 1
    print("Critical changes approved at the current head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
