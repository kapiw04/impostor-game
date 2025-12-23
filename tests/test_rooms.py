from fastapi.testclient import TestClient
import pytest
from starlette.testclient import WebSocketDenialResponse


pytestmark = pytest.mark.anyio


def test_create_room(client: TestClient):
    response = client.post("/rooms/", json={"name": "Test Room"})
    assert response.status_code == 200
    data = response.json()
    assert "room_id" in data
    assert data["name"] == "Test Room"


def test_join_nonexistent_room(client: TestClient):
    with pytest.raises(WebSocketDenialResponse) as excinfo:
        with client.websocket_connect("/rooms/invalid_room_id/ws?nick=test_user"):
            pass

    assert excinfo.value.status_code == 1008


# async def test_join_and_leave_room(client):
#     create_response = client.post("/rooms/", json={"name": "Test Room"})
#     room_id = create_response.json()["room_id"]
#
#     with client.websocket_connect(f"/rooms/{room_id}/ws?nick=test_user") as websocket:
#         async for message in websocket:
#             data = message.json()
#             assert data["type"] == "user_joined"
#             assert data["room_id"] == room_id
#             assert data["nick"] == "test_user"
#             break
#
#     websocket.close()
#     async for message in websocket:
#         data = message.json()
#         assert data["type"] == "user_left"
#         assert data["room_id"] == room_id
#         assert data["nick"] == "test_user"
#         break
