from enum import Enum


class TurnEndReason(str, Enum):
    SPOKEN = "spoken"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"
