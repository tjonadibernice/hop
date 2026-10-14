"""Pull the main article text and metadata out of a page's HTML."""

import json
from dataclasses import dataclass
from urllib.parse import urljoin

import lxml.html
import trafilatura
from lxml.etree import ParserError


@dataclass(frozen=True)
class Extracted:
    title: str | None
    text: str
    canonical_url: str | None  # from <link rel="canonical">, if any
    word_count: int


def canonical_link(html: bytes, url: str) -> str | None:
    """The page's own <link rel="canonical" href="...">, as an absolute URL."""
    try:
        document = lxml.html.fromstring(html)
    except (ParserError, ValueError):
        return None
    for link in document.iter("link"):
        rels = (link.get("rel") or "").lower().split()
        href = (link.get("href") or "").strip()
        if "canonical" in rels and href:
            return urljoin(url, href)
    return None


def extract_article(html: bytes, url: str) -> Extracted | None:
    """The page's main text without menus, ads, and footers, or None if there's none."""
    raw = trafilatura.extract(
        html,
        url=url,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    if raw is None:
        return None
    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    if not text:
        return None
    return Extracted(
        title=(data.get("title") or "").strip() or None,
        text=text,
        canonical_url=canonical_link(html, url),
        word_count=len(text.split()),
    )
