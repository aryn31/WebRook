"""HookFlow API client (stdlib only)."""

from __future__ import annotations

import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable, Generic, Iterator, Mapping, Sequence, TypeVar

from . import __version__
from .errors import APIConnectionError, APITimeoutError, HookFlowError, error_from_response

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRY_WAIT = 30.0  # never sleep longer than this for one retry (e.g. a daily-quota Retry-After)

T = TypeVar("T")
_sleep = time.sleep  # patched in tests


class _NotGiven:
    def __repr__(self) -> str:
        return "NOT_GIVEN"

    def __bool__(self) -> bool:
        return False


NOT_GIVEN: Any = _NotGiven()


def _clean(params: Mapping[str, Any]) -> dict[str, Any]:
    """Drop unset values and convert datetimes to ISO 8601."""
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value is NOT_GIVEN:
            continue
        if isinstance(value, datetime):
            value = value.isoformat()
        out[key] = value
    return out


def _seg(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("id must be a non-empty string")
    return urllib.parse.quote(value, safe="")


class Page(Generic[T]):
    """One page of a cursor-paginated list. Iterating a page yields only its own items;
    use :meth:`auto_paging_iter` to walk every page."""

    def __init__(self, data: list[T], next_cursor: str | None, fetch_next: Callable[[str], "Page[T]"]):
        self.data = data
        self.next_cursor = next_cursor
        self._fetch_next = fetch_next

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None

    def next_page(self) -> "Page[T] | None":
        return self._fetch_next(self.next_cursor) if self.next_cursor else None

    def auto_paging_iter(self) -> Iterator[T]:
        page: Page[T] | None = self
        while page is not None:
            yield from page.data
            page = page.next_page()

    def __iter__(self) -> Iterator[T]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __repr__(self) -> str:
        return f"Page(len={len(self.data)}, next_cursor={self.next_cursor!r})"


class HookFlow:
    """Client for the HookFlow API.

    :param api_key: ``hf_<prefix>_<secret>``. Defaults to the ``HOOKFLOW_API_KEY`` environment variable.
    :param base_url: API origin, e.g. ``https://hookflow.example.com``. Defaults to ``HOOKFLOW_BASE_URL``
        or ``http://localhost:8000``. ``/v1`` is added by the client.
    :param timeout: seconds per HTTP request (default 30).
    :param max_retries: retries for *safe* requests on connection errors, 429 and 5xx (default 2; 0 disables).
        Safe means GET/DELETE, and ``POST /v1/events`` only when an idempotency key is given. Other POST and
        PATCH requests are never retried.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        api_key = api_key or os.environ.get("HOOKFLOW_API_KEY")
        if not api_key:
            raise ValueError("An API key is required: pass api_key= or set HOOKFLOW_API_KEY.")
        self.api_key = api_key
        self.base_url = (base_url or os.environ.get("HOOKFLOW_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.events = Events(self)
        self.deliveries = Deliveries(self)
        self.endpoints = Endpoints(self)

    # -- transport -------------------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = NOT_GIVEN,
        headers: Mapping[str, str] | None = None,
        retryable: bool | None = None,
    ) -> Any:
        """Send a request to ``{base_url}{path}`` and return the decoded JSON (``None`` for 204)."""
        url = self.base_url + path
        query = _clean(params or {})
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        req_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"hookflow-python/{__version__}",
        }
        data: bytes | None = None
        if json_body is not NOT_GIVEN:
            data = json.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        req_headers.update(headers or {})
        if retryable is None:
            retryable = method.upper() in ("GET", "HEAD", "DELETE")

        attempt = 0
        while True:
            try:
                return self._send_once(method, url, data, req_headers)
            except HookFlowError as exc:
                wait = self._retry_wait(exc, attempt) if retryable and attempt < self.max_retries else None
                if wait is None:
                    raise
            _sleep(wait)
            attempt += 1

    def _send_once(self, method: str, url: str, data: bytes | None, headers: dict[str, str]) -> Any:
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status, resp_headers, raw = resp.status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as exc:
            status, resp_headers = exc.code, dict(exc.headers.items()) if exc.headers else {}
            try:
                raw = exc.read()
            except Exception:  # pragma: no cover - broken body
                raw = b""
            finally:
                exc.close()
        except (socket.timeout, TimeoutError) as exc:
            raise APITimeoutError(f"Request timed out after {self.timeout}s.") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise APITimeoutError(f"Request timed out after {self.timeout}s.") from exc
            raise APIConnectionError(f"Could not reach HookFlow at {self.base_url}: {exc.reason}") from exc
        except (ConnectionError, OSError) as exc:
            raise APIConnectionError(f"Connection to HookFlow failed: {exc}") from exc

        text = raw.decode("utf-8", errors="replace")
        body: Any = None
        if text:
            try:
                body = json.loads(text)
            except ValueError:
                body = None
        if 200 <= status < 300:
            if status == 204 or not text:
                return None
            if body is None:
                raise HookFlowError("The API returned a non-JSON response.", status=status, headers=resp_headers)
            return body
        raise error_from_response(status, resp_headers, body, text)

    @staticmethod
    def _retry_wait(exc: HookFlowError, attempt: int) -> float | None:
        if isinstance(exc, APIConnectionError):
            pass
        elif exc.status == 429 or (exc.status is not None and exc.status >= 500):
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                return retry_after if retry_after <= MAX_RETRY_WAIT else None
        else:
            return None
        return min(0.5 * (2**attempt), 8.0) * (0.75 + random.random() / 2)

    def _page(self, path: str, params: Mapping[str, Any]) -> Page[dict[str, Any]]:
        params = dict(params)

        def fetch(cursor: str | None) -> Page[dict[str, Any]]:
            body = self.request("GET", path, params={**params, "cursor": cursor})
            return Page(body.get("data", []), body.get("next_cursor"), fetch)

        return fetch(params.pop("cursor", None))


class _Resource:
    def __init__(self, client: HookFlow):
        self._client = client


class Events(_Resource):
    def send(
        self, event_type: str, data: Mapping[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        """``POST /v1/events``. Returns ``{"event_id", "status", "created_at", "delivery_count"}``.

        With ``idempotency_key`` the request is safe to retry (and is retried automatically on 429/5xx);
        without it, it is sent exactly once."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
        return self._client.request(
            "POST",
            "/v1/events",
            json_body={"event_type": event_type, "data": dict(data)},
            headers=headers,
            retryable=idempotency_key is not None,
        )

    def list(
        self,
        *,
        event_type: str | None = None,
        created_after: datetime | str | None = None,
        created_before: datetime | str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[dict[str, Any]]:
        """``GET /v1/events`` (newest first). Returns a :class:`Page` of ``EventSummary``."""
        return self._client._page("/v1/events", _clean(locals() | {"self": None}))

    def list_all(self, **filters: Any) -> Iterator[dict[str, Any]]:
        """Iterate every event matching ``filters`` (same arguments as :meth:`list`), fetching pages lazily."""
        return self.list(**filters).auto_paging_iter()

    def get(self, event_id: str) -> dict[str, Any]:
        return self._client.request("GET", f"/v1/events/{_seg(event_id)}")

    def deliveries(self, event_id: str) -> list[dict[str, Any]]:
        """``GET /v1/events/{id}/deliveries``: every delivery of the event (not paginated)."""
        return self._client.request("GET", f"/v1/events/{_seg(event_id)}/deliveries")["data"]

    def replay(self, event_id: str, endpoint_ids: Sequence[str] | None = None) -> dict[str, Any]:
        """``POST /v1/events/{id}/replay``: replay the event's failed/cancelled deliveries.
        Returns ``{"replayed": [{"replay", "delivery"}], "skipped": [{"delivery_id", "reason"}]}``."""
        body = {"endpoint_ids": list(endpoint_ids)} if endpoint_ids is not None else {}
        return self._client.request("POST", f"/v1/events/{_seg(event_id)}/replay", json_body=body)


class Deliveries(_Resource):
    def list(
        self,
        *,
        status: str | None = None,
        endpoint_id: str | None = None,
        event_id: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> Page[dict[str, Any]]:
        """``GET /v1/deliveries`` (newest first). Returns a :class:`Page` of ``Delivery``."""
        return self._client._page("/v1/deliveries", _clean(locals() | {"self": None}))

    def list_all(self, **filters: Any) -> Iterator[dict[str, Any]]:
        return self.list(**filters).auto_paging_iter()

    def get(self, delivery_id: str) -> dict[str, Any]:
        return self._client.request("GET", f"/v1/deliveries/{_seg(delivery_id)}")

    def attempts(self, delivery_id: str) -> list[dict[str, Any]]:
        """``GET /v1/deliveries/{id}/attempts`` (oldest first)."""
        return self._client.request("GET", f"/v1/deliveries/{_seg(delivery_id)}/attempts")["data"]

    def replays(self, delivery_id: str) -> list[dict[str, Any]]:
        """``GET /v1/deliveries/{id}/replays`` (oldest first)."""
        return self._client.request("GET", f"/v1/deliveries/{_seg(delivery_id)}/replays")["data"]

    def replay(self, delivery_id: str) -> dict[str, Any]:
        """``POST /v1/deliveries/{id}/replay``. Returns ``{"replay", "delivery"}``."""
        return self._client.request("POST", f"/v1/deliveries/{_seg(delivery_id)}/replay")

    def bulk_replay(
        self,
        *,
        endpoint_id: str | None = None,
        event_type: str | None = None,
        statuses: Sequence[str] | None = None,
        created_after: datetime | str | None = None,
        created_before: datetime | str | None = None,
        limit: int | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/deliveries/replay``: replay many failed/cancelled deliveries at once.

        Unset arguments use the server defaults (``statuses=["failed"]``, ``limit=100`` (max 500),
        ``dry_run=False``). Returns ``{"matched", "replayed": [delivery ids],
        "skipped": [{"delivery_id", "reason"}], "has_more", "dry_run"}``. Use ``dry_run=True`` to preview."""
        body = _clean(
            {
                "endpoint_id": endpoint_id,
                "event_type": event_type,
                "statuses": list(statuses) if statuses is not None else None,
                "created_after": created_after,
                "created_before": created_before,
                "limit": limit,
                "dry_run": dry_run,
            }
        )
        return self._client.request("POST", "/v1/deliveries/replay", json_body=body)


class Endpoints(_Resource):
    def list(self, *, limit: int | None = None, cursor: str | None = None) -> Page[dict[str, Any]]:
        """``GET /v1/endpoints``. Returns a :class:`Page` of ``Endpoint`` (each with ``health``)."""
        return self._client._page("/v1/endpoints", _clean({"limit": limit, "cursor": cursor}))

    def list_all(self, **filters: Any) -> Iterator[dict[str, Any]]:
        return self.list(**filters).auto_paging_iter()

    def get(self, endpoint_id: str) -> dict[str, Any]:
        return self._client.request("GET", f"/v1/endpoints/{_seg(endpoint_id)}")

    def create(
        self,
        url: str,
        event_types: Sequence[str],
        *,
        description: str | None = None,
        enabled: bool | None = None,
        max_attempts: int | None = None,
        retry_schedule: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/endpoints``. The response includes ``signing_secret`` (``whsec_...``).
        ``retry_schedule`` is a list of retry delays in seconds (omit for the default backoff)."""
        body = _clean(
            {
                "url": url,
                "event_types": list(event_types),
                "description": description,
                "enabled": enabled,
                "max_attempts": max_attempts,
                "retry_schedule": list(retry_schedule) if retry_schedule is not None else None,
            }
        )
        return self._client.request("POST", "/v1/endpoints", json_body=body)

    def update(
        self,
        endpoint_id: str,
        *,
        url: str = NOT_GIVEN,
        description: str | None = NOT_GIVEN,
        event_types: Sequence[str] = NOT_GIVEN,
        enabled: bool = NOT_GIVEN,
        max_attempts: int = NOT_GIVEN,
        retry_schedule: Sequence[int] | None = NOT_GIVEN,
    ) -> dict[str, Any]:
        """``PATCH /v1/endpoints/{id}``. Only the arguments you pass are sent;
        ``description=None`` clears the description and ``retry_schedule=None`` restores the default backoff."""
        fields = {
            "url": url,
            "description": description,
            "event_types": list(event_types) if event_types is not NOT_GIVEN else NOT_GIVEN,
            "enabled": enabled,
            "max_attempts": max_attempts,
            "retry_schedule": list(retry_schedule) if retry_schedule else retry_schedule,
        }
        body = {k: v for k, v in fields.items() if v is not NOT_GIVEN}
        return self._client.request("PATCH", f"/v1/endpoints/{_seg(endpoint_id)}", json_body=body)

    def delete(self, endpoint_id: str) -> None:
        """``DELETE /v1/endpoints/{id}``: archive the endpoint (its unsent deliveries are cancelled)."""
        self._client.request("DELETE", f"/v1/endpoints/{_seg(endpoint_id)}")

    def secret(self, endpoint_id: str) -> dict[str, Any]:
        """``GET /v1/endpoints/{id}/secret`` → ``{"signing_secret", "previous_secret_expires_at"}``."""
        return self._client.request("GET", f"/v1/endpoints/{_seg(endpoint_id)}/secret")

    def rotate_secret(self, endpoint_id: str, grace_period_seconds: int | None = None) -> dict[str, Any]:
        """``POST /v1/endpoints/{id}/rotate-secret`` (default grace period: 24 hours)."""
        body = {"grace_period_seconds": grace_period_seconds} if grace_period_seconds is not None else {}
        return self._client.request("POST", f"/v1/endpoints/{_seg(endpoint_id)}/rotate-secret", json_body=body)
