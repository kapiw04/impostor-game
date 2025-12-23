from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from starlette.testclient import WebSocketDenialResponse
from impostor.api.deps import RoomServiceDep, WSManagerDep
from impostor.application.errors import RoomNotFoundError

rooms_router = APIRouter(prefix="/rooms")


class RoomIn(BaseModel):
    name: str


class RoomOut(BaseModel):
    room_id: str
    name: str


@rooms_router.post("/", response_model=RoomOut)
async def create_room(room_in: RoomIn, room_service: RoomServiceDep):
    room = await room_service.create_room(room_in.name)
    room_out = RoomOut(room_id=room.room_id, name=room.name)

    return room_out


@rooms_router.websocket("/{room_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    room_service: RoomServiceDep,
    ws_manager: WSManagerDep,
    nick: str = Query(..., min_length=1, max_length=20),
):
    conn_id = room_service.make_conn_id()

    try:
        room_name, conns = await room_service.join_room(
            room_id=room_id,
            conn_id=conn_id,
            nickname=nick,
        )
    except RoomNotFoundError:
        raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)

    await ws_manager.broadcast(
        conns, {"type": "user_joined", "room_id": room_id, "nick": nick}
    )

    try:
        await ws_manager.connect(websocket, conn_id)
        while True:
            text = await websocket.receive_text()
            await ws_manager.broadcast(
                conns,
                {
                    "type": "msg",
                    "room": room_name,
                    "room_id": room_id,
                    "nick": nick,
                    "text": text,
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        await room_service.leave_room(room_id=room_id, conn_id=conn_id)
        ws_manager.disconnect(websocket)
        await ws_manager.broadcast(
            conns, {"type": "user_left", "room_id": room_id, "nick": nick}
        )
