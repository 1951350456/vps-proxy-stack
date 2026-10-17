"""A deterministic release-file guard, complementary to secret scanning."""
import ipaddress
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BAD_SUFFIXES = {".db", ".pem", ".key", ".p12", ".zip", ".gz", ".sqlite", ".log"}
failures = []
for path in ROOT.rglob("*"):
    relative = path.relative_to(ROOT)
    if any(part in {".git", "__pycache__", ".venv"} for part in relative.parts) or not path.is_file():
        continue
    if relative.parts[0] in {"data", "backups"} or path.suffix in BAD_SUFFIXES or relative.name == ".env":
        failures.append(str(relative) + ": runtime/private artifact")
        continue
    text = path.read_text()
    if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        failures.append(str(relative) + ": private key")
    for candidate in re.findall(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", text):
        try:
            ip = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue  # Deliberately invalid IP fixtures are not real addresses.
        if not (ip.is_loopback or ip.is_unspecified or candidate.startswith(("203.0.113.", "192.0.2.", "198.51.100."))):
            failures.append(str(relative) + ": non-documentation IP address")
if failures:
    raise SystemExit("\n".join(failures))
print("Public file guard passed")
