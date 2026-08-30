"""HTML text decoding for adapters.

lxml's HTML parser falls back to ISO-8859-1 for BOM-less documents whose
charset declaration it does not recognise (notably the HTML5 shorthand
``<meta charset="utf-8">`` preceded by content such as comments), which turns
whole UTF-8 pages into mojibake. Adapters therefore decode the payload to text
explicitly before handing it to lxml.
"""

from __future__ import annotations

import codecs
import re

_META_CHARSET = re.compile(rb"<meta[^>]*charset\s*=\s*['\"]?\s*([a-zA-Z0-9._:-]+)", re.IGNORECASE)

_XML_ENCODING_DECLARATION = re.compile(r"^\s*<\?xml[^>]*?\sencoding\s*=\s*(['\"])[^'\"]*\1", re.IGNORECASE)

_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def decode_html(body: bytes) -> str:
    """Decode an HTML payload using BOM, declared charset, or UTF-8 sniffing."""
    return _strip_xml_encoding(_decode_payload(body))


def _decode_payload(body: bytes) -> str:
    for bom, encoding in _BOMS:
        if body.startswith(bom):
            return body.decode(encoding, errors="replace")

    declared = _declared_charset(body[:4096])
    attempts: list[str] = []
    if declared is not None:
        attempts.append(declared)
    attempts.append("utf-8")
    for encoding in attempts:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue

    if declared is not None and declared != "utf-8":
        return body.decode(declared, errors="replace")
    return body.decode("latin-1", errors="replace")


def _declared_charset(head: bytes) -> str | None:
    match = _META_CHARSET.search(head)
    if match is None:
        return None
    charset = match.group(1).decode("ascii", errors="ignore").strip().lower()
    if not charset:
        return None
    try:
        codecs.lookup(charset)
    except LookupError:
        return None
    return charset


def _strip_xml_encoding(text: str) -> str:
    """Drop an XML encoding declaration; the payload is already decoded."""
    if text.lstrip().startswith("<?xml"):
        return _XML_ENCODING_DECLARATION.sub("<?xml", text, count=1)
    return text


__all__ = ["decode_html"]
