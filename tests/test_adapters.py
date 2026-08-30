from __future__ import annotations

import pytest

from webfetch_service.adapters import AdapterRegistry
from webfetch_service.core.errors import WebFetchError


async def test_generic_article_and_links() -> None:
    html = b"""<html><head><title>Page title</title><meta name="author" content="Alice"></head>
    <body><nav>noise</nav><article><h1>Headline</h1><p>Hello world</p>
    <a href="/next">Next</a></article></body></html>"""
    registry = AdapterRegistry()
    article = await registry.get("generic.article").extract(html, "https://example.com/a")
    links = await registry.get("generic.links").extract(html, "https://example.com/a")
    assert article["title"] == "Headline"
    assert "Hello world" in article["content"]
    assert article["author"] == "Alice"
    assert links["links"][0]["href"] == "https://example.com/next"


def test_unknown_adapter() -> None:
    with pytest.raises(WebFetchError) as caught:
        AdapterRegistry().get("missing")
    assert caught.value.code == "ADAPTER_NOT_FOUND"


async def test_generic_article_decodes_utf8_page_with_comment_before_html5_meta() -> None:
    """回归：新华网老页面在 <html> 前有含中文的注释，meta 用 HTML5 简写声明。

    lxml 对这种页面按 ISO-8859-1 解析会整体 mojibake（线上故障根因）。
    """
    html = (
        "<!-- * @time Wed Sep 28 2022 11:01:11 GMT+0800 (中国标准时间) -->\r\n"
        '<!DOCTYPE html>\r\n<html>\r\n<head>\r\n<meta charset="utf-8" />\r\n'
        "<title>中共中央政治局召开会议 习近平主持会议-新华网</title>\r\n</head>\r\n"
        "<body><article><p>新华社北京10月25日电 中共中央政治局召开会议。</p>"
        "<p>会议研究了其他事项。</p></article></body></html>"
    ).encode()

    article = await AdapterRegistry().get("generic.article").extract(html, "https://www.xinhuanet.com/a")

    assert article["title"] == "中共中央政治局召开会议 习近平主持会议-新华网"
    assert "中共中央政治局召开会议。" in article["content"]
    assert "ä¸­" not in article["content"]


async def test_generic_links_decodes_declared_gbk_page() -> None:
    html = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=gbk"></head>'
        "<body><a href='/a'>中共中央政治局会议</a></body></html>"
    ).encode("gbk")

    links = await AdapterRegistry().get("generic.links").extract(html, "https://example.com/")

    assert links["links"][0]["text"] == "中共中央政治局会议"


async def test_generic_article_decodes_utf8_page_without_charset_declaration() -> None:
    html = "<html><head><title>标题</title></head><body><main><p>正文内容</p></main></body></html>".encode()

    article = await AdapterRegistry().get("generic.article").extract(html, "https://example.com/a")

    assert article["title"] == "标题"


async def test_generic_article_survives_undecodable_bytes_with_latin1_fallback() -> None:
    html = b"<html><head><title>\xff\xfe</title></head><body>ok</body></html>"

    article = await AdapterRegistry().get("generic.article").extract(html, "https://example.com/a")

    assert "ok" in article["content"]


def test_decode_html_strips_xml_encoding_declaration() -> None:
    from webfetch_service.adapters.encoding import decode_html

    body = b'<?xml version="1.0" encoding="utf-8"?><html><body>ok</body></html>'
    decoded = decode_html(body)

    assert decoded.startswith("<?xml")
    assert "encoding" not in decoded
    assert "ok" in decoded
