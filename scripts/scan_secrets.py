"""Scan Git history and the current non-ignored files, redacting all findings."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    root = Path.cwd()
    report = root / "reports"
    report.mkdir(exist_ok=True)
    image = os.environ["GITLEAKS_IMAGE"]
    common = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{report}:/reports",
        "-v",
        f"{root}/.gitleaks.toml:/config.toml:ro",
    ]
    # A linked worktree has a .git file pointing outside the working directory.
    # Mount its Git metadata read-only at the same absolute path for git log.
    if (root / ".git").is_file():
        common_dir = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--git-common-dir"], text=True
            ).strip()
        ).resolve()
        common += ["-v", f"{common_dir}:{common_dir}:ro"]
    flags = [
        "--config=/config.toml",
        "--redact=100",
        "--report-format=json",
        "--exit-code=1",
    ]
    history = subprocess.run(
        common
        + [
            "-v",
            f"{root}:/repo:ro",
            image,
            "git",
            "/repo",
            "--log-opts=HEAD",
            "--report-path=/reports/secrets-history.json",
        ]
        + flags,
        check=False,
    )
    with tempfile.TemporaryDirectory(prefix="auction-secret-scan-") as directory:
        snapshot = Path(directory)
        snapshot.chmod(0o755)
        paths = (
            subprocess.check_output(
                ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
            )
            .decode()
            .split("\0")
        )
        for name in filter(None, paths):
            source = root / name
            if source.is_symlink():
                raise RuntimeError(f"Refusing symlink in secret scan: {name}")
            if source.is_file():
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        current = subprocess.run(
            common
            + [
                "-v",
                f"{snapshot}:/repo:ro",
                image,
                "dir",
                "/repo",
                "--report-path=/reports/secrets-worktree.json",
            ]
            + flags,
            check=False,
        )
    return 0 if history.returncode == current.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
