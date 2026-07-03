"""解析工具 — 从 HTML 中提取内容。

提供通用正文提取、XPath/CSS 选择器、表格提取等能力。
与抓取逻辑完全解耦。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_text(html: str) -> str:
    """提取纯文本（去标签）。"""
    try:
        import lxml.html
        tree = lxml.html.fromstring(html)
        return tree.text_content().strip()
    except Exception:
        # 回退到正则
        import re
        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\s+", " ", text).strip()


def xpath_select(html: str, expression: str) -> list[str]:
    """XPath 选择器，返回匹配的文本列表。"""
    import lxml.html
    tree = lxml.html.fromstring(html)
    results = tree.xpath(expression)
    return [str(r) for r in results]


def css_select(html: str, selector: str) -> list[str]:
    """CSS 选择器，返回匹配元素的文本列表。"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        elements = soup.select(selector)
        return [el.get_text(strip=True) for el in elements]
    except ImportError:
        # 用 lxml 的 CSS 选择器
        import lxml.html
        tree = lxml.html.fromstring(html)
        elements = tree.cssselect(selector)
        return [el.text_content().strip() for el in elements]


def extract_article(html: str) -> dict[str, str]:
    """通用正文提取（自动去导航、广告等噪声）。

    Returns:
        {"title": ..., "content": ..., "author": ..., "date": ...}
    """
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata
    except ImportError:
        logger.warning("trafilatura 未安装，回退到基础提取")
        return {
            "title": _extract_title(html),
            "content": extract_text(html),
            "author": "",
            "date": "",
        }

    metadata = extract_metadata(html)
    content = trafilatura.extract(html, include_links=True, include_tables=True)

    return {
        "title": metadata.title if metadata else _extract_title(html),
        "content": content or extract_text(html),
        "author": metadata.author if metadata else "",
        "date": metadata.date if metadata else "",
    }


def extract_tables(html: str) -> list[list[list[str]]]:
    """提取所有表格，返回二维数组列表。"""
    try:
        import pandas as pd
        tables = pd.read_html(html)
        return [t.astype(str).values.tolist() for t in tables]
    except Exception:
        # 回退到 lxml 手动解析
        import lxml.html
        tree = lxml.html.fromstring(html)
        tables = []
        for table in tree.xpath("//table"):
            rows = []
            for tr in table.xpath(".//tr"):
                cells = [td.text_content().strip() for td in tr.xpath(".//td|.//th")]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables


def extract_links(html: str, base_url: str = "") -> list[dict[str, str]]:
    """提取所有链接。

    Returns:
        [{"text": ..., "href": ...}, ...]
    """
    import lxml.html
    tree = lxml.html.fromstring(html)
    if base_url:
        tree.make_links_absolute(base_url)
    links = []
    for el in tree.xpath("//a[@href]"):
        links.append({
            "text": el.text_content().strip(),
            "href": el.get("href", ""),
        })
    return links


def extract_meta(html: str) -> dict[str, str]:
    """提取 <meta> 标签信息。"""
    import lxml.html
    tree = lxml.html.fromstring(html)
    meta = {}
    for el in tree.xpath("//meta"):
        name = el.get("name") or el.get("property") or el.get("http-equiv")
        content = el.get("content")
        if name and content:
            meta[name] = content
    return meta


def _extract_title(html: str) -> str:
    """提取 <title> 标签内容。"""
    import lxml.html
    tree = lxml.html.fromstring(html)
    title = tree.xpath("//title/text()")
    return title[0].strip() if title else ""
