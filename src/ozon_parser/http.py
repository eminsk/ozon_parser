"""
Resilient HTTP Transport Layer for Ozon SDK Pro (Sync & Async).

Features:
- Chrome TLS/HTTP2 impersonation via `curl_cffi` (`[tls]`) with automatic fallback to `httpx[http2]` -> `requests`.
- Forced IPv4 routing to prevent stalled IPv6 sockets on Windows/VPS.
- Exponential backoff with jitter for 429/5xx throttling + MobileProxy IP rotation (`proxy_change_url`).
- Clean Ozon anti-bot classification (`OzonAntiBotError`) + opt-in `[browser]` fallback (`use_browser_fallback=True`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import h2 as _h2  # noqa: F401
    HTTP2_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTP2_AVAILABLE = False

try:
    import requests as std_requests
except ImportError:  # pragma: no cover
    std_requests = None  # type: ignore[assignment]

try:
    from curl_cffi import requests as cffi_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    cffi_requests = None
    CURL_CFFI_AVAILABLE = False

from ozon_parser.config import OZON_BASE_URL
from ozon_parser.exceptions import (
    OzonAntiBotError,
    OzonNetworkError,
    OzonNotFoundError,
    OzonRateLimitError,
)

logger = logging.getLogger("ozon_parser.http")

_CURLOPT_IPRESOLVE = 113
_CURL_IPRESOLVE_V4 = 1
_CURLOPT_CONNECTTIMEOUT_MS = 156

DEFAULT_HEADERS: Dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": OZON_BASE_URL,
    "Referer": f"{OZON_BASE_URL}/",
    "x-o3-app-name": "dweb_client",
    "x-o3-app-version": "release_1-0-0",
}

_ANTIBOT_MARKERS = (
    "fab_challenge",
    "__cf_bm",
    "checking your browser",
    "access denied",
    "ddos-guard",
    "доступ ограничен",
    "captcha",
)


def parse_cookie_header(cookie_str: Optional[str]) -> Dict[str, str]:
    """Parse a raw HTTP `Cookie` header string into a dict."""
    if not cookie_str or not cookie_str.strip():
        return {}
    cookies: Dict[str, str] = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            k = k.strip()
            if k:
                cookies[k] = v.strip()
    return cookies


@dataclass
class HttpResponse:
    """Normalized HTTP response wrapper independent of transport backend."""

    status_code: int
    text: str
    content: bytes
    headers: Dict[str, str]

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))


class BaseOzonTransport:
    """Shared headers, status classification, anti-bot detection, and retry logic."""

    def __init__(
        self,
        *,
        proxy: Optional[str] = None,
        proxy_change_url: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
        force_ipv4: bool = True,
        impersonate: str = "chrome124",
        use_browser_fallback: bool = False,
        browser_headless: bool = True,
    ) -> None:
        self.proxy = proxy.strip() if proxy and proxy.strip() else None
        self.proxy_change_url = (
            proxy_change_url.strip() if proxy_change_url and proxy_change_url.strip() else None
        )
        self.cookies_dict = parse_cookie_header(cookies)
        self.user_agent = user_agent.strip() if user_agent and user_agent.strip() else None
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.force_ipv4 = bool(force_ipv4)
        self.impersonate = impersonate
        self.use_browser_fallback = bool(use_browser_fallback)
        self.browser_headless = bool(browser_headless)
        self.ip_rotations: int = 0

    def build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        if self.user_agent:
            headers["User-Agent"] = self.user_agent
        elif not CURL_CFFI_AVAILABLE:
            headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
        if extra:
            headers.update(extra)
        return headers

    def _looks_blocked(self, resp: HttpResponse) -> bool:
        if resp.status_code in (403, 498):
            return True
        ct = resp.headers.get("content-type", "").lower()
        if "text/html" in ct:
            low = resp.text[:4000].lower()
            return any(m in low for m in _ANTIBOT_MARKERS)
        return False

    def _raise_for_status(self, resp: HttpResponse, url: str) -> None:
        code = resp.status_code
        if code == 404:
            raise OzonNotFoundError(f"Resource not found (404): {url}")
        if code == 429:
            raise OzonRateLimitError(f"Ozon rate limit HTTP 429 at {url}")
        if self._looks_blocked(resp):
            raise OzonAntiBotError(
                f"HTTP {code} Ozon anti-bot challenge at {url}. "
                'Provide valid browser cookies, a residential/mobile RU proxy, or install "ozon-sdk-pro[tls]" / "[browser]".',
                status_code=code,
                url=url,
            )
        if code >= 500:
            raise OzonNetworkError(f"Ozon upstream error HTTP {code} at {url}")
        if code >= 400:
            raise OzonNetworkError(f"HTTP error {code} at {url}")

    def _backoff(self, attempt: int) -> float:
        return min(8.0, (0.6 * (2 ** attempt)) + random.uniform(0.15, 0.55))

    def _cffi_kwargs(self) -> Dict[str, Any]:
        curl_opts: Dict[int, Any] = {
            _CURLOPT_CONNECTTIMEOUT_MS: min(7000, max(2000, int(self.timeout * 1000)))
        }
        if self.force_ipv4:
            curl_opts[_CURLOPT_IPRESOLVE] = _CURL_IPRESOLVE_V4
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        return {
            "impersonate": self.impersonate,
            "timeout": self.timeout,
            "proxies": proxies,
            "curl_options": curl_opts,
        }


class SyncOzonTransport(BaseOzonTransport):
    """Synchronous HTTP transport for Ozon Composer JSON & HTML endpoints."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = threading.RLock()
        self._cffi_session = None
        self._httpx_client: Optional[Any] = None
        self._requests_session = None
        self._init_clients()

    def _init_clients(self) -> None:
        with self._lock:
            if CURL_CFFI_AVAILABLE and cffi_requests is not None:
                self._cffi_session = cffi_requests.Session(**self._cffi_kwargs())
                if self.cookies_dict:
                    self._cffi_session.cookies.update(self.cookies_dict)
            elif httpx is not None:  # pragma: no cover
                transport = httpx.HTTPTransport(local_address="0.0.0.0") if self.force_ipv4 else None
                self._httpx_client = httpx.Client(
                    http2=HTTP2_AVAILABLE,
                    timeout=httpx.Timeout(self.timeout),
                    proxy=self.proxy,
                    transport=transport,
                    cookies=self.cookies_dict or None,
                    follow_redirects=True,
                )
            elif std_requests is not None:  # pragma: no cover
                sess = std_requests.Session()
                if self.cookies_dict:
                    sess.cookies.update(self.cookies_dict)
                if self.proxy:
                    sess.proxies.update({"http": self.proxy, "https": self.proxy})
                self._requests_session = sess
            else:  # pragma: no cover
                raise RuntimeError("Install `httpx` or `requests` to perform HTTP requests")

    def _raw_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        req_headers = self.build_headers(headers)
        if self._cffi_session is not None:
            r = self._cffi_session.get(url, params=params, headers=req_headers)
            return HttpResponse(
                status_code=r.status_code,
                text=r.text,
                content=r.content,
                headers={k.lower(): v for k, v in r.headers.items()},
            )
        if self._httpx_client is not None:
            r = self._httpx_client.get(url, params=params, headers=req_headers)
            return HttpResponse(
                status_code=r.status_code,
                text=r.text,
                content=r.content,
                headers={k.lower(): v for k, v in r.headers.items()},
            )
        assert self._requests_session is not None
        r = self._requests_session.get(url, params=params, headers=req_headers, timeout=self.timeout)
        return HttpResponse(
            status_code=r.status_code,
            text=r.text,
            content=r.content,
            headers={k.lower(): v for k, v in r.headers.items()},
        )

    def rotate_proxy(self) -> bool:
        """Trigger proxy IP rotation URL if configured."""
        if not self.proxy_change_url:
            return False
        with self._lock:
            try:
                if httpx is not None:
                    with httpx.Client(timeout=8.0) as c:
                        status_code = c.get(self.proxy_change_url).status_code
                elif std_requests is not None:
                    status_code = std_requests.get(self.proxy_change_url, timeout=8.0).status_code
                else:
                    return False
                if status_code < 400:
                    self.ip_rotations += 1
                logger.info(f"Proxy IP rotation requested: HTTP {status_code}")
                time.sleep(2.0)
                return status_code < 400
            except Exception as exc:
                logger.warning(f"Proxy rotation failed: {exc}")
                return False

    def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Fetch JSON payload with retries, HTML state fallback, and optional `[browser]` fallback."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self._raw_get(url, params=params, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt + 1 < self.max_retries:
                    if resp.status_code == 429 and self.proxy_change_url:
                        self.rotate_proxy()
                    time.sleep(self._backoff(attempt))
                    continue
                self._raise_for_status(resp, url)
                try:
                    return resp.json()
                except Exception:
                    return resp.text
            except OzonAntiBotError:
                if self.use_browser_fallback:
                    from ozon_parser.browser import fetch_composer_json_via_browser
                    return fetch_composer_json_via_browser(
                        url,
                        headless=self.browser_headless,
                        proxy=self.proxy,
                    )
                raise
            except (OzonNotFoundError, OzonRateLimitError):
                raise
            except OzonNetworkError as exc:
                last_exc = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < self.max_retries:
                    self.close()
                    self._init_clients()
                    time.sleep(self._backoff(attempt))
                    continue
                raise OzonNetworkError(f"Request failed for {url}: {exc}") from exc
        raise OzonNetworkError(f"Request failed for {url}: {last_exc}")

    def _tls_name(self) -> str:
        if self._cffi_session is not None:
            return "curl_cffi"
        if self._httpx_client is not None:
            return "httpx"
        return "requests"

    def ping(self, url: str = f"{OZON_BASE_URL}/api/composer-api.bx/page/json/v2?url=/") -> Dict[str, Any]:
        """Measure latency and anti-bot status against Ozon."""
        t0 = time.perf_counter()
        try:
            resp = self._raw_get(url)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            blocked = self._looks_blocked(resp)
            return {
                "ok": resp.status_code == 200 and not blocked,
                "status_code": resp.status_code,
                "blocked": blocked,
                "latency_ms": ms,
                "bytes": len(resp.content),
                "tls": self._tls_name(),
            }
        except Exception as exc:
            ms = round((time.perf_counter() - t0) * 1000, 1)
            return {
                "ok": False,
                "status_code": 0,
                "blocked": False,
                "latency_ms": ms,
                "error": str(exc),
                "tls": self._tls_name(),
            }

    def close(self) -> None:
        with self._lock:
            for attr in ("_cffi_session", "_httpx_client", "_requests_session"):
                obj = getattr(self, attr, None)
                if obj is not None:
                    try:
                        obj.close()
                    except Exception:
                        pass
                    setattr(self, attr, None)


class AsyncOzonTransport(BaseOzonTransport):
    """Asynchronous transport using `curl_cffi.AsyncSession` or `httpx.AsyncClient`."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cffi_session = None
        self._httpx_client: Optional[Any] = None

    async def _ensure_client(self) -> None:
        if self._cffi_session is not None or self._httpx_client is not None:
            return
        if CURL_CFFI_AVAILABLE and cffi_requests is not None:
            self._cffi_session = cffi_requests.AsyncSession(**self._cffi_kwargs())
            if self.cookies_dict:
                self._cffi_session.cookies.update(self.cookies_dict)
        elif httpx is not None:  # pragma: no cover
            transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0") if self.force_ipv4 else None
            self._httpx_client = httpx.AsyncClient(
                http2=HTTP2_AVAILABLE,
                timeout=httpx.Timeout(self.timeout),
                proxy=self.proxy,
                transport=transport,
                cookies=self.cookies_dict or None,
                follow_redirects=True,
            )
        else:  # pragma: no cover
            raise RuntimeError("Install `httpx` or `curl-cffi` to use AsyncOzonClient")

    async def _raw_get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> HttpResponse:
        await self._ensure_client()
        req_headers = self.build_headers(headers)
        if self._cffi_session is not None:
            r = await self._cffi_session.get(url, params=params, headers=req_headers)
        else:
            assert self._httpx_client is not None
            r = await self._httpx_client.get(url, params=params, headers=req_headers)
        return HttpResponse(
            status_code=r.status_code,
            text=r.text,
            content=r.content,
            headers={k.lower(): v for k, v in r.headers.items()},
        )

    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Async fetch JSON payload with retries and jitter."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = await self._raw_get(url, params=params, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt + 1 < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                self._raise_for_status(resp, url)
                try:
                    return resp.json()
                except Exception:
                    return resp.text
            except (OzonNotFoundError, OzonAntiBotError):
                raise
            except (OzonRateLimitError, OzonNetworkError) as exc:
                last_exc = exc
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise OzonNetworkError(f"Async request failed for {url}: {exc}") from exc
        raise OzonNetworkError(f"Async request failed for {url}: {last_exc}")

    async def close(self) -> None:
        if self._cffi_session is not None:
            try:
                await self._cffi_session.close()
            except Exception:
                pass
        if self._httpx_client is not None:
            try:
                await self._httpx_client.aclose()
            except Exception:
                pass
