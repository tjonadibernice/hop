"""Queue URLs for the ingestion worker.

The file has one URL per line; blank lines and lines starting with # are skipped.

Usage, from backend/:  uv run python -m scripts.enqueue_urls scripts/sources.txt
"""

import asyncio
import sys
from pathlib import Path

from app.ingestion.urls import InvalidUrlError, canonicalize_url
from app.worker import broker, ingest_url_task


def read_urls(path: Path) -> list[str]:
    lines = (line.strip() for line in path.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


async def main(path: Path) -> None:
    await broker.startup()
    queued = skipped = 0
    seen: set[str] = set()
    for url in read_urls(path):
        try:
            canonical = canonicalize_url(url)
        except InvalidUrlError as error:
            print(f"skipped  {error}")
            skipped += 1
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        await ingest_url_task.kiq(canonical)
        queued += 1
    await broker.shutdown()
    print(f"Queued {queued} URLs ({skipped} skipped). Watch the worker's log.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.enqueue_urls FILE")
    asyncio.run(main(Path(sys.argv[1])))
