"""Checking that a webhook really came from Five More Minutes.

Anyone on your network can send your plugin a request, so a delivery is not believed until its signature
checks out. The signing key is worked out from your own key's secret, so there is nothing new to store.
See "Webhooks" in the public API reference at https://api.fivemoreminutes.app/docs.

>>> result = verify_webhook(api_key, headers=request.headers, body=raw_body)
>>> if not result.ok:
...     reject(401)             # result.reason is for your log; it never holds the key
>>> result.event["type"]        # "timer.started", and result.event["state"] is the computer's state then

Check the **raw** body. Re-serialising parsed JSON changes the bytes, and the signature is over the bytes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# How old a delivery may be before it is refused, in seconds. The timestamp is signed, so this stops replays.
DEFAULT_TOLERANCE_SECONDS = 300


def signing_key(api_key: str) -> bytes:
    """The key deliveries are signed with, worked out from your API key."""
    # The secret is the last 43 characters of the key. The service stores its SHA-256 as upper-case hex.
    secret = api_key[-43:]
    digest = hashlib.sha256(secret.encode()).hexdigest().upper()
    return hmac.new(digest.encode(), b"fmm-webhook-v1", hashlib.sha256).digest()


def sign(api_key: str, timestamp: str | int, body: str | bytes) -> str:
    """The signature of a delivery: ``v1=`` and the hex HMAC-SHA256 of ``"{timestamp}.{body}"``."""
    raw = body if isinstance(body, bytes) else body.encode()
    message = f"{timestamp}.".encode() + raw
    return "v1=" + hmac.new(signing_key(api_key), message, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class Verified:
    """The outcome of checking a delivery. ``event`` and ``delivery_id`` are only set when ``ok``."""

    ok: bool
    reason: str = ""
    event: dict[str, Any] | None = None
    delivery_id: str = ""


def verify_webhook(
    api_key: str,
    *,
    headers: Mapping[str, str],
    body: str | bytes,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
    now: Callable[[], float] = time.time,
) -> Verified:
    """Verifies a delivery and reads it. Never raises for a bad one: it says why not."""
    lowered = {name.lower(): value for name, value in headers.items()}
    signature = lowered.get("x-fmm-signature")
    timestamp = lowered.get("x-fmm-timestamp")
    delivery_id = lowered.get("x-fmm-delivery")

    if not signature or not timestamp or not delivery_id:
        return Verified(False, "not a Five More Minutes delivery: headers are missing")
    if not timestamp.isdigit() or len(timestamp) > 12:
        return Verified(False, "the timestamp is not a number")
    if not isinstance(api_key, str) or len(api_key) < 43:
        return Verified(False, "no usable API key to check with")

    if abs(now() - int(timestamp)) > tolerance_seconds:
        return Verified(False, "the timestamp is too old or too new: it may be a replay")

    # Constant-time, so how much of a guess was right cannot be read from how long the answer took.
    if not hmac.compare_digest(sign(api_key, timestamp, body).encode(), signature.encode()):
        return Verified(False, "the signature does not match")

    # Only now is the body trusted enough to read.
    try:
        event = json.loads(body)
    except ValueError:
        return Verified(False, "the body is not the JSON a delivery carries")
    if not isinstance(event, dict) or not isinstance(event.get("type"), str) or not isinstance(event.get("id"), str):
        return Verified(False, "the body is not the JSON a delivery carries")

    return Verified(True, event=event, delivery_id=delivery_id)
