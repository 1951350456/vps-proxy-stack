"""Local configuration and lifecycle for a fresh 3x-ui v3.10.2 stack."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data"
PORTS = {"https": 443, "reality": 8443, "shadowsocks": 8388,
         "panel": 2053, "subscription": 2096, "gateway": 8000,
         "xray_api": 62789, "metrics": 11111}


def write_private(path, text):
    path = Path(path)
    with path.open("w", encoding="utf-8") as f:
        os.chmod(path, 0o600)
        f.write(text)


def load():
    return json.loads((STATE / "config.json").read_text())


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", "--project-directory", str(ROOT),
                           "-p", "vps-proxy-stack", *args], check=True, **kwargs)


def validate_address(value):
    # A public IPv4 is the only supported public endpoint in this release.
    ip = ipaddress.IPv4Address(value)
    if str(ip) != value:
        raise ValueError("Use a canonical IPv4 address")
    return value


def keypair():
    private_der = subprocess.check_output(
        ["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"])
    public_der = subprocess.check_output(
        ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
        input=private_der)
    # RFC 8410 X25519 PKCS#8 and SubjectPublicKeyInfo encodings.
    private_prefix = bytes.fromhex("302e020100300506032b656e04220420")
    public_prefix = bytes.fromhex("302a300506032b656e032100")
    if len(private_der) != 48 or not private_der.startswith(private_prefix):
        raise ValueError("Unexpected X25519 private key encoding")
    if len(public_der) != 44 or not public_der.startswith(public_prefix):
        raise ValueError("Unexpected X25519 public key encoding")
    encode = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return encode(private_der[len(private_prefix):]), encode(public_der[len(public_prefix):])


def initialize(address, state=STATE):
    validate_address(address)
    state = Path(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state / "config.json"
    if path.exists():
        c = json.loads(path.read_text())
        if c["address"] != address:
            raise ValueError("Address differs from saved configuration; use a fresh directory for a new server")
        return c
    if any(state.iterdir()):
        raise ValueError("data/ is nonempty without config.json; inspect it before continuing")
    private, public = keypair()
    c = {"schema": 1, "address": address, "ports": PORTS,
         "username": "admin_" + secrets.token_hex(4),
         "password": secrets.token_urlsafe(24),
         "panel_path": "/" + secrets.token_hex(16) + "/",
         "gateway_path": "/" + secrets.token_hex(16) + "/",
         "sub_path": "/" + secrets.token_hex(16) + "/",
         "clash_path": "/" + secrets.token_hex(16) + "/",
         "sub_id": secrets.token_hex(16), "uuid": str(uuid.uuid4()),
         "reality_private": private, "reality_public": public,
         "short_id": secrets.token_hex(8), "reality_sni": "www.microsoft.com",
         "ss_server_password": base64.b64encode(secrets.token_bytes(16)).decode(),
         "ss_password": base64.b64encode(secrets.token_bytes(16)).decode()}
    write_private(path, json.dumps(c, indent=2) + "\n")
    for name in ["db", "cert", "acme", "xray-logs", "conversions"]:
        (state / name).mkdir(mode=0o700)
    return c


def nginx_config(c):
    locations = []
    for key, backend in [("panel_path", c["ports"]["panel"]),
                         ("sub_path", c["ports"]["subscription"]),
                         ("clash_path", c["ports"]["subscription"])]:
        locations.append(f"""        location ^~ {c[key]} {{
            proxy_pass http://127.0.0.1:{backend};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
        }}""")
    locations.append(f"""        location ^~ {c['gateway_path']} {{
            limit_req zone=convert burst=10 nodelay;
            proxy_pass http://127.0.0.1:{c['ports']['gateway']}/;
            proxy_set_header Host $host;
        }}""")
    return """worker_processes auto;
error_log /dev/stderr warn;
pid /var/run/nginx.pid;
events { worker_connections 1024; }
http {
    # Subscription paths and panel paths are credentials. Never write them to access logs.
    access_log off;
    server_tokens off;
    client_max_body_size 64k;
    map $http_upgrade $connection_upgrade { default upgrade; '' close; }
    limit_req_zone $binary_remote_addr zone=convert:10m rate=2r/s;
    server {
        listen 443 ssl;
        ssl_certificate /cert/fullchain.pem;
        ssl_certificate_key /cert/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
""" + "\n".join(locations) + """
        location / { return 404; }
    }
}
"""


def configure_database(c):
    dbpath = STATE / "db/x-ui.db"
    marker = STATE / "database-configured"
    if marker.exists():
        if not dbpath.is_file():
            raise RuntimeError("Configured database is missing")
        return
    if dbpath.exists():
        raise RuntimeError("Unmarked database exists; inspect before retrying initialization")
    compose("run", "--rm", "--no-deps", "--entrypoint", "/app/x-ui", "panel",
            "setting", "-username", c["username"], "-password", c["password"],
            "-port", str(c["ports"]["panel"]), "-listenIP", "127.0.0.1",
            "-webBasePath", c["panel_path"])
    settings = {"subEnable": "true", "subListen": "127.0.0.1",
                "subPort": str(c["ports"]["subscription"]),
                "subPath": c["sub_path"], "subClashEnable": "true",
                "subClashPath": c["clash_path"], "subJsonEnable": "false",
                "subEncrypt": "true", "subURI": "https://" + c["address"] + c["sub_path"],
                "subClashURI": "https://" + c["address"] + c["clash_path"]}
    with sqlite3.connect(dbpath) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(settings)")}
        if not {"id", "key", "value"} <= columns:
            raise RuntimeError("Upstream settings schema changed")
        for key, value in settings.items():
            if db.execute("SELECT count(*) FROM settings WHERE key=?", (key,)).fetchone()[0] > 1:
                raise RuntimeError("Duplicate upstream setting")
            db.execute("DELETE FROM settings WHERE key=?", (key,))
            db.execute("INSERT INTO settings(key,value) VALUES (?,?)", (key, value))
    dbpath.chmod(0o600)
    write_private(marker, "3x-ui v3.10.2\n")


def preflight():
    # Only check free ports before the first launch. Health checks handle subsequent deployments.
    if (STATE / "deployed").exists():
        return
    for name, port in {"acme": 80, **PORTS}.items():
        for kind in [socket.SOCK_STREAM, socket.SOCK_DGRAM] if name == "shadowsocks" else [socket.SOCK_STREAM]:
            with socket.socket(socket.AF_INET, kind) as sock:
                try:
                    sock.bind(("0.0.0.0", port))
                except OSError as e:
                    raise RuntimeError(f"Required port {port} ({name}) is occupied") from e


def certificate(c, renew=False):
    cert = STATE / "cert/fullchain.pem"
    old = cert.read_bytes() if cert.exists() else None
    if renew:
        compose("run", "--rm", "acme", "--cron", "--home", "/acmebin", "--config-home", "/acme.sh")
        if cert.read_bytes() != old:
            compose("exec", "-T", "web", "nginx", "-s", "reload")
        return
    if cert.exists():
        subprocess.run(["openssl", "x509", "-in", str(cert), "-checkip", c["address"], "-noout"], check=True)
        subprocess.run(["openssl", "x509", "-in", str(cert), "-checkend", "86400", "-noout"], check=True)
        return
    compose("run", "--rm", "acme", "--issue", "--server", "letsencrypt",
            "--config-home", "/acme.sh", "-d", c["address"], "--standalone",
            "--keylength", "ec-256", "--cert-profile", "shortlived")
    compose("run", "--rm", "acme", "--install-cert", "--config-home", "/acme.sh",
            "-d", c["address"], "--ecc", "--fullchain-file", "/cert/fullchain.pem",
            "--key-file", "/cert/privkey.pem")


def show(c):
    print("Panel: https://" + c["address"] + c["panel_path"])
    print("Username: " + c["username"])
    print("Password: " + c["password"])
    print("Mihomo subscription: https://" + c["address"] + c["clash_path"] + c["sub_id"])
    print("Raw subscription: https://" + c["address"] + c["sub_path"] + c["sub_id"])
    print("Manual converter: https://" + c["address"] + c["gateway_path"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "preflight", "database", "cert", "renew", "show", "render"])
    parser.add_argument("address", nargs="?")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "init":
        initialize(args.address)
    elif args.action == "preflight":
        preflight()
    else:
        c = load()
        if args.action == "render":
            write_private(STATE / "nginx.conf", nginx_config(c))
            os.chown(STATE / "conversions", 65532, 65532)
        elif args.action == "database":
            configure_database(c)
        elif args.action in ("cert", "renew"):
            certificate(c, renew=args.action == "renew")
        elif args.action == "show":
            show(c)


if __name__ == "__main__":
    main()
