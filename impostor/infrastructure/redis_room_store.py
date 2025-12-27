import inspect
from typing import Any, Awaitable, TypeVar, cast
from redis.asyncio.client import Redis

from impostor.domain.models import Room, Player, RoomSettings

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

    async def create_room(
        self, room_id: str, room_name: str, settings: RoomSettings
    ) -> None:
        await _await(
            self._r.hset(
                self._room_key(room_id),
                mapping={"name": room_name, "max_players": settings.max_players},
            )
        )

    async def get_room(self, room_id: str) -> Room | None:
        room_data = await _await(self._r.hgetall(self._room_key(room_id)))
        if not room_data:
            return None

        conns = await self.list_conns(room_id)
        players = []
        for conn_id in conns:
            nick = await self.get_conn_nickname(conn_id)
            players.append(Player(conn_id=conn_id, nickname=nick or "Unknown"))

        return Room(
            room_id=room_id,
            name=room_data.get("name", "Unknown"),
            host_id=room_data.get("host_id"),
            settings=RoomSettings(max_players=int(room_data.get("max_players", 10))),
            players=players,
        )

    async def update_room(self, room_id: str, **kwargs) -> None:
        await _await(self._r.hset(self._room_key(room_id), mapping=kwargs))

    async def delete_room(self, room_id: str) -> None:
        conns = await self.list_conns(room_id)
        for conn_id in conns:
            await self.remove_conn(room_id, conn_id)
        await _await(self._r.delete(self._room_key(room_id)))

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
        return set(await _await(self._r.smembers(self._room_conns_key(room_id))))

    async def get_conn_nickname(self, conn_id: str) -> str | None:
        return await _await(self._r.hget(self._conn_key(conn_id), "nickname"))
