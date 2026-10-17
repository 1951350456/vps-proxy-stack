"""Run only against the isolated Docker smoke deployment."""
import base64
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import yaml
import secrets
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime import ROOT, load
from provision import Panel

c = load()
panel = Panel(c)
panel.login(c)
rows = panel.call("panel/api/inbounds/list")
assert len(rows) == 2, "Repeated provisioning created duplicate nodes"
context = ssl.create_default_context(cafile=str(ROOT / "data/cert/fullchain.pem"))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
base = "https://127.0.0.1" + c["gateway_path"]
key = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
link = ("vless://00000000-0000-4000-8000-000000000001@203.0.113.10:8443"
        "?security=reality&type=tcp&pbk=" + key + "&sid=abcd&sni=www.example.com#Test")
request = urllib.request.Request(base + "api/convert", data=json.dumps({"links": link}).encode(),
                                 headers={"Content-Type": "application/json"})
with opener.open(request) as response:
    result = json.load(response)
with opener.open(base + result["path"]) as response:
    config = json.load(response)
assert config["proxies"][0]["uuid"] == "00000000-0000-4000-8000-000000000001"
try:
    opener.open(urllib.request.Request(base + "api/convert", data=b'{"links":"https://127.0.0.1/"}',
                headers={"Content-Type": "application/json"}))
    raise AssertionError("Remote URLs must be rejected")
except urllib.error.HTTPError as error:
    assert error.code == 400
with opener.open("https://127.0.0.1" + c["clash_path"] + c["sub_id"]) as response:
    native = yaml.safe_load(response.read())
# Validate the generated Xray configuration with the exact bundled core.
subprocess.run(["docker", "compose", "-p", "vps-proxy-stack", "exec", "-T", "panel", "sh", "-ec",
                'exec /app/bin/xray-linux-amd64 run -test -config /app/bin/config.json'], check=True, cwd=ROOT)
print("Verified: no duplicate nodes, HTTPS manual conversion, rejected remote URL, Xray configuration")

# Import the native YAML into a real Mihomo client and send traffic through each node.
native.update({"mixed-port": 17890, "bind-address": "127.0.0.1", "allow-lan": False,
               "external-controller": "127.0.0.1:19090", "secret": secrets.token_hex(16)})
client_dir = ROOT / "data/test-client"
client_dir.mkdir(mode=0o700, exist_ok=True)
(client_dir / "config.json").write_text(json.dumps(native))
subprocess.run(["docker", "run", "--rm", "-d", "--network", "host", "--name", "stack-test-client",
                "-v", str(client_dir) + ":/client", "metacubex/mihomo:v1.19.32",
                "-d", "/client", "-f", "/client/config.json"], check=True, stdout=subprocess.DEVNULL)
control = urllib.request.build_opener(urllib.request.ProxyHandler({}))
headers = {"Authorization": "Bearer " + native["secret"], "Content-Type": "application/json"}
deadline = time.monotonic() + 30
while True:
    try:
        control.open(urllib.request.Request("http://127.0.0.1:19090/version", headers=headers), timeout=3).close()
        break
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
try:
    for protocol in ("vless", "ss"):
        proxy = next(p for p in native["proxies"] if p["type"] == protocol)
        request = urllib.request.Request("http://127.0.0.1:19090/proxies/PROXY", method="PUT", headers=headers,
                                         data=json.dumps({"name": proxy["name"]}).encode())
        control.open(request, timeout=5).close()
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--max-time", "30",
                        "--noproxy", "", "--proxy", "socks5h://127.0.0.1:17890", "https://example.com", "-o", "/dev/null"], check=True)
        print("Verified real proxy traffic:", protocol)
finally:
    subprocess.run(["docker", "stop", "stack-test-client"], check=True, stdout=subprocess.DEVNULL)
