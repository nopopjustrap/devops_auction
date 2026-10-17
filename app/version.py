"""Release identity is baked into the image, never supplied at deployment time."""

import json
from pathlib import Path

APP_VERSION = "0.3.1"


def release_version() -> dict[str, str]:
    path = Path(__file__).with_name("build_info.json")
    revision = (
        json.loads(path.read_text())["revision"] if path.exists() else "development"
    )
    return {"version": APP_VERSION, "revision": revision}
