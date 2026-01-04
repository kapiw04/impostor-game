import pytest
from pytest_mock import MockerFixture

from impostor.application.game_service import GameService
from impostor.application.room_service import RoomService


pytestmark = pytest.mark.anyio


class DummyNotifier:
    async def send_to_conn(self, conn_id: str, payload: dict[str, object]) -> None:
        return None

    async def broadcast(self, conn_ids: object, payload: dict[str, object]) -> None:
        return None


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
    service = GameService(store)
    assign_roles = mocker.patch.object(service, "assign_roles", new=mocker.AsyncMock())
    start_rounds = mocker.patch.object(service, "_start_rounds", new=mocker.AsyncMock())

    await service.start_game("room-1", started_by="conn-1", notifier=notifier)

    store.get_room_name.assert_awaited_once_with("room-1")
    store.get_lobby_state.assert_awaited_once_with("room-1")
    store.set_game_state.assert_awaited_once_with("room-1", "in_progress")
    assign_roles.assert_awaited_once_with("room-1", notifier)
    start_rounds.assert_awaited_once_with(
        "room-1", notifier, store.get_lobby_state.return_value
    )
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
    service = GameService(store)
    assign_roles = mocker.patch.object(service, "assign_roles", new=mocker.AsyncMock())
    start_rounds = mocker.patch.object(service, "_start_rounds", new=mocker.AsyncMock())

    with pytest.raises(PermissionError):
        await service.start_game("room-1", started_by="conn-2", notifier=notifier)

    with pytest.raises(RuntimeError):
        await service.start_game("room-1", started_by="conn-1", notifier=notifier)

    assert store.set_game_state.await_count == 0
    assert assign_roles.await_count == 0
    assert start_rounds.await_count == 0
    assert notifier.broadcast.await_count == 0


async def test_end_game_broadcasts_and_returns_result(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.end_game = mocker.AsyncMock(
        return_value={"winner": "crew", "reason": "win_condition"}
    )
    store.list_conns = mocker.AsyncMock(return_value={"conn-1", "conn-2"})
    store.clear_roles = mocker.AsyncMock()
    store.clear_turn_state = mocker.AsyncMock()
    store.clear_votes = mocker.AsyncMock()
    notifier = mocker.Mock()
    notifier.broadcast = mocker.AsyncMock()
    service = GameService(store)

    result = await service.end_game("room-1", notifier=notifier)

    store.get_room_name.assert_awaited_once_with("room-1")
    store.end_game.assert_awaited_once_with("room-1", result=None)
    store.list_conns.assert_awaited_once_with("room-1")
    notifier.broadcast.assert_awaited_once_with(
        {"conn-1", "conn-2"},
        {"type": "game_ended", "room_id": "room-1", "result": result},
    )
    store.clear_roles.assert_awaited_once_with("room-1")
    store.clear_turn_state.assert_awaited_once_with("room-1")
    store.clear_votes.assert_awaited_once_with("room-1")


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


async def test_reconnect_returns_state_and_resends_role(mocker: MockerFixture):
    store = mocker.Mock()
    store.consume_resume_token = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "conn_id": "conn-3",
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
    room_service = RoomService(store)

    resume, state = await room_service.reconnect("resume-token")

    store.consume_resume_token.assert_awaited_once_with("resume-token")
    store.add_conn.assert_awaited_once_with("room-1", "conn-3", nickname="Player")
    store.set_ready.assert_awaited_once_with("room-1", "conn-3", True)
    store.get_lobby_state.assert_awaited_once_with("room-1")
    assert resume["role"] == "crew"
    assert state["room_id"] == "room-1"

    notifier = DummyNotifier()
    send_spy = mocker.spy(notifier, "send_to_conn")
    game_service = GameService(store)
    store.get_turn_state = mocker.AsyncMock(return_value=None)

    await game_service.handle_reconnect(
        resume["room_id"], resume["conn_id"], resume.get("role"), notifier
    )

    store.set_role.assert_awaited_once_with("room-1", "conn-3", "crew")
    store.get_secret_word.assert_awaited_once_with("room-1")
    send_spy.assert_called_once()
    assert send_spy.call_args.args[0] == "conn-3"
    assert send_spy.call_args.args[1] == {
        "type": "role",
        "role": "crew",
        "word": "apple",
    }


async def test_reconnect_impostor_sends_notice_only(mocker: MockerFixture):
    store = mocker.Mock()
    store.consume_resume_token = mocker.AsyncMock(
        return_value={
            "room_id": "room-1",
            "conn_id": "conn-9",
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
    room_service = RoomService(store)

    resume, _state = await room_service.reconnect("resume-token")

    store.consume_resume_token.assert_awaited_once_with("resume-token")
    store.add_conn.assert_awaited_once_with("room-1", "conn-9", nickname="Impostor")
    store.set_ready.assert_not_called()
    notifier = DummyNotifier()
    send_spy = mocker.spy(notifier, "send_to_conn")
    game_service = GameService(store)
    store.get_turn_state = mocker.AsyncMock(return_value=None)

    await game_service.handle_reconnect(
        resume["room_id"], resume["conn_id"], resume.get("role"), notifier
    )

    store.set_role.assert_awaited_once_with("room-1", "conn-9", "impostor")
    store.get_secret_word.assert_not_called()
    send_spy.assert_called_once()
    assert send_spy.call_args.args[0] == "conn-9"
    assert send_spy.call_args.args[1] == {
        "type": "role",
        "role": "impostor",
        "message": "you are impostor",
    }
