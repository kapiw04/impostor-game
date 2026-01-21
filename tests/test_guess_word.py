import pytest
from pytest_mock import MockerFixture

from impostor.application.game_service import GameService


pytestmark = pytest.mark.anyio


async def test_guess_word_correct_ends_game(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_impostor = mocker.AsyncMock(return_value="conn-2")
    store.get_secret_word = mocker.AsyncMock(return_value="Banana")
    notifier = mocker.Mock()
    service = GameService(store)
    service.end_game = mocker.AsyncMock(return_value={"winner": "impostor"})

    result = await service.guess_word("room-1", "conn-2", "banana", notifier)

    assert result["winner"] == "impostor"
    assert result["reason"] == "impostor_guessed"
    assert result["word"] == "Banana"
    service.end_game.assert_awaited_once()


async def test_guess_word_rejects_non_impostor(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_impostor = mocker.AsyncMock(return_value="conn-2")
    store.get_secret_word = mocker.AsyncMock(return_value="Banana")
    notifier = mocker.Mock()
    service = GameService(store)

    with pytest.raises(PermissionError):
        await service.guess_word("room-1", "conn-1", "banana", notifier)


async def test_guess_word_incorrect_ends_game(mocker: MockerFixture):
    store = mocker.Mock()
    store.get_room_name = mocker.AsyncMock(return_value="Room One")
    store.get_impostor = mocker.AsyncMock(return_value="conn-2")
    store.get_secret_word = mocker.AsyncMock(return_value="Banana")
    notifier = mocker.Mock()
    service = GameService(store)
    service.end_game = mocker.AsyncMock(return_value={"winner": "crew"})

    result = await service.guess_word("room-1", "conn-2", "apple", notifier)

    assert result["winner"] == "crew"
    assert result["reason"] == "impostor_failed_guess"
    assert result["word"] == "Banana"
    service.end_game.assert_awaited_once()
