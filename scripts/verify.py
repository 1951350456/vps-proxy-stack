"""End-to-end panel login and HTTPS subscription checks; no TLS bypass."""
import argparse
import ssl
import time
import urllib.error
import urllib.request
import yaml

from provision import Panel
from runtime import load


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--ca", help="Explicit CA file for the isolated smoke test")
    options = args.parse_args()
    c = load()
    panel = Panel(c)
    panel.login(c)
    existing = panel.call("panel/api/inbounds/list")
    expected = {"stack-reality", "stack-shadowsocks"}
    if not expected <= {row["remark"] for row in existing if row["enable"]}:
        raise RuntimeError("Generated inbounds are missing or disabled")
    context = ssl.create_default_context(cafile=options.ca)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    base = "https://" + c["address"]
    deadline = time.monotonic() + 60
    while True:
        try:
            response = opener.open(base + c["panel_path"], timeout=10)
            response.close()
            break
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLError) or time.monotonic() >= deadline:
                raise
            time.sleep(1)
    with opener.open(base + c["clash_path"] + c["sub_id"], timeout=15) as response:
        body = response.read()
        document = yaml.safe_load(body)
        proxies = document["proxies"]
        reality = [p for p in proxies if p["type"] == "vless"]
        shadowsocks = [p for p in proxies if p["type"] == "ss"]
        if len(reality) != 1 or reality[0]["uuid"] != c["uuid"] or reality[0]["server"] != c["address"]:
            raise RuntimeError("Native Reality export differs from generated identity: " + str({
                "types": [p.get("type") for p in proxies],
                "uuid_matches": bool(reality) and reality[0].get("uuid") == c["uuid"],
                "address_matches": bool(reality) and reality[0].get("server") == c["address"]}))
        if len(shadowsocks) != 1 or shadowsocks[0]["password"] != c["ss_server_password"] + ":" + c["ss_password"]:
            raise RuntimeError("Native Shadowsocks export differs from generated identity")
        if not response.headers.get("Subscription-Userinfo"):
            raise RuntimeError("Traffic metadata header is missing")
    with opener.open(base + c["gateway_path"], timeout=10) as response:
        if "生成 Mihomo 订阅".encode() not in response.read():
            raise RuntimeError("Converter page is unavailable")
    print("Verified: panel login, generated inbounds, HTTPS Mihomo subscription, traffic header, converter page")


if __name__ == "__main__":
    main()
