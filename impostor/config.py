from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _default_config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _require_int(value: Any, default: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class RedisRoomStoreSettings:
    round_time: int = 60
    max_players: int = 8
    turn_duration: int = 30
    turn_grace: int = 60

    def as_dict(self) -> dict[str, int]:
        return {
            "round_time": self.round_time,
            "max_players": self.max_players,
            "turn_duration": self.turn_duration,
            "turn_grace": self.turn_grace,
        }


@dataclass(frozen=True)
class RedisRoomStoreConfig:
    settings: RedisRoomStoreSettings = field(default_factory=RedisRoomStoreSettings)


@dataclass(frozen=True)
class Config:
    timer_tick_seconds: int = 1
    redis_room_store: RedisRoomStoreConfig = field(default_factory=RedisRoomStoreConfig)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        config_path = Path(path) if path else _default_config_path()
        if not config_path.exists():
            return cls()
        raw = yaml.safe_load(config_path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError("config.yaml must contain a mapping")
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        defaults = cls()
        timer_tick = _require_int(
            data.get("timer_tick_seconds"),
            defaults.timer_tick_seconds,
            "timer_tick_seconds",
        )
        redis_data = data.get("redis_room_store")
        settings_data: dict[str, Any] = {}
        if isinstance(redis_data, dict):
            settings_value = redis_data.get("settings")
            if isinstance(settings_value, dict):
                settings_data = settings_value
        settings = RedisRoomStoreSettings(
            round_time=_require_int(
                settings_data.get("round_time"),
                defaults.redis_room_store.settings.round_time,
                "redis_room_store.settings.round_time",
            ),
            max_players=_require_int(
                settings_data.get("max_players"),
                defaults.redis_room_store.settings.max_players,
                "redis_room_store.settings.max_players",
            ),
            turn_duration=_require_int(
                settings_data.get("turn_duration"),
                defaults.redis_room_store.settings.turn_duration,
                "redis_room_store.settings.turn_duration",
            ),
            turn_grace=_require_int(
                settings_data.get("turn_grace"),
                defaults.redis_room_store.settings.turn_grace,
                "redis_room_store.settings.turn_grace",
            ),
        )
        return cls(
            timer_tick_seconds=timer_tick,
            redis_room_store=RedisRoomStoreConfig(settings=settings),
        )
