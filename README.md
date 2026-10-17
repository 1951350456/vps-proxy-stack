# VPS Proxy Stack

[![Verify clean deployment](https://github.com/1951350456/vps-proxy-stack/actions/workflows/ci.yml/badge.svg)](https://github.com/1951350456/vps-proxy-stack/actions/workflows/ci.yml)

从零部署自己的 3x-ui、VLESS Reality、Shadowsocks 和 HTTPS 订阅。无需复制任何现成服务器的数据库或密钥。

## 一键部署

准备一台 **Debian 12、amd64 或 arm64、带独立公网 IPv4** 的服务器。先在云厂商安全组中放行：

| 端口 | 用途 |
| --- | --- |
| TCP 80 | Let's Encrypt IP 证书签发和续期，需持续开放 |
| TCP 443 | HTTPS 面板、订阅、手动转换页 |
| TCP 8443 | VLESS Reality |
| TCP / UDP 8388 | Shadowsocks-2022 |

保留你当前使用的 SSH 端口。脚本不修改 SSH、root 密码或防火墙规则。

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/1951350456/vps-proxy-stack.git
cd vps-proxy-stack
sudo bash deploy.sh 你的公网IPv4
```

脚本会从 Docker 官方 Debian 软件源安装缺少的 Docker，下载固定版本的 3x-ui，签发公网 IP 的短期证书，生成全新的账号、节点身份和订阅地址，并启动服务。首次执行需要联网下载镜像，TCP 80 必须从公网可达。

部署成功后会打印面板地址、随机用户名及密码、**Mihomo 订阅链接**和转换页面地址。将 Mihomo 链接导入 Clash Verge Rev / Mihomo 客户端即可使用两个自动创建的节点。

没有共享默认密码。首次生成的状态保存在 `data/`，文件权限受限；后续执行不会重新生成身份，也不会覆盖你在面板中修改过的节点。

## 功能

- 官方 3x-ui **v3.10.2** 镜像，可在面板添加其他协议和节点。
- 自动创建 VLESS Reality / XTLS Vision 节点和 Shadowsocks-2022 AES-128-GCM 节点，各自使用新的随机凭据。
- 面板原生 Mihomo 订阅同步节点变更及流量信息，不需要把订阅交给公共转换网站。
- HTTPS 手动转换页支持 **VLESS Reality TCP** 和 **SIP002 Shadowsocks**，生成独立的静态订阅；不支持的参数直接报错。
- acme.sh **3.1.6** 为公网 IPv4 申请 Let's Encrypt `shortlived` 证书，systemd 每六小时检查续期，证书更新后重载 nginx。
- 数据、证书、ACME 账户、转换记录均与源码分离；容器日志轮转，不记录订阅访问路径。

手动转换生成的文件采用 JSON 序列化，属于 YAML 1.2 的有效子集，Mihomo 可直接读取。静态转换不会同步面板流量和后续编辑；日常使用优先选原生 Mihomo 订阅。

## 日常管理

在本项目目录执行：

```bash
sudo bash deploy.sh show       # 显示本机生成的登录和订阅信息
sudo bash deploy.sh status     # 查看服务状态
sudo bash deploy.sh renew      # 立即检查证书续期
sudo docker compose -p vps-proxy-stack logs --tail=100 panel
sudo systemctl status vps-proxy-stack-renew.timer
sudo journalctl -u vps-proxy-stack-renew.service -n 50
```

`show` 展示的是初次生成的凭据。如果你在面板更改了用户名或密码，以面板中的新值为准；重新运行部署时的登录验证也需要同步更新本机 `data/config.json` 中的用户名、密码。

重复执行 `sudo bash deploy.sh 原公网IPv4` 会复用数据和身份。单台主机仅支持一个实例，不能与占用相同端口的服务同时运行。公网 IP 改变时，请在新目录部署并重新导入新订阅；当前版本不自动改写已有服务器配置。

添加新协议或新监听端口后，需要自行在安全组开放对应端口。容器使用 Linux host 网络，不使用 privileged 模式，不挂载主机 cgroup 或 Docker socket；面板和转换后端只监听 loopback，公网由 nginx 提供 HTTPS。

## 备份与迁移

完整的 `data/` 含全部身份和私钥，应当像密码一样保管。请在维护窗口停止服务再备份，避免 SQLite 写入中的不一致：

```bash
sudo systemctl stop vps-proxy-stack-renew.timer
sudo docker compose -p vps-proxy-stack down
sudo install -d -m 700 backups
sudo tar -czf backups/private-state.tar.gz data
sudo chmod 600 backups/private-state.tar.gz
sudo docker compose -p vps-proxy-stack up -d panel gateway web
sudo systemctl start vps-proxy-stack-renew.timer
```

备份目录已加入 `.gitignore`。请另行保存到你控制的安全位置。迁移到不同公网 IP 时，推荐重新部署并通过面板显式导入需要的配置，而不是直接替换数据库里的字节。

## 故障处理

- **证书申请失败**：检查公网 IP、TCP 80、安全组、端口占用及 Let's Encrypt 限流。脚本会停止，不会静默切换为自签名证书。
- **端口已占用**：部署前检查 TCP 80 / 443 / 8443 / 8388 / 2053 / 2096 / 8000 / 62789 / 11111，以及 UDP 8388；不要盲目停止未知服务。
- **Reality 节点连不上**：检查 TCP 8443、安全组，以及服务器是否能连接配置的 Reality 目标 `www.microsoft.com:443`。如目标不可达，在面板中选择适合你网络的目标和 SNI，并重新导出订阅。
- **初始化中断**：先检查报错和 `data/`。配置文件存在时会复用凭据；数据库存在但缺少初始化标记时会明确拒绝继续，以免误覆盖数据。对于从未使用过的新部署，可在保留备份后换一个干净目录重新开始。
- **证书接近过期**：先运行 `renew`，检查续期服务日志。证书有效期短，停止定时器或关闭 TCP 80 会影响续期。
- **转换数量已达上限**：每台服务器最多保存 1000 个静态转换文件。删除 `data/conversions/` 内不再使用的 `.yaml` 即可；对应旧链接会失效。

## 测试与发布边界

```bash
python3 -m unittest discover -s tests -v
bash -n deploy.sh tests/smoke.sh
python3 scripts/audit_public.py
```

单元测试中的密钥生成需要 OpenSSL 3。GitHub Actions 另在全新的 Linux Docker 环境中验证数据库初始化、API 创建节点、HTTPS 原生订阅、转换接口、重复运行和重启，并使用 Mihomo v1.19.32 分别经 Reality 与 Shadowsocks 请求真实 HTTPS 网页。隔离测试使用显式信任的临时测试证书；生产脚本只使用 Let's Encrypt 证书。

CI 不会实际向 Let's Encrypt 申请证书，也不等于已经验证你所在网络到代理节点的连接。首次真实服务器部署仍须完成公网证书签发及客户端连接验证。

公开仓库仅包含源码、示例和测试。数据库、证书、账户、私钥、运行日志、压缩资产和私人历史均不属于发布内容。修改后发布前运行文件检查，并人工检查新增文件；`.gitignore` 不能移除已经提交到 Git 历史的秘密。

## 上游与许可

本项目自己的部署脚本和网关采用 [MIT](LICENSE) 许可。3x-ui、Xray-core、nginx、Python 和 acme.sh 保持各自的许可；本仓库不打包其二进制或已有服务器文件。版本和接口依据见 [docs/upstream.md](docs/upstream.md)。
