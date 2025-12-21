from fastapi import FastAPI
from .api.routes.rooms import rooms_router
from contextlib import asynccontextmanager
import redis.asyncio as redis


REDIS_URL = "redis://redis:6379/0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(
        REDIS_URL,
        decode_responses=True,
        health_check_interval=30,
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)

app.include_router(rooms_router)
