import asyncio
import secrets
import time
from typing import Any

from impostor.application.guards import room_exists
from impostor.application.ports import Notifier, RoomStore
from impostor.config import Config
from impostor.domain.turn import TurnEndReason
from impostor.domain.word_pool import WORDS


class GameService:
    def __init__(self, store: RoomStore, config: Config | None = None):
        self._store = store
        self._config = config or Config()
        if self._config.timer_tick_seconds <= 0:
            raise ValueError("timer_tick_seconds must be positive")
        self._timer_tick_seconds = self._config.timer_tick_seconds
        self._turn_tasks: dict[str, asyncio.Task[None]] = {}
        self._grace_tasks: dict[str, asyncio.Task[None]] = {}
        self._turn_locks: dict[str, asyncio.Lock] = {}

    def _pick_impostor(self, conns: list[str]) -> str:
        return secrets.choice(conns)

    def _pick_secret_word(self) -> str:
        return secrets.choice(WORDS)

    def _get_lock(self, room_id: str) -> asyncio.Lock:
        lock = self._turn_locks.get(room_id)
        if lock is None:
            lock = asyncio.Lock()
            self._turn_locks[room_id] = lock
        return lock

    def _cancel_task(self, task: asyncio.Task[None] | None) -> None:
        if task and not task.done():
            task.cancel()

    async def _get_turn_state_for_phase(
        self, room_id: str, phase: str
    ) -> dict[str, Any] | None:
        state = await self._store.get_turn_state(room_id)
        if not state or state.get("phase") != phase:
            return None
        return state

    def _is_current_conn(self, state: dict[str, Any], conn_id: str) -> bool:
        return state.get("current_conn_id") == conn_id

    @room_exists
    async def start_game(
        self, room_id: str, started_by: str, notifier: Notifier
    ) -> None:
        state = await self._store.get_lobby_state(room_id)
        if state is None:
            raise RuntimeError("room state unavailable")
        if state["host"] != started_by:
            raise PermissionError("only host can start the game")
        players = state["players"].values()
        if not players or any(not player.get("ready") for player in players):
            raise RuntimeError("all players must be ready")
        await self._store.set_game_state(room_id, "in_progress")
        await self.assign_roles(room_id, notifier)
        conns = await self._store.list_conns(room_id)
        await notifier.broadcast(conns, {"type": "game_started", "room_id": room_id})
        await self._start_rounds(room_id, notifier, state)

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
        await self._store.clear_roles(room_id)
        await self._store.clear_turn_state(room_id)
        self._cancel_task(self._turn_tasks.pop(room_id, None))
        self._cancel_task(self._grace_tasks.pop(room_id, None))
        return result

    @room_exists
    async def assign_roles(self, room_id: str, notifier: Notifier) -> None:
        conns = sorted(await self._store.list_conns(room_id))
        if not conns:
            raise RuntimeError("no players in room")
        word = self._pick_secret_word()
        impostor = self._pick_impostor(conns)
        await self._store.set_secret_word(room_id, word)
        await self._store.set_impostor(room_id, impostor)
        for conn_id in conns:
            if conn_id == impostor:
                await self._store.set_role(room_id, conn_id, "impostor")
                await notifier.send_to_conn(
                    conn_id,
                    {"type": "role", "role": "impostor", "message": "you are impostor"},
                )
            else:
                await self._store.set_role(room_id, conn_id, "crew")
                await notifier.send_to_conn(
                    conn_id, {"type": "role", "role": "crew", "word": word}
                )

    async def handle_disconnect(
        self, room_id: str, conn_id: str, notifier: Notifier
    ) -> None:
        await self._pause_turn_if_current(room_id, conn_id, notifier)

    @room_exists
    async def handle_reconnect(
        self,
        room_id: str,
        conn_id: str,
        role: str | None,
        notifier: Notifier,
    ) -> None:
        if role:
            await self._store.set_role(room_id, conn_id, role)
            if role == "impostor":
                await notifier.send_to_conn(
                    conn_id,
                    {"type": "role", "role": "impostor", "message": "you are impostor"},
                )
            else:
                word = await self._store.get_secret_word(room_id)
                if word:
                    await notifier.send_to_conn(
                        conn_id, {"type": "role", "role": "crew", "word": word}
                    )
        await self._resume_turn_if_current(room_id, conn_id, notifier)

    async def handle_turn_message(
        self, room_id: str, conn_id: str, notifier: Notifier
    ) -> None:
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "active")
            if not state or not self._is_current_conn(state, conn_id):
                return
            await self._advance_turn_locked(
                room_id, notifier, state, TurnEndReason.SPOKEN
            )

    async def _start_rounds(
        self, room_id: str, notifier: Notifier, lobby_state: dict[str, Any]
    ) -> None:
        conns = list(lobby_state.get("players", {}).keys())
        if not conns:
            raise RuntimeError("no players in room")
        order = conns[:]
        secrets.SystemRandom().shuffle(order)
        await self._store.set_turn_order(room_id, order)
        round_num = 1
        turn_index = 0
        current_conn = order[turn_index]
        settings = lobby_state.get("settings", {})
        turn_duration = int(settings.get("turn_duration", 30))
        turn_grace = int(settings.get("turn_grace", 60))
        deadline = time.time() + turn_duration
        await self._store.set_turn_state(
            room_id,
            {
                "phase": "active",
                "round": round_num,
                "turn_index": turn_index,
                "current_conn_id": current_conn,
                "deadline_ts": deadline,
                "turn_duration": turn_duration,
                "turn_grace": turn_grace,
            },
        )
        conns_set = await self._store.list_conns(room_id)
        await notifier.broadcast(
            conns_set,
            {
                "type": "round_started",
                "room_id": room_id,
                "round": round_num,
                "order": order,
                "turn_duration": turn_duration,
            },
        )
        await notifier.broadcast(
            conns_set,
            {
                "type": "turn_started",
                "room_id": room_id,
                "round": round_num,
                "turn_index": turn_index,
                "conn_id": current_conn,
                "turn_duration": turn_duration,
            },
        )
        self._start_turn_timer(room_id, notifier)

    def _start_turn_timer(self, room_id: str, notifier: Notifier) -> None:
        self._cancel_task(self._turn_tasks.pop(room_id, None))
        task = asyncio.create_task(self._run_turn_timer(room_id, notifier))
        self._turn_tasks[room_id] = task

    def _start_grace_timer(self, room_id: str, notifier: Notifier) -> None:
        self._cancel_task(self._grace_tasks.pop(room_id, None))
        task = asyncio.create_task(self._run_grace_timer(room_id, notifier))
        self._grace_tasks[room_id] = task

    async def _run_turn_timer(self, room_id: str, notifier: Notifier) -> None:
        while True:
            state = await self._get_turn_state_for_phase(room_id, "active")
            if not state:
                return
            remaining = int(state["deadline_ts"] - time.time())
            if remaining <= 0:
                await self._advance_turn(room_id, notifier, TurnEndReason.TIMEOUT)
                return
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "turn_timer",
                    "room_id": room_id,
                    "round": state["round"],
                    "turn_index": state["turn_index"],
                    "remaining": remaining,
                    "phase": "active",
                },
            )
            await asyncio.sleep(self._timer_tick_seconds)

    async def _run_grace_timer(self, room_id: str, notifier: Notifier) -> None:
        while True:
            state = await self._get_turn_state_for_phase(room_id, "paused")
            if not state:
                return
            grace_deadline = state.get("grace_deadline_ts")
            if grace_deadline is None:
                return
            remaining = int(grace_deadline - time.time())
            if remaining <= 0:
                async with self._get_lock(room_id):
                    state = await self._get_turn_state_for_phase(room_id, "paused")
                    if not state:
                        return
                    await self._advance_turn_locked(
                        room_id, notifier, state, TurnEndReason.SKIPPED
                    )
                self._grace_tasks.pop(room_id, None)
                return
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "turn_timer",
                    "room_id": room_id,
                    "round": state["round"],
                    "turn_index": state["turn_index"],
                    "remaining": remaining,
                    "phase": "grace",
                },
            )
            await asyncio.sleep(self._timer_tick_seconds)

    async def _advance_turn(
        self, room_id: str, notifier: Notifier, reason: TurnEndReason
    ) -> None:
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "active")
            if not state:
                return
            await self._advance_turn_locked(room_id, notifier, state, reason)

    async def _advance_turn_locked(
        self,
        room_id: str,
        notifier: Notifier,
        state: dict[str, Any],
        reason: TurnEndReason,
    ) -> None:
        conns = await self._store.list_conns(room_id)
        current_conn = state.get("current_conn_id")
        await notifier.broadcast(
            conns,
            {
                "type": "turn_ended",
                "room_id": room_id,
                "round": state["round"],
                "turn_index": state["turn_index"],
                "conn_id": current_conn,
                "reason": reason.value,
            },
        )
        order = await self._store.get_turn_order(room_id)
        next_index = state["turn_index"] + 1
        if next_index >= len(order):
            await self._store.set_turn_state(
                room_id,
                {
                    **state,
                    "phase": "voting",
                },
            )
            await notifier.broadcast(
                conns,
                {
                    "type": "round_ended",
                    "room_id": room_id,
                    "round": state["round"],
                },
            )
            # TODO: hook into voting phase once implemented.
            await notifier.broadcast(
                conns,
                {
                    "type": "voting_started",
                    "room_id": room_id,
                    "round": state["round"],
                },
            )
            self._cancel_task(self._turn_tasks.pop(room_id, None))
            self._cancel_task(self._grace_tasks.pop(room_id, None))
            return
        next_conn = order[next_index]
        deadline = time.time() + int(state.get("turn_duration", 30))
        new_state = {
            **state,
            "phase": "active",
            "turn_index": next_index,
            "current_conn_id": next_conn,
            "deadline_ts": deadline,
        }
        new_state.pop("turn_remaining", None)
        new_state.pop("grace_deadline_ts", None)
        await self._store.set_turn_state(room_id, new_state)
        await notifier.broadcast(
            conns,
            {
                "type": "turn_started",
                "room_id": room_id,
                "round": state["round"],
                "turn_index": next_index,
                "conn_id": next_conn,
                "turn_duration": int(state.get("turn_duration", 30)),
            },
        )
        self._start_turn_timer(room_id, notifier)

    async def _pause_turn_if_current(
        self, room_id: str, conn_id: str, notifier: Notifier
    ) -> None:
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "active")
            if not state or not self._is_current_conn(state, conn_id):
                return
            remaining = max(0, int(state["deadline_ts"] - time.time()))
            turn_grace = int(state.get("turn_grace", 60))
            new_state = {
                **state,
                "phase": "paused",
                "turn_remaining": remaining,
                "grace_deadline_ts": time.time() + turn_grace,
            }
            await self._store.set_turn_state(room_id, new_state)
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "turn_paused",
                    "room_id": room_id,
                    "round": state["round"],
                    "turn_index": state["turn_index"],
                    "conn_id": conn_id,
                    "remaining": turn_grace,
                },
            )
            self._cancel_task(self._turn_tasks.pop(room_id, None))
            self._start_grace_timer(room_id, notifier)

    async def _resume_turn_if_current(
        self, room_id: str, conn_id: str, notifier: Notifier
    ) -> None:
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "paused")
            if not state or not self._is_current_conn(state, conn_id):
                return
            remaining = int(state.get("turn_remaining", 0))
            if remaining <= 0:
                await self._advance_turn_locked(
                    room_id, notifier, state, TurnEndReason.SKIPPED
                )
                return
            deadline = time.time() + remaining
            new_state = {
                **state,
                "phase": "active",
                "deadline_ts": deadline,
            }
            new_state.pop("grace_deadline_ts", None)
            new_state.pop("turn_remaining", None)
            await self._store.set_turn_state(room_id, new_state)
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "turn_resumed",
                    "room_id": room_id,
                    "round": state["round"],
                    "turn_index": state["turn_index"],
                    "conn_id": conn_id,
                    "remaining": remaining,
                },
            )
            self._cancel_task(self._grace_tasks.pop(room_id, None))
            self._start_turn_timer(room_id, notifier)
