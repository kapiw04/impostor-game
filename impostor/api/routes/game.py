from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from impostor.api.deps import GameServiceDep, WSManagerDep
from impostor.application.errors import RoomNotFoundError

game_router = APIRouter(prefix="/rooms")


class StartGameIn(BaseModel):
    conn_id: str


class StatusOut(BaseModel):
    status: str


class EndGameIn(BaseModel):
    result: dict[str, Any] | None = None


class EndGameOut(BaseModel):
    result: dict[str, Any]


class VoteIn(BaseModel):
    conn_id: str
    target_conn_id: str


class VoteOut(BaseModel):
    votes: dict[str, str]
    tally: dict[str, int]


@game_router.post("/{room_id}/start", response_model=StatusOut)
async def start_game(
    room_id: str,
    start_in: StartGameIn,
    game_service: GameServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        await game_service.start_game(room_id, start_in.conn_id, notifier=ws_manager)
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StatusOut(status="started")


@game_router.post("/{room_id}/end", response_model=EndGameOut)
async def end_game(
    room_id: str,
    end_in: EndGameIn,
    game_service: GameServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        result = await game_service.end_game(
            room_id, notifier=ws_manager, result=end_in.result
        )
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EndGameOut(result=result)


@game_router.post("/{room_id}/vote", response_model=VoteOut)
async def cast_vote(
    room_id: str,
    vote_in: VoteIn,
    game_service: GameServiceDep,
    ws_manager: WSManagerDep,
):
    try:
        result = await game_service.cast_vote(
            room_id=room_id,
            voter_conn_id=vote_in.conn_id,
            target_conn_id=vote_in.target_conn_id,
            notifier=ws_manager,
        )
    except RoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return VoteOut(votes=result["votes"], tally=result["tally"])
