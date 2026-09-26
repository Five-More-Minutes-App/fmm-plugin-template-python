from __future__ import annotations

import json

from fmm_client.webhook import sign, signing_key, verify_webhook

from .mock_fmm import KEY

# The same vector the service's tests and the Node starter check: three implementations, one answer.
VECTOR_TIMESTAMP = "1758823200"
VECTOR_BODY = '{"a":1}'
VECTOR_SIGNATURE = "v1=f37713737d00007fea817485a555bb9d43390f486496011023acb798df490cf1"

NOW = 1758823200.0
OTHER_KEY = "fmmk_" + "0123456789abcdef" * 2 + "_" + "B" * 43


def delivery(
    *, body: str | None = None, timestamp: str = VECTOR_TIMESTAMP, key: str = KEY
) -> tuple[dict[str, str], str]:
    text = body if body is not None else json.dumps({"id": "abc", "type": "timer.started", "state": {"apiVersion": 1}})
    headers = {
        "X-FMM-Event": "timer.started",
        "X-FMM-Delivery": "d1",
        "X-FMM-Timestamp": timestamp,
        "X-FMM-Signature": sign(key, timestamp, text),
    }
    return headers, text


def check(headers: dict[str, str], body: str | bytes, **kwargs: object):  # type: ignore[no-untyped-def]
    return verify_webhook(KEY, headers=headers, body=body, now=lambda: NOW, **kwargs)  # type: ignore[arg-type]


def test_signing_matches_the_vector_the_service_produces() -> None:
    assert sign(KEY, VECTOR_TIMESTAMP, VECTOR_BODY) == VECTOR_SIGNATURE
    assert sign(KEY, int(VECTOR_TIMESTAMP), VECTOR_BODY.encode()) == VECTOR_SIGNATURE
    assert len(signing_key(KEY)) == 32


def test_anything_that_changes_changes_the_signature() -> None:
    assert sign(OTHER_KEY, VECTOR_TIMESTAMP, VECTOR_BODY) != VECTOR_SIGNATURE
    assert sign(KEY, "1758823201", VECTOR_BODY) != VECTOR_SIGNATURE
    assert sign(KEY, VECTOR_TIMESTAMP, VECTOR_BODY + " ") != VECTOR_SIGNATURE


def test_accepts_a_good_delivery_and_reads_it() -> None:
    headers, body = delivery()

    result = check(headers, body)

    assert result.ok
    assert result.event is not None and result.event["type"] == "timer.started"
    assert result.delivery_id == "d1"


def test_accepts_bytes_and_headers_in_any_case() -> None:
    headers, body = delivery()

    assert check(headers, body.encode()).ok
    assert check({k.lower(): v for k, v in headers.items()}, body).ok


def test_refuses_a_body_that_was_changed_even_by_a_space() -> None:
    headers, body = delivery()

    assert not check(headers, body + " ").ok
    assert not check(headers, body.replace("timer.started", "timer.ended")).ok


def test_refuses_a_signature_made_with_a_different_key() -> None:
    headers, body = delivery(key=OTHER_KEY)

    assert check(headers, body).reason == "the signature does not match"


def test_refuses_what_is_too_old_or_from_the_future() -> None:
    old_headers, old_body = delivery(timestamp=str(1758823200 - 3600))
    future_headers, future_body = delivery(timestamp=str(1758823200 + 3600))
    fresh_headers, fresh_body = delivery(timestamp=str(1758823200 - 200))

    assert "replay" in check(old_headers, old_body).reason
    assert "replay" in check(future_headers, future_body).reason
    assert check(fresh_headers, fresh_body).ok
    assert not check(fresh_headers, fresh_body, tolerance_seconds=60).ok


def test_refuses_one_that_was_restamped_because_the_time_is_inside_the_signature() -> None:
    headers, body = delivery(timestamp="1758823000")

    assert not check({**headers, "X-FMM-Timestamp": "1758823200"}, body).ok


def test_says_so_when_it_is_not_a_delivery_at_all() -> None:
    headers, body = delivery()

    assert "headers are missing" in check({}, "{}").reason
    assert "not a number" in check({**headers, "X-FMM-Timestamp": "yesterday"}, body).reason
    assert "usable API key" in verify_webhook("", headers=headers, body=body, now=lambda: NOW).reason


def test_refuses_a_signed_body_that_is_not_json() -> None:
    headers, body = delivery(body="not json")

    assert "not the JSON" in check(headers, body).reason


def test_never_puts_the_key_in_what_it_says() -> None:
    cases = [delivery(key=OTHER_KEY), delivery(timestamp="1"), ({}, "")]

    for headers, body in cases:
        assert KEY not in repr(check(headers, body))
