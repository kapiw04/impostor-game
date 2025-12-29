import secrets
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar, cast

from impostor.application.ports import Notifier, RoomStore
from impostor.domain.models import Room
from impostor.application.errors import RoomNotFoundError

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def room_exists(func: F) -> F:
    @wraps(func)
    async def wrapper(self: "RoomService", *args: Any, **kwargs: Any) -> Any:
        room_id = kwargs.get("room_id")
        if room_id is None:
            if not args:
                raise ValueError("room_id is required")
            room_id = args[0]
        if await self._store.get_room_name(room_id) is None:
            raise RoomNotFoundError(room_id)
        return await func(self, *args, **kwargs)

    return cast(F, wrapper)


class RoomService:
    def __init__(self, store: RoomStore):
        self._store = store

    def make_conn_id(self, n: int = 16) -> str:
        return secrets.token_hex(n // 2)

    async def get_room_name(self, room_id: str) -> str:
        room_name = await self._store.get_room_name(room_id)
        if room_name is None:
            raise RoomNotFoundError(room_id)
        return room_name

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

    @room_exists
    async def set_ready(
        self, room_id: str, conn_id: str, ready: bool
    ) -> dict[str, Any]:
        await self._store.set_ready(room_id, conn_id, ready)
        state = await self._store.get_lobby_state(room_id)
        if state is None:
            raise RoomNotFoundError(room_id)
        return state

    @room_exists
    async def get_lobby_state(self, room_id: str) -> dict[str, Any]:
        state = await self._store.get_lobby_state(room_id)
        if state is None:
            raise RoomNotFoundError(room_id)
        return state

    async def start_game(
        self, room_id: str, started_by: str, notifier: Notifier
    ) -> None:
        state = await self.get_lobby_state(room_id)
        if state["host"] != started_by:
            raise PermissionError("only host can start the game")
        players = state["players"].values()
        if not players or any(not player.get("ready") for player in players):
            raise RuntimeError("all players must be ready")
        await self._store.set_game_state(room_id, "in_progress")
        conns = await self._store.list_conns(room_id)
        await notifier.broadcast(conns, {"type": "game_started", "room_id": room_id})

    @room_exists
    async def end_game(
        self,
        room_id: str,
        notifier: Notifier,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = await self._store.end_game(room_id, result=result)
        conns = await self._store.list_conns(room_id)
        await notifier.broadcast(
            conns,
            {"type": "game_ended", "room_id": room_id, "result": result},
        )
        return result

    @room_exists
    async def disconnect(self, room_id: str, conn_id: str) -> str:
        token = await self._store.issue_resume_token(room_id, conn_id)
        await self._store.remove_conn(room_id, conn_id)
        return token

    async def reconnect(
        self, token: str, conn_id: str, notifier: Notifier
    ) -> dict[str, Any]:
        resume = await self._store.consume_resume_token(token)
        room_id = resume.get("room_id")
        if not room_id:
            raise KeyError(token)
        if await self._store.get_room_name(room_id) is None:
            raise RoomNotFoundError(room_id)
        nickname = resume.get("nickname")
        ready_value = resume.get("ready")
        ready = ready_value is True or ready_value == "1"
        await self._store.add_conn(room_id, conn_id, nickname=nickname)
        if ready:
            await self._store.set_ready(room_id, conn_id, True)
        state = await self.get_lobby_state(room_id)
        await notifier.send_to_conn(
            conn_id,
            {"type": "lobby_state", "room_id": room_id, "state": state},
        )
        return state
