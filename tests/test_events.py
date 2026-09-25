from __future__ import annotations

from fmm_client import Computer, Lock, State, Timer, describe, events_between


def state(*, timer: Timer | None = None, lock: Lock | None = None, online: bool = True) -> State:
    return State(1, "2026-09-25T18:00:00+00:00", 1, Computer("d", "Elliots laptop", online), timer, lock)


def timer(id_: str, ends_at: str, message: str | None = None, seconds: int = 600) -> Timer:
    return Timer(id_, "2026-09-25T18:00:00+00:00", ends_at, seconds, message)


def lock(seconds: int = 1800) -> Lock:
    return Lock("2026-09-25T18:10:00+00:00", "2026-09-25T18:40:00+00:00", seconds, "Network")


T1 = "2026-09-25T18:10:00+00:00"
T2 = "2026-09-25T18:20:00+00:00"


def test_nothing_the_first_time() -> None:
    assert events_between(None, state(timer=timer("a", T1))) == []
    assert events_between(None, state(lock=lock())) == []


def test_nothing_when_nothing_changed() -> None:
    s = state(timer=timer("a", T1))
    assert events_between(s, s) == []


def test_a_timer_starting() -> None:
    assert events_between(state(), state(timer=timer("a", T1))) == ["timer-started"]


def test_a_timer_being_made_longer_is_not_a_new_timer() -> None:
    assert events_between(state(timer=timer("a", T1)), state(timer=timer("a", T2))) == ["timer-extended"]


def test_a_timer_ending_with_no_lock_is_being_let_go() -> None:
    assert events_between(state(timer=timer("a", T1)), state()) == ["timer-ended"]


def test_time_being_up_is_the_timer_ending_and_the_lock_starting_together() -> None:
    assert events_between(state(timer=timer("a", T1)), state(lock=lock())) == ["timer-ended", "lock-started"]


def test_the_lock_lifting() -> None:
    assert events_between(state(lock=lock()), state()) == ["lock-ended"]


def test_starting_time_during_a_lock_lifts_it() -> None:
    assert events_between(state(lock=lock()), state(timer=timer("b", T2))) == ["timer-started", "lock-ended"]


def test_one_timer_replaced_by_another_in_a_single_step() -> None:
    assert events_between(state(timer=timer("a", T1)), state(timer=timer("b", T2))) == ["timer-ended", "timer-started"]


def test_the_computer_going_away_and_coming_back() -> None:
    assert events_between(state(), state(online=False)) == ["went-offline"]
    assert events_between(state(online=False), state()) == ["came-online"]


def test_saying_it_in_words() -> None:
    assert describe(state(lock=lock(600))) == "Elliots laptop is locked for another 10 minutes."
    assert describe(state(timer=timer("a", T1, "Homework", 90))) == "Elliots laptop has 2 minutes left (Homework)."
    assert describe(state()) == "Elliots laptop has no timer running."
    assert describe(state(timer=timer("a", T1, seconds=1))) == "Elliots laptop has 1 second left."
    assert describe(state(timer=timer("a", T1, seconds=45))) == "Elliots laptop has 45 seconds left."
