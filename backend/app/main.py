from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import create_redis
from app.config import settings
from app.db import create_db_engine, create_session_factory
from app.email import SmtpEmailSender
from app.routers import auth, health, hop, interests, topics


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create shared connections once
    app.state.engine = create_db_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = create_redis(settings.redis_url)
    app.state.email_sender = SmtpEmailSender(
        settings.smtp_host,
        settings.smtp_port,
        settings.mail_from,
    )

    yield  # the app serves requests while paused here

    # Shutdown: close connections cleanly
    await app.state.redis.aclose()
    await app.state.engine.dispose()


app = FastAPI(title="Hop API", lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(topics.router)
app.include_router(interests.router)
app.include_router(hop.router)
