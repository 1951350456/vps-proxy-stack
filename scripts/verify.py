"""End-to-end panel login and HTTPS subscription checks; no TLS bypass."""
import argparse
import ssl
import time
import urllib.error
import urllib.request

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
        if b"proxies:" not in body or c["uuid"].encode() not in body or c["address"].encode() not in body:
            raise RuntimeError("Native Mihomo subscription did not contain the generated node")
        if b"shadowsocks" not in body and c["ss_password"].encode() not in body:
            raise RuntimeError("Native subscription did not contain Shadowsocks")
        if not response.headers.get("Subscription-Userinfo"):
            raise RuntimeError("Traffic metadata header is missing")
    with opener.open(base + c["gateway_path"], timeout=10) as response:
        if "生成 Mihomo 订阅".encode() not in response.read():
            raise RuntimeError("Converter page is unavailable")
    print("Verified: panel login, generated inbounds, HTTPS Mihomo subscription, traffic header, converter page")


if __name__ == "__main__":
    main()
