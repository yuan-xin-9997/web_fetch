from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urljoin

import lxml.html

from webfetch_service.core.errors import WebFetchError


class Adapter(Protocol):
    name: str
    version: str

    async def extract(self, body: bytes, base_url: str) -> dict[str, Any]: ...


class GenericArticleAdapter:
    name = "generic.article"
    version = "1"

    async def extract(self, body: bytes, base_url: str) -> dict[str, Any]:
        try:
            tree = lxml.html.fromstring(body)
        except (ValueError, lxml.etree.ParserError) as exc:
            raise WebFetchError("PARSE_FAILED", "HTML解析失败", 422) from exc
        for node in tree.xpath("//script|//style|//noscript|//nav|//footer"):
            node.drop_tree()
        title = "".join(tree.xpath("//title/text()")[:1]).strip()
        h1 = "".join(tree.xpath("//h1[1]//text()")[:1]).strip()
        article_nodes = tree.xpath("//article") or tree.xpath("//main") or tree.xpath("//body")
        content = article_nodes[0].text_content().strip() if article_nodes else tree.text_content().strip()
        author = "".join(tree.xpath("//meta[@name='author']/@content | //*[@rel='author'][1]//text()")[:1]).strip()
        date = "".join(
            tree.xpath("//meta[@property='article:published_time']/@content | //time[1]/@datetime")[:1]
        ).strip()
        return {"title": h1 or title, "content": " ".join(content.split()), "author": author, "date": date}


class GenericLinksAdapter:
    name = "generic.links"
    version = "1"

    async def extract(self, body: bytes, base_url: str) -> dict[str, Any]:
        try:
            tree = lxml.html.fromstring(body)
        except (ValueError, lxml.etree.ParserError) as exc:
            raise WebFetchError("PARSE_FAILED", "HTML解析失败", 422) from exc
        return {
            "links": [
                {"text": " ".join(node.text_content().split()), "href": urljoin(base_url, node.get("href"))}
                for node in tree.xpath("//a[@href]")
            ]
        }


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], Adapter] = {}
        self.register(GenericArticleAdapter())
        self.register(GenericLinksAdapter())

    def register(self, adapter: Adapter) -> None:
        self._adapters[(adapter.name, adapter.version)] = adapter

    def get(self, name: str, version: str = "latest") -> Adapter:
        versions = [key[1] for key in self._adapters if key[0] == name]
        resolved = max(versions, key=int) if version == "latest" and versions else version
        adapter = self._adapters.get((name, resolved))
        if adapter is None:
            raise WebFetchError("ADAPTER_NOT_FOUND", "适配器不存在", 404)
        return adapter
