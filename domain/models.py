from dataclasses import dataclass


@dataclass(frozen=True)
class Room:
    room_id: str
    name: str
