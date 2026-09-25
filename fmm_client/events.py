"""Turns "the state now" and "the state before" into things that happened.

Most plugins want events - "the time is up", "a timer started" - rather than a stream of snapshots,
and getting the edges right is fiddly enough to write once and test. Pure: no I/O, no clock.
"""

from __future__ import annotations

from datetime import datetime

from .client import State

TIMER_STARTED = "timer-started"
TIMER_EXTENDED = "timer-extended"
TIMER_ENDED = "timer-ended"
LOCK_STARTED = "lock-started"
LOCK_ENDED = "lock-ended"
CAME_ONLINE = "came-online"
WENT_OFFLINE = "went-offline"


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text)


def events_between(previous: State | None, current: State) -> list[str]:
    """What changed between two states, as event names in the order they make sense.

    ``previous`` is ``None`` for the first state seen, which reports nothing: a plugin that has just
    started has not watched anything happen, and pretending it has would fire "timer started" for a
    timer that began an hour ago.
    """
    if previous is None:
        return []

    events: list[str] = []

    if previous.timer is None and current.timer is not None:
        events.append(TIMER_STARTED)
    elif previous.timer is not None and current.timer is None:
        events.append(TIMER_ENDED)
    elif previous.timer is not None and current.timer is not None:
        # A different timer is a new one; the same one running longer is an extension.
        if previous.timer.id != current.timer.id:
            events += [TIMER_ENDED, TIMER_STARTED]
        elif _instant(current.timer.ends_at) > _instant(previous.timer.ends_at):
            events.append(TIMER_EXTENDED)

    if previous.lock is None and current.lock is not None:
        events.append(LOCK_STARTED)
    if previous.lock is not None and current.lock is None:
        events.append(LOCK_ENDED)

    if not previous.device.online and current.device.online:
        events.append(CAME_ONLINE)
    if previous.device.online and not current.device.online:
        events.append(WENT_OFFLINE)

    return events


def describe(state: State) -> str:
    """A sentence for a person, for logs and notifications."""
    name = state.device.name

    if state.lock is not None:
        return f"{name} is locked for another {_minutes(state.lock.seconds_left)}."
    if state.timer is not None:
        why = f" ({state.timer.message})" if state.timer.message else ""
        return f"{name} has {_minutes(state.timer.seconds_left)} left{why}."
    return f"{name} has no timer running."


def _minutes(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    whole = round(seconds / 60)
    return f"{whole} minute{'' if whole == 1 else 's'}"
