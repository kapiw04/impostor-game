import pytest
from pytest_mock import MockerFixture

from impostor.application.game_service import GameService


pytestmark = pytest.mark.anyio


async def test_submit_turn_word_broadcasts_and_advances(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "active",
            "round": 1,
            "turn_index": 0,
            "current_conn_id": "conn-1",
        }
    )
    store.append_turn_word = mocker.AsyncMock()
    store.append_word_history = mocker.AsyncMock()
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2"})
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)
    advance = mocker.patch.object(
        service, "_advance_turn_locked", new=mocker.AsyncMock()
    )

    result = await service.submit_turn_word("room-1", "conn-1", "apple", notifier)

    notifier.broadcast.assert_awaited_once()
    payload = notifier.broadcast.await_args.args[1]
    assert payload["type"] == "turn_word_submitted"
    assert payload["word"] == "apple"
    assert payload["conn_id"] == "conn-1"
    store.append_turn_word.assert_awaited_once_with(
        "room-1",
        {"word": "apple", "conn_id": "conn-1", "round": 1, "turn_index": 0},
    )
    store.append_word_history.assert_awaited_once_with(
        "room-1",
        {"word": "apple", "conn_id": "conn-1", "round": 1, "turn_index": 0},
    )
    advance.assert_awaited_once()
    assert result == {"word": "apple", "round": 1, "turn_index": 0}


async def test_submit_turn_word_rejects_non_current(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "active",
            "round": 1,
            "turn_index": 0,
            "current_conn_id": "conn-2",
        }
    )
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(PermissionError):
        await service.submit_turn_word("room-1", "conn-1", "apple", notifier)

    notifier.broadcast.assert_not_called()


async def test_submit_turn_word_requires_active_turn(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_turn_state = mocker.AsyncMock(
        return_value={
            "phase": "voting",
            "round": 1,
            "turn_index": 0,
            "current_conn_id": "conn-1",
        }
    )
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(RuntimeError):
        await service.submit_turn_word("room-1", "conn-1", "apple", notifier)

    notifier.broadcast.assert_not_called()


async def test_submit_turn_word_rejects_blank(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(RuntimeError):
        await service.submit_turn_word("room-1", "conn-1", "   ", notifier)

    notifier.broadcast.assert_not_called()
