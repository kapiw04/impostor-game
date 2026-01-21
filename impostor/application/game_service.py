import asyncio
import json
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
        self._voting_tasks: dict[str, asyncio.Task[None]] = {}
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

    def _normalize_guess(self, value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def _parse_voters(self, state: dict[str, Any]) -> list[str]:
        raw = state.get("voters")
        if not raw:
            return []
        if isinstance(raw, list):
            return [str(value) for value in raw]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                return [str(value) for value in parsed]
        return []

    def _tally_votes(
        self, votes: dict[str, str], voters: list[str]
    ) -> dict[str, int]:
        allowed_targets = set(voters)
        allowed_targets.add("skip")
        tally: dict[str, int] = {}
        for voter, target in votes.items():
            if voter not in voters:
                continue
            if target not in allowed_targets:
                continue
            tally[target] = tally.get(target, 0) + 1
        return tally

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
        await self._store.clear_word_history(room_id)
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
        for conn_id in conns:
            await self._store.set_ready(room_id, conn_id, False)
        lobby_state = await self._store.get_lobby_state(room_id)
        if lobby_state:
            await notifier.broadcast(
                conns,
                {"type": "lobby_state", "room_id": room_id, "state": lobby_state},
            )
        await self._store.clear_roles(room_id)
        await self._store.clear_turn_state(room_id)
        await self._store.clear_votes(room_id)
        await self._store.clear_turn_words(room_id)
        await self._store.clear_word_history(room_id)
        self._cancel_task(self._turn_tasks.pop(room_id, None))
        self._cancel_task(self._grace_tasks.pop(room_id, None))
        self._cancel_task(self._voting_tasks.pop(room_id, None))
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

    @room_exists
    async def submit_turn_word(
        self,
        room_id: str,
        conn_id: str,
        word: str,
        notifier: Notifier,
    ) -> dict[str, Any]:
        cleaned_word = word.strip()
        if not cleaned_word:
            raise RuntimeError("word is required")
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "active")
            if not state:
                raise RuntimeError("turn is not active")
            if not self._is_current_conn(state, conn_id):
                raise PermissionError("not your turn")
            entry = {
                "word": cleaned_word,
                "conn_id": conn_id,
                "round": state["round"],
                "turn_index": state["turn_index"],
            }
            await self._store.append_turn_word(room_id, entry)
            await self._store.append_word_history(room_id, entry)
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "turn_word_submitted",
                    "room_id": room_id,
                    **entry,
                },
            )
            await self._advance_turn_locked(
                room_id, notifier, state, TurnEndReason.SPOKEN
            )
            return {
                "word": cleaned_word,
                "round": state["round"],
                "turn_index": state["turn_index"],
            }

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
        settings = lobby_state.get("settings", {})
        turn_duration = int(settings.get("turn_duration", 30))
        turn_grace = int(settings.get("turn_grace", 60))
        vote_duration = int(settings.get("round_time", 60))
        await self._start_round(
            room_id,
            notifier,
            round_num,
            order,
            turn_duration,
            turn_grace,
            vote_duration,
        )

    def _start_turn_timer(self, room_id: str, notifier: Notifier) -> None:
        self._cancel_task(self._turn_tasks.pop(room_id, None))
        task = asyncio.create_task(self._run_turn_timer(room_id, notifier))
        self._turn_tasks[room_id] = task

    def _start_grace_timer(self, room_id: str, notifier: Notifier) -> None:
        self._cancel_task(self._grace_tasks.pop(room_id, None))
        task = asyncio.create_task(self._run_grace_timer(room_id, notifier))
        self._grace_tasks[room_id] = task

    def _start_voting_timer(self, room_id: str, notifier: Notifier) -> None:
        self._cancel_task(self._voting_tasks.pop(room_id, None))
        task = asyncio.create_task(self._run_voting_timer(room_id, notifier))
        self._voting_tasks[room_id] = task

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

    async def _run_voting_timer(self, room_id: str, notifier: Notifier) -> None:
        while True:
            state = await self._get_turn_state_for_phase(room_id, "voting")
            if not state:
                return
            deadline = state.get("vote_deadline_ts")
            if deadline is None:
                return
            remaining = int(deadline - time.time())
            if remaining <= 0:
                async with self._get_lock(room_id):
                    state = await self._get_turn_state_for_phase(room_id, "voting")
                    if not state:
                        return
                    await self._finalize_voting_locked(room_id, notifier, state)
                self._voting_tasks.pop(room_id, None)
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
                    "phase": "voting",
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
            await self._start_voting(room_id, notifier, state)
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

    async def _start_round(
        self,
        room_id: str,
        notifier: Notifier,
        round_num: int,
        order: list[str],
        turn_duration: int,
        turn_grace: int,
        vote_duration: int,
    ) -> None:
        if not order:
            raise RuntimeError("no players in room")
        await self._store.clear_turn_words(room_id)
        turn_index = 0
        current_conn = order[turn_index]
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
                "vote_duration": vote_duration,
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

    @room_exists
    async def get_turn_snapshot(self, room_id: str) -> dict[str, Any] | None:
        state = await self._store.get_turn_state(room_id)
        if not state:
            return None
        order = await self._store.get_turn_order(room_id)
        words = await self._store.get_turn_words(room_id)
        history = await self._store.get_word_history(room_id)
        snapshot = {
            **state,
            "order": order,
            "words": words,
            "history": history,
        }
        remaining = None
        now = time.time()
        phase = state.get("phase")
        if phase == "active":
            deadline = state.get("deadline_ts")
            if deadline is not None:
                remaining = max(0, int(deadline - now))
        elif phase == "paused":
            grace_deadline = state.get("grace_deadline_ts")
            if grace_deadline is not None:
                remaining = max(0, int(grace_deadline - now))
        elif phase == "voting":
            vote_deadline = state.get("vote_deadline_ts")
            if vote_deadline is not None:
                remaining = max(0, int(vote_deadline - now))
            voters = self._parse_voters(state)
            votes = await self._store.get_votes(room_id)
            snapshot["voters"] = voters
            snapshot["votes"] = votes
            snapshot["tally"] = self._tally_votes(votes, voters)
        if remaining is not None:
            snapshot["remaining"] = remaining
        return snapshot

    async def _start_voting(
        self, room_id: str, notifier: Notifier, state: dict[str, Any]
    ) -> None:
        voters = sorted(await self._store.list_conns(room_id))
        if not voters:
            return
        vote_duration = int(state.get("vote_duration", 60))
        new_state = {
            **state,
            "phase": "voting",
            "vote_deadline_ts": time.time() + vote_duration,
            "voters": json.dumps(voters),
        }
        new_state.pop("deadline_ts", None)
        new_state.pop("turn_remaining", None)
        new_state.pop("grace_deadline_ts", None)
        await self._store.set_turn_state(room_id, new_state)
        await self._store.clear_votes(room_id)
        await notifier.broadcast(
            voters,
            {
                "type": "round_ended",
                "room_id": room_id,
                "round": state["round"],
            },
        )
        await notifier.broadcast(
            voters,
            {
                "type": "voting_started",
                "room_id": room_id,
                "round": state["round"],
                "voters": voters,
                "vote_duration": vote_duration,
            },
        )
        self._cancel_task(self._turn_tasks.pop(room_id, None))
        self._cancel_task(self._grace_tasks.pop(room_id, None))
        self._start_voting_timer(room_id, notifier)

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

    @room_exists
    async def cast_vote(
        self,
        room_id: str,
        voter_conn_id: str,
        target_conn_id: str,
        notifier: Notifier,
    ) -> dict[str, Any]:
        async with self._get_lock(room_id):
            state = await self._get_turn_state_for_phase(room_id, "voting")
            if not state:
                raise RuntimeError("voting is not active")
            deadline = state.get("vote_deadline_ts")
            if deadline is not None and time.time() >= deadline:
                await self._finalize_voting_locked(room_id, notifier, state)
                raise RuntimeError("voting has ended")
            voters = self._parse_voters(state)
            if voter_conn_id not in voters:
                raise PermissionError("voter is not eligible")
            if target_conn_id != "skip" and target_conn_id not in voters:
                raise RuntimeError("invalid vote target")
            votes = await self._store.get_votes(room_id)
            if voter_conn_id in votes:
                raise RuntimeError("vote already cast")
            await self._store.set_vote(room_id, voter_conn_id, target_conn_id)
            votes = await self._store.get_votes(room_id)
            tally = self._tally_votes(votes, voters)
            conns = await self._store.list_conns(room_id)
            await notifier.broadcast(
                conns,
                {
                    "type": "vote_cast",
                    "room_id": room_id,
                    "round": state.get("round"),
                    "voter": voter_conn_id,
                    "target": target_conn_id,
                    "votes": votes,
                    "tally": tally,
                },
            )
            if len(voters) > 0 and len(votes) >= len(voters):
                await self._finalize_voting_locked(room_id, notifier, state)
            return {"votes": votes, "tally": tally}

    @room_exists
    async def guess_word(
        self,
        room_id: str,
        conn_id: str,
        guess: str,
        notifier: Notifier,
    ) -> dict[str, Any]:
        impostor = await self._store.get_impostor(room_id)
        if impostor is None:
            raise RuntimeError("impostor is not set")
        if impostor != conn_id:
            raise PermissionError("only impostor can guess the word")
        word = await self._store.get_secret_word(room_id)
        if not word:
            raise RuntimeError("secret word is not set")
        cleaned_guess = guess.strip()
        if not cleaned_guess:
            raise RuntimeError("guess is required")
        normalized_guess = self._normalize_guess(cleaned_guess)
        normalized_word = self._normalize_guess(word)
        correct = normalized_guess == normalized_word
        result = {
            "winner": "impostor" if correct else "crew",
            "reason": "impostor_guessed" if correct else "impostor_failed_guess",
            "impostor": impostor,
            "guess": cleaned_guess,
            "word": word,
        }
        await self.end_game(room_id, notifier, result=result)
        return result

    async def _finalize_voting_locked(
        self, room_id: str, notifier: Notifier, state: dict[str, Any]
    ) -> None:
        task = self._voting_tasks.pop(room_id, None)
        if task and task is not asyncio.current_task():
            self._cancel_task(task)
        votes = await self._store.get_votes(room_id)
        voters = self._parse_voters(state)
        tally = self._tally_votes(votes, voters)
        total_voters = len(voters)
        majority_needed = total_voters // 2 + 1 if total_voters else 0
        winner: str | None = None
        for target, count in tally.items():
            if target in voters and count >= majority_needed:
                winner = target
                break
        conns = await self._store.list_conns(room_id)
        if winner:
            impostor = await self._store.get_impostor(room_id)
            word = await self._store.get_secret_word(room_id)
            crew_wins = winner == impostor
            result = {
                "winner": "crew" if crew_wins else "impostor",
                "reason": "impostor_eliminated" if crew_wins else "crew_eliminated",
                "voted_out": winner,
                "impostor": impostor,
                "word": word,
                "tally": tally,
                "votes": votes,
            }
            await notifier.broadcast(
                conns,
                {
                    "type": "voting_result",
                    "room_id": room_id,
                    "round": state.get("round"),
                    "result": result,
                },
            )
            await self.end_game(room_id, notifier, result=result)
            return
        await notifier.broadcast(
            conns,
            {
                "type": "voting_result",
                "room_id": room_id,
                "round": state.get("round"),
                "result": {
                    "winner": None,
                    "reason": "no_majority",
                    "tally": tally,
                    "votes": votes,
                },
            },
        )
        await self._store.clear_votes(room_id)
        await self._start_next_round(room_id, notifier, state)

    async def _start_next_round(
        self, room_id: str, notifier: Notifier, state: dict[str, Any]
    ) -> None:
        order = await self._store.get_turn_order(room_id)
        if not order:
            return
        await self._store.clear_votes(room_id)
        round_num = int(state.get("round", 1)) + 1
        turn_duration = int(state.get("turn_duration", 30))
        turn_grace = int(state.get("turn_grace", 60))
        vote_duration = int(state.get("vote_duration", 60))
        await self._start_round(
            room_id,
            notifier,
            round_num,
            order,
            turn_duration,
            turn_grace,
            vote_duration,
        )
