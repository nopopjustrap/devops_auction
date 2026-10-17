#!/bin/sh
set -eu
: "${IMAGE:?Set IMAGE to the image being tested}"
mkdir -p reports
container="auction-smoke-$$"
cleanup() {
    docker logs "$container" > reports/container.log 2>&1 || true
    docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
docker run -d --name "$container" --read-only --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --tmpfs /data:rw,nosuid,size=32m,uid=10001,gid=10001 \
    "$IMAGE" >/dev/null
docker exec "$container" python -c '
import os, time, urllib.request
assert os.getuid() == 10001, "Container must run as non-root"
for attempt in range(30):
    try:
        for path in ("/health", "/ready", "/"):
            with urllib.request.urlopen("http://127.0.0.1:8000" + path, timeout=2) as r:
                assert r.status == 200
        print("Container smoke passed: non-root, health, ready, UI")
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("Container did not become ready")
' > reports/container-smoke.txt
cat reports/container-smoke.txt
