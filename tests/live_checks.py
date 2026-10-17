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
    (ROOT / "data/native.yaml").write_bytes(response.read())
# Validate the generated Xray configuration with the exact bundled core.
subprocess.run(["docker", "compose", "-p", "vps-proxy-stack", "exec", "-T", "panel", "sh", "-ec",
                'exec /app/bin/xray-linux-amd64 run -test -config /app/bin/config.json'], check=True, cwd=ROOT)
print("Verified: no duplicate nodes, HTTPS manual conversion, rejected remote URL, Xray configuration")
