# WebFetch 共享网页抓取服务需求规格说明书

版本：1.0  
状态：草案  
目标环境：Ubuntu Server 24.04（`192.168.0.111`）  
部署方式：Linux 原生进程 + systemd，不使用 Docker

## 1. 文档目的

本文档定义 WebFetch 共享网页抓取服务的产品边界、功能需求、接口约定、数据要求、可靠性要求、部署方式和验收标准，用于指导系统设计、开发、测试、部署和后续迭代。

## 2. 项目背景

多个业务系统均需要访问网页、获取原始内容并提取结构化信息。若每个系统分别实现 HTTP 请求、浏览器渲染、代理、重试、限速、缓存和登录态管理，将产生以下问题：

- 相同能力在不同项目中重复开发；
- 同一 URL 被多个系统重复访问，增加被限流或封禁的风险；
- 网站发生变化后，需要同时修改多个项目；
- Cookie、代理和抓取策略分散，难以统一管理；
- 抓取失败缺少统一日志、指标和原始证据，难以排查；
- 抓取实现与业务逻辑耦合，无法独立升级。

本项目将抓取能力建设成局域网内独立运行的基础服务，业务系统统一通过 HTTP API 使用。

## 3. 建设目标

### 3.1 核心目标

1. 为不同业务系统提供统一、稳定、可追踪的网页抓取 API。
2. 支持普通 HTTP、浏览器渲染和站点专用适配器三种抓取方式。
3. 集中提供缓存、去重、限速、重试、代理、登录态和任务管理能力。
4. 保存必要的原始响应，使解析失败可以复现并支持离线重新解析。
5. 网站改版时优先只修改中央适配器，不修改业务系统。
6. 使用 systemd 管理服务，实现开机启动、异常重启和日志归集。

### 3.2 成功标准

- 新业务系统只需调用 HTTP API，不需要安装 Playwright 或实现重试、限速和缓存。
- 相同身份、策略和请求条件下的相同 URL，在缓存有效期内不重复访问目标网站。
- 所有请求均可通过 `request_id` 查询完整执行过程。
- 普通网页抓取成功率在目标网站可访问的前提下达到 99% 以上。
- 服务进程异常退出后能够自动恢复，已入队任务不静默丢失。
- 关键站点页面改版或解析失败能够被监控发现。

## 4. 项目范围

### 4.1 本期范围

- REST API 和 API Key 认证；
- 同步抓取和异步任务；
- HTTP 抓取；
- Playwright/Chromium 浏览器抓取；
- 自动策略升级；
- 文件缓存与 Redis 短期缓存；
- 按域名限速、并发控制、重试和熔断；
- Clash HTTP 代理支持；
- Cookie/登录态 Profile 隔离；
- 原始 HTML、JSON、截图和错误现场保存；
- 通用内容提取和站点适配器机制；
- PostgreSQL 元数据及任务记录；
- 健康检查、结构化日志和 Prometheus 指标；
- systemd 原生部署和运维脚本。

### 4.2 非本期范围

- 验证码自动破解；
- 绕过付费墙、访问控制或明确禁止的安全措施；
- 大规模代理 IP 池采购和调度平台；
- 分布式浏览器集群；
- Kafka、Kubernetes 等重型基础设施；
- 面向公网用户的开放 SaaS 服务；
- 对所有网站承诺永久通用的结构化解析效果。

## 5. 用户与使用场景

### 5.1 使用角色

| 角色 | 说明 |
|---|---|
| 业务系统 | 调用抓取、提取和任务查询 API |
| 开发者 | 新增站点适配器、排查失败任务、重放历史响应 |
| 运维管理员 | 部署、配置、监控、备份和升级服务 |

### 5.2 典型场景

1. 业务系统同步抓取一篇普通新闻文章。
2. 业务系统批量提交数百个 URL，由后台异步执行。
3. 目标网页依赖 JavaScript，服务自动升级到浏览器策略。
4. 目标网站需要登录，服务使用指定身份 Profile 抓取。
5. 多个业务系统同时请求同一 URL，服务合并进行中的任务并共享缓存。
6. 网站页面结构发生变化，适配器解析失败并触发告警。
7. 开发者使用历史原始响应测试新版本解析器，不再次请求目标网站。

## 6. 总体架构约束

```text
业务系统
   │ HTTP/JSON
   ▼
WebFetch API
   ├── 缓存与请求去重
   ├── 同步快速抓取
   └── 异步任务队列
          ├── HTTP Worker
          ├── Browser Worker
          └── Adapter/Parser

Redis           PostgreSQL            NAS 文件存储
短期缓存/队列    任务/元数据/结果索引    HTML/JSON/截图/错误现场
```

### 6.1 技术约束

- 编程语言：Python 3.12 或 Ubuntu 24.04 官方支持的稳定 Python 版本；
- API 框架：FastAPI；
- HTTP 客户端：httpx 异步客户端；
- 浏览器：Playwright + Chromium；
- 队列和短期缓存：Redis；
- 持久化数据库：PostgreSQL；
- 进程管理：systemd；
- 反向代理：可使用现有 Nginx；
- 日志：JSON Lines，输出到 journald 并支持文件归档；
- 服务默认仅监听内网地址，不直接暴露公网。

### 6.2 运行位置

- API、HTTP Worker、Browser Worker：`192.168.0.111`；
- PostgreSQL：`192.168.0.100:15432`，使用独立数据库和最小权限用户，不使用默认业务库账号硬编码；
- 代理：`http://192.168.0.100:7890`；
- 原始文件：优先挂载 NAS 目录到 Ubuntu，例如 `/mnt/nas/AppHome/webfetch`；
- Redis：可原生安装于 Ubuntu VM，监听本机或受限内网地址，不暴露公网。

## 7. 功能需求

需求优先级定义：P0 为首版必须实现，P1 为首版应实现，P2 为后续增强。

### 7.1 API 认证与调用方管理

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-AUTH-001 | P0 | 所有业务接口必须使用 API Key 认证，健康检查除外。 |
| FR-AUTH-002 | P0 | API Key 仅保存不可逆哈希，不在日志中记录明文。 |
| FR-AUTH-003 | P0 | 每个 API Key 必须绑定调用方名称、启用状态和请求配额。 |
| FR-AUTH-004 | P1 | 支持按调用方限制每分钟请求数和最大并发任务数。 |
| FR-AUTH-005 | P1 | 管理接口与业务接口使用不同权限范围。 |

### 7.2 同步抓取

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-FETCH-001 | P0 | 提供 `POST /v1/fetch`，接收 URL、策略、缓存、身份、代理和超时参数。 |
| FR-FETCH-002 | P0 | 支持 `auto`、`http`、`browser` 三种模式。 |
| FR-FETCH-003 | P0 | 返回最终 URL、状态码、响应头、正文、策略、缓存状态、耗时和 `request_id`。 |
| FR-FETCH-004 | P0 | 同步接口必须设置服务端最长等待时间，超过后转为异步任务或返回明确超时。 |
| FR-FETCH-005 | P0 | 支持 GET 页面以及必要的自定义请求头，但默认禁止调用方传入 `Host` 等危险头。 |
| FR-FETCH-006 | P1 | 支持返回正文、原始文件引用或二者兼有，避免大响应占用 API 内存。 |
| FR-FETCH-007 | P1 | 支持配置最大响应体大小，超过限制应中止并返回明确错误。 |

### 7.3 异步任务与批量抓取

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-JOB-001 | P0 | 提供 `POST /v1/jobs` 创建单个或批量抓取任务。 |
| FR-JOB-002 | P0 | 提供 `GET /v1/jobs/{job_id}` 查询状态和结果。 |
| FR-JOB-003 | P0 | 状态至少包括 `queued`、`running`、`succeeded`、`failed`、`cancelled`。 |
| FR-JOB-004 | P0 | 队列采用至少一次投递语义，Worker 必须以幂等方式处理任务。 |
| FR-JOB-005 | P0 | Worker 崩溃后，超时未确认任务应能被其他 Worker 重新领取。 |
| FR-JOB-006 | P1 | 支持取消尚未执行的任务；运行中任务尽力取消。 |
| FR-JOB-007 | P1 | 支持 Webhook 通知，并对 Webhook 失败进行有限重试。 |
| FR-JOB-008 | P1 | 相同抓取键的进行中任务应合并，调用方共享最终结果。 |

### 7.4 抓取策略

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-STRATEGY-001 | P0 | `http` 模式仅使用 HTTP 客户端，不隐式启动浏览器。 |
| FR-STRATEGY-002 | P0 | `browser` 模式使用 Playwright Chromium，并复用浏览器进程。 |
| FR-STRATEGY-003 | P0 | 每次浏览器任务使用隔离的 Browser Context；同一 Profile 可按策略复用持久化登录态。 |
| FR-STRATEGY-004 | P0 | `auto` 首先尝试 HTTP，再根据状态码、正文特征及站点配置决定是否升级到浏览器。 |
| FR-STRATEGY-005 | P0 | 自动升级信号至少包括 `403`、`429`、部分 `5xx`、正文过短、JavaScript 提示和关键选择器缺失。 |
| FR-STRATEGY-006 | P0 | 域名配置可以强制指定策略，优先级高于自动判断。 |
| FR-STRATEGY-007 | P1 | 抓取结果必须记录每次策略尝试及升级原因。 |

### 7.5 限速、重试和熔断

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-RES-001 | P0 | 按域名分别设置请求间隔和最大并发数。 |
| FR-RES-002 | P0 | 对连接错误、读取超时、`429` 和可重试 `5xx` 执行指数退避和随机抖动。 |
| FR-RES-003 | P0 | 服务应尊重目标网站返回的 `Retry-After`。 |
| FR-RES-004 | P0 | 默认最大尝试次数为 3，可按域名配置。 |
| FR-RES-005 | P0 | 非幂等请求默认不得自动重试。 |
| FR-RES-006 | P1 | 域名连续失败达到阈值后开启熔断，冷却后进行半开探测。 |
| FR-RES-007 | P1 | 调用方可查询域名当前限速和熔断状态。 |

### 7.6 缓存与去重

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-CACHE-001 | P0 | 缓存键至少包含规范化 URL、抓取模式、Profile、请求方法和影响内容的关键请求头摘要。 |
| FR-CACHE-002 | P0 | 认证令牌、Cookie 和 API Key 不得以明文进入缓存键或日志。 |
| FR-CACHE-003 | P0 | 支持每次请求设置 TTL、跳过缓存和强制刷新。 |
| FR-CACHE-004 | P0 | 默认只缓存成功响应；负缓存的状态码和短 TTL 必须可配置。 |
| FR-CACHE-005 | P0 | 同一抓取键在同一时刻最多有一个真实上游请求。 |
| FR-CACHE-006 | P1 | 支持管理员按 URL、域名、Profile 或适配器版本清理缓存。 |
| FR-CACHE-007 | P1 | 支持 `stale-if-error`：目标网站临时失败时可返回标记为过期的最近成功结果。 |

### 7.7 代理

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-PROXY-001 | P0 | 支持直连和 Clash HTTP 代理。 |
| FR-PROXY-002 | P0 | 支持按域名配置 `direct`、`proxy` 或 `auto`。 |
| FR-PROXY-003 | P0 | 结果中记录使用的代理策略，但不得泄露代理认证信息。 |
| FR-PROXY-004 | P1 | 代理故障时可按域名策略决定失败、直连降级或再次代理。 |

### 7.8 登录态与 Profile

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-PROFILE-001 | P0 | Profile 表示一组隔离的 Cookie、Local Storage、请求头和浏览器设置。 |
| FR-PROFILE-002 | P0 | 不同 Profile 的登录态、缓存和浏览器 Context 不得互相共享。 |
| FR-PROFILE-003 | P0 | Profile 数据必须限制文件权限，敏感字段必须加密保存。 |
| FR-PROFILE-004 | P0 | 日志、异常和 API 响应不得输出完整 Cookie 或认证头。 |
| FR-PROFILE-005 | P1 | 提供管理员导入、导出、检查有效期和停用 Profile 的能力。 |
| FR-PROFILE-006 | P1 | 登录失效必须产生可识别错误和告警，不得无限重复登录。 |

### 7.9 内容提取与站点适配器

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-PARSE-001 | P0 | 提供 `POST /v1/extract`，支持通用文章提取和指定适配器提取。 |
| FR-PARSE-002 | P0 | 通用提取至少返回标题、正文、作者、发布时间、链接和页面元数据。 |
| FR-PARSE-003 | P0 | 站点适配器必须有唯一名称、版本和输出 Schema。 |
| FR-PARSE-004 | P0 | 适配器只能处理解析，不得自行绕过中央限速、代理和缓存。 |
| FR-PARSE-005 | P0 | 解析结果必须记录所用适配器版本和原始文件标识。 |
| FR-PARSE-006 | P0 | 关键字段缺失或 Schema 校验失败时，任务必须标记解析失败，而非返回伪成功。 |
| FR-PARSE-007 | P1 | 支持使用历史原始文件重新解析，不访问目标网站。 |
| FR-PARSE-008 | P1 | 每个关键适配器应维护匿名化 HTML/JSON 样本和回归测试。 |

### 7.10 原始文件与证据保存

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-ART-001 | P0 | 可保存原始 HTML/JSON、最终 URL、响应头、状态码和抓取时间。 |
| FR-ART-002 | P0 | 浏览器失败时可按配置保存截图和页面 HTML。 |
| FR-ART-003 | P0 | 文件按日期和内容摘要分层保存，数据库仅保存索引和相对路径。 |
| FR-ART-004 | P0 | 文件写入必须采用临时文件加原子重命名，避免产生半文件。 |
| FR-ART-005 | P1 | 支持按保留策略自动清理；失败证据应比普通缓存保留更久。 |
| FR-ART-006 | P1 | 文件记录内容 SHA-256，用于去重和完整性验证。 |

### 7.11 管理与运维接口

| 编号 | 优先级 | 需求 |
|---|---:|---|
| FR-OPS-001 | P0 | 提供 `/health/live` 和 `/health/ready`。 |
| FR-OPS-002 | P0 | Ready 检查必须覆盖 PostgreSQL、Redis、存储目录及 Worker 状态。 |
| FR-OPS-003 | P0 | 提供 `/metrics` 输出 Prometheus 格式指标。 |
| FR-OPS-004 | P0 | 支持查询单次请求的尝试记录、错误类型和文件引用。 |
| FR-OPS-005 | P1 | 提供失败任务重试、缓存清理、域名暂停和熔断重置接口。 |
| FR-OPS-006 | P1 | 所有管理操作必须写入审计日志。 |

## 8. API 初步规格

### 8.1 同步抓取

```http
POST /v1/fetch
Authorization: Bearer <api-key>
Content-Type: application/json
```

```json
{
  "url": "https://example.com/article/123",
  "mode": "auto",
  "profile": "anonymous",
  "proxy_policy": "auto",
  "cache_ttl": 3600,
  "force_refresh": false,
  "save_artifact": true,
  "timeout_seconds": 30
}
```

```json
{
  "request_id": "req_01...",
  "success": true,
  "requested_url": "https://example.com/article/123",
  "final_url": "https://example.com/article/123",
  "status_code": 200,
  "strategy": "http",
  "from_cache": false,
  "stale": false,
  "elapsed_ms": 428,
  "content_type": "text/html; charset=utf-8",
  "body": "<html>...</html>",
  "artifact_id": "art_01...",
  "fetched_at": "2026-07-03T12:00:00Z"
}
```

### 8.2 创建异步任务

```http
POST /v1/jobs
```

```json
{
  "requests": [
    {"url": "https://example.com/1", "mode": "auto"},
    {"url": "https://example.com/2", "mode": "browser"}
  ],
  "priority": "normal",
  "webhook_url": null
}
```

### 8.3 内容提取

```http
POST /v1/extract
```

```json
{
  "source": {
    "url": "https://example.com/article/123"
  },
  "adapter": "generic.article",
  "adapter_version": "latest",
  "fetch_options": {
    "mode": "auto",
    "cache_ttl": 3600
  }
}
```

### 8.4 错误响应

所有错误必须使用稳定错误码：

```json
{
  "request_id": "req_01...",
  "success": false,
  "error": {
    "code": "UPSTREAM_RATE_LIMITED",
    "message": "目标网站暂时限制访问",
    "retryable": true,
    "retry_after_seconds": 120
  }
}
```

首版至少定义以下错误码：

- `INVALID_REQUEST`
- `AUTHENTICATION_FAILED`
- `DOMAIN_NOT_ALLOWED`
- `DNS_FAILED`
- `CONNECT_TIMEOUT`
- `READ_TIMEOUT`
- `RESPONSE_TOO_LARGE`
- `UPSTREAM_RATE_LIMITED`
- `UPSTREAM_BLOCKED`
- `BROWSER_FAILED`
- `LOGIN_REQUIRED`
- `PROFILE_EXPIRED`
- `PARSE_FAILED`
- `QUEUE_UNAVAILABLE`
- `STORAGE_UNAVAILABLE`
- `INTERNAL_ERROR`

## 9. 数据需求

### 9.1 主要实体

| 实体 | 主要内容 |
|---|---|
| clients | 调用方、API Key 哈希、配额、状态 |
| fetch_requests | 请求参数、调用方、状态、抓取键、时间 |
| fetch_attempts | 每次 HTTP/Browser 尝试、耗时、状态码、错误 |
| fetch_results | 最终响应摘要、缓存状态、原始文件引用 |
| jobs | 异步任务状态、优先级、领取和确认信息 |
| artifacts | 文件路径、类型、大小、摘要、保留期限 |
| profiles | 身份 Profile 元数据及加密状态引用 |
| adapters | 适配器名称、版本、Schema 和启用状态 |
| extraction_results | 结构化结果、适配器版本、原始文件引用 |
| domain_policies | 域名策略、限速、代理、重试、熔断配置 |
| audit_logs | 管理操作和安全相关事件 |

### 9.2 数据保留默认值

- 成功请求元数据：180 天；
- 失败请求和尝试记录：90 天；
- 普通原始响应：30 天；
- 失败现场及截图：90 天；
- 审计日志：365 天；
- 可按域名、适配器和业务系统覆盖默认值。

## 10. 非功能需求

### 10.1 性能

- 缓存命中接口 P95 响应时间不高于 200ms；
- 普通 HTTP 抓取的服务自身附加开销 P95 不高于 100ms，不含目标网站耗时；
- 首版至少支持 50 个并发 HTTP 请求；
- 首版默认最多同时运行 3 个 Browser Context，必须可配置；
- 单个响应正文默认上限 10MB，浏览器页面资源不应无限下载；
- API 不得在内存中长期保存批量任务的完整正文。

### 10.2 可用性与恢复

- 月度服务可用性目标为 99.5%；
- API 和 Worker 由 systemd 自动重启；
- PostgreSQL、Redis 或 NAS 暂时不可用时必须明确降级或拒绝，不得伪造成功；
- 已持久化任务在服务重启后可以继续处理；
- 服务启动时应恢复超时的运行中任务；
- 配置错误应导致启动失败并输出明确原因。

### 10.3 安全

- 默认仅允许 `http` 和 `https` URL；
- 必须防御 SSRF：禁止访问 loopback、链路本地、云元数据地址和未授权内网网段；
- 允许访问的内网目标必须通过显式白名单配置；
- 每次重定向后都必须重新执行目标地址安全检查；
- 禁止调用方读取任意本地文件路径；
- API Key、Cookie、数据库密码和加密密钥必须通过权限受限的环境文件或凭据文件提供；
- 配置文件和日志中不得出现不必要的明文凭据；
- Profile 存储文件权限不高于 `0600`；
- 服务使用独立 Linux 用户运行，不使用 root；
- systemd 单元启用合理的文件系统和权限沙箱。

### 10.4 可观测性

每次请求日志至少包含：

- `timestamp`
- `request_id`
- `job_id`
- `client_id`
- `domain`
- `strategy`
- `profile_id`（非敏感标识）
- `proxy_policy`
- `attempt`
- `status_code`
- `error_code`
- `elapsed_ms`
- `from_cache`

指标至少包含：

- 请求量、成功率和各错误码数量；
- 按域名和策略统计的延迟；
- 缓存命中率；
- 队列长度、最老任务等待时间和失败任务数；
- HTTP Worker 与 Browser Worker 活跃数；
- 浏览器启动失败和 Context 泄漏数量；
- 重试、限流、熔断和代理失败数量；
- NAS 可用空间及文件写入失败数量。

### 10.5 可维护性

- 业务代码、基础抓取、适配器和存储实现必须分层；
- 所有外部接口使用版本前缀 `/v1`；
- 数据库变更使用迁移工具；
- 配置必须经过 Schema 校验；
- 核心模块单元测试覆盖率目标不低于 80%；
- 关键工作流必须有集成测试；
- 测试默认不得访问真实外部网站，应使用固定响应和本地测试站点。

## 11. 配置需求

配置分为四类：

1. 非敏感全局配置：YAML/TOML 文件；
2. 密钥和密码：权限受限的 EnvironmentFile 或凭据文件；
3. 可动态调整的域名策略：PostgreSQL；
4. Profile 登录状态：独立加密目录。

示例配置项：

```yaml
server:
  host: 192.168.0.111
  port: 9120
  sync_timeout_seconds: 30

workers:
  http_concurrency: 50
  browser_concurrency: 3

storage:
  artifact_root: /mnt/nas/AppHome/webfetch/artifacts

proxy:
  default_policy: auto
  http_url: http://192.168.0.100:7890

fetch:
  max_response_bytes: 10485760
  default_cache_ttl: 3600
  default_domain_interval_seconds: 1.0
  max_redirects: 10
```

生产配置中不得提交真实密码和 API Key。

## 12. Linux 原生部署需求

### 12.1 目录规划

```text
/opt/webfetch/                 应用代码和 Python 虚拟环境
/etc/webfetch/                 非敏感配置
/etc/webfetch/secrets.env      密钥，权限 0600
/var/lib/webfetch/             本机运行数据和临时文件
/var/log/webfetch/             可选文件日志
/mnt/nas/AppHome/webfetch/     NAS 原始文件存储
```

### 12.2 Linux 用户

- 创建系统用户 `webfetch`；
- 用户无交互登录 Shell；
- 仅授予应用、配置和数据目录所需权限；
- 不加入无关高权限用户组。

### 12.3 systemd 服务

至少拆分以下单元：

- `webfetch-api.service`
- `webfetch-http-worker.service`
- `webfetch-browser-worker.service`
- `webfetch-maintenance.timer`

systemd 单元必须满足：

- 开机自动启动；
- 异常退出自动重启；
- 明确的启动和停止超时；
- 使用同一版本虚拟环境；
- 使用 EnvironmentFile 或 systemd credentials 加载密钥；
- 停止时允许 Worker 完成或归还正在处理的任务；
- 日志写入 journald；
- 配置 `NoNewPrivileges`、`PrivateTmp` 等安全选项。

### 12.4 发布和回滚

- 应用按版本发布到 `/opt/webfetch/releases/<version>`；
- `/opt/webfetch/current` 指向当前版本；
- 升级前执行配置校验、数据库迁移检查和健康检查；
- 版本切换失败时可恢复上一版本；
- 数据库迁移必须声明是否支持降级；
- Playwright 升级时必须同步安装匹配的 Chromium 版本。

## 13. 测试需求

### 13.1 单元测试

- URL 规范化与缓存键；
- SSRF 和重定向安全检查；
- 指数退避、`Retry-After` 和重试分类；
- 域名限速与并发控制；
- 熔断状态转换；
- Cookie 和敏感头脱敏；
- 适配器 Schema 校验；
- 文件原子写入和摘要验证。

### 13.2 集成测试

- API → 队列 → Worker → PostgreSQL → 文件存储完整链路；
- HTTP 成功、重定向、超时、限流和大响应；
- HTTP 自动升级 Browser；
- Browser Context 和 Profile 隔离；
- Worker 被强制终止后的任务恢复；
- Redis、PostgreSQL、NAS 短暂故障及恢复；
- 缓存命中、强制刷新、进行中请求合并和 stale 返回。

### 13.3 适配器回归测试

- 每个关键适配器至少保存一个成功样本和一个异常样本；
- 样本必须移除 Cookie、Token 和个人敏感数据；
- 适配器输出必须通过固定 Schema 校验；
- 适配器修改后必须运行全部样本测试。

## 14. 验收标准

### 14.1 功能验收

1. 两个不同的测试业务系统可使用各自 API Key 调用服务。
2. 普通网页可通过 HTTP 模式成功获取。
3. JavaScript 测试页面可在 auto 模式下升级浏览器并成功获取。
4. 同一 URL 并发请求只产生一次符合条件的上游访问。
5. 缓存命中、强制刷新和 TTL 均符合预期。
6. `429` 和可重试 `5xx` 会按规则重试并记录尝试过程。
7. 域名并发上限和请求间隔能够被自动化测试验证。
8. Browser Profile A 与 Profile B 的 Cookie 完全隔离。
9. Worker 执行中被终止后，任务能够重新入队并最终完成。
10. 解析结果可定位到适配器版本和原始文件。
11. 历史原始文件可重新解析且不访问目标网站。
12. 所有失败响应均包含 `request_id` 和稳定错误码。

### 14.2 运维验收

1. Ubuntu 重启后所有服务自动恢复。
2. API 或 Worker 异常退出后 systemd 自动重启。
3. PostgreSQL、Redis 或 NAS 不可用时 Ready 检查失败并输出明确原因。
4. journald 中不存在明文 API Key、Cookie、数据库密码或认证头。
5. `/metrics` 可查看请求、缓存、队列、Worker、重试和错误指标。
6. 新版本发布失败后可回滚至上一可用版本。
7. 定时清理能遵守数据保留策略且不会删除仍被引用的文件。

### 14.3 性能验收

在局域网测试环境下：

- 1000 次缓存命中请求成功率为 100%，P95 不高于 200ms；
- 50 个并发 HTTP 抓取任务不会突破配置的域名并发限制；
- 连续运行 24 小时无明显文件句柄、HTTP 连接或 Browser Context 泄漏；
- 浏览器 Worker 达到并发上限时任务排队，不应无限创建 Chromium 进程。

## 15. 建设阶段

### 第一阶段：共享抓取 MVP

- FastAPI 与 API Key；
- HTTP/Browser/auto；
- Redis 队列和缓存；
- PostgreSQL 任务记录；
- NAS 原始 HTML 保存；
- 域名限速、重试和去重；
- systemd 部署；
- 健康检查与基础指标。

### 第二阶段：稳定性与站点适配

- Profile 和登录态；
- 站点适配器及回归样本；
- 熔断、stale-if-error；
- 截图和错误现场；
- 管理接口与审计日志；
- Webhook。

### 第三阶段：运营与优化

- 简单管理后台；
- 容量和成功率报表；
- 适配器异常告警；
- 浏览器资源池调优；
- 数据保留和备份自动化。

## 16. 风险与约束

| 风险 | 应对方式 |
|---|---|
| 目标网站页面改版 | 适配器版本化、样本回归、字段缺失告警 |
| 网站反爬或账号封禁 | 限速、缓存、熔断、身份隔离，遵守目标网站规则 |
| Chromium 内存较高 | 限制并发、复用浏览器、定期回收进程 |
| NAS 短暂不可用 | Ready 失败、任务延迟执行、禁止伪成功 |
| Redis 任务重复投递 | 幂等抓取键、数据库状态约束、结果去重 |
| 登录态泄露 | 加密存储、最小权限、日志脱敏、API 权限隔离 |
| 服务成为 SSRF 跳板 | 地址校验、内网白名单、重定向复检、调用方认证 |
| 抓取结果具有法律或合规风险 | 记录来源和时间，遵守 robots、服务条款、版权和隐私要求 |

## 17. 待确认事项

下列事项不阻塞 MVP 设计，但应在实施前确认：

1. WebFetch 对外使用的内网端口及是否配置独立域名；
2. NAS 目录通过 NFS 还是 SMB 挂载到 Ubuntu；
3. Redis 安装在 Ubuntu VM 还是使用 NAS 上现有实例；
4. PostgreSQL 是否创建独立数据库 `webfetch` 和独立最小权限用户；
5. 首批需要实现专用适配器的网站清单；
6. 哪些网站需要登录 Profile，以及登录状态的更新方式；
7. 是否需要通过现有 Nginx/Cloudflare Tunnel 暴露给局域网外的业务系统。

