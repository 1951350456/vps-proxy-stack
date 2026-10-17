"""Provision generated identities through the pinned panel's authenticated API."""
import http.cookiejar
import json
import time
import urllib.error
import urllib.request

from runtime import STATE, load, write_private


class Panel:
    def __init__(self, config):
        self.base = f"http://127.0.0.1:{config['ports']['panel']}{config['panel_path']}"
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = None

    def call(self, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.base + path,
                                        data=None if body is None else json.dumps(body).encode(),
                                        headers=headers)
        with self.opener.open(request, timeout=10) as response:
            result = json.load(response)
        if result.get("success") is not True:
            raise RuntimeError(f"Panel rejected {path}: {result.get('msg', 'unknown error')}")
        return result.get("obj")

    def login(self, config):
        deadline = time.monotonic() + 60
        while True:
            try:
                self.csrf = self.call("csrf-token")
                break
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                # Startup readiness has a fixed deadline; protocol/API errors fail immediately.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        self.call("login", {"username": config["username"], "password": config["password"]})
        self.csrf = self.call("csrf-token")


def inbounds(c):
    common = {"enable": True, "expiryTime": 0, "total": 0, "listen": "0.0.0.0",
              "shareAddrStrategy": "custom", "shareAddr": c["address"],
              "sniffing": json.dumps({"enabled": True, "destOverride": ["http", "tls", "quic"],
                                       "routeOnly": True})}
    client = {"enable": True, "expiryTime": 0, "totalGB": 0, "limitIp": 0,
              "subId": c["sub_id"], "tgId": 0, "reset": 0}
    reality = {**common, "remark": "stack-reality", "port": c["ports"]["reality"],
               "protocol": "vless",
               "settings": json.dumps({"clients": [{**client, "id": c["uuid"],
                   "email": "stack-reality", "flow": "xtls-rprx-vision"}], "decryption": "none"}),
               "streamSettings": json.dumps({"network": "tcp", "security": "reality",
                   "realitySettings": {"show": False, "dest": c["reality_sni"] + ":443",
                       "xver": 0, "serverNames": [c["reality_sni"]],
                       "privateKey": c["reality_private"], "shortIds": [c["short_id"]],
                       "settings": {"publicKey": c["reality_public"], "fingerprint": "chrome",
                                    "serverName": c["reality_sni"], "spiderX": "/"}}})}
    ss = {**common, "remark": "stack-shadowsocks", "port": c["ports"]["shadowsocks"],
          "protocol": "shadowsocks",
          "settings": json.dumps({"method": "2022-blake3-aes-128-gcm",
              "password": c["ss_server_password"], "network": "tcp,udp",
              "clients": [{**client, "email": "stack-shadowsocks", "method": "2022-blake3-aes-128-gcm",
                           "password": c["ss_password"]}]}),
          "streamSettings": json.dumps({"network": "tcp", "security": "none",
                                        "tcpSettings": {"header": {"type": "none"}}})}
    return [reality, ss]


def provision():
    c = load()
    panel = Panel(c)
    panel.login(c)
    if (STATE / "provisioned").exists():
        return
    existing = panel.call("panel/api/inbounds/list")
    for expected in inbounds(c):
        found = [x for x in existing if x["remark"] == expected["remark"]]
        if found:
            # Exact identity checks allow resuming an interrupted first provisioning.
            if len(found) != 1 or found[0]["port"] != expected["port"] or found[0]["protocol"] != expected["protocol"]:
                raise RuntimeError("Generated inbound conflicts with an existing inbound")
            stored = json.loads(found[0]["settings"])
            wanted = json.loads(expected["settings"])
            if stored["clients"][0]["subId"] != c["sub_id"]:
                raise RuntimeError("Existing inbound belongs to a different generated identity")
            for key in ("id", "password"):
                if stored["clients"][0].get(key) != wanted["clients"][0].get(key):
                    raise RuntimeError("Existing inbound identity differs")
            continue
        panel.call("panel/api/inbounds/add", expected)
    write_private(STATE / "provisioned", "3x-ui v3.10.2\n")


if __name__ == "__main__":
    provision()
