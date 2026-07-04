from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import lxml.html

from webfetch_service.core.errors import WebFetchError

PROFILE_SELECTORS: dict[str, tuple[str, ...]] = {
    "cppcc.gov.cn": (".con", ".cnt_box"),
    "people.com.cn": (".p_content", ".rm_txt_con", ".text_con"),
    "news.cn": ("#detail", ".main-aticle", ".xl-main-content", ".article"),
}

BOUNDED_PERIOD = re.compile(r"^(?P<start>\d{4})(?:年)?\s*[－—–-]\s*(?P<end>\d{4})?年?\s*(?P<position>.+)$")
POINT_PERIOD = re.compile(r"^(?P<period>\d{4}(?:[.年]\d{1,2}(?:月)?)?)(?:起|\s+)(?P<position>.+)$")


class ChinaOfficialProfileAdapter:
    """Extract structured official biographies from common central-media layouts."""

    name = "china.official-profile"
    version = "1"

    async def extract(self, body: bytes, base_url: str) -> dict[str, Any]:
        try:
            tree = lxml.html.fromstring(self._decode_html(body))
        except (ValueError, lxml.etree.ParserError) as exc:
            raise WebFetchError("PARSE_FAILED", "HTML解析失败", 422) from exc

        host = (urlsplit(base_url).hostname or "").lower()
        container = self._find_container(tree, host)
        lines = self._extract_lines(container)
        if not lines:
            raise WebFetchError("PARSE_FAILED", "履历正文为空", 422)

        title = self._first_text(tree, "//h1//text() | //title/text()")
        name = self._profile_name(title, lines)
        summary = next((line for line in lines if name and line.startswith(f"{name}，")), "")
        current_position = next((line for line in lines if line.startswith("现任")), "")
        timeline = [item for line in lines if (item := self._timeline_item(line))]
        if not summary and not timeline:
            raise WebFetchError("PARSE_FAILED", "页面不包含可识别的履历字段", 422)

        return {
            "name": name,
            "title": title,
            "summary": summary,
            "current_position": current_position,
            "timeline": timeline,
            "source_url": base_url,
            "source_host": host,
        }

    @staticmethod
    def _decode_html(body: bytes) -> str:
        match = re.search(br"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)", body[:4096], re.IGNORECASE)
        encoding = match.group(1).decode("ascii") if match else "utf-8"
        try:
            return body.decode(encoding, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    @staticmethod
    def _find_container(tree, host: str):
        candidates: tuple[str, ...] = ()
        for domain, selectors in PROFILE_SELECTORS.items():
            if host == domain or host.endswith(f".{domain}"):
                candidates = selectors
                break
        for selector in candidates:
            matches = tree.cssselect(selector)
            if matches:
                return max(matches, key=lambda node: len(node.text_content()))
        for selector in ("article", "main", ".content", ".text"):
            matches = tree.cssselect(selector)
            if matches:
                return matches[0]
        return tree

    @staticmethod
    def _extract_lines(container) -> list[str]:
        for node in container.xpath(".//script|.//style|.//noscript"):
            node.drop_tree()
        paragraphs = container.xpath(".//p")
        raw_lines = [node.text_content() for node in paragraphs] if paragraphs else [container.text_content()]
        lines: list[str] = []
        for raw in raw_lines:
            for part in raw.splitlines():
                normalized = " ".join(part.replace("\xa0", " ").split()).strip()
                if normalized and normalized not in lines:
                    lines.append(normalized)
        return lines

    @staticmethod
    def _first_text(tree, expression: str) -> str:
        values = tree.xpath(expression)
        return " ".join(str(values[0]).split()) if values else ""

    @staticmethod
    def _profile_name(title: str, lines: list[str]) -> str:
        match = re.search(r"([\u4e00-\u9fff]{2,4})(?:同志)?简历", title)
        if match:
            return match.group(1)
        for line in lines:
            match = re.match(r"([\u4e00-\u9fff]{2,4})，(?:男|女)，", line)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _timeline_item(line: str) -> dict[str, str] | None:
        bounded = BOUNDED_PERIOD.match(line)
        if bounded:
            end = bounded.group("end") or "至今"
            return {
                "period": f"{bounded.group('start')}－{end}",
                "position": bounded.group("position").strip(),
            }
        point = POINT_PERIOD.match(line)
        if point:
            return {
                "period": point.group("period"),
                "position": point.group("position").strip(),
            }
        return None
