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

### API Key 给谁使用

API Key 是发放给调用 WebFetch 的下游业务系统使用的服务端凭据，不是网页目标站点的登录密码。下游系统调用 `/v1` 业务接口时，将 Key 放入 `Authorization: Bearer <API_KEY>` 请求头。

当前版本使用一个共享的 bootstrap API Key。Ubuntu 服务器上的明文 Key 保存在 `/etc/webfetch/api-key`，可由服务器管理员读取：

```bash
sudo cat /etc/webfetch/api-key
```

下游系统应通过环境变量或自身的密钥管理功能保存该值，不得硬编码、写入日志或提交到 Git。若 Key 泄露，应在 `/etc/webfetch/service.env` 中更新 `WEBFETCH_AUTH__BOOTSTRAP_API_KEY`，同步更新 `/etc/webfetch/api-key`，再重启 WebFetch 服务及更新下游系统配置。规划中的调用方管理能力会为每个下游系统签发独立 Key，以支持单独吊销、限流和审计；该能力尚未在当前版本开放。

## 主要接口

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/v1/fetch` | 同步抓取网页 |
| POST | `/v1/jobs` | 创建异步批量任务 |
| GET | `/v1/jobs/{job_id}` | 查询任务 |
| POST | `/v1/jobs/{job_id}/cancel` | 取消排队任务 |
| POST | `/v1/extract` | 抓取并解析或重新解析 artifact |
| GET | `/v1/artifacts/{artifact_id}` | 读取原始响应 |

人物履历页面可指定 `china.official-profile` 适配器，输出 `summary`、`current_position` 和结构化 `timeline`。

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

需要继续调用 `generic.links`、`generic.article` 等提取适配器时，请设置 `save_artifact: true`。缓存键会区分 `save_artifact` 的 `null`、`false`、`true` 三种状态，保证要求保存 artifact 的请求不会复用缺少 `artifact_id` 的缓存结果。

## 配置文件说明

所有配置使用 `WEBFETCH_` 前缀环境变量，层级以双下划线分隔。完整模板见 [.env.example](.env.example)。

当前 Ubuntu 部署的主配置文件是 `/etc/webfetch/service.env`；单独供管理员读取和分发的 API Key 文件是 `/etc/webfetch/api-key`。两者均为服务器本地的权限受限文件。

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

也可以使用辅助脚本自动生成随机服务密码，并把密码写入权限受限的指定文件：

```bash
scripts/bootstrap_database.sh database-host 5432 admin-user admin-password \
  sql/init-postgresql.sql /secure/path/webfetch-db-password
```

### 3. 创建服务用户和配置

```bash
sudo useradd --system --home /var/lib/webfetch --shell /usr/sbin/nologin webfetch
sudo install -d -m 0750 -o root -g webfetch /etc/webfetch
sudo cp .env.example /etc/webfetch/service.env
sudo chmod 0640 /etc/webfetch/service.env
sudo editor /etc/webfetch/service.env
```

仓库也提供参数化初始化脚本。它会创建服务用户、生成随机 API Key、写入权限受限的配置文件并启动 Redis：

```bash
sudo scripts/configure_server.sh database-host 5432 /secure/path/webfetch-db-password
```

### 4. 发布

```bash
sudo bash scripts/install-native.sh "$PWD" /opt/webfetch webfetch
```

安装脚本会创建版本目录、安装 Python 依赖、执行 Alembic、安装 systemd 单元、启动服务并检查 Ready 状态。失败时会尝试切回上一版本。

### 5. 服务器目录结构

标准部署在 Ubuntu 服务器上使用以下目录结构：

```text
/opt/webfetch/
├── current -> releases/<当前发布版本>   当前运行版本的软链接
└── releases/                           Jenkins/安装脚本生成的版本目录
    ├── <历史发布版本>/
    └── <当前发布版本>/
        ├── .venv/                      当前版本独立 Python 虚拟环境
        ├── src/                        应用源码
        ├── migrations/                 数据库迁移
        ├── scripts/                    运维及测试脚本
        ├── sql/                        数据库初始化脚本
        ├── docs/                       需求和设计文档
        └── README.md

/etc/webfetch/
├── service.env                         主配置及服务端密钥，root:webfetch 0640
└── api-key                            供管理员向下游分发的 API Key，root:webfetch 0640

/var/lib/webfetch/
├── artifacts/                          抓取结果及原始响应文件
├── .cache/ms-playwright/               Playwright 浏览器文件
└── .local/                             webfetch 服务用户运行数据

/etc/systemd/system/
├── webfetch-api.service
├── webfetch-http-worker.service
└── webfetch-browser-worker.service

/usr/local/bin/webfetch-launch          systemd 统一启动入口
/usr/local/sbin/webfetch-jenkins-deploy Jenkins 受限部署入口
/etc/sudoers.d/webfetch-jenkins         Jenkins 最小 sudo 权限规则
```

`/opt/webfetch/current` 只负责选择当前版本，持久配置和抓取数据不会放在发布目录内，因此切换或回滚版本不会覆盖 `/etc/webfetch` 和 `/var/lib/webfetch`。

## 运维方式

```bash
systemctl status webfetch-api
systemctl status webfetch-http-worker
systemctl status webfetch-browser-worker
journalctl -u webfetch-api -f
systemctl restart webfetch-api webfetch-http-worker webfetch-browser-worker
systemctl list-timers webfetch-maintenance.timer
```

### systemd 服务

三个 WebFetch 服务都以低权限的 `webfetch:webfetch` 用户运行，读取 `/etc/webfetch/service.env`，配置为开机启动并在异常退出时自动重启：

| 服务 | 作用 | 主要依赖与限制 |
|---|---|---|
| `webfetch-api.service` | 提供 REST API、同步抓取和任务查询 | 在网络和 Redis 之后启动；监听地址及端口由配置决定 |
| `webfetch-http-worker.service` | 领取 `http` 队列，执行普通 HTTP 抓取 | 在 API 和 Redis 之后启动 |
| `webfetch-browser-worker.service` | 领取 `browser` 队列，执行 Playwright 抓取 | 在 API 和 Redis 之后启动；默认设置 `MemoryMax=3G` |

本机还有两个相关服务：

| 服务 | 类型 | 与 WebFetch 的关系 |
|---|---|---|
| `redis-server.service` | 运行依赖 | 提供缓存、请求合并和任务队列；应仅监听本机地址，WebFetch API 和 Worker 均依赖它 |
| `jenkins.service` | 构建部署依赖 | 检出代码、执行检查和测试、创建新 release、切换 `current`、重启服务并检查健康状态；WebFetch 已启动后，请求处理不依赖 Jenkins |

`webfetch-maintenance.timer` 用于定期清理遗留临时文件。PostgreSQL 是部署在外部数据库服务器上的运行依赖，因此不属于 111 服务器上的 systemd 服务。

查看全部相关服务：

```bash
systemctl status \
  webfetch-api \
  webfetch-http-worker \
  webfetch-browser-worker \
  redis-server \
  jenkins
```

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

生产部署使用 root 所有的固定入口 `deploy/webfetch-jenkins-deploy`。应将它安装为 `/usr/local/sbin/webfetch-jenkins-deploy`，并只为 Jenkins 放行这一条 sudo 命令，禁止授予 Jenkins 全局免密 sudo。
仓库中的 `deploy/sudoers-webfetch-jenkins` 给出了与 `WebFetchService` Job 精确匹配的 sudoers 规则。

部署脚本在新版本健康检查成功后自动清理旧发布目录。默认保留 `/opt/webfetch/releases` 下最近 5 个版本，可通过 `/etc/webfetch/service.env` 中的 `WEBFETCH_RELEASES_TO_KEEP` 调整，最小值为 2；`/opt/webfetch/current` 指向的版本始终受到保护。健康检查失败并回滚时不会执行清理。

## 测试

```bash
pytest --cov=webfetch_service --cov-fail-under=80
ruff check src tests
```

测试使用 MockTransport、本地 ASGI 和临时目录，不访问真实媒体网站。真实网站兼容性应通过经批准的预发布冒烟任务验证，避免 CI 对外站产生重复流量。
