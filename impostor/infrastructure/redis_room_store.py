import inspect
import json
import secrets
from typing import Any, Awaitable, TypeVar, cast
from redis.asyncio.client import Redis

from impostor.config import Config

T = TypeVar("T")


async def _await(x: T | Awaitable[T]) -> T:
    if inspect.isawaitable(x):
        return await cast(Awaitable[T], x)
    return x


class RedisRoomStore:
    def __init__(self, r: Redis, config: Config | None = None):
        self._r = r
        self._default_settings = (
            config or Config()
        ).redis_room_store.settings.as_dict()
        self._turn_state_cache: dict[str, dict[str, Any]] = {}
        self._room_conns_cache: dict[str, set[str]] = {}

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

    def _room_votes_key(self, room_id: str) -> str:
        return f"room:{room_id}:votes"

    def _turn_order_key(self, room_id: str) -> str:
        return f"room:{room_id}:turn_order"

    def _turn_state_key(self, room_id: str) -> str:
        return f"room:{room_id}:turn_state"

    def _turn_words_key(self, room_id: str) -> str:
        return f"room:{room_id}:turn_words"

    def _word_history_key(self, room_id: str) -> str:
        return f"room:{room_id}:word_history"

    def _conn_key(self, conn_id: str) -> str:
        return f"conn:{conn_id}"

    def _resume_token_key(self, token: str) -> str:
        return f"resume:{token}"

    async def create_room(self, room_id: str, room_name: str) -> None:
        await _await(self._r.set(self._room_key(room_id), room_name))
        settings = {key: str(value) for key, value in self._default_settings.items()}
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
        self._room_conns_cache.setdefault(room_id, set()).add(conn_id)
        mapping: dict[str, Any] = {"room_id": room_id, "ready": "1" if ready else "0"}
        if nickname:
            mapping["nickname"] = nickname
        await _await(self._r.hset(self._conn_key(conn_id), mapping=mapping))
        await _await(self._r.setnx(self._room_host_key(room_id), conn_id))

    async def set_nickname(
        self, room_id: str, conn_id: str, nickname: str
    ) -> None:
        del room_id
        await _await(
            self._r.hset(self._conn_key(conn_id), mapping={"nickname": nickname})
        )

    async def remove_conn(self, room_id: str, conn_id: str) -> None:
        await _await(self._r.srem(self._room_conns_key(room_id), conn_id))
        cache = self._room_conns_cache.get(room_id)
        if cache is not None:
            cache.discard(conn_id)
            if not cache:
                self._room_conns_cache.pop(room_id, None)
        await _await(self._r.delete(self._conn_key(conn_id)))
        host_key = self._room_host_key(room_id)
        host = await _await(self._r.get(host_key))
        if host == conn_id:
            await _await(self._r.delete(host_key))
            remaining = await self.list_conns(room_id)
            if remaining:
                new_host = sorted(remaining)[0]
                await _await(self._r.set(host_key, new_host))

    async def list_conns(self, room_id: str) -> set[str]:
        cached = self._room_conns_cache.get(room_id)
        if cached is not None:
            return set(cached)
        conns = await _await(self._r.smembers(self._room_conns_key(room_id)))
        self._room_conns_cache[room_id] = set(conns)
        return set(conns)

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
        settings = await self.get_room_settings(room_id)
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

    async def get_room_settings(self, room_id: str) -> dict[str, Any]:
        raw_settings = await _await(self._r.hgetall(self._room_settings_key(room_id)))
        settings: dict[str, Any] = {**self._default_settings}
        for key, value in raw_settings.items():
            if value.isdigit():
                settings[key] = int(value)
            else:
                settings[key] = value
        return settings

    async def set_room_settings(self, room_id: str, settings: dict[str, Any]) -> None:
        mapping = {key: str(value) for key, value in settings.items()}
        await _await(self._r.hset(self._room_settings_key(room_id), mapping=mapping))

    async def set_secret_word(self, room_id: str, word: str) -> None:
        await _await(self._r.set(self._room_word_key(room_id), word))

    async def get_secret_word(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_word_key(room_id)))

    async def set_impostor(self, room_id: str, conn_id: str) -> None:
        await _await(self._r.set(self._room_impostor_key(room_id), conn_id))

    async def get_impostor(self, room_id: str) -> str | None:
        return await _await(self._r.get(self._room_impostor_key(room_id)))

    async def set_role(self, room_id: str, conn_id: str, role: str) -> None:
        del room_id
        await _await(self._r.hset(self._conn_key(conn_id), mapping={"role": role}))

    async def clear_roles(self, room_id: str) -> None:
        conns = await self.list_conns(room_id)
        for conn_id in conns:
            await _await(self._r.hdel(self._conn_key(conn_id), "role"))
        await _await(self._r.delete(self._room_word_key(room_id)))
        await _await(self._r.delete(self._room_impostor_key(room_id)))

    async def set_turn_order(self, room_id: str, order: list[str]) -> None:
        key = self._turn_order_key(room_id)
        await _await(self._r.delete(key))
        if order:
            await _await(self._r.rpush(key, *order))

    async def get_turn_order(self, room_id: str) -> list[str]:
        return await _await(self._r.lrange(self._turn_order_key(room_id), 0, -1))

    async def set_turn_state(self, room_id: str, state: dict[str, Any]) -> None:
        mapping = {key: str(value) for key, value in state.items()}
        await _await(self._r.hset(self._turn_state_key(room_id), mapping=mapping))
        self._turn_state_cache[room_id] = dict(state)

    async def get_turn_state(self, room_id: str) -> dict[str, Any] | None:
        cached = self._turn_state_cache.get(room_id)
        if cached is not None:
            return dict(cached)
        data = await _await(self._r.hgetall(self._turn_state_key(room_id)))
        if not data:
            return None
        parsed: dict[str, Any] = {}
        int_keys = {
            "round",
            "turn_index",
            "turn_remaining",
            "turn_duration",
            "turn_grace",
            "vote_duration",
        }
        float_keys = {"deadline_ts", "grace_deadline_ts", "vote_deadline_ts"}
        for key, value in data.items():
            if key in int_keys:
                parsed[key] = int(value)
            elif key in float_keys:
                parsed[key] = float(value)
            else:
                parsed[key] = value
        self._turn_state_cache[room_id] = dict(parsed)
        return dict(parsed)

    async def clear_turn_state(self, room_id: str) -> None:
        await _await(self._r.delete(self._turn_state_key(room_id)))
        await _await(self._r.delete(self._turn_order_key(room_id)))
        await _await(self._r.delete(self._room_votes_key(room_id)))
        self._turn_state_cache.pop(room_id, None)

    async def append_turn_word(self, room_id: str, entry: dict[str, Any]) -> None:
        await _await(
            self._r.rpush(self._turn_words_key(room_id), json.dumps(entry))
        )

    async def get_turn_words(self, room_id: str) -> list[dict[str, Any]]:
        raw = await _await(self._r.lrange(self._turn_words_key(room_id), 0, -1))
        words: list[dict[str, Any]] = []
        for item in raw:
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                words.append(parsed)
        return words

    async def clear_turn_words(self, room_id: str) -> None:
        await _await(self._r.delete(self._turn_words_key(room_id)))

    async def append_word_history(self, room_id: str, entry: dict[str, Any]) -> None:
        await _await(
            self._r.rpush(self._word_history_key(room_id), json.dumps(entry))
        )

    async def get_word_history(self, room_id: str) -> list[dict[str, Any]]:
        raw = await _await(self._r.lrange(self._word_history_key(room_id), 0, -1))
        history: list[dict[str, Any]] = []
        for item in raw:
            try:
                parsed = json.loads(item)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                history.append(parsed)
        return history

    async def clear_word_history(self, room_id: str) -> None:
        await _await(self._r.delete(self._word_history_key(room_id)))

    async def set_vote(
        self, room_id: str, voter_conn_id: str, target_conn_id: str
    ) -> None:
        await _await(
            self._r.hset(
                self._room_votes_key(room_id),
                mapping={voter_conn_id: target_conn_id},
            )
        )

    async def get_votes(self, room_id: str) -> dict[str, str]:
        return await _await(self._r.hgetall(self._room_votes_key(room_id)))

    async def clear_votes(self, room_id: str) -> None:
        await _await(self._r.delete(self._room_votes_key(room_id)))

    async def issue_resume_token(self, room_id: str, conn_id: str) -> str:
        data = await _await(self._r.hgetall(self._conn_key(conn_id)))
        token = secrets.token_urlsafe(24)
        mapping: dict[str, Any] = {"room_id": room_id, "conn_id": conn_id}
        if "nickname" in data:
            mapping["nickname"] = data["nickname"]
        if "ready" in data:
            mapping["ready"] = data["ready"]
        if "role" in data:
            mapping["role"] = data["role"]
        await _await(self._r.hset(self._resume_token_key(token), mapping=mapping))
        return token

    async def peek_resume_token(self, token: str) -> dict[str, Any]:
        key = self._resume_token_key(token)
        data = await _await(self._r.hgetall(key))
        if not data:
            raise KeyError(token)
        if "ready" in data:
            data["ready"] = data["ready"] == "1"
        return data

    async def consume_resume_token(self, token: str) -> dict[str, Any]:
        key = self._resume_token_key(token)
        data = await _await(self._r.hgetall(key))
        if not data:
            raise KeyError(token)
        await _await(self._r.delete(key))
        if "ready" in data:
            data["ready"] = data["ready"] == "1"
        return data
