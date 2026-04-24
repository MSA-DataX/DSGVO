"""Thin async wrapper around the five Mollie REST endpoints we use.

Why not ``mollie-api-python``: the official SDK is sync and would
force thread-pool shuffling from every FastAPI handler. Our surface is
exactly five calls — an httpx wrapper is ~80 lines and stays async
end-to-end.

All monetary values on the wire are strings with two decimals in
Mollie's API. We keep internal amounts as integer cents and format at
the boundary.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import httpx


log = logging.getLogger("mollie")


class MollieError(RuntimeError):
    """Raised when Mollie returns a non-2xx response we can't recover
    from. The caller typically surfaces this as a 502 / 503 so the
    client knows retrying may or may not help."""
    def __init__(self, status_code: int, body: str):
        super().__init__(f"Mollie HTTP {status_code}: {body[:500]}")
        self.status_code = status_code
        self.body = body


class MollieClient(Protocol):
    """Shape the rest of the billing code relies on. Tests inject a
    fake that records arguments + returns canned responses."""
    async def create_customer(self, *, name: str, email: str) -> dict[str, Any]: ...
    async def create_first_payment(
        self, *, customer_id: str, amount_cents: int, description: str,
        redirect_url: str, webhook_url: str, metadata: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def get_payment(self, payment_id: str) -> dict[str, Any]: ...
    async def create_subscription(
        self, *, customer_id: str, amount_cents: int, interval: str,
        description: str, webhook_url: str, metadata: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def cancel_subscription(
        self, *, customer_id: str, subscription_id: str,
    ) -> dict[str, Any]: ...


class HttpMollieClient:
    """Production implementation. One shared httpx client per process —
    Mollie allows plenty of concurrent connections and TLS handshake
    per call would be wasteful."""

    BASE_URL = "https://api.mollie.com/v2"

    def __init__(self, api_key: str, *, timeout_s: float = 15.0):
        self._api_key = api_key
        self._timeout = timeout_s
        self._client: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                    "user-agent": "MSA-DataX-Scanner/1.0",
                },
                timeout=self._timeout,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, *, json: dict | None = None) -> dict:
        client = await self._http()
        try:
            res = await client.request(method, path, json=json)
        except httpx.HTTPError as e:
            # Transport-level failure; re-raise with a stable type so
            # the caller doesn't have to care about httpx specifics.
            raise MollieError(-1, f"transport: {e}") from e
        if res.status_code >= 300:
            raise MollieError(res.status_code, res.text)
        return res.json()

    # ----- customers -------------------------------------------------

    async def create_customer(self, *, name: str, email: str) -> dict[str, Any]:
        return await self._request("POST", "/customers", json={
            "name": name, "email": email,
        })

    # ----- payments --------------------------------------------------

    async def create_first_payment(
        self, *, customer_id: str, amount_cents: int, description: str,
        redirect_url: str, webhook_url: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        # sequenceType=first tells Mollie this payment authorises a
        # recurring mandate. The subsequent `create_subscription`
        # call then uses the stored mandate to charge monthly.
        return await self._request(
            "POST", f"/customers/{customer_id}/payments",
            json={
                "amount": {"currency": "EUR", "value": _cents_to_mollie(amount_cents)},
                "description": description,
                "sequenceType": "first",
                "redirectUrl": redirect_url,
                "webhookUrl": webhook_url,
                "metadata": metadata,
            },
        )

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/payments/{payment_id}")

    # ----- subscriptions --------------------------------------------

    async def create_subscription(
        self, *, customer_id: str, amount_cents: int, interval: str,
        description: str, webhook_url: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST", f"/customers/{customer_id}/subscriptions",
            json={
                "amount": {"currency": "EUR", "value": _cents_to_mollie(amount_cents)},
                "interval": interval,      # e.g. "1 month"
                "description": description,
                "webhookUrl": webhook_url,
                "metadata": metadata,
            },
        )

    async def cancel_subscription(
        self, *, customer_id: str, subscription_id: str,
    ) -> dict[str, Any]:
        return await self._request(
            "DELETE", f"/customers/{customer_id}/subscriptions/{subscription_id}",
        )


def _cents_to_mollie(cents: int) -> str:
    """Mollie wants strings like ``"19.00"``; integer cents in, two
    decimals out. Going through int avoids float drift on round-trips."""
    if cents < 0:
        raise ValueError("negative amount")
    euros, rem = divmod(cents, 100)
    return f"{euros}.{rem:02d}"


# ---------------------------------------------------------------------------
# Module-level singleton with a test-injectable seam (mirrors jobs.get_pool)
# ---------------------------------------------------------------------------

_client: MollieClient | None = None


def get_mollie_client() -> MollieClient:
    """Lazily construct a production client from settings. Raises
    ``RuntimeError`` if the API key isn't configured — the handler
    then surfaces that as a 503."""
    global _client
    if _client is None:
        from app.config import settings
        if not settings.mollie_api_key:
            raise RuntimeError(
                "MOLLIE_API_KEY is not configured. Billing checkout is disabled; "
                "admins can still assign plans via /admin/organizations/{id}/set-plan.",
            )
        _client = HttpMollieClient(settings.mollie_api_key)
    return _client


async def close_mollie_client() -> None:
    global _client
    if _client is not None and isinstance(_client, HttpMollieClient):
        await _client.aclose()
    _client = None


def set_mollie_client_for_tests(client: MollieClient | None) -> None:
    """Install a fake for the duration of a test. Production code paths
    never call this — the module-level singleton is managed by
    :func:`get_mollie_client` / :func:`close_mollie_client`."""
    global _client
    _client = client
