"""Three targeted mutations in disposable copies; never edit the working tree."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MUTATIONS = [
    (
        "price-floor",
        "app/services.py",
        'if data.final_price < lot["starting_price"]:',
        "if False:",
        "tests/test_api.py::test_complete_sale_scenario",
    ),
    (
        "equal-price",
        "app/services.py",
        'if data.final_price < lot["starting_price"]:',
        'if data.final_price <= lot["starting_price"]:',
        "tests/test_lr3_api.py::test_sale_at_starting_price_and_rate_boundaries",
    ),
    (
        "commission-rounding",
        "app/finance.py",
        "(price_kopecks * rate_bps + 5000) // 10000",
        "(price_kopecks * rate_bps) // 10000",
        "tests/test_unit.py::test_commission_rounding_and_boundaries",
    ),
]


def main() -> int:
    results = []
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTEST_ADDOPTS", "COVERAGE_PROCESS_START"):
        env.pop(key, None)
    for name, filename, original, replacement, test in MUTATIONS:
        with tempfile.TemporaryDirectory(prefix="auction-mutant-") as directory:
            work = Path(directory)
            for folder in ("app", "tests", "migrations"):
                shutil.copytree(
                    ROOT / folder,
                    work / folder,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            for filename_config in ("alembic.ini", "pytest.ini", "pyproject.toml"):
                shutil.copy2(ROOT / filename_config, work / filename_config)
            path = work / filename
            code = path.read_text()
            if code.count(original) != 1:
                raise RuntimeError(f"{name}: expected exactly one mutation location")

            # Baseline must pass the same selected tests; collection errors are not kills.
            def run():
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        test,
                        "--junitxml=result.xml",
                    ],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=90,
                )
                xml = ET.parse(work / "result.xml").getroot()
                return result, xml

            baseline, _ = run()
            if baseline.returncode != 0:
                raise RuntimeError(
                    f"{name}: baseline failed\n{baseline.stdout}\n{baseline.stderr}"
                )
            path.write_text(code.replace(original, replacement))
            # Avoid reusing bytecode when a same-size edit happens in the same second.
            for cache in work.rglob("__pycache__"):
                shutil.rmtree(cache)
            result, xml = run()
            failures, errors = (
                len(xml.findall(".//failure")),
                len(xml.findall(".//error")),
            )
            killed = result.returncode == 1 and failures > 0 and errors == 0
            results.append(
                {
                    "mutation": name,
                    "killed": killed,
                    "test": test,
                    "assertion_failures": failures,
                    "errors": errors,
                }
            )
            print(f"{name}: {'detected' if killed else 'NOT detected'}")
    output = ROOT / "reports/mutations.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    return 0 if all(r["killed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
