import os
from pathlib import Path
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from impostor.api.routes.game import game_router
from impostor.api.routes.rooms import rooms_router
from impostor.application.game_service import GameService
from impostor.application.room_service import RoomService
from impostor.config import Config
from impostor.env import load_env_file
from impostor.infrastructure.redis_room_store import RedisRoomStore
from impostor.infrastructure.ws_manager import WSManager


def app_factory(redis_url):
    config = Config.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.redis = redis.from_url(
            redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
        app.state.config = config
        app.state.ws_manager = WSManager()
        app.state.room_store = RedisRoomStore(app.state.redis, config=config)
        app.state.room_service = RoomService(app.state.room_store)
        app.state.game_service = GameService(app.state.room_store, config=config)
        try:
            yield
        finally:
            await app.state.redis.aclose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(rooms_router)
    app.include_router(game_router)
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")

    return app


load_env_file()
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

app = app_factory(REDIS_URL)
