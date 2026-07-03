# WebFetch Service

WebFetch 是一个供多个业务系统共用的网页抓取基础服务。业务系统通过 REST API 请求网页，不需要各自维护 HTTP 客户端、浏览器、缓存、重试、限速和解析代码。

首版提供普通 HTTP 抓取、可选 Playwright 浏览器抓取、自动策略升级、缓存、请求合并、域名限速、持久任务、原始文件保存和通用新闻内容提取。

## 系统介绍

主要执行路径：

```text
业务系统 → WebFetch API → 缓存/去重 → HTTP 或 Browser Worker
                                ├→ PostgreSQL 任务
                                ├→ Redis 缓存
                                └→ Ubuntu artifact 文件
```

安全边界包括 API Key、逐跳 SSRF 校验、响应大小限制、敏感头脱敏以及隔离的浏览器 Context。WebFetch 不提供验证码破解，也不用于绕过付费墙或访问控制。

详细文档：

- [需求规格说明书](docs/webfetch-service-srs.md)
- [设计说明书](docs/webfetch-service-design.md)
- [PostgreSQL 初始化脚本](sql/init-postgresql.sql)

## 页面介绍

本项目没有独立管理前端，FastAPI 自动提供以下页面：

- `/docs`：Swagger UI，可查看和调试 API；
- `/redoc`：ReDoc API 文档；
- `/openapi.json`：OpenAPI 契约；
- `/metrics`：Prometheus 指标；
- `/health/live`：进程存活检查；
- `/health/ready`：数据库、缓存和文件存储就绪检查。

业务接口均位于 `/v1` 下，除健康检查和指标外需携带：

```http
Authorization: Bearer <API_KEY>
```

## 主要接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/fetch` | 同步抓取网页 |
| POST | `/v1/jobs` | 创建异步批量任务 |
| GET | `/v1/jobs/{job_id}` | 查询任务 |
| POST | `/v1/jobs/{job_id}/cancel` | 取消排队任务 |
| POST | `/v1/extract` | 抓取并解析或重新解析 artifact |
| GET | `/v1/artifacts/{artifact_id}` | 读取原始响应 |

抓取示例：

```bash
curl -X POST 'http://server-host:33333/v1/fetch' \
  -H 'Authorization: Bearer replace-api-key' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","mode":"http"}'
```

`mode` 支持：

- `http`：只使用 HTTP 客户端；
- `browser`：只使用 Playwright；
- `auto`：先 HTTP，根据状态码、挑战页特征和关键选择器决定是否升级浏览器。

## 配置文件说明

所有配置使用 `WEBFETCH_` 前缀环境变量，层级以双下划线分隔。完整模板见 [.env.example](.env.example)。

关键配置：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `WEBFETCH_SERVER__HOST` | `127.0.0.1` | 监听地址 |
| `WEBFETCH_SERVER__PORT` | `33333` | 服务端口 |
| `WEBFETCH_AUTH__BOOTSTRAP_API_KEY` | 无生产默认值 | API Key，生产环境必须替换 |
| `WEBFETCH_DATABASE__URL` | 本地 SQLite 开发值 | 生产 PostgreSQL 异步连接 URL |
| `WEBFETCH_REDIS__URL` | 未启用 | Redis URL |
| `WEBFETCH_STORAGE__ARTIFACT_ROOT` | `./data/artifacts` | 原始文件目录 |
| `WEBFETCH_PROXY__HTTP_URL` | 空 | 可选 HTTP 代理 |
| `WEBFETCH_BROWSER__ENABLED` | `false` | 是否启用 Playwright |
| `WEBFETCH_FETCH__MAX_RESPONSE_BYTES` | `10485760` | 最大响应字节数 |
| `WEBFETCH_SECURITY__ALLOWED_HOSTS` | `[]` | 显式放行的内网主机 |

真实 `.env`、密码、Cookie 和 API Key 不得提交到 Git。

## 本地开发

要求 Python 3.11 以上：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check src tests
```

本地启动：

```bash
cp .env.example .env
# 修改 .env，至少替换 API Key 和数据库配置
alembic upgrade head
webfetch-api
```

需要浏览器抓取时：

```bash
pip install -e '.[browser]'
playwright install chromium
```

## Linux 原生部署

目标系统为 Ubuntu Server 24.04，不使用 Docker。

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv redis-server postgresql-client rsync curl
sudo systemctl enable --now redis-server
```

Playwright 所需系统库可以在部署前执行：

```bash
sudo python3 -m playwright install-deps chromium
```

### 2. 初始化 PostgreSQL

在具有建库权限的 PostgreSQL 管理连接上运行：

```bash
psql -h database-host -U postgres \
  -v webfetch_password='replace-with-strong-password' \
  -f sql/init-postgresql.sql
```

脚本可重复执行，并会创建或更新独立的 `webfetch` 用户和数据库。

### 3. 创建服务用户和配置

```bash
sudo useradd --system --home /var/lib/webfetch --shell /usr/sbin/nologin webfetch
sudo install -d -m 0750 -o root -g webfetch /etc/webfetch
sudo cp .env.example /etc/webfetch/service.env
sudo chmod 0640 /etc/webfetch/service.env
sudo editor /etc/webfetch/service.env
```

### 4. 发布

```bash
sudo bash scripts/install-native.sh "$PWD" /opt/webfetch webfetch
```

安装脚本会创建版本目录、安装 Python 依赖、执行 Alembic、安装 systemd 单元、启动服务并检查 Ready 状态。失败时会尝试切回上一版本。

## 运维方式

```bash
systemctl status webfetch-api
systemctl status webfetch-http-worker
systemctl status webfetch-browser-worker
journalctl -u webfetch-api -f
systemctl restart webfetch-api webfetch-http-worker webfetch-browser-worker
systemctl list-timers webfetch-maintenance.timer
```

部署进程：

- `webfetch-api`：同步 API；
- `webfetch-http-worker`：只领取显式 HTTP 任务；
- `webfetch-browser-worker`：领取 `auto` 和 `browser` 任务；
- `webfetch-maintenance.timer`：清理遗留临时文件。

备份至少包含 PostgreSQL `webfetch` 数据库、`/etc/webfetch/service.env` 的安全副本和 artifact 目录。配置副本必须按密钥材料管理。

## 访问方式

默认端口为 `33333`，可通过环境变量修改。服务初始定位为内网访问：

```text
http://<linux-server>:33333/docs
http://<linux-server>:33333/health/ready
```

若后续配置 Nginx 或 Cloudflare Tunnel，应在反向代理层启用 TLS、限制管理路径，并继续保留 API Key 认证。代理配置由部署环境维护，不写入本仓库代码。

## Jenkins

Pipeline 文件位于 [src/JenkinsConfig/Jenkinsfile](src/JenkinsConfig/Jenkinsfile)。任务应配置为 `Pipeline script from SCM`，仓库使用 SSH 地址，脚本路径填写：

```text
src/JenkinsConfig/Jenkinsfile
```

Pipeline 每 30 分钟轮询 SCM；只有存在新提交时触发。流水线执行检出、依赖安装、静态检查、覆盖率不低于 80% 的测试、原生发布和健康检查。Jenkins 运行用户需要对限定的部署脚本和相关 systemd 服务拥有 sudo 权限。

## 测试

```bash
pytest --cov=webfetch_service --cov-fail-under=80
ruff check src tests
```

测试使用 MockTransport、本地 ASGI 和临时目录，不访问真实媒体网站。真实网站兼容性应通过经批准的预发布冒烟任务验证，避免 CI 对外站产生重复流量。
