from typing import Annotated
import secrets
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import redis.asyncio as redis
from ..deps import get_redis

rooms_router = APIRouter(prefix="/rooms")


class RoomIn(BaseModel):
    name: str


class RoomOut(BaseModel):
    room_id: str
    name: str


@rooms_router.post("/", response_model=RoomOut)
async def create_room(room_in: RoomIn, r: Annotated[redis.Redis, Depends(get_redis)]):
    def make_room_id(n: int = 8) -> str:
        ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        return "".join(secrets.choice(ALPHABET) for _ in range(n))

    room_id = make_room_id()
    room_out = RoomOut(room_id=room_id, name=room_in.name)
    await r.set(f"room:{room_id}", room_in.name)

    return room_out


@rooms_router.get("/{id:str}", response_model=RoomOut)
async def get_room(room_id: str, r: Annotated[redis.Redis, Depends(get_redis)]):
    room_name = await r.get(f"room:{room_id}")
    if not room_name:
        return JSONResponse("Room doesn't exist", status.HTTP_404_NOT_FOUND)
    return RoomOut(room_id=room_id, name=room_name)
