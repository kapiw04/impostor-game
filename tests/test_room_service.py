import pytest

from impostor.application.errors import RoomNotFoundError
from impostor.application.room_service import RoomService


pytestmark = pytest.mark.anyio


@pytest.fixture
def store(mocker):
    store = mocker.Mock()
    store.create_room = mocker.AsyncMock()
    store.get_room_name = mocker.AsyncMock()
    store.add_conn = mocker.AsyncMock()
    store.list_conns = mocker.AsyncMock()
    store.remove_conn = mocker.AsyncMock()
    store.set_ready = mocker.AsyncMock()
    store.get_lobby_state = mocker.AsyncMock()
    store.set_secret_word = mocker.AsyncMock()
    store.set_impostor = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    store.clear_roles = mocker.AsyncMock()
    store.get_secret_word = mocker.AsyncMock()
    store.set_turn_order = mocker.AsyncMock()
    store.get_turn_order = mocker.AsyncMock(return_value=[])
    store.set_turn_state = mocker.AsyncMock()
    store.get_turn_state = mocker.AsyncMock(return_value=None)
    store.clear_turn_state = mocker.AsyncMock()
    store.peek_resume_token = mocker.AsyncMock()
    return store


async def test_create_room_persists_and_returns_room(store, mocker):
    service = RoomService(store)
    make_room_id = mocker.patch.object(
        service, "_make_room_id", return_value="ROOM1234"
    )

    room = await service.create_room("Room Name")

    make_room_id.assert_called_once_with()
    store.create_room.assert_awaited_once_with("ROOM1234", "Room Name")
    assert room.room_id == "ROOM1234"
    assert room.name == "Room Name"


async def test_join_room_adds_conn_and_returns_conns(store):
    store.get_room_name.return_value = "Room One"
    store.list_conns.return_value = {"conn-1", "conn-2"}
    service = RoomService(store)

    room_name, conns = await service.join_room("room-1", "conn-1", nickname="Nick")

    store.get_room_name.assert_awaited_once_with("room-1")
    store.add_conn.assert_awaited_once_with("room-1", "conn-1", nickname="Nick")
    store.list_conns.assert_awaited_once_with("room-1")
    assert room_name == "Room One"
    assert conns == {"conn-1", "conn-2"}


async def test_join_room_missing_room_raises(store):
    store.get_room_name.return_value = None
    service = RoomService(store)

    with pytest.raises(RoomNotFoundError):
        await service.join_room("room-404", "conn-1")

    store.add_conn.assert_not_called()
    store.list_conns.assert_not_called()


async def test_leave_room_removes_conn(store):
    service = RoomService(store)

    await service.leave_room("room-1", "conn-1")

    store.remove_conn.assert_awaited_once_with("room-1", "conn-1")


async def test_set_ready_updates_lobby_state(store):
    store.get_room_name.return_value = "Room One"
    store.get_lobby_state.return_value = {"room_id": "room-1"}
    service = RoomService(store)

    state = await service.set_ready("room-1", "conn-1", True)

    store.set_ready.assert_awaited_once_with("room-1", "conn-1", True)
    assert state == {"room_id": "room-1"}
