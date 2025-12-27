from fastapi import FastAPI
from impostor.api.routes.rooms import rooms_router
from contextlib import asynccontextmanager
import redis.asyncio as redis
import os

from impostor.application.room_service import RoomService
from impostor.infrastructure.redis_room_store import RedisRoomStore
from impostor.infrastructure.ws_manager import WSManager
from impostor.logging_config import setup_logging, get_logger
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

setup_logging()
logger = get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def app_factory(redis_url):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.redis = redis.from_url(
            redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
        app.state.ws_manager = WSManager()
        app.state.room_store = RedisRoomStore(app.state.redis)
        app.state.room_service = RoomService(app.state.room_store)
        try:
            yield
        finally:
            await app.state.redis.aclose()

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(CorrelationMiddleware)
    app.include_router(rooms_router)

    logger.info("Application initialized")

    return app


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = app_factory(REDIS_URL)
