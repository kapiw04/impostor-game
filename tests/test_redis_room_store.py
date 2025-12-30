import pytest
import redis.asyncio as redis

from impostor.infrastructure.redis_room_store import RedisRoomStore


pytestmark = pytest.mark.anyio


@pytest.fixture
async def redis_client(redis_url):
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await client.flushdb()
        yield client
    finally:
        await client.aclose()


async def test_create_room_and_get_name(redis_client):
    store = RedisRoomStore(redis_client)

    await store.create_room("room-1", "Room One")

    assert await store.get_room_name("room-1") == "Room One"


async def test_add_and_remove_conn(redis_client):
    store = RedisRoomStore(redis_client)

    await store.add_conn("room-1", "conn-1", nickname="Nick")

    assert await store.list_conns("room-1") == {"conn-1"}

    data = await redis_client.hgetall("conn:conn-1")
    assert data["room_id"] == "room-1"
    assert data["nickname"] == "Nick"
    assert data["ready"] == "0"

    await store.remove_conn("room-1", "conn-1")

    assert await store.list_conns("room-1") == set()
    assert await redis_client.exists("conn:conn-1") == 0


async def test_add_conn_without_nickname(redis_client):
    store = RedisRoomStore(redis_client)

    await store.add_conn("room-2", "conn-2")

    assert await store.list_conns("room-2") == {"conn-2"}

    data = await redis_client.hgetall("conn:conn-2")
    assert data == {"room_id": "room-2", "ready": "0"}


async def test_lobby_state_tracks_host_ready_and_settings(redis_client):
    store = RedisRoomStore(redis_client)

    await store.create_room("room-1", "Room One")
    await store.add_conn("room-1", "conn-1", nickname="Host")
    await store.add_conn("room-1", "conn-2", nickname="Player")

    state = await store.get_lobby_state("room-1")

    assert state["host"] == "conn-1"
    assert state["players"]["conn-1"]["ready"] is False
    assert state["players"]["conn-2"]["nick"] == "Player"
    assert state["settings"]["round_time"] == 60
    assert state["settings"]["max_players"] == 8

    await store.set_ready("room-1", "conn-2", True)
    state = await store.get_lobby_state("room-1")
    assert state["players"]["conn-2"]["ready"] is True

    await store.remove_conn("room-1", "conn-1")
    state = await store.get_lobby_state("room-1")
    assert state["host"] == "conn-2"


async def test_game_state_and_end_game(redis_client):
    store = RedisRoomStore(redis_client)

    await store.create_room("room-1", "Room One")
    await store.set_game_state("room-1", "in_progress")

    assert await store.get_game_state("room-1") == "in_progress"

    result = {"winner": "crew", "reason": "win_condition"}
    assert await store.end_game("room-1", result=result) == result
    assert await store.get_game_state("room-1") == "ended"


async def test_resume_token_round_trip(redis_client):
    store = RedisRoomStore(redis_client)

    await store.create_room("room-1", "Room One")
    await store.add_conn("room-1", "conn-1", nickname="Nick")
    await store.set_ready("room-1", "conn-1", True)
    await store.set_role("room-1", "conn-1", "crew")

    token = await store.issue_resume_token("room-1", "conn-1")
    data = await store.consume_resume_token(token)

    assert data["room_id"] == "room-1"
    assert data["conn_id"] == "conn-1"
    assert data["nickname"] == "Nick"
    assert data["ready"] is True
    assert data["role"] == "crew"

    with pytest.raises(KeyError):
        await store.consume_resume_token(token)


async def test_role_storage_and_clear(redis_client):
    store = RedisRoomStore(redis_client)

    await store.create_room("room-1", "Room One")
    await store.add_conn("room-1", "conn-1", nickname="Nick")
    await store.set_secret_word("room-1", "apple")
    await store.set_impostor("room-1", "conn-1")
    await store.set_role("room-1", "conn-1", "impostor")

    assert await store.get_secret_word("room-1") == "apple"

    await store.clear_roles("room-1")

    assert await store.get_secret_word("room-1") is None
    data = await redis_client.hgetall("conn:conn-1")
    assert "role" not in data
