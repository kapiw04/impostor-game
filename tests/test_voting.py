import json
import time

import pytest
from pytest_mock import MockerFixture

from impostor.application.game_service import GameService


pytestmark = pytest.mark.anyio


async def test_cast_vote_broadcasts_tally(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "voting",
            "round": 1,
            "vote_deadline_ts": time.time() + 30,
            "voters": json.dumps(["conn-1", "conn-2", "conn-3"]),
        }
    )
    store.set_vote = mocker.AsyncMock()
    store.get_votes = mocker.AsyncMock(return_value={"conn-1": "conn-2"})
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2", "conn-3"})
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)
    finalize = mocker.patch.object(service, "_finalize_voting_locked", new=mocker.AsyncMock())

    result = await service.cast_vote("room-1", "conn-1", "conn-2", notifier)

    store.set_vote.assert_awaited_once_with("room-1", "conn-1", "conn-2")
    notifier.broadcast.assert_awaited_once()
    payload = notifier.broadcast.await_args.args[1]
    assert payload["type"] == "vote_cast"
    assert payload["votes"] == {"conn-1": "conn-2"}
    assert payload["tally"] == {"conn-2": 1}
    assert result["tally"] == {"conn-2": 1}
    finalize.assert_not_awaited()


async def test_cast_vote_rejects_invalid_target(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "voting",
            "round": 1,
            "vote_deadline_ts": time.time() + 30,
            "voters": json.dumps(["conn-1", "conn-2"]),
        }
    )
    store.set_vote = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(RuntimeError):
        await service.cast_vote("room-1", "conn-1", "conn-3", notifier)

    store.set_vote.assert_not_called()


async def test_cast_vote_rejects_ineligible_voter(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "voting",
            "round": 1,
            "vote_deadline_ts": time.time() + 30,
            "voters": json.dumps(["conn-1", "conn-2"]),
        }
    )
    store.set_vote = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(PermissionError):
        await service.cast_vote("room-1", "conn-9", "conn-1", notifier)

    store.set_vote.assert_not_called()


async def test_finalize_voting_majority_ends_game(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_votes = mocker.AsyncMock(
        return_value={"conn-1": "conn-2", "conn-3": "conn-2"}
    )
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2", "conn-3"})
    store.get_impostor = mocker.AsyncMock(return_value="conn-2")
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)
    service.end_game = mocker.AsyncMock()
    state = {"round": 2, "voters": json.dumps(["conn-1", "conn-2", "conn-3"])}

    await service._finalize_voting_locked("room-1", notifier, state)

    assert notifier.broadcast.await_count == 1
    payload = notifier.broadcast.await_args.args[1]
    assert payload["type"] == "voting_result"
    result = payload["result"]
    assert result["winner"] == "crew"
    assert result["voted_out"] == "conn-2"
    service.end_game.assert_awaited_once()
    end_result = service.end_game.await_args.kwargs["result"]
    assert end_result["winner"] == "crew"


async def test_finalize_voting_skip_majority_starts_next_round(
    mocker: MockerFixture,
):
    store = mocker.Mock()
    store.get_votes = mocker.AsyncMock(
        return_value={"conn-1": "skip", "conn-2": "skip", "conn-3": "skip"}
    )
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2", "conn-3"})
    store.clear_votes = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)
    service._start_next_round = mocker.AsyncMock()
    state = {"round": 1, "voters": json.dumps(["conn-1", "conn-2", "conn-3"])}

    await service._finalize_voting_locked("room-1", notifier, state)

    payload = notifier.broadcast.await_args.args[1]
    assert payload["type"] == "voting_result"
    assert payload["result"]["reason"] == "no_majority"
    store.clear_votes.assert_awaited_once_with("room-1")
    service._start_next_round.assert_awaited_once_with("room-1", notifier, state)


async def test_cast_vote_after_deadline_finalizes_and_errors(
    mocker: MockerFixture,
):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "voting",
            "round": 1,
            "vote_deadline_ts": time.time() - 1,
            "voters": json.dumps(["conn-1", "conn-2"]),
        }
    )
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)
    finalize = mocker.patch.object(service, "_finalize_voting_locked", new=mocker.AsyncMock())

    with pytest.raises(RuntimeError):
        await service.cast_vote("room-1", "conn-1", "conn-2", notifier)

    finalize.assert_awaited_once()
