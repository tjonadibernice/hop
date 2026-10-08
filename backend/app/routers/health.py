import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 2.0


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


async def check_postgres(request: Request) -> str:
    """Return "ok" if Postgres answers SELECT 1 within the timeout, else "error"."""
    engine = request.app.state.engine

    async def run_query() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(run_query(), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.exception("Postgres health check failed")
        return "error"


async def check_redis(request: Request) -> str:
    """Return "ok" if Redis answers PING within the timeout, else "error"."""
    redis = request.app.state.redis

    try:
        await asyncio.wait_for(redis.ping(), timeout=CHECK_TIMEOUT_SECONDS)
        return "ok"
    except Exception:
        logger.exception("Redis health check failed")
        return "error"


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    postgres_status, redis_status = await asyncio.gather(
        check_postgres(request), check_redis(request)
    )

    checks = {"postgres": postgres_status, "redis": redis_status}
    if all(result == "ok" for result in checks.values()):
        return JSONResponse(status_code=200, content={"status": "ok", "checks": checks})

    return JSONResponse(
        status_code=503, content={"status": "degraded", "checks": checks}
    )
