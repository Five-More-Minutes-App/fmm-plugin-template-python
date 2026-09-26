"""A small client for the Five More Minutes plugin API (v1), using aiohttp.

Copy this package into your own project; it is meant to be read, and changed.

What it will not do, on purpose:

* It never puts your key in an error message, a log line, or a ``repr``.
* It refuses a key that is not shaped like one, so a typo fails at start-up rather than at three in
  the morning.
* It does not follow redirects. The plugin API does not redirect, so a redirect means something is in
  the way, and following it would send your key to wherever it points.

The API itself is described in ``docs/plugins/api-v1.md`` in the Five More Minutes repository.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import aiohttp

BASE_PATH = "/api/integrations/v1"

# fmmk_ + 32 hex characters + _ + 43 url-safe characters.
_KEY_SHAPE = re.compile(r"\Afmmk_[0-9a-f]{32}_[A-Za-z0-9_-]{43}\Z")

_NOT_WORTH_RETRYING = {"config", "auth", "network-only", "forbidden", "not-possible", "invalid"}


class FmmError(Exception):
    """What went wrong, in a form a program can act on.

    ``kind`` is one of:

    ============== ================================================================ ===========
    kind           meaning                                                          retryable
    ============== ================================================================ ===========
    config         The address or the key is not usable. Fix the setup.             no
    auth           The key was refused: wrong, revoked or expired.                  no
    network-only   The service only answers from the local network.                 no
    forbidden      The key is valid but lacks a permission this call needs.         no
    not-possible   The computer is not in a state that allows it.                   no
    invalid        The request itself was wrong.                                    no
    rate-limited   Too many requests. ``retry_after`` says how long to wait.        yes
    network        Could not reach the service at all.                              yes
    unexpected     The service answered with something this client did not expect.  yes
    ============== ================================================================ ===========

    Every message is safe to show a person; none contains the key.
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        """Whether trying the same thing again later could work."""
        return self.kind not in _NOT_WORTH_RETRYING


@dataclass(frozen=True, slots=True)
class Computer:
    id: str
    name: str
    online: bool


@dataclass(frozen=True, slots=True)
class Timer:
    id: str
    starts_at: str
    ends_at: str
    seconds_left: int
    message: str | None


@dataclass(frozen=True, slots=True)
class Lock:
    starts_at: str
    ends_at: str
    seconds_left: int
    mode: str


@dataclass(frozen=True, slots=True)
class State:
    """The computer's timer and lock. ``timer`` and ``lock`` are ``None`` when there is none."""

    api_version: int
    server_time: str
    signal: int
    device: Computer
    timer: Timer | None
    lock: Lock | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> State:
        # Reads the fields it knows and ignores the rest: within v1 the service only ever adds fields.
        device = data["device"]
        timer = data.get("timer")
        lock = data.get("lock")
        return cls(
            api_version=data["apiVersion"],
            server_time=data["serverTime"],
            signal=data["signal"],
            device=Computer(device["id"], device["name"], bool(device["online"])),
            timer=None
            if timer is None
            else Timer(timer["id"], timer["startsAt"], timer["endsAt"], timer["secondsLeft"], timer.get("message")),
            lock=None if lock is None else Lock(lock["startsAt"], lock["endsAt"], lock["secondsLeft"], lock["mode"]),
        )


@dataclass(frozen=True, slots=True)
class Me:
    """Who the key is and what it may do."""

    key_id: str
    name: str
    plugin_id: str | None
    scopes: tuple[str, ...]
    expires_at: str | None
    device_id: str
    device_name: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Me:
        key = data["key"]
        return cls(
            key_id=key["id"],
            name=key["name"],
            plugin_id=key.get("pluginId"),
            scopes=tuple(key["scopes"]),
            expires_at=key.get("expiresAt"),
            device_id=data["device"]["id"],
            device_name=data["device"]["name"],
        )


class FiveMoreMinutes:
    """The plugin API, for the one computer a key opens.

    >>> async with FiveMoreMinutes("http://192.168.1.10:5072", api_key) as fmm:
    ...     print((await fmm.me()).scopes)
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        session: aiohttp.ClientSession | None = None,
        timeout: float = 10.0,
    ) -> None:
        parts = urlsplit(url or "")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FmmError(
                "config",
                f'"{url}" is not a web address that starts with http:// or https://. '
                "Use something like http://192.168.1.10:5072",
            )

        if parts.username or parts.password:
            raise FmmError("config", "Do not put a user name or password in the address. The key goes in FMM_API_KEY.")

        if not isinstance(api_key, str) or not _KEY_SHAPE.match(api_key):
            # Deliberately does not say what was given.
            raise FmmError(
                "config",
                "That does not look like a Five More Minutes API key. It starts with fmmk_ and is 81 characters long.",
            )

        self._base = f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}{BASE_PATH}"
        self._key = api_key
        self._timeout = timeout
        self._session = session
        self._owns_session = session is None

    def __repr__(self) -> str:  # never shows the key
        return f"FiveMoreMinutes({self._base!r})"

    def __getstate__(self) -> object:
        raise TypeError("a client holds a key and cannot be pickled")

    async def __aenter__(self) -> FiveMoreMinutes:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Closes the connection, if this client opened it."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    # --- the API --------------------------------------------------------------------------------

    async def me(self) -> Me:
        """Who this key is, what it may do, and which computer it opens. Call it first."""
        return Me.from_json(await self._request("GET", "/me"))

    async def state(self, *, wait: int | None = None, since: int | None = None) -> State:
        """The computer's timer and lock.

        With ``wait`` (seconds, up to 25) the request is held open until something changes, so a
        plugin hears about a change at once instead of polling for it. ``since`` is the ``signal``
        from the last state you saw; without it the answer is immediate.
        """
        query: dict[str, str] = {}
        timeout = self._timeout
        if wait is not None:
            wait = max(1, min(25, int(wait)))
            query["wait"] = str(wait)
            timeout += wait  # a held-open request has to be allowed to last as long as the wait
        if since is not None:
            query["since"] = str(since)

        return State.from_json(await self._request("GET", "/state", query=query, timeout=timeout))

    async def start(self, *, minutes: int | None = None, until: str | None = None, message: str | None = None) -> State:
        """Start time: ``minutes`` or ``until`` ("20:00", in the household's time zone), not both.

        Starting during a lock lifts the lock.
        """
        body = {k: v for k, v in {"minutes": minutes, "until": until, "message": message}.items() if v is not None}
        return State.from_json(await self._request("POST", "/timer/start", body=body))

    async def extend(self, minutes: int | None = None) -> State:
        """Add time to what is running. Without ``minutes``, the household's usual "five more"."""
        body = {} if minutes is None else {"minutes": minutes}
        return State.from_json(await self._request("POST", "/timer/extend", body=body))

    async def stop(self) -> State:
        """Time is up, now: the timer ends and the lock the rules ask for begins."""
        return State.from_json(await self._request("POST", "/timer/stop"))

    async def cancel(self) -> State:
        """Let go: the timer ends and nothing else happens. The computer is simply free."""
        return State.from_json(await self._request("POST", "/timer/cancel"))

    async def watch(
        self, *, wait_seconds: int = 25, backoff: tuple[float, float] = (1.0, 60.0)
    ) -> AsyncIterator[State]:
        """Follows the computer: yields the state now, then again each time it changes.

        Reconnects by itself when the network drops; raises the error when trying again cannot
        help, such as when the key is revoked. Stop it by cancelling the task or breaking the loop.
        """
        minimum, maximum = backoff
        since: int | None = None
        delay = minimum

        while True:
            try:
                state = await self.state(wait=wait_seconds, since=since)
            except FmmError as error:
                if not error.retryable:
                    raise
                pause = error.retry_after if error.retry_after else delay
                await asyncio.sleep(pause + random.uniform(0, 0.25))
                delay = min(delay * 2, maximum)
                continue

            since = state.signal
            delay = minimum
            yield state

    # --- the plumbing ---------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - aiohttp's own total timeout, not a wrapper
    ) -> dict[str, Any]:
        if self._session is None:
            self._session = aiohttp.ClientSession()

        try:
            async with self._session.request(
                method,
                f"{self._base}{path}",
                params=query,
                json=body,
                headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout or self._timeout),
            ) as response:
                if 300 <= response.status < 400:
                    raise FmmError(
                        "unexpected",
                        "The service redirected the request, which it never does. "
                        "Something is in the way; check the address.",
                        status=response.status,
                    )

                if response.status < 300:
                    try:
                        data = await response.json(content_type=None)
                    except ValueError as error:
                        raise FmmError(
                            "unexpected",
                            "The service answered with something that was not JSON.",
                            status=response.status,
                        ) from error
                    if not isinstance(data, dict):
                        raise FmmError(
                            "unexpected", "The service answered with an unexpected shape.", status=response.status
                        )
                    return data

                raise await _problem(response)
        except FmmError:
            raise
        except (aiohttp.ClientError, TimeoutError) as error:
            # The connection errors carry the address and never the request, so chaining them
            # does not put the key in a traceback. (aiohttp's ClientResponseError does carry the
            # request headers, which is why this client never calls raise_for_status.)
            raise FmmError(
                "network",
                f"Could not reach Five More Minutes at {urlsplit(self._base).netloc}. "
                "Is it running, and is this on the same network?",
            ) from error


async def _problem(response: aiohttp.ClientResponse) -> FmmError:
    """Turns a refusal into an error a program can act on."""
    try:
        problem = await response.json(content_type=None)
    except ValueError:
        problem = {}
    if not isinstance(problem, dict):
        problem = {}

    detail = problem.get("detail") or problem.get("title") or response.reason or "The service refused the request."
    status = response.status

    if status == 401:
        return FmmError(
            "auth",
            "The API key was not accepted. It may have been revoked or have expired; make a new one in the portal.",
            status=status,
        )
    if status == 403:
        if str(problem.get("type", "")).endswith("/local-network-only"):
            return FmmError(
                "network-only",
                "Five More Minutes only answers plugins on the local network. "
                "Run this on the same network as the service.",
                status=status,
            )
        return FmmError("forbidden", detail, status=status)
    if status in (404, 409):
        return FmmError("not-possible", detail, status=status)
    if status == 400:
        return FmmError("invalid", detail, status=status)
    if status == 429:
        try:
            seconds = float(response.headers.get("Retry-After", ""))
        except ValueError:
            seconds = 0.0
        return FmmError("rate-limited", detail, status=status, retry_after=seconds or None)

    return FmmError("unexpected", f"The service answered {status}.", status=status)
