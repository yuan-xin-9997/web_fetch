# WebFetch 共享网页抓取服务设计说明书

版本：1.0  
状态：实现基线  
对应需求：`docs/webfetch-service-srs.md` 1.0

## 1. 设计目标

WebFetch 是部署在单台 Linux 服务器上的内网基础服务，默认监听可配置端口 `33333`。它把网络访问、浏览器渲染、缓存、限速、重试、任务、原始证据和内容解析集中起来，通过稳定的 REST API 提供给多个业务系统。

首版设计遵循以下原则：

1. 单机优先，保持组件边界，未来可横向扩展 Worker；
2. 普通 HTTP 是默认路径，浏览器是受控的昂贵资源；
3. 抓取与解析分离，原始响应是可重放的事实；
4. 每个请求全链路携带 `request_id`；
5. 配置和凭据全部外置，代码中不包含环境地址、账号和绝对路径；
6. 外部依赖故障必须显式可见，不返回伪成功；
7. 所有执行路径可测试，测试不依赖真实互联网。

## 2. 系统上下文

```text
┌──────────────┐       HTTP/JSON        ┌─────────────────────┐
│ 业务系统 A/B │ ─────────────────────▶ │ WebFetch API        │
└──────────────┘                         │ auth / fetch / jobs │
                                       └──────────┬──────────┘
                                                  │
                   ┌──────────────────────────────┼──────────────────────┐
                   ▼                              ▼                      ▼
          ┌─────────────────┐           ┌─────────────────┐    ┌─────────────────┐
          │ HTTP Fetcher    │           │ Browser Fetcher │    │ Job Worker      │
          │ httpx pool      │           │ Playwright pool │    │ persistent jobs │
          └────────┬────────┘           └────────┬────────┘    └────────┬────────┘
                   └──────────────┬──────────────┘                      │
                                  ▼                                     ▼
                         ┌─────────────────┐                    ┌─────────────────┐
                         │ Adapter/Parser  │                    │ PostgreSQL      │
                         └────────┬────────┘                    └─────────────────┘
                                  │
                  ┌───────────────┼───────────────┐
                  ▼               ▼               ▼
               Redis          PostgreSQL       Ubuntu files
            cache/locks       metadata/jobs    artifacts
```

## 3. 进程设计

### 3.1 API 进程

- 入口：`webfetch-api`；
- 运行 ASGI 应用；
- 负责认证、参数校验、同步抓取、任务创建和查询；
- 每个进程持有一个复用的 `httpx.AsyncClient`；
- 不在 API 请求中执行长时间批量任务。

### 3.2 Worker 进程

- 入口：`webfetch-worker`；
- 从 PostgreSQL 以 `FOR UPDATE SKIP LOCKED` 原子领取任务；
- 执行抓取和可选解析；
- 使用租约字段识别失联 Worker，超时任务可以被重新领取；
- 优雅停止时不再领取新任务，并完成或释放当前任务。

首版 HTTP 与 Browser 采用同一 Worker 程序、不同环境配置和队列标签启动，方便 systemd 分别限制并发和内存。

### 3.3 Maintenance 进程

- 入口：`webfetch-maintenance`；
- 由 systemd timer 周期运行；
- 回收过期租约、清理过期缓存和原始文件、检查孤立文件。

## 4. 代码分层

```text
src/webfetch_service/
├── api/                 FastAPI 路由、认证依赖、异常映射
├── adapters/            通用和站点专用解析器
├── core/                配置、日志、错误、安全、指标
├── fetch/               HTTP/Browser、策略、限速、重试
├── persistence/         SQLAlchemy 模型、仓储、数据库生命周期
├── services/            抓取编排、任务、缓存、原始文件
├── main.py              ASGI 工厂
├── worker.py            Worker 入口
└── maintenance.py       定时维护入口
```

依赖方向必须由外向内：API 调用 service，service 调用抽象接口，具体存储和抓取器在应用工厂装配。路由不得直接编写 SQL 或启动浏览器。

## 5. 核心执行流程

### 5.1 同步抓取

```text
认证与配额
  → 请求参数校验
  → URL/SSRF 校验
  → 生成 fetch_key
  → 查询缓存
  → 获取同键分布式锁
  → 二次查询缓存
  → 获取域名并发许可并等待限速
  → 根据 mode/domain policy 执行 HTTP
  → auto 模式判断是否升级 Browser
  → 保存 artifact
  → 写入请求、尝试和结果记录
  → 写缓存并释放锁
  → 返回统一响应
```

`fetch_key` 必须包含请求的 `save_artifact` 原始三态值。`null` 表示服从服务端默认配置，语义不同于显式 `false` 或 `true`；三个值必须生成不同缓存键，防止要求保存 artifact 的请求命中没有 `artifact_id` 的旧缓存。

缓存和分布式锁不可用时，首版允许在配置开启的情况下退化为本进程锁；降级必须记录指标和警告。PostgreSQL 或 artifact 存储不可用时，若请求要求保存证据，则 Ready 失败并拒绝执行。

### 5.2 异步任务

```text
POST /v1/jobs
  → 校验每个请求
  → 数据库事务创建 job/items
  → 返回 job_id

Worker
  → 领取 queued/retryable item 并设置 lease
  → 调用与同步接口相同的 FetchService
  → 成功：保存 result，标记 succeeded
  → 可重试失败：计算 next_run_at，标记 queued
  → 最终失败：标记 failed
  → 汇总 job 状态
```

### 5.3 自动策略升级

HTTP 结果满足任一条件时，`auto` 可以升级 Browser：

- 状态码属于域名策略配置的升级集合；
- HTML 长度低于阈值；
- 包含已配置的 JavaScript/挑战页特征；
- 请求携带 `required_selector` 且 HTTP HTML 中不存在；
- 域名策略强制 Browser。

不会因为 DNS 错误、非法 URL 或 SSRF 拒绝而升级。每次升级都写入 attempt，并记录机器可读原因。

## 6. URL 安全设计

`UrlGuard` 在首次请求和每一次重定向前执行：

1. 只接受 `http`、`https`；
2. 拒绝 URL 用户信息；
3. 规范化 IDN、主机名、默认端口和查询参数；
4. DNS 解析全部 A/AAAA 地址；
5. 默认拒绝 loopback、link-local、multicast、unspecified、reserved 和 private 地址；
6. 内网目标仅在配置的 CIDR/主机白名单中放行；
7. HTTP 客户端禁用自动重定向，由抓取器逐跳验证；
8. 限制重定向次数并检测循环。

DNS 结果在单次请求内固定使用于判定，并在连接后校验最终 peer 的能力作为后续增强；首版通过短 DNS 缓存和逐跳解析降低 DNS rebinding 风险。

## 7. 身份认证与敏感信息

- API Key 是 WebFetch 发放给下游业务系统的服务端调用凭据，不是目标网站的登录凭据；
- API Key 格式为随机高熵字符串；数据库只存 SHA-256/HMAC 摘要；
- 请求使用 `Authorization: Bearer`；
- 首版支持通过配置提供 bootstrap API Key，启动时转换为内存摘要，永不打印；
- 当前首版的 bootstrap API Key 由所有下游系统共享，因此仅提供统一认证；按调用方独立签发、吊销、限流和审计属于后续调用方管理设计；
- 下游系统必须通过环境变量或密钥管理设施保存 Key，不得硬编码、提交到 Git 或输出到日志；
- Ubuntu 生产部署通过 `/etc/webfetch/service.env` 向服务注入 Key，并将可供管理员分发的明文副本保存在权限受限的 `/etc/webfetch/api-key`；
- 管理接口要求 `admin` scope；
- Cookie、Authorization、Proxy-Authorization 等字段经过统一脱敏器；
- Profile 状态文件独立目录，权限 `0600`，逻辑标识不含用户名；
- 加密密钥从环境或 systemd credential 读取。

## 8. 缓存与请求合并

### 8.1 Fetch Key

Fetch Key 是以下规范化数据的 SHA-256：

```json
{
  "method": "GET",
  "url": "normalized-url",
  "mode": "http|browser|auto",
  "profile": "profile-id",
  "headers": {"accept-language": "..."},
  "body_digest": null,
  "adapter": null
}
```

敏感头只能使用 HMAC 摘要，绝不写入键的调试文本。

### 8.2 两级缓存

- L1：进程内有界 TTL 缓存，保存热点小响应；
- L2：Redis，跨进程共享；
- Artifact：大正文不直接存 Redis，只缓存元数据和 artifact 引用；
- `force_refresh` 跳过读取但更新缓存；
- `cache_ttl=0` 表示不缓存；
- `stale-if-error` 保存最近成功版本的额外过期窗口。

### 8.3 Singleflight

- 同进程使用 `asyncio.Lock`；
- 跨进程使用带唯一 token 和 TTL 的 Redis 锁；
- 释放锁使用比较 token 的 Lua 脚本；
- 等待者轮询缓存并有上限，锁过期后可重新竞争。

## 9. 限速、重试与熔断

### 9.1 限速

- 域名键使用小写 hostname，不包含路径；
- 进程内 token/next-slot 算法保证间隔；
- 域名 `Semaphore` 限制并发；
- 多 Worker 场景使用 Redis Lua 实现全局时间槽作为增强，首版至少保证单进程限制并提供全局配置上限。

### 9.2 重试

重试分类：

- 可重试：连接错误、读超时、`408`、`425`、`429`、`500`、`502`、`503`、`504`；
- 不可重试：参数错误、SSRF、绝大多数 `4xx`、解析 Schema 错误；
- 延迟：优先 `Retry-After`，否则指数退避加抖动；
- 每次尝试独立记录耗时、状态和错误码。

### 9.3 熔断

状态为 `closed/open/half_open`。连续可归因于目标域名的失败达到阈值后打开；冷却期后只允许少量探测。调用方错误、存储错误不计入目标域名熔断。

## 10. HTTP 与 Browser 设计

### 10.1 HTTP Fetcher

- 复用 `httpx.AsyncClient` 连接池；
- `follow_redirects=False`，逐跳交给 UrlGuard；
- 流式读取并执行字节上限；
- 根据响应头和内容探测编码；
- 可选 Clash 代理由配置和域名策略决定；
- 默认请求头固定且可配置，不进行无意义的每请求 UA 随机化。

### 10.2 Browser Fetcher

- Playwright 延迟初始化；
- 一个 Worker 复用 Chromium 进程；
- 每个匿名请求创建并关闭独立 Context；
- Profile 使用独立 storage state；
- 阻止字体、媒体等非必要资源可按域名配置；
- 页面导航、总任务和内容读取分别限时；
- 异常时按配置保存截图和 HTML；
- 达到任务数或内存阈值后优雅回收浏览器。

Playwright 是可选运行依赖。未安装时 `browser` 请求返回 `BROWSER_UNAVAILABLE`，不得静默回退并伪称浏览器成功。

## 11. Artifact 设计

目录结构：

```text
<artifact_root>/YYYY/MM/DD/<sha256-prefix>/<artifact-id>/
├── body.bin
├── metadata.json
└── screenshot.png        可选
```

- ID 使用 UUIDv7/ULID 风格可排序标识；
- 内容文件先写同目录临时文件，`fsync` 后原子替换；
- metadata 不包含 Cookie 和敏感认证头；
- 数据库保存相对路径、MIME、大小、SHA-256 和保留期限；
- API 读取 artifact 必须鉴权，并校验解析后的绝对路径仍位于根目录。

## 12. 解析器与适配器

适配器协议：

```python
class Adapter(Protocol):
    name: str
    version: str
    output_model: type[BaseModel]

    async def extract(self, artifact: FetchArtifact) -> BaseModel: ...
```

首版内置：

- `generic.article@1`：标题、正文、作者、日期、链接、meta；
- `generic.links@1`：页面链接列表。
- `china.official-profile@1`：中央媒体及中央国家机关页面的人物基本信息、现任职务和时间线履历。

首批目标覆盖中国中央媒体、中国主流媒体和欧美主流媒体。由于“媒体官网”不是稳定的单一页面协议，首版以 `generic.article@1` 配合域名策略承接；只有获得具体 URL 和失败样本后才增加站点专用适配器，避免在没有证据时编写脆弱选择器。

注册表以 `(name, version)` 定位适配器；`latest` 在服务端解析为明确版本并写入结果。适配器只读取 artifact，不自行联网。

## 13. 数据库设计

使用 SQLAlchemy 2.x 与 Alembic。所有时间使用 UTC timestamptz，主键使用字符串形式的 UUID。

### 13.1 clients

- `id`, `name`, `key_digest`, `scopes`, `enabled`
- `requests_per_minute`, `max_concurrent_jobs`
- `created_at`, `updated_at`

### 13.2 fetch_requests

- `id`（request_id）, `client_id`, `fetch_key`
- `requested_url`, `normalized_url`, `mode`, `profile_id`
- `state`, `created_at`, `started_at`, `finished_at`

### 13.3 fetch_attempts

- `id`, `request_id`, `sequence`
- `strategy`, `proxy_policy`, `status_code`
- `error_code`, `upgrade_reason`, `elapsed_ms`, `created_at`

### 13.4 fetch_results

- `id`, `request_id`, `final_url`, `status_code`
- `content_type`, `artifact_id`, `from_cache`, `stale`
- `elapsed_ms`, `fetched_at`

### 13.5 jobs / job_items

- job：`id`, `client_id`, `state`, `priority`, 汇总数量和时间；
- item：`id`, `job_id`, `position`, `payload`, `state`, `attempts`；
- 租约：`worker_id`, `leased_until`, `next_run_at`；
- 结果：`request_id`, `error_code`, `error_message`。

### 13.6 artifacts / extraction_results / domain_policies / audit_logs

字段遵循需求规格的数据实体定义。JSON 扩展字段仅用于低频可选数据，稳定查询字段必须单独建列和索引。

关键索引：`fetch_key`、`state + next_run_at`、`job_id + position`、`domain`、`created_at`、`expires_at`。

## 14. API 设计

### 14.1 路由

| 方法 | 路径 | Scope | 用途 |
|---|---|---|---|
| GET | `/health/live` | 无 | 进程存活 |
| GET | `/health/ready` | 无 | 依赖就绪 |
| GET | `/metrics` | 配置决定 | Prometheus 指标 |
| POST | `/v1/fetch` | fetch | 同步抓取 |
| POST | `/v1/jobs` | fetch | 创建任务 |
| GET | `/v1/jobs/{id}` | fetch | 查询本调用方任务 |
| POST | `/v1/jobs/{id}/cancel` | fetch | 取消任务 |
| POST | `/v1/extract` | extract | 抓取并解析或重解析 artifact |
| GET | `/v1/artifacts/{id}` | fetch | 获取原始文件 |
| GET | `/v1/requests/{id}` | fetch | 查询执行轨迹 |

### 14.2 版本和兼容性

- URL 主版本为 `/v1`；
- 字段只做向后兼容增加；
- 删除或改变语义必须发布新主版本；
- 错误体统一包含 `request_id/code/message/retryable`；
- OpenAPI 是客户端契约的一部分，并在 CI 中生成快照。

## 15. 配置设计

配置通过环境变量读取，使用 `WEBFETCH_` 前缀和 `__` 层级分隔，例如：

```text
WEBFETCH_SERVER__HOST
WEBFETCH_SERVER__PORT
WEBFETCH_DATABASE__URL
WEBFETCH_REDIS__URL
WEBFETCH_STORAGE__ARTIFACT_ROOT
WEBFETCH_PROXY__HTTP_URL
WEBFETCH_AUTH__BOOTSTRAP_API_KEY
```

仓库只提供 `.env.example`，不包含真实环境值。应用启动时校验目录、URL、并发数、超时和密钥长度。

## 16. 可观测性设计

- 使用 Python logging 输出单行 JSON；
- middleware 建立/校验 `X-Request-ID`，响应始终回传；
- 指标使用 Prometheus client；
- URL 日志默认移除 query，避免查询参数泄密；
- 域名标签设置允许列表，防止指标基数失控；
- `/health/live` 不检查外部依赖；`/health/ready` 带超时检查数据库、Redis、artifact 根目录和抓取器状态。

## 17. 异常模型

领域异常包含：

- 稳定错误码；
- 面向调用方的安全消息；
- HTTP 状态；
- 是否可重试；
- 可选 `retry_after_seconds`；
- 内部 cause 只进入脱敏日志。

未知异常映射为 `INTERNAL_ERROR`，不得把堆栈返回客户端。

## 18. 部署设计

采用版本目录和软链接：

```text
/opt/webfetch/releases/<build>/
/opt/webfetch/current -> releases/<build>
/opt/webfetch/shared/.env
/opt/webfetch/shared/venv/
/var/lib/webfetch/artifacts/       Ubuntu 本地 artifact 默认目录
```

发布步骤：

1. Jenkins 从 SSH Git 仓库检出；
2. 在临时 release 目录安装代码和依赖；
3. 运行静态检查、单元测试和配置校验；
4. 安装/更新 systemd unit；
5. 停止 Worker，再停止 API；
6. 执行数据库迁移；
7. 原子切换 `current`；
8. 启动 API 和 Worker；
9. 调用 live/ready 冒烟检查；
10. 失败时切回上一链接并恢复服务。
11. 健康检查成功后清理旧 release，默认保留最近 5 个且始终保护 `current` 指向的目录；保留数由 `WEBFETCH_RELEASES_TO_KEEP` 配置，最小为 2。

Jenkinsfile 不写入环境密码；部署路径、服务名、Python 路径和健康地址均使用参数或环境变量。

## 19. 测试设计

### 19.1 单元测试

- 配置校验、缓存键、URL Guard；
- 重试分类和 `Retry-After`；
- 自动升级判定；
- 进程内限速和熔断；
- artifact 原子写入与路径防穿越；
- API Key 摘要和日志脱敏；
- 通用适配器输出。

### 19.2 集成测试

- FastAPI ASGI 客户端调用完整 API；
- `httpx.MockTransport` 模拟跳转、429、5xx、超时和大响应；
- 临时目录模拟 artifact；
- fake cache/database 隔离外部设施；
- PostgreSQL/Redis 适配器另设可选集成测试，通过环境变量启用。

### 19.3 冒烟测试

- 启动本地 ASGI 服务；
- 调用 live、ready；
- 抓取本地 fixture HTTP 服务；
- 验证缓存二次命中、artifact 和解析；
- 不访问互联网。

## 20. 首版实现边界

本轮开发交付一个可运行的 MVP，包含：

- API Key、请求 ID、统一错误；
- 同步 HTTP 抓取及 auto 判定；
- 可选 Playwright 抓取器接口；
- URL 安全检查；
- 内存/Redis 缓存抽象和同进程 singleflight；
- 域名限速、重试；
- artifact 文件存储；
- 通用文章和链接解析；
- 持久化任务的数据模型、仓储和 Worker；
- live/ready/metrics；
- PostgreSQL/Alembic 基线；
- systemd、安装脚本和 Jenkins Pipeline；
- 单元、API 集成及冒烟测试。

Profile 管理 UI、动态域名策略管理 API、分布式熔断和完整管理后台属于后续阶段，但其接口边界在首版中保留。

## 21. 需求追踪

| 需求区域 | 设计章节 | 首版状态 |
|---|---|---|
| API 认证 | 7、14 | 实现 |
| 同步抓取 | 5、10、14 | 实现 |
| 异步任务 | 3、5、13 | 实现 |
| 自动策略 | 5、10 | 实现 |
| 限速重试 | 9 | 实现 |
| 缓存去重 | 8 | 实现核心路径 |
| 代理 | 10、15 | 实现配置路径 |
| Profile | 7、10 | 实现隔离接口，管理能力后续 |
| 解析适配器 | 12 | 实现通用适配器 |
| 原始文件 | 11 | 实现 |
| 健康与指标 | 16 | 实现 |
| 原生部署 | 18 | 实现 |
