"""Embed approved pages that have no embedding yet, such as the seed pages.

The recommender needs embeddings to compare pages with a user's taste.
Pages approved by enrichment already have one; this fills in the rest.

Usage, from backend/:  uv run python -m scripts.embed_pages
"""

import asyncio

import httpx

from app.ai.embeddings import VoyageEmbedder
from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.ingestion.backfill import backfill_embeddings
from app.models import EMBEDDING_DIMENSIONS


async def main() -> None:
    if not settings.voyage_api_key:
        raise SystemExit("Set VOYAGE_API_KEY in .env first.")
    engine = create_db_engine(settings.database_url)
    async with httpx.AsyncClient(timeout=60) as client:
        embedder = VoyageEmbedder(
            client, settings.voyage_api_key, settings.voyage_model, EMBEDDING_DIMENSIONS
        )
        done = await backfill_embeddings(create_session_factory(engine), embedder)
    await engine.dispose()
    print(f"Embedded {done} pages.")


if __name__ == "__main__":
    asyncio.run(main())
