from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from starlette.testclient import WebSocketDenialResponse
from impostor.api.deps import GameServiceDep, RoomServiceDep, WSManagerDep
from impostor.application.errors import RoomNotFoundError

rooms_router = APIRouter(prefix="/rooms")


class RoomIn(BaseModel):
    name: str


class RoomOut(BaseModel):
    room_id: str
    name: str


class LobbyPlayer(BaseModel):
    nick: str | None = None
    ready: bool


class LobbyState(BaseModel):
    room_id: str
    name: str
    players: dict[str, LobbyPlayer]
    host: str | None = None
    settings: dict[str, Any]


class ReadyIn(BaseModel):
    conn_id: str
    ready: bool


class NickIn(BaseModel):
    conn_id: str
    nickname: str = Field(min_length=1, max_length=20)


class SettingsIn(BaseModel):
    conn_id: str
    max_players: int | None = Field(default=None, ge=2, le=20)
    turn_duration: int | None = Field(default=None, ge=5, le=300)
    round_time: int | None = Field(default=None, ge=10, le=300)


class KickIn(BaseModel):
    conn_id: str
    target_conn_id: str


class DisconnectIn(BaseModel):
    conn_id: str


class DisconnectOut(BaseModel):
    token: str


class ReconnectIn(BaseModel):
    token: str


@rooms_router.post("/", response_model=RoomOut)
async def create_room(room_in: RoomIn, room_service: RoomServiceDep):
    room = await room_service.create_room(room_in.name)
    room_out = RoomOut(room_id=room.room_id, name=room.name)

    return room_out


@rooms_router.get("/{room_id}/lobby", response_model=LobbyState)
async def get_lobby_state(room_id: str, room_service: RoomServiceDep):
    try:
        return await room_service.get_lobby_state(room_id)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@rooms_router.post("/{room_id}/ready", response_model=LobbyState)
async def set_ready(
    room_id: str,
    ready_in: ReadyIn,
    room_service: RoomServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        state = await room_service.set_ready(room_id, ready_in.conn_id, ready_in.ready)
        await ws_manager.broadcast(
            state.get("players", {}).keys(),
            {"type": "lobby_state", "room_id": room_id, "state": state},
        )
        return state
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@rooms_router.post("/{room_id}/nick", response_model=LobbyState)
async def set_nickname(
    room_id: str,
    nick_in: NickIn,
    room_service: RoomServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        state = await room_service.set_nickname(
            room_id, nick_in.conn_id, nick_in.nickname
        )
        await ws_manager.broadcast(
            state.get("players", {}).keys(),
            {
                "type": "user_renamed",
                "room_id": room_id,
                "conn_id": nick_in.conn_id,
                "nick": nick_in.nickname,
            },
        )
        await ws_manager.broadcast(
            state.get("players", {}).keys(),
            {"type": "lobby_state", "room_id": room_id, "state": state},
        )
        return state
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@rooms_router.post("/{room_id}/settings", response_model=LobbyState)
async def update_settings(
    room_id: str,
    settings_in: SettingsIn,
    room_service: RoomServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        settings = {
            key: value
            for key, value in {
                "max_players": settings_in.max_players,
                "turn_duration": settings_in.turn_duration,
                "round_time": settings_in.round_time,
            }.items()
            if value is not None
        }
        state = await room_service.update_settings(
            room_id, settings_in.conn_id, settings
        )
        await ws_manager.broadcast(
            state.get("players", {}).keys(),
            {"type": "lobby_state", "room_id": room_id, "state": state},
        )
        return state
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@rooms_router.post("/{room_id}/kick", response_model=LobbyState)
async def kick_player(
    room_id: str,
    kick_in: KickIn,
    room_service: RoomServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        state = await room_service.kick_player(
            room_id, kick_in.conn_id, kick_in.target_conn_id
        )
        await ws_manager.send_to_conn(
            kick_in.target_conn_id,
            {"type": "kicked", "room_id": room_id},
        )
        await ws_manager.close_conn(kick_in.target_conn_id)
        await ws_manager.broadcast(
            state.get("players", {}).keys(),
            {"type": "lobby_state", "room_id": room_id, "state": state},
        )
        return state
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@rooms_router.post("/{room_id}/disconnect", response_model=DisconnectOut)
async def disconnect_room(
    room_id: str,
    disconnect_in: DisconnectIn,
    room_service: RoomServiceDep,
    game_service: GameServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        await game_service.handle_disconnect(
            room_id, disconnect_in.conn_id, notifier=ws_manager
        )
        token = await room_service.disconnect(room_id, disconnect_in.conn_id)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DisconnectOut(token=token)


@rooms_router.post("/reconnect", response_model=LobbyState)
async def reconnect_room(
    reconnect_in: ReconnectIn,
    room_service: RoomServiceDep,
):
    try:
        _, state = await room_service.reconnect(reconnect_in.token)
        return state
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="invalid resume token") from exc


@rooms_router.websocket("/{room_id}/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    room_service: RoomServiceDep,
    game_service: GameServiceDep,
    ws_manager: WSManagerDep,
    token: str | None = Query(None),
    nick: str | None = Query(None, min_length=1, max_length=20),
):
    conn_id = room_service.make_conn_id()
    conns: set[str] = set()
    room_name = ""
    nick_value = nick
    room_id_value = room_id

    async def send_turn_snapshot(target_conn_id: str, room_id_value: str) -> None:
        snapshot = await game_service.get_turn_snapshot(room_id_value)
        if snapshot:
            await ws_manager.send_to_conn(
                target_conn_id,
                {"type": "turn_state", "room_id": room_id_value, "state": snapshot},
            )

    if token:
        try:
            preview = await room_service.preview_reconnect(token)
        except KeyError:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        conn_id = preview["conn_id"]
        await ws_manager.connect(websocket, conn_id)
        try:
            resume, state = await room_service.reconnect(token)
        except (RoomNotFoundError, KeyError):
            ws_manager.disconnect(websocket)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        room_id_value = state["room_id"]
        room_name = await room_service.get_room_name(room_id_value)
        conn_id = resume["conn_id"]
        nick_value = state.get("players", {}).get(conn_id, {}).get("nick") or "unknown"
        conns = set(state.get("players", {}).keys())
        await game_service.handle_reconnect(
            room_id_value, conn_id, resume.get("role"), notifier=ws_manager
        )
        await ws_manager.send_to_conn(
            conn_id,
            {
                "type": "welcome",
                "room_id": room_id_value,
                "conn_id": conn_id,
                "nick": nick_value,
            },
        )
        await ws_manager.send_to_conn(
            conn_id,
            {"type": "lobby_state", "room_id": room_id_value, "state": state},
        )
        await send_turn_snapshot(conn_id, room_id_value)
        other_conns = set(conns) - {conn_id}
        await ws_manager.broadcast(
            other_conns,
            {"type": "user_joined", "room_id": room_id_value, "nick": nick_value},
        )
    else:
        if nick_value is not None and not nick_value.strip():
            raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)
        try:
            room_name, conns = await room_service.join_room(
                room_id=room_id_value,
                conn_id=conn_id,
                nickname=nick_value,
            )
        except RoomNotFoundError:
            raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)
        except RuntimeError:
            raise WebSocketDenialResponse(status_code=status.WS_1008_POLICY_VIOLATION)
        await ws_manager.connect(websocket, conn_id)
        await ws_manager.send_to_conn(
            conn_id,
            {
                "type": "welcome",
                "room_id": room_id_value,
                "conn_id": conn_id,
                "nick": nick_value or "unknown",
            },
        )
        await send_turn_snapshot(conn_id, room_id_value)
        other_conns = set(conns) - {conn_id}
        await ws_manager.broadcast(
            other_conns,
            {"type": "user_joined", "room_id": room_id_value, "nick": nick_value},
        )

    try:
        while True:
            text = await websocket.receive_text()
            await ws_manager.broadcast(
                conns,
                {
                    "type": "msg",
                    "room": room_name,
                    "room_id": room_id_value,
                    "nick": nick_value,
                    "text": text,
                },
            )
    except WebSocketDisconnect:
        pass
    finally:
        await game_service.handle_disconnect(
            room_id=room_id_value, conn_id=conn_id, notifier=ws_manager
        )
        await room_service.leave_room(room_id=room_id_value, conn_id=conn_id)
        ws_manager.disconnect(websocket)
        other_conns = set(conns) - {conn_id}
        await ws_manager.broadcast(
            other_conns,
            {"type": "user_left", "room_id": room_id_value, "nick": nick_value},
        )
