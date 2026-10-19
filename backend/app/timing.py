import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ServerTimingMiddleware:
    """Add how long the app spent on each request: "Server-Timing: app;dur=12.3".

    Browsers show it in the Network tab, and the load test compares it with
    the total time to see how much was work and how much was waiting.

    It's a plain ASGI middleware rather than @app.middleware("http"), which
    wraps every request in extra tasks and costs noticeable CPU under load.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()

        async def send_with_timing(message: Message) -> None:
            if message["type"] == "http.response.start":
                duration_ms = (time.perf_counter() - started) * 1000
                headers = MutableHeaders(scope=message)
                headers.append("Server-Timing", f"app;dur={duration_ms:.1f}")
            await send(message)

        await self.app(scope, receive, send_with_timing)
