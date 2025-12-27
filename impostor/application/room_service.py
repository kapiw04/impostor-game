from impostor.domain.models import Room, RoomSettings
import secrets
from impostor.application.errors import RoomNotFoundError, RoomFullError
from impostor.infrastructure.redis_room_store import RedisRoomStore


class RoomService:
    def __init__(self, store: RedisRoomStore):
        self._store = store

    def make_conn_id(self, n: int = 16) -> str:
        return secrets.token_hex(n // 2)

    def _make_room_id(self, n: int = 8) -> str:
        ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
        return "".join(secrets.choice(ALPHABET) for _ in range(n))

    async def create_room(self, room_name: str, max_players: int = 10) -> Room:
        room_id = self._make_room_id()
        settings = RoomSettings(max_players=max_players)
        await self._store.create_room(room_id, room_name, settings)
        return Room(room_id, room_name, settings=settings)

    async def join_room(
        self, room_id: str, conn_id: str, nickname: str | None = None
    ) -> Room:
        room = await self._store.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        if len(room.players or []) >= room.settings.max_players:
            raise RoomFullError(room_id)

        await self._store.add_conn(room_id, conn_id, nickname=nickname)

        if room.host_id is None:
            await self._store.update_room(room_id, host_id=conn_id)

        return await self._store.get_room(room_id)

    async def leave_room(self, room_id: str, conn_id: str) -> None:
        room = await self._store.get_room(room_id)
        if not room:
            return

        await self._store.remove_conn(room_id, conn_id)

        if room.host_id == conn_id:
            await self._store.delete_room(room_id)

    async def kick_player(self, room_id: str, host_id: str, target_conn_id: str) -> None:
        room = await self._store.get_room(room_id)
        if not room or room.host_id != host_id:
            raise Exception("Unauthorized or room not found")

        await self._store.remove_conn(room_id, target_conn_id)

    async def update_room_settings(
        self, room_id: str, host_id: str, max_players: int
    ) -> None:
        room = await self._store.get_room(room_id)
        if not room or room.host_id != host_id:
            raise Exception("Unauthorized or room not found")

        await self._store.update_room(room_id, max_players=max_players)
