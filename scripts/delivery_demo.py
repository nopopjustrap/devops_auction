"""Docker/registry acceptance rehearsal in disposable staging (never a real host)."""

import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from deploy import docker

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    image = os.environ["IMAGE"]
    registry = "auction-rehearsal-" + uuid.uuid4().hex[:10]
    registry_port, service_port = port(), port()
    repo = f"127.0.0.1:{registry_port}/auction"
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    results = []
    volumes, containers, images = set(), set(), set()
    with tempfile.TemporaryDirectory(prefix="auction-delivery-") as temporary:
        root = Path(temporary)
        config = root / "staging.env"
        normal = (
            f"IMAGE_REPOSITORY={repo}\nAPP_NAME=Delivery rehearsal\n"
            "SESSION_TTL_HOURS=8\nCOOKIE_SECURE=false\n"
            f"STAGING_PORT={service_port}\nSMOKE_USERNAME=release_operator\n"
            f"SMOKE_PASSWORD={secrets.token_urlsafe(24)}\n"
        )
        config.write_text(normal)
        config.chmod(0o600)

        def exercise(name, action="deploy", tag="", success=True, reason=""):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/deploy.py"),
                    action,
                    "--root",
                    str(root),
                    "--tag",
                    tag,
                    "--health-timeout",
                    "45",
                ],
                text=True,
                capture_output=True,
                timeout=240,
            )
            record = {
                "case": name,
                "exit_code": result.returncode,
                "output": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
            results.append(record)
            print(json.dumps(record), flush=True)
            if (result.returncode == 0) != success:
                raise RuntimeError(f"Unexpected result: {name}")
            if reason and reason not in result.stdout:
                raise RuntimeError(f"Wrong failure cause: {name}")
            return json.loads(result.stdout)

        def current():
            return json.loads((root / "state.json").read_text())["current"]

        def unchanged(sha):
            assert current()["sha"] == sha, "Failed release changed accepted revision"
            state = json.loads(docker("inspect", current()["container"]))[0]["State"]
            assert state["Running"], "Previous release was not restored"
            # Separate HTTP check verifies recovery, not merely the recorded state.
            import urllib.request

            with urllib.request.urlopen(
                f"http://127.0.0.1:{service_port}/version", timeout=10
            ) as r:
                assert json.load(r)["revision"] == sha

        def build_fixture(sha, fault=""):
            tag = repo + ":sha-" + sha
            # Test-only derivative images are built on the CI runner, never on staging.
            # No fault flags are added to the application or production deployment.
            text = (
                f"FROM {image}\nUSER root\n"
                + 'RUN python -c "import json; '
                + f"open('app/build_info.json','w').write(json.dumps(dict(revision='{sha}')))\"\n"
                + f"LABEL org.opencontainers.image.revision={sha}\n"
            )
            if fault == "scenario":
                text += (
                    "RUN python -c \"from pathlib import Path; p=Path('app/main.py'); "
                    "p.write_text(p.read_text().replace('return services.create_sale(database, data)', "
                    "'return {}'))\"\n"
                )
            text += "USER 10001:10001\n"
            if fault == "health":
                text += 'CMD ["python", "-m", "http.server", "8000"]\n'
            text += (
                "HEALTHCHECK --interval=2s --timeout=2s --start-period=2s --retries=2 "
                'CMD python -c "import urllib.request; '
                "urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=1)\"\n"
            )
            dockerfile = root / "Dockerfile"
            dockerfile.write_text(text)
            docker("build", "--tag", tag, "--file", str(dockerfile), str(root))
            images.add(tag)
            docker("push", tag)
            return "sha-" + sha

        try:
            docker(
                "run",
                "-d",
                "--name",
                registry,
                "-p",
                f"127.0.0.1:{registry_port}:5000",
                "registry:2.8.3",
            )
            for _ in range(30):
                with socket.socket() as sock:
                    if sock.connect_ex(("127.0.0.1", registry_port)) == 0:
                        break
                time.sleep(1)
            a = build_fixture("a" * 40)
            b = build_fixture("b" * 40)
            health = build_fixture("c" * 40, "health")
            scenario = build_fixture("d" * 40, "scenario")
            exercise("first accepted release", tag=a)
            exercise(
                "nonexistent tag",
                tag="sha-" + "e" * 40,
                success=False,
                reason="docker pull failed",
            )
            unchanged("a" * 40)
            config.write_text(
                "\n".join(
                    x
                    for x in normal.splitlines()
                    if not x.startswith("SESSION_TTL_HOURS=")
                )
                + "\n"
            )
            exercise(
                "missing required variable",
                tag=b,
                success=False,
                reason="Missing required variable: SESSION_TTL_HOURS",
            )
            unchanged("a" * 40)
            config.write_text(normal)
            exercise(
                "failed container healthcheck",
                tag=health,
                success=False,
                reason="healthcheck failed",
            )
            unchanged("a" * 40)
            exercise(
                "healthy app but broken sale",
                tag=scenario,
                success=False,
                reason="/api/v1/sales: HTTP 500",
            )
            unchanged("a" * 40)
            docker("stop", registry)
            exercise(
                "registry unavailable",
                tag=b,
                success=False,
                reason="docker pull failed",
            )
            unchanged("a" * 40)
            docker("start", registry)
            exercise("second accepted release", tag=b)
            unchanged("b" * 40)
            docker("stop", registry)
            exercise("manual rollback without registry", action="rollback")
            unchanged("a" * 40)
            results.append({"status": "all delivery scenarios passed"})
        finally:
            # Only resources recorded under this temporary staging root are removed.
            if (root / "releases").exists():
                for directory in (root / "releases").iterdir():
                    containers.add("auction-staging-" + directory.name)
                    volumes.add("auction-staging-" + directory.name)
            for name in containers | {registry}:
                with contextlib.suppress(RuntimeError):
                    docker("rm", "-f", name)
            for name in volumes:
                with contextlib.suppress(RuntimeError):
                    docker("volume", "rm", name)
            for name in images:
                with contextlib.suppress(RuntimeError):
                    docker("image", "rm", name)
            (reports / "delivery-rehearsal.json").write_text(
                json.dumps(results, indent=2) + "\n"
            )


if __name__ == "__main__":
    main()
