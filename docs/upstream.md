# Upstream references

Verified on 2026-10-17. Runtime interfaces are bound to the pinned 3x-ui release; upgrades need a smoke-test pass before changing `compose.yaml`.

| Component | Version / documentation ID | Primary sources |
| --- | --- | --- |
| 3x-ui | v3.10.2; Context7 `/mhsanaei/3x-ui` | [release](https://github.com/MHSanaei/3x-ui/releases/tag/v3.10.2), [CLI flags](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/main.go), [container](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/Dockerfile) |
| Panel API | v3.10.2 | [login / CSRF](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/web/controller/index.go), [inbounds](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/web/controller/inbound.go), [client model](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/database/model/model.go) |
| Native Clash/Mihomo export | v3.10.2 | [subscription controller](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/sub/controller.go), [setting keys](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/web/service/setting.go) |
| acme.sh | 3.1.6 | [release](https://github.com/acmesh-official/acme.sh/releases/tag/3.1.6), [Docker image](https://github.com/acmesh-official/acme.sh/blob/3.1.6/Dockerfile) |
| Docker / Compose | Compose v2 with `up --wait`; Context7 `/docker/docs` | [Debian installation](https://docs.docker.com/engine/install/debian/), [host network](https://docs.docker.com/engine/network/drivers/host/), [Compose specification](https://docs.docker.com/reference/compose-file/) |
| X25519 DER encoding | RFC 8410 | [PKCS#8 and SubjectPublicKeyInfo](https://www.rfc-editor.org/rfc/rfc8410) |
| Shadowsocks links | SIP002 | [URI scheme](https://shadowsocks.org/doc/sip002.html) |

The bootstrap uses the public upstream image, not a copy of any preconfigured panel. The only direct SQLite writes occur on a newly created, offline database to configure subscription listeners and paths which the upstream CLI does not expose. The expected settings schema is checked explicitly. Node creation uses the authenticated API with CSRF tokens.

The native subscription exporter replaces a separate subconverter daemon for panel-managed nodes. Manual conversion deliberately supports the two documented URI formats only. Unknown parameters, unsupported transports, duplicate names and invalid key lengths fail without silently rewriting the user's inputs.
