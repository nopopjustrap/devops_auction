#!/usr/bin/env bash
set -euo pipefail
: "${STAGING_HOST:?Set staging environment variable STAGING_HOST}"
: "${STAGING_USER:?Set staging environment variable STAGING_USER}"
: "${STAGING_PORT_SSH:?Set staging environment variable STAGING_PORT_SSH}"
: "${STAGING_SSH_KEY:?Set staging environment secret STAGING_SSH_KEY}"
: "${STAGING_KNOWN_HOSTS:?Set staging environment secret STAGING_KNOWN_HOSTS}"
[[ "$STAGING_HOST" =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]]
[[ "$STAGING_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]
[[ "$STAGING_PORT_SSH" =~ ^[0-9]{1,5}$ ]]
[[ "$DELIVERY_ACTION" =~ ^(deploy|rollback|recover)$ ]]
[[ -z "$DELIVERY_TAG" || "$DELIVERY_TAG" =~ ^sha-[0-9a-f]{40}$ ]]
[[ "$GITHUB_RUN_ID" =~ ^[0-9]+$ && "$GITHUB_RUN_ATTEMPT" =~ ^[0-9]+$ ]]
mkdir -p reports
credentials=$(mktemp -d)
trap 'rm -rf "$credentials"' EXIT
chmod 700 "$credentials"
printf '%s\n' "$STAGING_SSH_KEY" > "$credentials/key"
printf '%s\n' "$STAGING_KNOWN_HOSTS" > "$credentials/known_hosts"
chmod 600 "$credentials/key" "$credentials/known_hosts"
options=(-i "$credentials/key" -o BatchMode=yes -o IdentitiesOnly=yes
         -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$credentials/known_hosts"
         -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
target="$STAGING_USER@$STAGING_HOST"
bundle="/opt/auction-staging/bundles/$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
ssh "${options[@]}" -p "$STAGING_PORT_SSH" "$target" "umask 077; mkdir -p '$bundle'"
scp "${options[@]}" -P "$STAGING_PORT_SSH" scripts/deploy.py scripts/release_check.py "$target:$bundle/"
# The fixed program and regex-validated arguments cannot inject remote shell commands.
ssh "${options[@]}" -p "$STAGING_PORT_SSH" "$target" \
    "python3 '$bundle/deploy.py' '$DELIVERY_ACTION' --tag '$DELIVERY_TAG'" \
    | tee reports/delivery.json
