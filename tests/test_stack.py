import base64
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from runtime import initialize, nginx_config, validate_address
from provision import inbounds

spec = importlib.util.spec_from_file_location("gateway", ROOT / "gateway/server.py")
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


def node(name="Example"):
    key = base64.urlsafe_b64encode(bytes(range(32))).rstrip(b"=").decode()
    return ("vless://00000000-0000-4000-8000-000000000001@203.0.113.10:8443"
            "?type=tcp&security=reality&pbk=" + key + "&sid=abcd&sni=www.example.com"
            "&fp=chrome&flow=xtls-rprx-vision#" + name)


class ConversionTests(unittest.TestCase):
    def test_reality_config_and_escaped_name(self):
        config = json.loads(gateway.convert(node('name%22%3A%20%23special')))
        self.assertEqual(config["proxies"][0]["name"], 'name": #special')
        self.assertEqual(config["proxies"][0]["type"], "vless")
        self.assertEqual(config["proxy-groups"][0]["proxies"][0], 'name": #special')

    def test_sip002_preserves_case_password_and_ipv6(self):
        user = base64.urlsafe_b64encode(b"aes-128-gcm:MiXeD:secret").decode().rstrip("=")
        config = json.loads(gateway.convert("ss://" + user + "@[2001:db8::1]:8388#SS"))
        self.assertEqual(config["proxies"][0]["password"], "MiXeD:secret")
        self.assertEqual(config["proxies"][0]["server"], "2001:db8::1")

    def test_ss2022_multiuser(self):
        key = base64.b64encode(bytes(range(16))).decode()
        uri = f"ss://2022-blake3-aes-128-gcm:{key}:{key}@203.0.113.10:8388#SS"
        self.assertEqual(gateway.parse_node(uri)["password"], key + ":" + key)

    def test_unsupported_transports_and_bad_data_fail(self):
        cases = [node().replace("type=tcp", "type=ws"), node().replace("security=reality", "security=tls"),
                 node().replace("sid=abcd", "sid=abc"), node() + "\nvmess://unsupported",
                 node() + "\n" + node(), node("Proxy"), node().replace("sni=www.example.com", "sni="),
                 node().replace("type=tcp", "type=tcp&type=tcp"), "https://127.0.0.1/secret",
                 "ss://bad@[::1]:8388?plugin=obfs#SS", node("bad%0Aname")]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                gateway.convert(case)


class InitializationTests(unittest.TestCase):
    def test_independent_secrets_and_no_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = initialize("203.0.113.10", Path(tmp) / "first")
            second = initialize("203.0.113.10", Path(tmp) / "second")
            for key in ("password", "panel_path", "sub_id", "uuid", "reality_private", "ss_password"):
                self.assertNotEqual(first[key], second[key], key)
            self.assertEqual(first, initialize("203.0.113.10", Path(tmp) / "first"))
            self.assertEqual((Path(tmp) / "first/config.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(base64.b64decode(first["ss_password"])), 16)
            with self.assertRaises(ValueError):
                initialize("203.0.113.11", Path(tmp) / "first")

    def test_fail_on_noncanonical_or_invalid_ip(self):
        for value in ("999.1.1.1", "0203.0.113.10", "example.com", "203.0.113.10;id", "::1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_address(value)

    def test_nginx_routes_and_node_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = initialize("203.0.113.10", Path(tmp) / "state")
            rendered = nginx_config(c)
            self.assertIn("access_log off", rendered)
            for name in ("panel_path", "sub_path", "clash_path", "gateway_path"):
                self.assertIn("location ^~ " + c[name], rendered)
            generated = inbounds(c)
            reality = json.loads(generated[0]["settings"])
            self.assertEqual(reality["clients"][0]["id"], c["uuid"])
            for item in generated:
                self.assertEqual(json.loads(item["settings"])["clients"][0]["subId"], c["sub_id"])


if __name__ == "__main__":
    unittest.main()
