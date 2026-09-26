"""A small client for the Five More Minutes plugin API."""

from .client import Computer, FiveMoreMinutes, FmmError, Lock, Me, State, Timer
from .events import describe, events_between
from .webhook import Verified, sign, signing_key, verify_webhook

__all__ = [
    "Computer",
    "FiveMoreMinutes",
    "FmmError",
    "Lock",
    "Me",
    "State",
    "Timer",
    "Verified",
    "describe",
    "events_between",
    "sign",
    "signing_key",
    "verify_webhook",
]
