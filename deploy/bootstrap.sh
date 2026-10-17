#!/bin/sh
# Run once as an administrator on a DEDICATED staging VM with Docker installed.
set -eu
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo'; exit 1; }
command -v docker >/dev/null
command -v python3 >/dev/null
getent group docker >/dev/null
if ! id auction-deploy >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash auction-deploy
fi
usermod -aG docker auction-deploy
install -d -m 700 -o auction-deploy -g auction-deploy /opt/auction-staging
install -d -m 700 -o auction-deploy -g auction-deploy /home/auction-deploy/.ssh
printf '%s\n' 'Account ready. Install the dedicated public SSH key and staging.env as documented.'
