"""A small client for the Five More Minutes plugin API."""

from .client import Computer, FiveMoreMinutes, FmmError, Lock, Me, State, Timer
from .events import describe, events_between

__all__ = [
    "Computer",
    "FiveMoreMinutes",
    "FmmError",
    "Lock",
    "Me",
    "State",
    "Timer",
    "describe",
    "events_between",
]
