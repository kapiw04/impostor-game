from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from starlette.testclient import WebSocketDenialResponse
from impostor.api.deps import RoomServiceDep, WSManagerDep
from impostor.application.errors import RoomNotFoundError, RoomFullError

rooms_router = APIRouter(prefix="/rooms")


import json
from dataclasses import asdict


class RoomSettingsMsg(BaseModel):
    max_players: int = 10


class RoomIn(BaseModel):
    name: str
    max_players: int = 10


class RoomOut(BaseModel):
    room_id: str
    name: str
    settings: RoomSettingsMsg


@rooms_router.post("/", response_model=RoomOut)
async def create_room(room_in: RoomIn, room_service: RoomServiceDep):
    room = await room_service.create_room(room_in.name, room_in.max_players)
    room_out = RoomOut(
        room_id=room.room_id,
        name=room.name,
        settings=RoomSettingsMsg(max_players=room.settings.max_players),
    )

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
        room = await room_service.join_room(
            room_id=room_id,
            conn_id=conn_id,
            nickname=nick,
        )
    except RoomNotFoundError:
        raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)
    except RoomFullError:
        raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)
    except Exception:
        raise WebSocketDenialResponse(status_code=status.WS_1011_INTERNAL_ERROR)

    conns = [p.conn_id for p in room.players]

    await ws_manager.broadcast(
        conns,
        {
            "type": "room_state",
            "room": asdict(room),
        },
    )

    try:
        await ws_manager.connect(websocket, conn_id)
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "msg":
                await ws_manager.broadcast(
                    conns,
                    {
                        "type": "msg",
                        "nick": nick,
                        "text": data.get("text"),
                    },
                )
            elif msg_type == "kick":
                target_id = data.get("target_id")
                try:
                    await room_service.kick_player(
                        room_id=room_id, host_id=conn_id, target_conn_id=target_id
                    )
                    await ws_manager.disconnect_conn(target_id)
                except Exception:
                    pass
            elif msg_type == "settings":
                new_max = data.get("max_players")
                try:
                    await room_service.update_room_settings(
                        room_id=room_id, host_id=conn_id, max_players=new_max
                    )
                    updated_room = await room_service._store.get_room(room_id)
                    if updated_room:
                        await ws_manager.broadcast(
                            conns,
                            {
                                "type": "room_state",
                                "room": asdict(updated_room),
                            },
                        )
                except Exception:
                    pass

    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        await room_service.leave_room(room_id=room_id, conn_id=conn_id)
        ws_manager.disconnect(websocket)
        
        room = await room_service._store.get_room(room_id)
        if room:
            conns = [p.conn_id for p in room.players]
            await ws_manager.broadcast(
                conns,
                {
                    "type": "room_state",
                    "room": asdict(room),
                },
            )
        else:
            await ws_manager.broadcast(
                conns,
                {
                    "type": "room_closed",
                    "room_id": room_id,
                },
            )
