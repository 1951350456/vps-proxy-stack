#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -e data ]]; then echo 'Smoke test requires a fresh checkout with no data/.' >&2; exit 2; fi
umask 077
apt-get update -qq
apt-get install -y --no-install-recommends python3-yaml
python3 scripts/runtime.py init 127.0.0.1
python3 scripts/runtime.py preflight
python3 scripts/runtime.py render
# The CI-only certificate is explicitly trusted by the test client, never used by deploy.sh.
openssl req -x509 -newkey rsa:2048 -nodes -days 2 \
  -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 \
  -keyout data/cert/privkey.pem -out data/cert/fullchain.pem 2>/dev/null
docker compose -p vps-proxy-stack pull panel web
docker compose -p vps-proxy-stack --profile tools pull acme
docker compose -p vps-proxy-stack run --rm acme --version
# Reproduce a checkout created under umask 077. The image must explicitly make
# program sources readable to its unprivileged runtime user.
chmod 600 gateway/server.py gateway/index.html
docker compose -p vps-proxy-stack build gateway
python3 scripts/runtime.py database
docker compose -p vps-proxy-stack up -d --wait gateway
docker compose -p vps-proxy-stack up -d panel
python3 scripts/provision.py
docker compose -p vps-proxy-stack run --rm --no-deps web nginx -t
docker compose -p vps-proxy-stack up -d web
python3 scripts/verify.py --ca data/cert/fullchain.pem
python3 tests/live_checks.py
# A second deployment must preserve both credentials and all panel changes.
cp data/config.json data/config.before.json
python3 scripts/runtime.py init 127.0.0.1
python3 scripts/runtime.py database
python3 scripts/provision.py
cmp data/config.json data/config.before.json
python3 tests/live_checks.py
docker compose -p vps-proxy-stack restart panel gateway web
docker compose -p vps-proxy-stack up -d --wait gateway
python3 scripts/verify.py --ca data/cert/fullchain.pem
