from impostor.domain.models import Room
import secrets
from impostor.application.errors import RoomNotFoundError
from impostor.infrastructure.redis_room_store import RedisRoomStore


class RoomService:
    def __init__(self, store: RedisRoomStore):
        self._store = store

    def make_conn_id(self, n: int = 16) -> str:
        return secrets.token_hex(n // 2)

    def _make_room_id(self, n: int = 8) -> str:
        ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        return "".join(secrets.choice(ALPHABET) for _ in range(n))

    async def create_room(self, room_name: str) -> Room:
        room_id = self._make_room_id()
        await self._store.create_room(room_id, room_name)
        return Room(room_id, room_name)

    async def join_room(
        self, room_id: str, conn_id: str, nickname: str | None = None
    ) -> tuple[str, set[str]]:
        room_name = await self._store.get_room_name(room_id)
        if room_name is None:
            raise RoomNotFoundError(room_id)

        await self._store.add_conn(room_id, conn_id, nickname=nickname)
        conns = await self._store.list_conns(room_id)
        return room_name, conns

    async def leave_room(self, room_id: str, conn_id: str) -> None:
        await self._store.remove_conn(room_id, conn_id)
