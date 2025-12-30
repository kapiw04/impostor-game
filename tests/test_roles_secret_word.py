from unittest.mock import call

import pytest
from pytest_mock import MockerFixture

from impostor.application.errors import RoomNotFoundError
from impostor.application.game_service import GameService


pytestmark = pytest.mark.anyio


async def test_assign_roles_distributes_word_and_impostor_notice(
    mocker: MockerFixture,
):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2", "conn-3"})
    store.set_secret_word = mocker.AsyncMock()
    store.set_impostor = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = GameService(store)
    mocker.patch.object(service, "_pick_secret_word", return_value="apple")
    mocker.patch.object(service, "_pick_impostor", return_value="conn-1")

    await service.assign_roles("room-1", notifier=notifier)

    store.get_room_name.assert_awaited_once_with("room-1")
    store.list_conns.assert_awaited_once_with("room-1")
    store.set_secret_word.assert_awaited_once_with("room-1", "apple")
    store.set_impostor.assert_awaited_once_with("room-1", "conn-1")
    store.set_role.assert_has_awaits(
        [
            call("room-1", "conn-1", "impostor"),
            call("room-1", "conn-2", "crew"),
            call("room-1", "conn-3", "crew"),
        ]
    )
    assert notifier.send_to_conn.await_count == 3

    sent = {
        call.args[0]: call.args[1] for call in notifier.send_to_conn.await_args_list
    }
    assert set(sent.keys()) == {"conn-1", "conn-2", "conn-3"}

    impostors = [cid for cid, payload in sent.items() if payload.get("role") == "impostor"]
    assert impostors == ["conn-1"]

    for cid, payload in sent.items():
        assert payload.get("type") == "role"
        if cid == "conn-1":
            assert payload.get("message") == "you are impostor"
            assert "word" not in payload
        else:
            assert payload.get("role") == "crew"
            assert payload.get("word") == "apple"


async def test_assign_roles_picks_exactly_one_impostor(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.list_conns = mocker.AsyncMock(
        return_value={"conn-1", "conn-2", "conn-3", "conn-4"}
    )
    store.set_secret_word = mocker.AsyncMock()
    store.set_impostor = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = GameService(store)
    mocker.patch.object(service, "_pick_secret_word", return_value="river")
    mocker.patch.object(service, "_pick_impostor", return_value="conn-3")

    await service.assign_roles("room-2", notifier=notifier)

    payloads = [call.args[1] for call in notifier.send_to_conn.await_args_list]
    assert sum(payload.get("role") == "impostor" for payload in payloads) == 1


async def test_assign_roles_requires_players(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.list_conns = mocker.AsyncMock(return_value=set())
    store.set_secret_word = mocker.AsyncMock()
    store.set_impostor = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(RuntimeError):
        await service.assign_roles("room-1", notifier=notifier)

    store.list_conns.assert_awaited_once_with("room-1")
    assert store.set_secret_word.await_count == 0
    assert notifier.send_to_conn.await_count == 0


async def test_assign_roles_missing_room_raises(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value=None)
    store.list_conns = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = GameService(store)

    with pytest.raises(RoomNotFoundError):
        await service.assign_roles("room-404", notifier=notifier)

    store.list_conns.assert_not_called()
    assert notifier.send_to_conn.await_count == 0
