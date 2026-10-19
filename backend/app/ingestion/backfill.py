"""Embed pages that don't have an embedding yet (for example, the seed pages)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from app.ai.embeddings import VoyageEmbedder
from app.ingestion.enrich import MAX_CONTENT_CHARS
from app.models import Page

BATCH_SIZE = 64


def embedding_text(page: Page) -> str:
    """The same text enrichment embeds: title, summary, and the start of the article."""
    parts = [page.title, page.summary or "", (page.content or "")[:MAX_CONTENT_CHARS]]
    return "\n\n".join(part for part in parts if part)


async def backfill_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
    embedder: VoyageEmbedder,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Embed approved pages that have no embedding, in batches. Returns how many."""
    done = 0
    while True:
        async with session_factory() as session:
            pages = list(
                await session.scalars(
                    select(Page)
                    .where(Page.status == "approved", Page.embedding.is_(None))
                    .order_by(Page.created_at)
                    .limit(batch_size)
                    .options(undefer(Page.content))
                )
            )
            if not pages:
                return done
            vectors = await embedder.embed_documents([embedding_text(p) for p in pages])
            for page, vector in zip(pages, vectors, strict=True):
                page.embedding = vector
            await session.commit()
            done += len(pages)
