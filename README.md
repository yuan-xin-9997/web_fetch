# webfetch

通用网页抓取共享库。所有项目共享同一份抓取代码和缓存。

## 特性

- 🚀 **自动策略选择** — 优先 httpx 快速抓取，需要时降级 Playwright 浏览器渲染
- 💾 **内置缓存** — 文件缓存（默认）/ Redis，避免重复请求
- ⏱️ **按域名限速** — 防止被封，每个域名独立控制
- 🔄 **自动重试** — 指数退避 + 随机抖动
- 🎭 **UA 轮换** — 内置 7 个 User-Agent 随机使用
- 📄 **内容解析** — 正文提取、XPath/CSS 选择器、表格提取、链接提取
- 🔗 **并发抓取** — `get_many()` 多线程并发

## 安装

```bash
cd ~/src/webfetch
pip install -e .

# 可选依赖（按需安装）
pip install -e ".[browser]"   # Playwright JS 渲染
pip install -e ".[parser]"    # trafilatura 正文提取
pip install -e ".[redis]"     # Redis 缓存
pip install -e ".[all]"       # 全部安装
```

## 快速使用

```python
from webfetch import Fetcher

# 创建抓取器（配置全局共享）
fetcher = Fetcher(
    cache_dir="~/.cache/webfetch",  # 缓存目录
    cache_ttl=3600,                  # 缓存 1 小时
    rate_interval=1.0,               # 同域名间隔 1 秒
)

# 抓取
result = fetcher.get("https://example.com")
print(result.status_code)
print(result.body[:500])
print(result.from_cache)  # 是否来自缓存

# JS 渲染抓取（慢，仅必要时）
result = fetcher.get("https://spa-app.com", render_js=True)

# 并发抓取
results = fetcher.get_many([
    "https://example.com/page1",
    "https://example.com/page2",
    "https://example.com/page3",
], concurrency=3)

# 强制刷新（跳过缓存）
result = fetcher.get("https://example.com", force_refresh=True)
```

## 内容解析

```python
from webfetch.parser import extract_article, xpath_select, extract_tables

# 通用正文提取（自动去导航/广告）
article = extract_article(html)
# {"title": "...", "content": "...", "author": "...", "date": "..."}

# XPath
titles = xpath_select(html, "//h1/text()")

# CSS 选择器
items = css_select(html, ".article-list .title")

# 表格
tables = extract_tables(html)

# 链接
from webfetch.parser import extract_links
links = extract_links(html, base_url="https://example.com")
```

## 自定义配置

```python
# 按域名限速
fetcher = Fetcher(
    rate_interval=1.0,
    rate_per_domain={
        "example.com": 3.0,    # 慢一点
        "api.github.com": 0.5,  # 快一点
    },
)

# 使用代理
fetcher = Fetcher(proxy="http://127.0.0.1:7890")

# Redis 缓存（多进程共享）
fetcher = Fetcher(
    cache_backend="redis",
    redis_url="redis://192.168.0.100:6379/0",
)

# 自定义请求头
fetcher = Fetcher(default_headers={
    "Authorization": "Bearer xxx",
})

# 每次请求额外头
result = fetcher.get(url, headers={"X-Custom": "value"})
```

## 架构

```
URL → 缓存检查 → 限速等待 → 抓取(httpx/Playwright) → 重试 → 缓存写入 → 返回
```

| 模块 | 职责 |
|------|------|
| `fetcher.py` | 核心抓取器，统一接口 |
| `cache.py` | 缓存层（文件/Redis） |
| `rate_limit.py` | 按域名限速 |
| `parser.py` | 内容解析（正文/XPath/表格/链接） |
| `utils.py` | UA 池、重试、默认头 |
