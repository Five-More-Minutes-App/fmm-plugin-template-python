from __future__ import annotations

import asyncio
import copy
import pickle

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from fmm_client import FiveMoreMinutes, FmmError

from .mock_fmm import KEY

OTHER_KEY = "fmmk_" + "f" * 32 + "_" + "B" * 43


def assert_no_key(error: FmmError) -> None:
    assert KEY not in str(error)
    assert KEY not in repr(error)
    assert error.__traceback__ is None or KEY not in "".join(map(str, [error.args]))


# --- setting up --------------------------------------------------------------------------------


def test_takes_a_web_address_and_a_key() -> None:
    FiveMoreMinutes("http://192.168.1.10:5072", KEY)
    FiveMoreMinutes("https://fmm.example.com/", KEY)


@pytest.mark.parametrize(
    "url", ["", "not a url", "192.168.1.10:5072", "ftp://192.168.1.10", "file:///etc/passwd", "javascript:alert(1)"]
)
def test_refuses_an_address_that_is_not_one(url: str) -> None:
    with pytest.raises(FmmError) as info:
        FiveMoreMinutes(url, KEY)
    assert info.value.kind == "config"


def test_refuses_credentials_in_the_address() -> None:
    with pytest.raises(FmmError, match="Do not put"):
        FiveMoreMinutes("http://user:pass@192.168.1.10", KEY)


@pytest.mark.parametrize(
    "key", ["", "hunter2", "fmmk_short", KEY + "x", " " + KEY, KEY.upper(), KEY.replace("fmmk_", "fmmx_"), KEY + "\n"]
)
def test_refuses_a_key_that_is_not_shaped_like_one_without_repeating_it(key: str) -> None:
    with pytest.raises(FmmError) as info:
        FiveMoreMinutes("http://localhost:5072", key)
    assert info.value.kind == "config"
    assert key.strip() == "" or key not in str(info.value)


def test_never_shows_the_key_when_printed_or_copied() -> None:
    client = FiveMoreMinutes("http://localhost:5072", KEY)

    for text in (repr(client), str(client), f"{client!r}", repr([client]), repr({"c": client})):
        assert KEY not in text
        assert "fmmk_" not in text

    with pytest.raises(TypeError):
        pickle.dumps(client)
    with pytest.raises(TypeError):
        copy.deepcopy(client)


# --- asking ------------------------------------------------------------------------------------


async def test_sends_the_key_as_a_bearer_token(make) -> None:
    mock, fmm = await make()
    await fmm.me()

    request = mock.requests[0]
    assert request["headers"]["Authorization"] == f"Bearer {KEY}"
    assert request["path"] == "/api/integrations/v1/me"


async def test_says_who_the_key_is_and_what_it_may_do(make) -> None:
    _, fmm = await make(scopes=["state:read"])
    me = await fmm.me()

    assert me.scopes == ("state:read",)
    assert me.device_name == "Elliots laptop"
    assert me.expires_at is None


async def test_reads_the_state_of_the_one_computer(make) -> None:
    _, fmm = await make()
    state = await fmm.state()

    assert state.timer is None
    assert state.lock is None
    assert state.device.online is True
    assert isinstance(state.signal, int)


async def test_ignores_fields_it_does_not_know_because_v1_only_ever_adds_them(make) -> None:
    mock, fmm = await make()
    view = mock._view  # noqa: SLF001

    def with_extras() -> dict:
        data = view()
        data["somethingNew"] = {"a": 1}
        data["device"]["colour"] = "blue"
        return data

    mock._view = with_extras  # type: ignore[method-assign]  # noqa: SLF001
    assert (await fmm.state()).device.name == "Elliots laptop"


# --- doing -------------------------------------------------------------------------------------


async def test_starts_extends_and_stops(make) -> None:
    mock, fmm = await make()

    started = await fmm.start(minutes=30, message="Homework")
    assert started.timer is not None
    assert started.timer.message == "Homework"
    assert started.timer.seconds_left > 1700
    assert mock.requests[-1]["body"] == {"minutes": 30, "message": "Homework"}

    extended = await fmm.extend(10)
    assert extended.timer is not None
    assert extended.timer.seconds_left > 2300

    stopped = await fmm.stop()
    assert stopped.timer is None
    assert stopped.lock is not None
    assert stopped.lock.seconds_left > 0


async def test_cancelling_leaves_no_lock(make) -> None:
    _, fmm = await make()
    await fmm.start(minutes=10)

    state = await fmm.cancel()

    assert state.timer is None
    assert state.lock is None


async def test_leaves_out_what_it_was_not_given(make) -> None:
    mock, fmm = await make()
    await fmm.start(until="20:00")
    assert mock.requests[-1]["body"] == {"until": "20:00"}

    await fmm.extend()
    assert mock.requests[-1]["body"] == {}


# --- being refused -----------------------------------------------------------------------------


async def test_says_the_key_was_not_accepted(make) -> None:
    _, fmm = await make(key=OTHER_KEY)
    with pytest.raises(FmmError) as info:
        await fmm.me()

    assert info.value.kind == "auth"
    assert not info.value.retryable
    assert_no_key(info.value)


async def test_says_a_permission_is_missing_naming_it(make) -> None:
    _, fmm = await make(scopes=["state:read"])
    with pytest.raises(FmmError, match="timer:start") as info:
        await fmm.start(minutes=5)

    assert info.value.kind == "forbidden"


async def test_says_the_service_only_answers_on_the_local_network(make) -> None:
    _, fmm = await make(local_only=True)
    with pytest.raises(FmmError, match="local network") as info:
        await fmm.me()

    assert info.value.kind == "network-only"
    assert not info.value.retryable


async def test_says_when_the_computer_is_not_in_a_state_that_allows_it(make) -> None:
    _, fmm = await make()

    for action in (lambda: fmm.extend(5), fmm.stop, fmm.cancel):
        with pytest.raises(FmmError) as info:
            await action()
        assert info.value.kind == "not-possible"

    await fmm.start(minutes=5)
    with pytest.raises(FmmError) as info:
        await fmm.start(minutes=5)
    assert info.value.kind == "not-possible"


async def test_says_when_the_request_was_wrong(make) -> None:
    _, fmm = await make()
    with pytest.raises(FmmError) as info:
        await fmm.start()

    assert info.value.kind == "invalid"


async def test_says_how_long_to_wait_when_slowed_down(make) -> None:
    _, fmm = await make(limit=0)
    with pytest.raises(FmmError) as info:
        await fmm.me()

    assert info.value.kind == "rate-limited"
    assert info.value.retry_after == 1
    assert info.value.retryable


async def test_calls_a_server_error_unexpected_and_worth_retrying(make) -> None:
    mock, fmm = await make()
    mock.fail_next = 1

    with pytest.raises(FmmError) as info:
        await fmm.me()

    assert info.value.kind == "unexpected"
    assert info.value.retryable


async def test_says_when_the_service_cannot_be_reached(make) -> None:
    mock, fmm = await make()
    await mock.close()

    with pytest.raises(FmmError) as info:
        await fmm.me()

    assert info.value.kind == "network"
    assert info.value.retryable
    assert_no_key(info.value)
    assert KEY not in "".join(map(repr, [info.value.__cause__]))


async def test_gives_up_on_a_service_that_does_not_answer(make) -> None:
    async def stuck(_request: web.Request) -> web.Response:
        await asyncio.sleep(30)
        return web.Response()

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stuck)
    server = TestServer(app)
    await server.start_server()
    try:
        fmm = FiveMoreMinutes(f"http://127.0.0.1:{server.port}", KEY, timeout=0.15)
        with pytest.raises(FmmError) as info:
            await fmm.me()
        assert info.value.kind == "network"
        await fmm.close()
    finally:
        await server.close()


# --- never sending the key somewhere else ------------------------------------------------------


async def test_does_not_follow_a_redirect() -> None:
    seen: list[str | None] = []

    async def elsewhere(request: web.Request) -> web.Response:
        seen.append(request.headers.get("Authorization"))
        return web.json_response({})

    other = TestServer(web.Application())
    other.app.router.add_route("*", "/{tail:.*}", elsewhere)
    await other.start_server()

    async def redirect(_request: web.Request) -> web.Response:
        raise web.HTTPFound(f"http://127.0.0.1:{other.port}/steal")

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", redirect)
    server = TestServer(app)
    await server.start_server()

    try:
        fmm = FiveMoreMinutes(f"http://127.0.0.1:{server.port}", KEY)
        with pytest.raises(FmmError) as info:
            await fmm.me()
        assert info.value.kind == "unexpected"
        assert seen == [], "the key was sent to the redirect target"
        await fmm.close()
    finally:
        await server.close()
        await other.close()


# --- waiting for a change ----------------------------------------------------------------------


async def test_holds_the_request_open_until_something_changes_then_answers_at_once(make) -> None:
    mock, fmm = await make()
    before = await fmm.state()

    waiting = asyncio.create_task(fmm.state(wait=20, since=before.signal))
    await asyncio.sleep(0.2)
    assert not waiting.done()
    mock.parent_starts(15, "x")

    after = await asyncio.wait_for(waiting, timeout=5)

    assert after.signal > before.signal
    assert after.timer is not None
    assert after.timer.message == "x"
    assert mock.requests[-1]["query"] == {"wait": "20", "since": str(before.signal)}


async def test_keeps_the_wait_inside_what_the_service_allows(make) -> None:
    mock, fmm = await make()
    await fmm.state(wait=999)
    await fmm.state(wait=-5)

    assert mock.requests[0]["query"]["wait"] == "25"
    assert mock.requests[1]["query"]["wait"] == "1"


# --- watching ----------------------------------------------------------------------------------


async def collect(fmm: FiveMoreMinutes, count: int, during=None) -> list:
    seen: list = []

    async def run() -> None:
        async for state in fmm.watch(wait_seconds=5, backoff=(0.02, 0.04)):
            seen.append(state)
            if len(seen) >= count:
                return

    task = asyncio.create_task(run())
    if during:
        await during()
    await asyncio.wait_for(task, timeout=10)
    return seen


async def test_yields_the_state_now_then_again_for_each_change(make) -> None:
    mock, fmm = await make()

    async def during() -> None:
        await asyncio.sleep(0.15)
        mock.parent_starts(20, "Homework")
        await asyncio.sleep(0.15)
        mock.parent_locks()

    seen = await collect(fmm, 3, during)

    assert seen[0].timer is None
    assert seen[1].timer is not None
    assert seen[1].timer.message == "Homework"
    assert seen[2].timer is None
    assert seen[2].lock is not None


async def test_carries_on_through_a_hiccup(make) -> None:
    mock, fmm = await make()
    mock.fail_next = 2

    seen = await collect(fmm, 1)

    assert len(seen) == 1
    assert len(mock.requests) >= 3


async def test_stops_with_the_error_when_trying_again_cannot_help(make) -> None:
    _, fmm = await make(key=OTHER_KEY)

    with pytest.raises(FmmError) as info:
        async for _ in fmm.watch(wait_seconds=1):
            pass

    assert info.value.kind == "auth"


async def test_watching_only_reads(make) -> None:
    mock, fmm = await make(scopes=["state:read"])
    assert len(await collect(fmm, 1)) == 1
    assert all(request["method"] == "GET" for request in mock.requests)
