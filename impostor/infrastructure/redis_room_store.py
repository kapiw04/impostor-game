import inspect
from typing import Any, Awaitable, TypeVar, cast
from redis.asyncio.client import Redis

T = TypeVar("T")


async def _await(x: T | Awaitable[T]) -> T:
    if inspect.isawaitable(x):
        return await cast(Awaitable[T], x)
    return x


class RedisRoomStore:
    def __init__(self, r: Redis):
        self._r = r

    def _room_key(self, room_id: str) -> str:
        return f"room:{room_id}"

    def _room_conns_key(self, room_id: str) -> str:
        return f"room:{room_id}:conns"

    def _conn_key(self, conn_id: str) -> str:
        return f"conn:{conn_id}"

    async def create_room(self, room_id: str, room_name: str) -> None:
        await _await(self._r.set(self._room_key(room_id), room_name))

    async def get_room_name(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_key(room_id)))

    async def add_conn(
        self, room_id: str, conn_id: str, nickname: str | None = None
    ) -> None:
        await _await(self._r.sadd(self._room_conns_key(room_id), conn_id))
        mapping: dict[str, Any] = {"room_id": room_id}
        if nickname:
            mapping["nickname"] = nickname
        await _await(self._r.hset(self._conn_key(conn_id), mapping=mapping))

    async def remove_conn(self, room_id: str, conn_id: str) -> None:
        await _await(self._r.srem(self._room_conns_key(room_id), conn_id))
        await _await(self._r.delete(self._conn_key(conn_id)))

    async def list_conns(self, room_id: str) -> set[str]:
        return await _await(self._r.smembers(self._room_conns_key(room_id)))
