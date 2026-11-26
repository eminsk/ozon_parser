"""
Typed exceptions for Ozon SDK Pro (`ozon_parser`).
"""

from __future__ import annotations

from typing import Optional


class OzonError(Exception):
    """Base exception for all Ozon SDK errors."""


class OzonNetworkError(OzonError):
    """Raised when an HTTP transport or timeout failure exhausts retries."""


class OzonNotFoundError(OzonError):
    """Raised when the requested product, seller, or reviews endpoint returns 404."""


class OzonRateLimitError(OzonError):
    """Raised when Ozon throttles requests with HTTP 429 or 503 rate limits."""


class OzonAntiBotError(OzonError):
    """
    Raised when Ozon anti-bot / Cloudflare / DDoS-Guard blocks a request (403/498 or JS challenge).

    Provide clean browser `cookies` (e.g. from Chrome or optional `[browser]` session helper),
    a residential/mobile proxy, or install Chrome TLS impersonation (`uv add "ozon-sdk-pro[tls]"`).
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        url: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class OzonValidationError(OzonError):
    """Raised when URL/SKU parsing or response schema validation fails."""
