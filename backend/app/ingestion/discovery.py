"""Link discovery: grow the library from the links inside good pages.

When a page is approved, the links in its article text become candidates.
Limits keep this from turning into an unbounded crawl:

- Depth: only pages added by hand, from feeds, or as seeds (depth 0) share
  their links. Pages found through links (depth 1) don't, so discovery stops
  one step away from pages a person or a feed chose.
- At most 10 links per page, and at most 3 of them to any one site.
- At most 50 pages per site in the library, so no single site takes over.
- Skipped: known pages, blocked domains, social and video sites, and links
  to files (PDFs, images, archives).
"""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.ingestion.safety import EXCLUDED_SITES, is_blocked
from app.ingestion.urls import InvalidUrlError, canonicalize_url, site_of
from app.models import Page

MAX_DEPTH = 1
MAX_STORED_LINKS = 50  # kept per page at ingestion time
MAX_LINKS_PER_PAGE = 10
MAX_LINKS_PER_SITE_PER_PAGE = 3
MAX_PAGES_PER_SITE = 50

# Sites whose pages are posts, videos, or profiles rather than articles
SKIP_SITES = frozenset(
    {
        "twitter.com",
        "x.com",
        "facebook.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "youtu.be",
        "tiktok.com",
        "reddit.com",
        "pinterest.com",
        "t.me",
    }
)
SKIP_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".mp3",
        ".mp4",
        ".zip",
        ".gz",
        ".tar",
        ".exe",
        ".dmg",
        ".csv",
        ".xlsx",
        ".docx",
        ".pptx",
    }
)


def choose_links(
    page_url: str, links: list[str], blocklist: frozenset[str]
) -> list[str]:
    """Pick the candidate links worth queuing, in page order (pure, no I/O)."""
    page_canonical = canonicalize_url(page_url)
    chosen: list[str] = []
    per_site: dict[str, int] = {}
    for link in links:
        try:
            canonical = canonicalize_url(link)
        except InvalidUrlError:
            continue
        site = site_of(canonical)
        extension = PurePosixPath(urlsplit(canonical).path).suffix.lower()
        if (
            canonical == page_canonical
            or canonical in chosen
            or extension in SKIP_EXTENSIONS
            or is_blocked(site, SKIP_SITES)
            or is_blocked(site, EXCLUDED_SITES)
            or is_blocked(site, blocklist)
            or per_site.get(site, 0) >= MAX_LINKS_PER_SITE_PER_PAGE
        ):
            continue
        per_site[site] = per_site.get(site, 0) + 1
        chosen.append(canonical)
        if len(chosen) == MAX_LINKS_PER_PAGE:
            break
    return chosen


async def links_to_queue(
    session: AsyncSession, page_id, blocklist: frozenset[str]
) -> tuple[list[str], int]:
    """The links an approved page should share, and the depth they get.

    Each page shares its links once: links_queued_at is set even when nothing
    qualifies, so a later link check doesn't queue them again.
    """
    page = await session.get(Page, page_id, options=[undefer(Page.outlinks)])
    if (
        page is None
        or page.status != "approved"
        or page.depth >= MAX_DEPTH
        or page.links_queued_at is not None
        or page.outlinks is None
    ):
        return [], 0

    candidates = choose_links(page.url, page.outlinks, blocklist)
    known = (
        set(
            await session.scalars(
                select(Page.canonical_url).where(Page.canonical_url.in_(candidates))
            )
        )
        if candidates
        else set()
    )
    sites = {site_of(url) for url in candidates}
    counts = (
        dict(
            (
                await session.execute(
                    select(Page.site, func.count())
                    .where(Page.site.in_(sites))
                    .group_by(Page.site)
                )
            ).all()
        )
        if sites
        else {}
    )

    chosen = [
        url
        for url in candidates
        if url not in known and counts.get(site_of(url), 0) < MAX_PAGES_PER_SITE
    ]
    page.links_queued_at = datetime.now(UTC)
    await session.commit()
    return chosen, page.depth + 1
