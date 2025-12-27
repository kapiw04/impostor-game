from dataclasses import dataclass


@dataclass(frozen=True)
class Player:
    conn_id: str
    nickname: str


@dataclass(frozen=True)
class RoomSettings:
    max_players: int = 10


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
    settings: RoomSettings
    host_id: str | None = None
    players: list[Player] = None
