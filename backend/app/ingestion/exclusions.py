"""Take pages from excluded sites (excluded_sites.txt) out of the library.

New pages from those sites are never stored (see pipeline.py), but pages
collected before a site was excluded are still there. This retires them.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.safety import EXCLUDED_SITES, is_excluded
from app.models import Page

# Pages that are shown, or could be after screening or review
ACTIVE_STATUSES = ("approved", "pending", "needs_review")


async def retire_excluded_pages(
    session: AsyncSession, excluded: frozenset[str] = EXCLUDED_SITES
) -> int:
    """Reject every active page on an excluded site. Returns how many.

    The rows stay, so the crawler treats the URLs as known and never fetches
    them again. Queued hops skip them (each entry is re-checked when served).
    """
    pages = await session.scalars(
        select(Page).where(Page.status.in_(ACTIVE_STATUSES), Page.purged_at.is_(None))
    )
    retired = 0
    for page in pages:
        if is_excluded(page.url, excluded):
            page.status = "rejected"
            page.status_reason = f"excluded site ({page.site})"
            page.next_check_at = None
            retired += 1
    await session.commit()
    return retired
