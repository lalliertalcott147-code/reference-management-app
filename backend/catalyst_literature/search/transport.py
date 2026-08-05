from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2


@dataclass(frozen=True)
class JsonResponse:
    status_code: int
    data: dict[str, Any]
    headers: Mapping[str, str]


class JsonTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15,
    ) -> JsonResponse: ...


class HttpxTransport:
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15,
    ) -> JsonResponse:
        with httpx2.Client(trust_env=True, timeout=timeout) as client:
            response = client.get(url, params=params, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": "Response was not valid JSON"}
        return JsonResponse(response.status_code, payload, response.headers)


class RetryPolicy:
    def __init__(
        self,
        *,
        attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.attempts = attempts
        self.sleeper = sleeper

    def get(
        self,
        transport: JsonTransport,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 15,
    ) -> JsonResponse:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = transport.get(url, params=params, headers=headers, timeout=timeout)
            except Exception as error:  # transport boundary
                last_error = error
            else:
                if response.status_code < 500 or attempt == self.attempts - 1:
                    return response
            if attempt < self.attempts - 1:
                self.sleeper(float(2**attempt))
        if last_error is not None:
            raise last_error
        raise RuntimeError("Retry policy exhausted without a response")


class RateGate:
    def __init__(
        self,
        requests_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("Request rate must be positive")
        self.minimum_interval = 1.0 / requests_per_second
        self.clock = clock
        self.sleeper = sleeper
        self.last_request_at: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self.last_request_at is not None:
            delay = self.minimum_interval - (now - self.last_request_at)
            if delay > 0:
                self.sleeper(delay)
                now = self.clock()
        self.last_request_at = now
