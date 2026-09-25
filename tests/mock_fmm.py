"""A stand-in for the Five More Minutes plugin API, for tests: the same routes, the same answers,
over real HTTP. Small and deliberately faithful to docs/plugins/api-v1.md rather than clever, so that a
test failing here means the plugin misunderstood the API, not that the mock did.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

KEY = "fmmk_" + "0123456789abcdef" * 2 + "_" + "A" * 43
ALL = ["state:read", "timer:start", "timer:extend", "timer:stop", "timer:cancel"]
DEVICE_ID = "11111111-1111-1111-1111-111111111111"


def _problem(status: int, title: str, detail: str, kind: str = "about:blank") -> tuple[int, dict[str, Any]]:
    return status, {"type": kind, "title": title, "status": status, "detail": detail}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class MockFmm:
    def __init__(
        self,
        *,
        scopes: list[str] | None = None,
        key: str = KEY,
        local_only: bool = False,
        limit: int | None = None,
    ) -> None:
        self.scopes = ALL if scopes is None else scopes
        self.key = key
        self.local_only = local_only
        self.limit = limit
        self.signal = 0
        self.online = True
        self.timer: dict[str, Any] | None = None
        self.lock: dict[str, Any] | None = None
        self.requests: list[dict[str, Any]] = []
        self.fail_next = 0
        self._waiters: list[asyncio.Future[None]] = []
        self._server: TestServer | None = None

    # --- lifecycle ------------------------------------------------------------------------------

    async def start(self) -> str:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._server = TestServer(app)
        await self._server.start_server()
        return f"http://127.0.0.1:{self._server.port}"

    async def close(self) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        if self._server is not None:
            await self._server.close()

    # --- what a parent pressing buttons would do ------------------------------------------------

    def parent_starts(self, minutes: int, message: str | None = None) -> tuple[int, dict[str, Any]]:
        if self.timer:
            return _problem(409, "Not possible right now", "Time is already running on that computer. Add to it instead.")
        if not minutes or minutes < 1:
            return _problem(400, "Cannot do that", "Say how long: a number of minutes, or a time to stop at.")
        self.lock = None
        at = _now()
        self.timer = {
            "id": f"t{self.signal + 1}",
            "startsAt": _iso(at),
            "endsAt": _iso(at + timedelta(minutes=minutes)),
            "message": message,
        }
        self._changed()
        return 200, self._view()

    def parent_locks(self, minutes: int = 30) -> None:
        at = _now()
        self.timer = None
        self.lock = {"startsAt": _iso(at), "endsAt": _iso(at + timedelta(minutes=minutes)), "mode": "Network"}
        self._changed()

    def parent_lifts(self) -> None:
        self.lock = None
        self._changed()

    def set_online(self, online: bool) -> None:
        self.online = online
        self._changed()

    # --- the API --------------------------------------------------------------------------------

    def _changed(self) -> None:
        self.signal += 1
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    @staticmethod
    def _left(moment: str) -> int:
        return max(0, int(-(-(datetime.fromisoformat(moment) - _now()).total_seconds() // 1)))

    def _view(self) -> dict[str, Any]:
        return {
            "apiVersion": 1,
            "serverTime": _iso(_now()),
            "signal": self.signal,
            "device": {"id": DEVICE_ID, "name": "Elliots laptop", "online": self.online},
            "timer": self.timer and {**self.timer, "secondsLeft": self._left(self.timer["endsAt"])},
            "lock": self.lock and {**self.lock, "secondsLeft": self._left(self.lock["endsAt"])},
        }

    def _need(self, scope: str) -> tuple[int, dict[str, Any]] | None:
        if scope in self.scopes:
            return None
        return _problem(403, "Permission missing", f"This key does not have the {scope} permission.")

    async def _handle(self, request: web.Request) -> web.Response:
        text = await request.text()
        body = json.loads(text) if text else {}
        self.requests.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "headers": dict(request.headers),
                "body": json.loads(text) if text else None,
            }
        )

        def send(result: tuple[int, dict[str, Any]], headers: dict[str, str] | None = None) -> web.Response:
            status, payload = result
            return web.Response(
                status=status,
                text=json.dumps(payload),
                content_type="application/problem+json" if status >= 400 else "application/json",
                headers=headers,
            )

        if self.fail_next > 0:
            self.fail_next -= 1
            return send(_problem(500, "Boom", "Something broke."))

        if self.local_only:
            return send(
                _problem(
                    403,
                    "Local network only",
                    "Integration keys work only from the local network.",
                    "https://fivemoreminutes.app/problems/local-network-only",
                )
            )

        if self.limit is not None and len(self.requests) > self.limit:
            return send(_problem(429, "Too many requests", "Slow down."), {"Retry-After": "1"})

        if request.headers.get("Authorization") != f"Bearer {self.key}":
            return send(_problem(401, "Unauthorized", "nope"))

        route = f"{request.method} {request.path.removeprefix('/api/integrations/v1')}"

        if route == "GET /me":
            return send(
                (
                    200,
                    {
                        "apiVersion": 1,
                        "key": {
                            "id": "k1",
                            "name": "Test key",
                            "pluginId": None,
                            "scopes": self.scopes,
                            "createdAt": _iso(_now()),
                            "expiresAt": None,
                            "lastUsedAt": None,
                        },
                        "device": {"id": DEVICE_ID, "name": "Elliots laptop"},
                    },
                )
            )

        if route == "GET /state":
            if denied := self._need("state:read"):
                return send(denied)

            since = int(request.query["since"]) if "since" in request.query else -1
            wait = int(request.query.get("wait", "0"))

            if wait > 0 and since == self.signal:
                waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                self._waiters.append(waiter)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(waiter, timeout=min(wait, 25))

            return send((200, self._view()))

        if route == "POST /timer/start":
            # `until` is a clock time in the household's zone; the mock just treats it as an hour away.
            minutes = body.get("minutes") or (60 if body.get("until") else 0)
            return send(self._need("timer:start") or self.parent_starts(minutes, body.get("message")))

        if route in ("POST /timer/extend", "POST /timer/stop", "POST /timer/cancel"):
            scope = "timer:" + route.rsplit("/", 1)[1]
            if denied := self._need(scope):
                return send(denied)
            if not self.timer:
                return send(_problem(409, "Not possible right now", "Nothing is running on that computer."))

            if scope == "timer:extend":
                ends = datetime.fromisoformat(self.timer["endsAt"]) + timedelta(minutes=body.get("minutes") or 5)
                self.timer["endsAt"] = _iso(ends)
            elif scope == "timer:stop":
                self.timer = None
                at = _now()
                self.lock = {"startsAt": _iso(at), "endsAt": _iso(at + timedelta(minutes=30)), "mode": "Network"}
            else:
                self.timer = None
            self._changed()
            return send((200, self._view()))

        return send(_problem(404, "Not found", "No such route."))


async def started(**options: Any) -> tuple[MockFmm, str]:
    mock = MockFmm(**options)
    return mock, await mock.start()


Runner = Callable[[], Any]
