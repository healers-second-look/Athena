"""Transient-failure retry policy."""

import httpx
import pytest

from secondlook.http_retry import RETRYABLE_STATUS, is_retryable, with_retry


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test/x")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(code, request=request)
    )


def test_transport_errors_are_retryable():
    assert is_retryable(httpx.ConnectError("reset")) is True
    assert is_retryable(httpx.ReadTimeout("slow")) is True


@pytest.mark.parametrize("code", sorted(RETRYABLE_STATUS))
def test_rate_limit_and_server_errors_are_retryable(code):
    assert is_retryable(_status_error(code)) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_client_errors_are_not_retryable(code):
    """A 404 means the record is absent; retrying makes a clear answer a slow one."""
    assert is_retryable(_status_error(code)) is False


def test_succeeds_after_a_transient_failure():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("reset by peer")
        return "ok"

    assert with_retry(flaky, sleeper=lambda _s: None) == "ok"
    assert len(calls) == 3


def test_gives_up_and_reraises_the_original_error():
    """A real outage must still surface — retry is not suppression."""

    def dead():
        raise httpx.ConnectError("reset by peer")

    with pytest.raises(httpx.ConnectError):
        with_retry(dead, attempts=3, sleeper=lambda _s: None)


def test_non_retryable_error_is_not_retried():
    calls = []

    def missing():
        calls.append(1)
        raise _status_error(404)

    with pytest.raises(httpx.HTTPStatusError):
        with_retry(missing, sleeper=lambda _s: None)
    assert len(calls) == 1


def test_backoff_is_exponential():
    waits = []

    def dead():
        raise httpx.ConnectError("reset")

    with pytest.raises(httpx.ConnectError):
        with_retry(dead, attempts=3, backoff_seconds=0.5, sleeper=waits.append)
    assert waits == [0.5, 1.0]


def test_no_sleep_when_the_first_attempt_succeeds():
    waits = []
    assert with_retry(lambda: "ok", sleeper=waits.append) == "ok"
    assert waits == []


def test_uniprot_still_converts_an_exhausted_retry_to_its_own_error():
    """Retry must not change the error type callers already handle."""
    from secondlook.uniprot import UniProtLookupError, UniProtSequenceProvider

    class ResettingTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("reset by peer", request=request)

    client = httpx.Client(transport=ResettingTransport())
    with pytest.raises(UniProtLookupError):
        UniProtSequenceProvider(client=client).fetch("TP53")
