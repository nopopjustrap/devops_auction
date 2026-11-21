"""Apply the real playbook to two disposable Debian hosts and repair drift."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "infra"


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def recap(output):
    matches = re.findall(
        r"^(\S+)\s+:\s+ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)",
        output,
        re.MULTILINE,
    )
    result = {
        host: dict(zip(("ok", "changed", "unreachable", "failed"), map(int, counts)))
        for host, *counts in matches
    }
    if set(result) != {"auction-test", "auction-staging"}:
        raise RuntimeError("Both host recaps are required")
    if any(item["failed"] or item["unreachable"] for item in result.values()):
        raise RuntimeError("Ansible reported a failed or unreachable host")
    return result


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    prefix = "auction-infra-" + uuid.uuid4().hex[:8]
    image = prefix + ":debian12"
    containers = []
    results = {}
    with tempfile.TemporaryDirectory(prefix=prefix) as work:
        work = Path(work)
        work.chmod(0o700)
        key = work / "admin"
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
        public_key = key.with_suffix(".pub").read_text().strip()
        inventory = work / "inventory"
        shutil.copytree(ROOT / "infra/inventories/lab/group_vars", inventory / "group_vars")
        hosts = {"all": {"children": {"auction": {"children": {}}}}}
        known_hosts = work / "known_hosts"
        overrides = {
            "admin_public_keys": [public_key],
            "deploy_public_key": public_key,
            "secrets_directory": str(work / "credentials"),
            "firewall_ssh_sources": ["172.16.0.0/12"],
            "monitoring_source": "172.16.0.0/12",
            # Nested Docker uses vfs to avoid relying on nested overlay support.
            "docker_daemon_overrides": {"storage-driver": "vfs"},
            "ansible_ssh_common_args": f"-o UserKnownHostsFile={known_hosts}",
        }
        (work / "overrides.json").write_text(json.dumps(overrides))
        try:
            subprocess.run(
                ["docker", "build", "-t", image, str(ROOT / "infra/tests")], check=True
            )
            for environment in ("test", "staging"):
                name = prefix + "-" + environment
                containers.append(name)
                # Privileged mode and cgroups are limited to these throwaway CI
                # hosts; the application itself keeps its normal restrictions.
                run(
                    "docker", "run", "-d", "--name", name, "--privileged",
                    "--cgroupns=host", "--tmpfs", "/run", "--tmpfs", "/run/lock",
                    "--tmpfs", "/tmp", "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
                    "-v", f"{key.with_suffix('.pub')}:/initial-key.pub:ro",
                    image, "sh", "-c",
                    "cp /initial-key.pub /root/.ssh/authorized_keys; "
                    "chmod 600 /root/.ssh/authorized_keys; ssh-keygen -A; exec /sbin/init",
                )
                address = run(
                    "docker", "inspect", "--format",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", name
                )
                for _ in range(60):
                    ready = subprocess.run(
                        ["docker", "exec", name, "systemctl", "is-active", "ssh"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    if ready.returncode == 0:
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError(f"SSH did not start on {environment}")
                host_key = run("docker", "exec", name, "cat", "/etc/ssh/ssh_host_ed25519_key.pub")
                with known_hosts.open("a") as output:
                    output.write(address + " " + " ".join(host_key.split()[:2]) + "\n")
                hosts["all"]["children"]["auction"]["children"][environment] = {
                    "hosts": {"auction-" + environment: {"ansible_host": address}}
                }
            inventory_file = inventory / "hosts.yml"
            inventory_file.write_text(yaml.safe_dump(hosts))

            def apply(label, bootstrap=False):
                command = [
                    "ansible-playbook", "bootstrap.yml" if bootstrap else "site.yml",
                    "-i", str(inventory_file), "--private-key", str(key),
                    "-e", "@" + str(work / "overrides.json"),
                ]
                if bootstrap:
                    command.extend(["-e", "ansible_user=root"])
                process = subprocess.run(
                    command, cwd=ROOT / "infra", text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={**os.environ, "ANSIBLE_NOCOLOR": "1"},
                )
                (REPORTS / (label + ".log")).write_text(process.stdout)
                print(process.stdout, flush=True)
                process.check_returncode()
                results[label] = recap(process.stdout)
                return results[label]

            apply("bootstrap", bootstrap=True)
            apply("first")
            second = apply("repeat")
            if any(host["changed"] for host in second.values()):
                raise RuntimeError("A repeat run changed the desired state")
            target = containers[0]
            state = json.loads(run("docker", "exec", target, "cat", "/opt/auction-test/state.json"))
            run(
                "docker", "exec", target, "sh", "-c",
                "printf 'ENVIRONMENT=broken\\n' > /etc/auction/environment; "
                "chmod 777 /opt/auction-test",
            )
            run("docker", "exec", target, "docker", "stop", state["current"]["container"])
            repair = apply("repair")
            if repair["auction-test"]["changed"] == 0 or repair["auction-staging"]["changed"]:
                raise RuntimeError("Drift repair must change only the affected host")
            if run("docker", "exec", target, "stat", "-c", "%a", "/opt/auction-test") != "700":
                raise RuntimeError("Directory permissions were not restored")
            if "ENVIRONMENT=test" not in run("docker", "exec", target, "cat", "/etc/auction/environment"):
                raise RuntimeError("Environment configuration was not restored")
            final = apply("final")
            if any(host["changed"] for host in final.values()):
                raise RuntimeError("Repaired configuration is not idempotent")
            results["status"] = "passed"
            print("Two Debian environments, repeat run and drift repair: passed")
        finally:
            (REPORTS / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
            for name in containers:
                subprocess.run(["docker", "rm", "-fv", name], check=False)
            subprocess.run(["docker", "image", "rm", image], check=False)


if __name__ == "__main__":
    main()
