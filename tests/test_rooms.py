from fastapi.testclient import TestClient
import pytest
from starlette.testclient import WebSocketDenialResponse


pytestmark = pytest.mark.anyio


def test_create_room(client: TestClient):
    response = client.post("/rooms/", json={"name": "Test Room", "max_players": 5})
    assert response.status_code == 200
    data = response.json()
    assert "room_id" in data
    assert data["name"] == "Test Room"
    assert data["settings"]["max_players"] == 5


def test_join_nonexistent_room(client: TestClient):
    with pytest.raises(WebSocketDenialResponse) as excinfo:
        with client.websocket_connect("/rooms/invalid_room_id/ws?nick=test_user"):
            pass

    assert excinfo.value.status_code == 1008


def test_room_lifecycle_host_and_kick(client: TestClient):
    create_response = client.post("/rooms/", json={"name": "Lifecycle Room", "max_players": 2})
    room_id = create_response.json()["room_id"]

    with client.websocket_connect(f"/rooms/{room_id}/ws?nick=host_user") as ws1:
        msg1 = ws1.receive_json()
        assert msg1["type"] == "room_state"
        room_state = msg1["room"]
        assert room_state["name"] == "Lifecycle Room"
        assert room_state["host_id"] is not None
        host_id = room_state["host_id"]
        assert len(room_state["players"]) == 1
        assert room_state["players"][0]["nickname"] == "host_user"

        with client.websocket_connect(f"/rooms/{room_id}/ws?nick=guest_user") as ws2:
            msg2_initial = ws2.receive_json()
            assert msg2_initial["type"] == "room_state"
            assert len(msg2_initial["room"]["players"]) == 2
            
            msg1_update = ws1.receive_json()
            assert msg1_update["type"] == "room_state"
            assert len(msg1_update["room"]["players"]) == 2
            guest_id = [p["conn_id"] for p in msg1_update["room"]["players"] if p["nickname"] == "guest_user"][0]

            with pytest.raises(WebSocketDenialResponse) as excinfo:
                with client.websocket_connect(f"/rooms/{room_id}/ws?nick=player3"):
                    pass
            assert excinfo.value.status_code == 1008

            ws1.send_json({"type": "kick", "target_id": guest_id})
            
            with pytest.raises(WebSocketDisconnect):
                ws2.receive_json()
        
        msg1_kick_update = ws1.receive_json()
        assert msg1_kick_update["type"] == "room_state"
        assert len(msg1_kick_update["room"]["players"]) == 1

    with pytest.raises(WebSocketDenialResponse) as excinfo:
        with client.websocket_connect(f"/rooms/{room_id}/ws?nick=late_user"):
            pass
    assert excinfo.value.status_code == 1008
