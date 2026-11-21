#!/bin/sh
# Run as root on the control host after bootstrap.yml has created auction-admin.
set -eu
test "$(id -u)" -eq 0
source_directory=$(CDPATH='' cd -- "$(dirname "$0")" && pwd)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl python3-venv git openssh-client make
install -d -m 755 /opt/auction-control
if [ ! -x /opt/auction-control/bootstrap/bin/python ]; then
    python3 -m venv /opt/auction-control/bootstrap
fi
/opt/auction-control/bootstrap/bin/python -m pip install 'uv==0.13.9'
export UV_PYTHON_INSTALL_DIR=/opt/auction-control/python
export UV_CACHE_DIR=/opt/auction-control/cache
uv_program=/opt/auction-control/bootstrap/bin/uv
"$uv_program" python install 3.13.18
if [ ! -x /opt/auction-control/venv/bin/python ]; then
    "$uv_program" venv --python 3.13.18 /opt/auction-control/venv
fi
"$uv_program" pip sync --python /opt/auction-control/venv/bin/python "$source_directory/requirements.lock"
for program in ansible ansible-playbook ansible-config ansible-inventory ansible-lint; do
    ln -sfn "/opt/auction-control/venv/bin/$program" "/usr/local/bin/$program"
done
if [ ! -f /home/auction-admin/.ssh/auction_infra ]; then
    runuser -u auction-admin -- ssh-keygen -q -t ed25519 -N '' \
        -f /home/auction-admin/.ssh/auction_infra -C auction-infra-controller
fi
ansible --version
