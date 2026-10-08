from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import create_redis
from app.config import settings
from app.db import create_db_engine
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create shared connections once
    app.state.engine = create_db_engine(settings.database_url)
    app.state.redis = create_redis(settings.redis_url)

    yield  # the app serves requests while paused here

    # Shutdown: close connections cleanly
    await app.state.redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(title="Hop API", lifespan=lifespan)
app.include_router(health.router)
