from typing import Any, Iterable
from starlette.websockets import WebSocket
from impostor.logging_config import get_logger

logger = get_logger(__name__)


class WSManager:
    def __init__(self) -> None:
        self._by_id: dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, conn_id: str) -> None:
        logger.info("ws_connecting", conn_id=conn_id)
        await ws.accept()
        ws.state.conn_id = conn_id
        self._by_id[conn_id] = ws

    def disconnect(self, ws: WebSocket) -> None:
        cid = getattr(ws.state, "conn_id", None)
        if cid:
            logger.info("ws_disconnected", conn_id=cid)
            self._by_id.pop(cid, None)

    async def send_to_conn(self, conn_id: str, payload: dict[str, Any]) -> None:
        ws = self._by_id.get(conn_id)
        if ws:
            await ws.send_json(payload)

    async def broadcast(self, conn_ids: Iterable[str], payload: dict[str, Any]) -> None:
        logger.debug("ws_broadcasting", type=payload.get("type"), count=len(list(conn_ids)))
        for cid in conn_ids:
            await self.send_to_conn(cid, payload)

    async def disconnect_conn(self, conn_id: str) -> None:
        ws = self._by_id.get(conn_id)
        if ws:
            await ws.close()
            self.disconnect(ws)
