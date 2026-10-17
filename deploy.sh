#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077

usage() {
    cat <<'EOF'
Usage: sudo bash deploy.sh PUBLIC_IPV4
       sudo bash deploy.sh show
       sudo bash deploy.sh renew
       sudo bash deploy.sh status
Fresh server: Debian 12, amd64 or arm64, public IPv4.
Allow inbound TCP 80,443,8443,8388 and UDP 8388 in the provider firewall.
EOF
}
if [[ $# -ne 1 ]]; then usage >&2; exit 2; fi
if [[ $1 == --help || $1 == -h ]]; then usage; exit 0; fi
if [[ $(id -u) -ne 0 ]]; then echo 'Run with sudo or as root.' >&2; exit 2; fi
if [[ $(uname -s) != Linux ]]; then echo 'Deployment requires Linux.' >&2; exit 2; fi

case "$1" in
    show) exec python3 scripts/runtime.py show ;;
    renew) exec python3 scripts/runtime.py renew ;;
    status) exec docker compose -p vps-proxy-stack ps ;;
esac

# Fail before making host changes on an unsupported system.
# shellcheck source=/dev/null
. /etc/os-release
if [[ $ID != debian || $VERSION_ID != 12 ]]; then
    echo 'This release supports Debian 12 only.' >&2; exit 2
fi
case "$(dpkg --print-architecture)" in amd64|arm64) ;; *) echo 'Use amd64 or arm64.' >&2; exit 2 ;; esac
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl python3 openssl iproute2
python3 - "$1" <<'PY'
import ipaddress, sys
ip = ipaddress.IPv4Address(sys.argv[1])
if str(ip) != sys.argv[1] or not ip.is_global:
    raise SystemExit('A canonical public IPv4 address is required.')
PY
if ! command -v docker >/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl --fail --show-error --silent --location https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable\n' "$(dpkg --print-architecture)" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
fi
docker compose version
docker info >/dev/null
python3 scripts/runtime.py init "$1"
python3 scripts/runtime.py preflight
docker compose -p vps-proxy-stack config --quiet
docker compose -p vps-proxy-stack --profile tools pull
docker compose -p vps-proxy-stack build --pull gateway
python3 scripts/runtime.py render
python3 scripts/runtime.py cert
python3 scripts/runtime.py database
docker compose -p vps-proxy-stack up -d --wait gateway
docker compose -p vps-proxy-stack up -d panel
python3 scripts/provision.py
docker compose -p vps-proxy-stack run --rm --no-deps web nginx -t
docker compose -p vps-proxy-stack up -d web
python3 scripts/verify.py

# Keep renewal tied to this checkout. No Docker socket is mounted in any container.
python3 - <<'PY'
from pathlib import Path
root = Path.cwd()
if any(ch in str(root) for ch in '\n\r%"\\'):
    raise SystemExit('Checkout path contains unsupported systemd characters')
Path('/etc/systemd/system/vps-proxy-stack-renew.service').write_text(f'''[Unit]
Description=Renew VPS Proxy Stack IP certificate
Requires=docker.service
After=docker.service network-online.target
[Service]
Type=oneshot
WorkingDirectory="{root}"
ExecStart=/usr/bin/python3 "{root}/scripts/runtime.py" renew
''')
Path('/etc/systemd/system/vps-proxy-stack-renew.timer').write_text('''[Unit]
Description=Check the short-lived IP certificate every six hours
[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
RandomizedDelaySec=15min
Persistent=true
[Install]
WantedBy=timers.target
''')
PY
systemctl daemon-reload
systemctl enable --now vps-proxy-stack-renew.timer
install -m 0600 /dev/null data/deployed
python3 scripts/runtime.py show
