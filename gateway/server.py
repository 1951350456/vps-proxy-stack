"""Strict VLESS Reality/TCP and SIP002 Shadowsocks conversion, with no URL fetching."""
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import urllib.parse
import uuid

MAX_BODY = 65536
DATA = Path(os.environ.get("CONVERSION_DIR", "/data"))
INDEX = Path(__file__).with_name("index.html")
CIPHERS = {"aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305",
           "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm",
           "2022-blake3-chacha20-poly1305"}


def decode64(value):
    if not re.fullmatch(r"[A-Za-z0-9_+/-]*={0,2}", value):
        raise ValueError("Invalid base64 characters")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except binascii.Error as e:
        raise ValueError("Invalid base64 encoding") from e


def parse_node(link):
    parsed = urllib.parse.urlsplit(link)
    if parsed.scheme not in {"vless", "ss"} or not parsed.hostname or not parsed.port:
        raise ValueError("Use a complete vless:// or SIP002 ss:// URI")
    if not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid port")
    name = urllib.parse.unquote(parsed.fragment) or "Node"
    if len(name) > 128 or any(ord(ch) < 32 for ch in name):
        raise ValueError("Invalid node name")
    node = {"name": name, "server": parsed.hostname, "port": parsed.port, "udp": True}
    q = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True) if parsed.query else {}
    if any(len(values) != 1 for values in q.values()):
        raise ValueError("Repeated URI parameters are unsupported")
    q = {key: values[0] for key, values in q.items()}
    if parsed.scheme == "vless":
        allowed = {"type", "security", "pbk", "sid", "sni", "fp", "flow", "spx", "encryption", "headerType"}
        if set(q) - allowed:
            raise ValueError("Unsupported VLESS parameter")
        if q.get("type", "tcp") != "tcp" or q.get("security") != "reality":
            raise ValueError("Manual VLESS conversion supports TCP + Reality only; use the panel's native export for other transports")
        if q.get("encryption", "none") != "none" or q.get("headerType", "none") != "none":
            raise ValueError("Unsupported VLESS encryption/header")
        identity = str(uuid.UUID(parsed.username or ""))
        if parsed.password is not None:
            raise ValueError("Unexpected password in VLESS URI")
        if len(decode64(q.get("pbk", ""))) != 32:
            raise ValueError("Reality public key must encode 32 bytes")
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}){0,8}", q.get("sid", "")):
            raise ValueError("Invalid Reality short ID")
        if not q.get("sni"):
            raise ValueError("Reality SNI is required")
        flow = q.get("flow", "")
        if flow not in {"", "xtls-rprx-vision"}:
            raise ValueError("Unsupported Reality flow")
        node.update(type="vless", uuid=identity, network="tcp", tls=True,
                    flow=flow, servername=q["sni"])
        node["client-fingerprint"] = q.get("fp", "chrome")
        node["reality-opts"] = {"public-key": q["pbk"], "short-id": q.get("sid", "")}
    else:
        if q:
            raise ValueError("Shadowsocks plugins and query parameters are unsupported")
        userinfo = urllib.parse.unquote(parsed.netloc.rsplit("@", 1)[0])
        # SIP002 specifies base64url userinfo, or plain userinfo for AEAD-2022.
        if ":" not in userinfo:
            userinfo = decode64(userinfo).decode("utf-8")
        method, sep, password = userinfo.partition(":")
        if not sep or not password or method not in CIPHERS:
            raise ValueError("Unsupported cipher or missing Shadowsocks password")
        if method.startswith("2022-"):
            size = 16 if method == "2022-blake3-aes-128-gcm" else 32
            if any(len(decode64(key)) != size for key in password.split(":")):
                raise ValueError("Invalid Shadowsocks-2022 key length")
        node.update(type="ss", cipher=method, password=password)
    return node


def convert(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or len(lines) > 100:
        raise ValueError("Provide between 1 and 100 node URIs")
    nodes = [parse_node(line) for line in lines]
    names = [node["name"] for node in nodes]
    if len(set(names)) != len(names) or set(names) & {"Proxy", "DIRECT", "REJECT"}:
        raise ValueError("Node names must be unique and cannot be Proxy, DIRECT or REJECT")
    config = {"mixed-port": 7890, "allow-lan": False, "mode": "rule",
              "proxies": nodes,
              "proxy-groups": [{"name": "Proxy", "type": "select", "proxies": names + ["DIRECT"]}],
              "rules": ["GEOIP,LAN,DIRECT", "GEOIP,CN,DIRECT", "MATCH,Proxy"]}
    # JSON is a strict subset of YAML 1.2. Serialization safely escapes quotes/newlines.
    return json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *_args):
        # Never log subscription paths, URIs or passwords.
        pass

    def respond(self, code, body, kind="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, b'{"status":"ok"}')
        elif self.path == "/":
            self.respond(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif re.fullmatch(r"/subscriptions/[0-9a-f]{48}\.yaml", self.path):
            path = DATA / self.path.rsplit("/", 1)[1]
            if path.is_file():
                self.respond(200, path.read_bytes(), "application/yaml; charset=utf-8")
            else:
                self.respond(404, b'{"error":"Not found"}')
        else:
            self.respond(404, b'{"error":"Not found"}')

    def do_POST(self):
        if self.path != "/api/convert":
            self.respond(404, b'{"error":"Not found"}')
            return
        if self.headers.get_content_type() != "application/json":
            self.respond(415, b'{"error":"Use application/json"}')
            return
        try:
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_BODY:
                self.respond(413, b'{"error":"Request must be 1-65536 bytes"}')
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or set(body) != {"links"} or not isinstance(body["links"], str):
                raise ValueError("Expected an object containing a links string")
            result = convert(body["links"])
        except (ValueError, TypeError, KeyError, UnicodeError) as e:
            self.respond(400, json.dumps({"error": str(e)}).encode())
            return
        if len(list(DATA.glob("*.yaml"))) >= 1000:
            self.respond(507, b'{"error":"Conversion quota reached; administrator must remove unused files"}')
            return
        token = secrets.token_hex(24)
        path = DATA / (token + ".yaml")
        with path.open("xb") as f:
            os.chmod(path, 0o600)
            f.write(result)
        self.respond(201, json.dumps({"path": "subscriptions/" + path.name}).encode())


if __name__ == "__main__":
    DATA.mkdir(mode=0o700, parents=True, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
