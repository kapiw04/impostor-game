import inspect
import json
import secrets
from typing import Any, Awaitable, TypeVar, cast
from redis.asyncio.client import Redis

T = TypeVar("T")
DEFAULT_SETTINGS: dict[str, int] = {"round_time": 60, "max_players": 8}


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

    def _room_host_key(self, room_id: str) -> str:
        return f"room:{room_id}:host"

    def _room_settings_key(self, room_id: str) -> str:
        return f"room:{room_id}:settings"

    def _room_state_key(self, room_id: str) -> str:
        return f"room:{room_id}:game_state"

    def _room_result_key(self, room_id: str) -> str:
        return f"room:{room_id}:game_result"

    def _room_word_key(self, room_id: str) -> str:
        return f"room:{room_id}:secret_word"

    def _room_impostor_key(self, room_id: str) -> str:
        return f"room:{room_id}:impostor"

    def _conn_key(self, conn_id: str) -> str:
        return f"conn:{conn_id}"

    def _resume_token_key(self, token: str) -> str:
        return f"resume:{token}"

    async def create_room(self, room_id: str, room_name: str) -> None:
        await _await(self._r.set(self._room_key(room_id), room_name))
        settings = {key: str(value) for key, value in DEFAULT_SETTINGS.items()}
        await _await(self._r.hset(self._room_settings_key(room_id), mapping=settings))
        await _await(self._r.set(self._room_state_key(room_id), "lobby"))

    async def get_room_name(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_key(room_id)))

    async def add_conn(
        self,
        room_id: str,
        conn_id: str,
        nickname: str | None = None,
        ready: bool = False,
    ) -> None:
        await _await(self._r.sadd(self._room_conns_key(room_id), conn_id))
        mapping: dict[str, Any] = {"room_id": room_id, "ready": "1" if ready else "0"}
        if nickname:
            mapping["nickname"] = nickname
        await _await(self._r.hset(self._conn_key(conn_id), mapping=mapping))
        await _await(self._r.setnx(self._room_host_key(room_id), conn_id))

    async def remove_conn(self, room_id: str, conn_id: str) -> None:
        await _await(self._r.srem(self._room_conns_key(room_id), conn_id))
        await _await(self._r.delete(self._conn_key(conn_id)))
        host_key = self._room_host_key(room_id)
        host = await _await(self._r.get(host_key))
        if host == conn_id:
            await _await(self._r.delete(host_key))
            remaining = await _await(self._r.smembers(self._room_conns_key(room_id)))
            if remaining:
                new_host = sorted(remaining)[0]
                await _await(self._r.set(host_key, new_host))

    async def list_conns(self, room_id: str) -> set[str]:
        return await _await(self._r.smembers(self._room_conns_key(room_id)))

    async def set_ready(self, room_id: str, conn_id: str, ready: bool) -> None:
        await _await(
            self._r.hset(
                self._conn_key(conn_id), mapping={"ready": "1" if ready else "0"}
            )
        )

    async def get_lobby_state(self, room_id: str) -> dict[str, Any] | None:
        room_name = await self.get_room_name(room_id)
        if room_name is None:
            return None
        conns = await self.list_conns(room_id)
        players: dict[str, dict[str, Any]] = {}
        for conn_id in conns:
            data = await _await(self._r.hgetall(self._conn_key(conn_id)))
            players[conn_id] = {
                "nick": data.get("nickname"),
                "ready": data.get("ready") == "1",
            }
        host = await _await(self._r.get(self._room_host_key(room_id)))
        raw_settings = await _await(self._r.hgetall(self._room_settings_key(room_id)))
        settings: dict[str, Any] = {**DEFAULT_SETTINGS}
        for key, value in raw_settings.items():
            if value.isdigit():
                settings[key] = int(value)
            else:
                settings[key] = value
        return {
            "room_id": room_id,
            "name": room_name,
            "players": players,
            "host": host,
            "settings": settings,
        }

    async def set_game_state(self, room_id: str, state: str) -> None:
        await _await(self._r.set(self._room_state_key(room_id), state))

    async def get_game_state(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_state_key(room_id)))

    async def end_game(
        self, room_id: str, result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if result is None:
            result = {"reason": "win_condition"}
        await self.set_game_state(room_id, "ended")
        await _await(self._r.set(self._room_result_key(room_id), json.dumps(result)))
        return result

    async def set_secret_word(self, room_id: str, word: str) -> None:
        await _await(self._r.set(self._room_word_key(room_id), word))

    async def get_secret_word(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_word_key(room_id)))

    async def set_impostor(self, room_id: str, conn_id: str) -> None:
        await _await(self._r.set(self._room_impostor_key(room_id), conn_id))

    async def set_role(self, room_id: str, conn_id: str, role: str) -> None:
        del room_id
        await _await(self._r.hset(self._conn_key(conn_id), mapping={"role": role}))

    async def clear_roles(self, room_id: str) -> None:
        conns = await self.list_conns(room_id)
        for conn_id in conns:
            await _await(self._r.hdel(self._conn_key(conn_id), "role"))
        await _await(self._r.delete(self._room_word_key(room_id)))
        await _await(self._r.delete(self._room_impostor_key(room_id)))

    async def issue_resume_token(self, room_id: str, conn_id: str) -> str:
        data = await _await(self._r.hgetall(self._conn_key(conn_id)))
        token = secrets.token_urlsafe(24)
        mapping: dict[str, Any] = {"room_id": room_id}
        if "nickname" in data:
            mapping["nickname"] = data["nickname"]
        if "ready" in data:
            mapping["ready"] = data["ready"]
        if "role" in data:
            mapping["role"] = data["role"]
        await _await(self._r.hset(self._resume_token_key(token), mapping=mapping))
        return token

    async def consume_resume_token(self, token: str) -> dict[str, Any]:
        key = self._resume_token_key(token)
        data = await _await(self._r.hgetall(key))
        if not data:
            raise KeyError(token)
        await _await(self._r.delete(key))
        if "ready" in data:
            data["ready"] = data["ready"] == "1"
        return data
