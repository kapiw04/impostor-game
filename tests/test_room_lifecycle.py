import pytest
from pytest_mock import MockerFixture

from impostor.application.room_service import RoomService


pytestmark = pytest.mark.anyio


async def test_lobby_state_includes_players_ready_host_settings(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_lobby_state = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "players": {
                "conn-1": {"nick": "Host", "ready": True},
                "conn-2": {"nick": "Player", "ready": True},
            },
            "host": "conn-1",
            "settings": {"round_time": 60, "max_players": 8},
        }
    )
    service = RoomService(store)

    state = await service.get_lobby_state("room-1")

    store.get_room_name.assert_awaited_once_with("room-1")
    store.get_lobby_state.assert_awaited_once_with("room-1")
    assert state["host"] == "conn-1"
    assert state["players"]["conn-2"]["ready"] is True
    assert state["settings"]["round_time"] == 60


async def test_start_game_requires_host_and_all_ready(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_lobby_state = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "players": {
                "conn-1": {"nick": "Host", "ready": True},
                "conn-2": {"nick": "Player", "ready": True},
            },
            "host": "conn-1",
            "settings": {"round_time": 60},
        }
    )
    store.set_game_state = mocker.AsyncMock()
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2"})
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = RoomService(store)
    assign_roles = mocker.patch.object(
        service, "assign_roles", new=mocker.AsyncMock()
    )

    await service.start_game("room-1", started_by="conn-1", notifier=notifier)

    store.get_room_name.assert_awaited_once_with("room-1")
    store.get_lobby_state.assert_awaited_once_with("room-1")
    store.set_game_state.assert_awaited_once_with("room-1", "in_progress")
    assign_roles.assert_awaited_once_with("room-1", notifier)
    notifier.broadcast.assert_awaited_once_with(
        {"conn-1", "conn-2"}, {"type": "game_started", "room_id": "room-1"}
    )


async def test_start_game_rejects_non_host_or_not_ready(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_lobby_state = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "players": {
                "conn-1": {"nick": "Host", "ready": True},
                "conn-2": {"nick": "Player", "ready": False},
            },
            "host": "conn-1",
            "settings": {},
        }
    )
    store.set_game_state = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = RoomService(store)
    assign_roles = mocker.patch.object(
        service, "assign_roles", new=mocker.AsyncMock()
    )

    with pytest.raises(PermissionError):
        await service.start_game("room-1", started_by="conn-2", notifier=notifier)

    with pytest.raises(RuntimeError):
        await service.start_game("room-1", started_by="conn-1", notifier=notifier)

    assert store.set_game_state.await_count == 0
    assert assign_roles.await_count == 0
    assert notifier.broadcast.await_count == 0


async def test_end_game_broadcasts_and_returns_result(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.end_game = mocker.AsyncMock(
        return_value={"winner": "crew", "reason": "win_condition"}
    )
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2"})
    store.clear_roles = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = RoomService(store)

    result = await service.end_game("room-1", notifier=notifier)

    store.get_room_name.assert_awaited_once_with("room-1")
    store.end_game.assert_awaited_once_with("room-1", result=None)
    store.list_conns.assert_awaited_once_with("room-1")
    notifier.broadcast.assert_awaited_once_with(
        {"conn-1", "conn-2"},
        {"type": "game_ended", "room_id": "room-1", "result": result},
    )
    store.clear_roles.assert_awaited_once_with("room-1")


async def test_disconnect_removes_conn_and_returns_resume_token(
    mocker: MockerFixture,
):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.remove_conn = mocker.AsyncMock()
    store.issue_resume_token = mocker.AsyncMock(return_value="resume-token")
    service = RoomService(store)

    token = await service.disconnect("room-1", "conn-1")

    store.get_room_name.assert_awaited_once_with("room-1")
    store.remove_conn.assert_awaited_once_with("room-1", "conn-1")
    store.issue_resume_token.assert_awaited_once_with("room-1", "conn-1")
    assert token == "resume-token"


async def test_reconnect_sends_state_snapshot(mocker: MockerFixture):
    store = mocker.Mock()
    store.consume_resume_token = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "nickname": "Player",
            "ready": True,
            "role": "crew",
        }
    )
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.add_conn = mocker.AsyncMock()
    store.set_ready = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    store.get_secret_word = mocker.AsyncMock(return_value="apple")
    store.get_lobby_state = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "players": {"conn-2": {"nick": "Host", "ready": True}},
            "host": "conn-2",
            "settings": {"round_time": 60},
        }
    )
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = RoomService(store)

    await service.reconnect("resume-token", "conn-3", notifier=notifier)

    store.consume_resume_token.assert_awaited_once_with("resume-token")
    store.add_conn.assert_awaited_once_with("room-1", "conn-3", nickname="Player")
    store.set_ready.assert_awaited_once_with("room-1", "conn-3", True)
    store.set_role.assert_awaited_once_with("room-1", "conn-3", "crew")
    store.get_secret_word.assert_awaited_once_with("room-1")
    store.get_lobby_state.assert_awaited_once_with("room-1")
    assert notifier.send_to_conn.await_count == 2
    notifier.send_to_conn.assert_any_await(
        "conn-3", {"type": "role", "role": "crew", "word": "apple"}
    )
    notifier.send_to_conn.assert_any_await(
        "conn-3",
        {
            "type": "lobby_state",
            "room_id": "room-1",
            "state": {
                "room_id": "room-1",
                "players": {"conn-2": {"nick": "Host", "ready": True}},
                "host": "conn-2",
                "settings": {"round_time": 60},
            },
        },
    )


async def test_reconnect_impostor_sends_notice_only(mocker: MockerFixture):
    store = mocker.Mock()
    store.consume_resume_token = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "nickname": "Impostor",
            "ready": False,
            "role": "impostor",
        }
    )
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.add_conn = mocker.AsyncMock()
    store.set_ready = mocker.AsyncMock()
    store.set_role = mocker.AsyncMock()
    store.get_secret_word = mocker.AsyncMock()
    store.get_lobby_state = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "players": {"conn-2": {"nick": "Host", "ready": True}},
            "host": "conn-2",
            "settings": {"round_time": 60},
        }
    )
    notifier = mocker.Mock()
    notifier.send_to_conn = mocker.AsyncMock()
    service = RoomService(store)

    await service.reconnect("resume-token", "conn-9", notifier=notifier)

    store.consume_resume_token.assert_awaited_once_with("resume-token")
    store.add_conn.assert_awaited_once_with("room-1", "conn-9", nickname="Impostor")
    store.set_ready.assert_not_called()
    store.set_role.assert_awaited_once_with("room-1", "conn-9", "impostor")
    store.get_secret_word.assert_not_called()
    notifier.send_to_conn.assert_any_await(
        "conn-9",
        {"type": "role", "role": "impostor", "message": "you are impostor"},
    )
