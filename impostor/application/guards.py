from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar, cast

from impostor.application.errors import RoomNotFoundError

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def room_exists(func: F) -> F:
    @wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        room_id = kwargs.get("room_id")
        if room_id is None:
            if not args:
                raise ValueError("room_id is required")
            room_id = args[0]
        if await self._store.get_room_name(room_id) is None:
            raise RoomNotFoundError(room_id)
        return await func(self, *args, **kwargs)

    return cast(F, wrapper)
