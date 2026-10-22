"""Chrome-compatible HTTP transport, imported lazily outside the event loop."""

from contextlib import asynccontextmanager
import importlib
import os
import ssl
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant


def _load_browser() -> tuple[Any, str | bool]:
    """Load native dependencies and discover CA trust in an executor."""
    requests = importlib.import_module("curl_cffi.requests")
    ca_bundle = (
        os.environ.get("REQUESTS_CA_BUNDLE")
        or os.environ.get("CURL_CA_BUNDLE")
        or os.environ.get("SSL_CERT_FILE")
        or ssl.get_default_verify_paths().cafile
        or True
    )
    return requests, ca_bundle


async def async_create_browser_session(hass: HomeAssistant) -> "ChromeSession":
    """Avoid native imports during Home Assistant config-flow discovery."""
    requests, ca_bundle = await hass.async_add_executor_job(_load_browser)
    return ChromeSession(requests, ca_bundle)


class _Response:
    """Expose the small aiohttp-compatible interface used by the inventory API."""

    def __init__(self, response) -> None:
        self.status = response.status_code
        self.headers = response.headers
        self.reason = response.reason
        self._response = response

    async def text(self) -> str:
        return self._response.text

    async def read(self) -> bytes:
        return self._response.content


class ChromeSession:
    """Use Chrome's TLS/HTTP fingerprint and its matching default headers."""

    def __init__(self, requests, ca_bundle: str | bool) -> None:
        self._request_error = requests.RequestsError
        self._session = requests.AsyncSession(
            impersonate="chrome",
            verify=ca_bundle,
            trust_env=True,
            retry=0,
            max_clients=1,
            max_redirects=3,
        )
        self._closed = False

    @asynccontextmanager
    async def get(self, url: str, **kwargs):
        timeout = kwargs.pop("timeout", None)
        if isinstance(timeout, ClientTimeout):
            kwargs["timeout"] = timeout.total
        try:
            response = await self._session.get(url, **kwargs)
        except self._request_error as err:
            raise ClientError(f"Chrome request failed ({type(err).__name__})") from err
        yield _Response(response)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._session.close()
