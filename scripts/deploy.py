"""Staging-only Docker delivery. One host lock, immutable images, retained data.

A candidate gets an offline SQLite copy. A failed candidate never becomes current.
Rollback reactivates the retained old container AND its database snapshot.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from release_check import HTTPClient, ReleaseError, verify

REQUIRED = (
    "IMAGE_REPOSITORY",
    "APP_NAME",
    "SESSION_TTL_HOURS",
    "COOKIE_SECURE",
    "SMOKE_USERNAME",
    "SMOKE_PASSWORD",
    "STAGING_PORT",
)


def config(path):
    if path.stat().st_mode & 0o077:
        raise ReleaseError("staging.env must have mode 600")
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key in values:
            raise ReleaseError("Invalid or duplicate configuration key")
        values[key] = value
    for key in REQUIRED:
        if not values.get(key):
            raise ReleaseError(f"Missing required variable: {key}")
    if not re.fullmatch(
        r"[a-z0-9][a-z0-9.:-]*/[a-z0-9/_-]+", values["IMAGE_REPOSITORY"]
    ):
        raise ReleaseError("Invalid IMAGE_REPOSITORY")
    if (
        not values["SESSION_TTL_HOURS"].isdigit()
        or int(values["SESSION_TTL_HOURS"]) <= 0
    ):
        raise ReleaseError("Invalid SESSION_TTL_HOURS")
    # The service is deliberately bound to host loopback, accessed with SSH forwarding.
    if values["COOKIE_SECURE"] != "false":
        raise ReleaseError("This loopback HTTP staging requires COOKIE_SECURE=false")
    if (
        not values["STAGING_PORT"].isdigit()
        or not 1024 <= int(values["STAGING_PORT"]) <= 65535
    ):
        raise ReleaseError("Invalid STAGING_PORT")
    if not re.fullmatch(r"[\w.-]{3,50}", values["SMOKE_USERNAME"]):
        raise ReleaseError("Invalid SMOKE_USERNAME")
    if not 16 <= len(values["SMOKE_PASSWORD"]) <= 128:
        raise ReleaseError("SMOKE_PASSWORD must contain 16 to 128 characters")
    return values


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def docker(*args, stdin=None, timeout=180):
    result = subprocess.run(
        ["docker", *args], input=stdin, text=True, capture_output=True, timeout=timeout
    )
    if result.returncode:
        # Docker output may contain environment values. Keep failure messages bounded.
        raise ReleaseError(f"docker {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


def inspect(kind, name):
    return json.loads(docker(kind, "inspect", name))[0]


def wait_healthy(container, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = inspect("container", container)["State"]
        if state.get("Health", {}).get("Status") == "healthy" and state["Running"]:
            return
        if not state["Running"] or state.get("Health", {}).get("Status") == "unhealthy":
            raise ReleaseError("Container stopped or healthcheck failed")
        time.sleep(2)
    raise ReleaseError("Container healthcheck timed out")


class Deployment:
    def __init__(self, root, timeout=90):
        self.root = root
        self.timeout = timeout
        self.state_path = root / "state.json"
        self.state = (
            json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        )

    def probe(self, release):
        wait_healthy(release["container"], self.timeout)
        cfg = config(self.root / "releases" / release["id"] / "staging.env")
        return verify(
            HTTPClient(f"http://127.0.0.1:{release['port']}"),
            release["sha"],
            cfg["SMOKE_USERNAME"],
            cfg["SMOKE_PASSWORD"],
        )

    def restore_current(self, candidate):
        if candidate:
            with contextlib.suppress(ReleaseError):
                docker("stop", "--time", "10", candidate["container"])
        if self.state.get("current"):
            current = self.state["current"]
            docker("start", current["container"])
            self.probe(current)
            return "previous accepted release restored and verified"
        return "no previous release; service remains unavailable"

    def deploy(self, tag):
        if not re.fullmatch(r"sha-[0-9a-f]{40}", tag):
            raise ReleaseError("Tag must be sha-<full 40-character commit SHA>")
        cfg = config(self.root / "staging.env")
        current = self.state.get("current")
        if current and current["port"] != cfg["STAGING_PORT"]:
            raise ReleaseError("Changing STAGING_PORT requires a separate environment")
        image = cfg["IMAGE_REPOSITORY"] + ":" + tag
        docker("pull", image)  # Fail before touching the running service.
        metadata = inspect("image", image)
        if (
            metadata["Config"]
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            != tag[4:]
        ):
            raise ReleaseError("Image revision label does not match requested tag")
        digest = next(
            (
                d
                for d in metadata["RepoDigests"]
                if d.startswith(cfg["IMAGE_REPOSITORY"] + "@sha256:")
            ),
            None,
        )
        if not digest:
            raise ReleaseError("Registry digest unavailable")
        release_id = (
            time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
        )
        release = {
            "id": release_id,
            "sha": tag[4:],
            "image": digest,
            "container": "auction-staging-" + release_id,
            "volume": "auction-staging-" + release_id,
            "port": cfg["STAGING_PORT"],
        }
        directory = self.root / "releases" / release_id
        directory.mkdir(parents=True)
        (directory / "staging.env").write_text((self.root / "staging.env").read_text())
        app_env = directory / "app.env"
        app_env.write_text(
            "\n".join(
                f"{k}={cfg[k]}"
                for k in ("APP_NAME", "SESSION_TTL_HOURS", "COOKIE_SECURE")
            )
            + "\nDATABASE_PATH=/data/auctions.db\n"
        )
        # Intent survives interruption. Subsequent attempts require explicit recovery.
        write_json(
            self.root / "pending.json", {"candidate": release, "previous": current}
        )
        stage = "snapshot"
        try:
            if current:
                docker("stop", "--time", "15", current["container"])
            docker("volume", "create", release["volume"])
            common = [
                "run",
                "--rm",
                "-i",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--read-only",
                "-v",
                release["volume"] + ":/data",
            ]
            if current:
                docker(
                    *common,
                    "-v",
                    current["volume"] + ":/source:ro",
                    digest,
                    "python",
                    "-c",
                    "import sqlite3; s=sqlite3.connect('file:/source/auctions.db?mode=ro',uri=True); "
                    "t=sqlite3.connect('/data/auctions.db'); s.backup(t); "
                    "assert t.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; t.close(); s.close()",
                )
            stage = "migration"
            docker(
                *common,
                "--env-file",
                str(app_env),
                digest,
                "python",
                "-m",
                "app.migrate",
            )
            # Bootstrap the isolated staging operator before exposing HTTP registration.
            stage = "operator"
            docker(
                *common,
                "--env-file",
                str(directory / "staging.env"),
                digest,
                "python",
                "-",
                stdin="""import os
from app.db import connect
from app.auth import registration_is_open, register_first_user
from app.schemas import AuthCredentials
with connect('/data/auctions.db') as c:
    if registration_is_open(c):
        register_first_user(c, AuthCredentials(username=os.environ['SMOKE_USERNAME'], password=os.environ['SMOKE_PASSWORD']))
""",
            )
            stage = "start"
            docker(
                "run",
                "-d",
                "--name",
                release["container"],
                "--restart",
                "unless-stopped",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--env-file",
                str(app_env),
                "-v",
                release["volume"] + ":/data",
                "-p",
                f"127.0.0.1:{release['port']}:8000",
                digest,
            )
            stage = "acceptance"
            result = self.probe(release)
            write_json(self.state_path, {"current": release, "previous": current})
            self.state = {"current": release, "previous": current}
            (self.root / "pending.json").unlink()
            return {**result, "image": digest, "release": release_id}
        except Exception as error:
            recovery = self.restore_current(release)
            (self.root / "pending.json").unlink()
            raise ReleaseError(
                f"Release rejected at {stage}; {recovery}; {type(error).__name__}: {error}"
            ) from None

    def rollback(self):
        previous = self.state.get("previous")
        if not previous:
            raise ReleaseError("No previous accepted release available")
        current = self.state["current"]
        # No registry access is needed: old container, immutable image and DB retained.
        write_json(
            self.root / "pending.json", {"candidate": previous, "previous": current}
        )
        try:
            docker("stop", "--time", "15", current["container"])
            docker("start", previous["container"])
            result = self.probe(previous)
            self.state = {"current": previous, "previous": current}
            write_json(self.state_path, self.state)
            (self.root / "pending.json").unlink()
            return {**result, "action": "rollback", "image": previous["image"]}
        except Exception:
            recovery = self.restore_current(previous)
            (self.root / "pending.json").unlink()
            raise ReleaseError(f"Rollback rejected; {recovery}") from None

    def recover(self):
        path = self.root / "pending.json"
        pending = json.loads(path.read_text())
        # state.json may already have committed just before interruption.
        candidate = pending["candidate"]
        if candidate == self.state.get("current"):
            candidate = None
        result = self.restore_current(candidate)
        path.unlink()
        return {"status": "recovered", "detail": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("deploy", "rollback", "recover", "status"))
    parser.add_argument("--tag", default="")
    parser.add_argument("--root", type=Path, default=Path("/opt/auction-staging"))
    parser.add_argument("--health-timeout", type=int, default=90)
    args = parser.parse_args()
    os.umask(0o077)
    args.root.mkdir(parents=True, exist_ok=True)
    with (args.root / "deploy.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another deployment is running")
            return 1
        try:
            deployment = Deployment(args.root, args.health_timeout)
            if (args.root / "pending.json").exists() and args.action not in (
                "recover",
                "status",
            ):
                raise ReleaseError("Interrupted deployment detected; run recover first")
            if args.action == "deploy":
                result = deployment.deploy(args.tag)
            elif args.action == "rollback":
                result = deployment.rollback()
            elif args.action == "recover":
                result = deployment.recover()
            else:
                result = deployment.state
            write_json(args.root / "last-result.json", result)
            print(json.dumps(result))
            return 0
        except (ReleaseError, OSError, ValueError, subprocess.SubprocessError) as error:
            result = {"status": "failed", "action": args.action, "error": str(error)}
            write_json(args.root / "last-result.json", result)
            print(json.dumps(result))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
