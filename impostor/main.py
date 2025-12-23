from fastapi import FastAPI
from impostor.api.routes.rooms import rooms_router
from contextlib import asynccontextmanager
import redis.asyncio as redis
import os

from impostor.application.room_service import RoomService
from impostor.infrastructure.redis_room_store import RedisRoomStore
from impostor.infrastructure.ws_manager import WSManager


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
    app.include_router(rooms_router)

    return app


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = app_factory(REDIS_URL)
