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
