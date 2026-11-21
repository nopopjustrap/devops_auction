"""Apply the real playbook to two disposable Debian hosts and repair drift."""

import json
import os
import re
import shlex
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


def wait_for_boot(environment, process, probe, attempts=180, pause=time.sleep):
    for _ in range(attempts):
        code = process.poll()
        if code is not None:
            raise RuntimeError(
                f"{environment}: QEMU exited with code {code}; "
                f"see {environment}-console.log"
            )
        if probe(
            environment, "test", "-f", "/var/lib/cloud/instance/boot-finished",
            user="root", check=False,
        ).returncode == 0:
            return
        pause(2)
    raise RuntimeError(f"Debian did not become ready: {environment}")


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = {}
    machines = []
    acceleration = "kvm" if os.access("/dev/kvm", os.W_OK) else "tcg"
    print(f"Virtualization: {acceleration}", flush=True)
    cloud_url = "https://cloud.debian.org/images/cloud/bookworm/latest/"
    cloud_name = "debian-12-genericcloud-amd64.qcow2"
    with tempfile.TemporaryDirectory(prefix="auction-infra-") as directory:
        work = Path(directory)
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
            "ansible_ssh_common_args": f"-o UserKnownHostsFile={known_hosts}",
        }
        (work / "overrides.json").write_text(json.dumps(overrides))
        try:
            base = work / cloud_name
            run("curl", "--fail", "--location", "--retry", "3", "-o", str(base), cloud_url + cloud_name)
            checksum_text = run("curl", "--fail", "--location", "--retry", "3", cloud_url + "SHA512SUMS")
            expected = next(
                line.split()[0] for line in checksum_text.splitlines()
                if line.split()[-1].lstrip("*./") == cloud_name
            )
            if run("sha512sum", str(base)).split()[0] != expected:
                raise RuntimeError("Debian cloud image checksum mismatch")
            results["debian_image_sha512"] = expected
            for index, environment in enumerate(("test", "staging")):
                name = "auction-" + environment
                port = 22001 + index
                disk = work / (environment + ".qcow2")
                host_key = work / (environment + "-host-key")
                run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key))
                public_host_key = host_key.with_suffix(".pub").read_text().strip()
                with known_hosts.open("a") as output:
                    output.write(f"[127.0.0.1]:{port} " + " ".join(public_host_key.split()[:2]) + "\n")
                user_data = work / (environment + "-user-data")
                user_data.write_text("#cloud-config\n" + yaml.safe_dump({
                    "hostname": name,
                    "disable_root": False,
                    "ssh_pwauth": False,
                    "users": [{"name": "root", "ssh_authorized_keys": [public_key]}],
                    "ssh_deletekeys": True,
                    "ssh_keys": {
                        "ed25519_private": host_key.read_text(),
                        "ed25519_public": public_host_key,
                    },
                }))
                user_data.chmod(0o600)
                metadata = work / (environment + "-meta-data")
                metadata.write_text(yaml.safe_dump({
                    "instance-id": name + "-" + uuid.uuid4().hex,
                    "local-hostname": name,
                }))
                seed = work / (environment + "-seed.img")
                run("cloud-localds", str(seed), str(user_data), str(metadata))
                run("qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", str(base), str(disk))
                run("qemu-img", "resize", str(disk), "12G")
                console = (REPORTS / (environment + "-console.log")).open("w")
                process = subprocess.Popen([
                    "qemu-system-x86_64", "-accel", acceleration,
                    "-m", "1024", "-smp", "1", "-nographic", "-no-reboot",
                    "-drive", f"file={disk},if=virtio,format=qcow2",
                    "-drive", f"file={seed},if=virtio,format=raw,readonly=on",
                    "-netdev", f"user,id=network,hostfwd=tcp:127.0.0.1:{port}-:22",
                    "-device", "virtio-net-pci,netdev=network",
                ], stdin=subprocess.DEVNULL, stdout=console, stderr=subprocess.STDOUT)
                machines.append((process, console))
                hosts["all"]["children"]["auction"]["children"][environment] = {
                    "hosts": {name: {"ansible_host": "127.0.0.1", "ansible_port": port}}
                }

            def ssh(environment, *command, user="auction-admin", check=True):
                port = 22001 if environment == "test" else 22002
                return subprocess.run([
                    "ssh", "-F", "/dev/null", "-i", str(key), "-p", str(port),
                    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                    "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
                    "-o", "ConnectTimeout=3", f"{user}@127.0.0.1", shlex.join(command),
                ], stdin=subprocess.DEVNULL, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=check, timeout=15)

            for index, environment in enumerate(("test", "staging")):
                wait_for_boot(environment, machines[index][0], ssh)
            inventory_file = inventory / "hosts.yml"
            inventory_file.write_text(yaml.safe_dump(hosts))

            def apply(label, bootstrap=False):
                print(f"Applying {label}", flush=True)
                command = [
                    "ansible-playbook", "bootstrap.yml" if bootstrap else "site.yml",
                    "-i", str(inventory_file), "--private-key", str(key),
                    "-e", "@" + str(work / "overrides.json"),
                ]
                if bootstrap:
                    command.extend(["-e", "ansible_user=root"])
                process = subprocess.run(
                    command, cwd=ROOT / "infra", text=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    env={**os.environ, "ANSIBLE_NOCOLOR": "1"},
                )
                (REPORTS / (label + ".log")).write_text(process.stdout)
                print(process.stdout, flush=True)
                if process.returncode:
                    diagnostics = []
                    for environment in ("test", "staging"):
                        try:
                            delivery = json.loads(ssh(
                                environment, "sudo", "-n", "cat",
                                f"/opt/auction-{environment}/last-result.json",
                            ).stdout)
                            diagnostics.append({
                                "environment": environment,
                                **{key: delivery[key] for key in ("status", "action", "error") if key in delivery},
                            })
                        except (subprocess.SubprocessError, ValueError):
                            diagnostics.append({"environment": environment, "status": "diagnostics unavailable"})
                    (REPORTS / (label + "-diagnostics.json")).write_text(json.dumps(diagnostics, indent=2) + "\n")
                    print(json.dumps(diagnostics), flush=True)
                process.check_returncode()
                results[label] = recap(process.stdout)
                return results[label]

            apply("bootstrap", bootstrap=True)
            apply("first")
            second = apply("repeat")
            if any(host["changed"] for host in second.values()):
                raise RuntimeError("A repeat run changed the desired state")
            accepted = {
                environment: json.loads(ssh(
                    environment, "sudo", "-n", "cat",
                    f"/opt/auction-{environment}/state.json",
                ).stdout)["current"]
                for environment in ("test", "staging")
            }
            # A bootstrap pin must not roll back a release accepted by CD.
            # The nonexistent revision makes an unintended deployment fail.
            overrides["application_revision"] = "0" * 40
            (work / "overrides.json").write_text(json.dumps(overrides))
            preserved = apply("preserve-release")
            if any(host["changed"] for host in preserved.values()):
                raise RuntimeError("A different bootstrap pin changed an accepted release")
            for environment, release in accepted.items():
                current = json.loads(ssh(
                    environment, "sudo", "-n", "cat",
                    f"/opt/auction-{environment}/state.json",
                ).stdout)["current"]
                if current != release:
                    raise RuntimeError(f"Accepted release was replaced: {environment}")
            del overrides["application_revision"]
            (work / "overrides.json").write_text(json.dumps(overrides))
            state = json.loads(ssh("test", "sudo", "-n", "cat", "/opt/auction-test/state.json").stdout)
            ssh("test", "sudo", "-n", "sh", "-c",
                "printf 'ENVIRONMENT=broken\\n' > /etc/auction/environment; chmod 777 /opt/auction-test")
            ssh("test", "sudo", "-n", "docker", "stop", state["current"]["container"])
            repair = apply("repair")
            if repair["auction-test"]["changed"] == 0 or repair["auction-staging"]["changed"]:
                raise RuntimeError("Drift repair must change only the affected host")
            if ssh("test", "sudo", "-n", "stat", "-c", "%a", "/opt/auction-test").stdout.strip() != "700":
                raise RuntimeError("Directory permissions were not restored")
            if "ENVIRONMENT=test" not in ssh("test", "cat", "/etc/auction/environment").stdout:
                raise RuntimeError("Environment configuration was not restored")
            final = apply("final")
            if any(host["changed"] for host in final.values()):
                raise RuntimeError("Repaired configuration is not idempotent")
            results["status"] = "passed"
            print("Two Debian environments, repeat run and drift repair: passed")
        finally:
            (REPORTS / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
            for process, console in machines:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                console.close()


if __name__ == "__main__":
    main()
