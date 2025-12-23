from typing import Annotated

from fastapi import Depends
from fastapi.requests import HTTPConnection
import redis.asyncio as redis

from impostor.application.room_service import RoomService
from impostor.infrastructure.ws_manager import WSManager


def get_redis(conn: HTTPConnection) -> redis.Redis:
    return conn.app.state.redis


def get_room_service(conn: HTTPConnection) -> RoomService:
    return conn.app.state.room_service


def get_ws_manager(conn: HTTPConnection) -> WSManager:
    return conn.app.state.ws_manager


RedisDep = Annotated[redis.Redis, Depends(get_redis)]
RoomServiceDep = Annotated[RoomService, Depends(get_room_service)]
WSManagerDep = Annotated[WSManager, Depends(get_ws_manager)]
