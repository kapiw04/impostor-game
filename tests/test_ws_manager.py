from types import SimpleNamespace

import pytest

from impostor.infrastructure.ws_manager import WSManager


pytestmark = pytest.mark.anyio


class FakeWebSocket:
    def __init__(self) -> None:
        self.state = SimpleNamespace()

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: object) -> None:
        return None


async def test_connect_send_and_disconnect(mocker):
    manager = WSManager()
    ws = FakeWebSocket()
    accept_spy = mocker.spy(ws, "accept")
    send_spy = mocker.spy(ws, "send_json")

    await manager.connect(ws, "conn-1")

    assert accept_spy.call_count == 1
    assert ws.state.conn_id == "conn-1"
    assert manager._by_id["conn-1"] is ws

    payload = {"type": "hello"}
    await manager.send_to_conn("conn-1", payload)
    send_spy.assert_called_once_with(payload)

    manager.disconnect(ws)
    assert "conn-1" not in manager._by_id

    await manager.send_to_conn("conn-1", {"type": "ignored"})
    assert send_spy.call_count == 1


async def test_broadcast_to_multiple_connections(mocker):
    manager = WSManager()
    ws1 = FakeWebSocket()
    ws2 = FakeWebSocket()
    send_spy_1 = mocker.spy(ws1, "send_json")
    send_spy_2 = mocker.spy(ws2, "send_json")

    await manager.connect(ws1, "conn-1")
    await manager.connect(ws2, "conn-2")

    payload = {"type": "notice"}
    await manager.broadcast(["conn-1", "conn-2", "missing"], payload)

    send_spy_1.assert_called_once_with(payload)
    send_spy_2.assert_called_once_with(payload)
