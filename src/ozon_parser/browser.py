"""
Optional Selenium/Chrome fallback adapter for Ozon anti-bot challenges (`uv add "ozon-sdk-pro[browser]"`).

Kept strictly optional so core SDK, CLI, AI reviews, and MCP server install and run cleanly
on pure Python across CPython 3.8-3.16, PyPy, and No-GIL without requiring Chrome.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Dict, Optional

from ozon_parser.config import OZON_BASE_URL
from ozon_parser.exceptions import OzonAntiBotError

logger = logging.getLogger("ozon_parser.browser")

_BLOCKED_INDICATORS = (
    "cloudflare",
    "checking your browser",
    "enable javascript",
    "access denied",
    "ddos-guard",
    "проверка браузера",
    "доступ ограничен",
    "access restricted",
)


def is_browser_available() -> bool:
    """Return True when optional `selenium` is installed."""
    try:
        import selenium  # noqa: F401
        return True
    except ImportError:
        return False


def _create_chrome_driver(headless: bool = True, proxy: Optional[str] = None) -> object:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError as exc:  # pragma: no cover
        raise OzonAntiBotError(
            'Optional browser fallback requires `selenium`. Install via: uv add "ozon-sdk-pro[browser]"'
        ) from exc

    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
    if proxy:
        options.add_argument(f"--proxy-server={proxy}")

    driver = webdriver.Chrome(options=options)
    try:
        from selenium_stealth import stealth  # type: ignore[import-untyped]
        stealth(
            driver,
            languages=["ru-RU", "ru"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
    except Exception:
        pass
    driver.set_page_load_timeout(60)
    return driver


def harvest_ozon_cookies(
    url: str = OZON_BASE_URL,
    *,
    headless: bool = False,
    proxy: Optional[str] = None,
    wait_seconds: int = 12,
) -> str:
    """
    Open Ozon in Chrome (`[browser]` extra), wait for initial session/anti-bot cookies,
    and return a serialized `Cookie` header string ready for `OzonClient(cookies=...)`.
    """
    driver = _create_chrome_driver(headless=headless, proxy=proxy)
    try:
        driver.get(url)  # type: ignore[attr-defined]
        deadline = time.time() + max(3, wait_seconds)
        while time.time() < deadline:
            source = (driver.page_source or "").lower()  # type: ignore[attr-defined]
            if not any(ind in source for ind in _BLOCKED_INDICATORS) and len(source) > 500:
                break
            time.sleep(1.5)
        cookies = driver.get_cookies()  # type: ignore[attr-defined]
        return "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value"))
    finally:
        try:
            driver.quit()  # type: ignore[attr-defined]
        except Exception:
            pass


def fetch_composer_json_via_browser(
    api_url: str,
    *,
    headless: bool = True,
    proxy: Optional[str] = None,
    timeout: int = 45,
) -> Dict:
    """
    Fetch Ozon composer JSON payload via headless/visible Chrome when HTTP clients hit JS checks.
    Note: does not bypass interactive CAPTCHAs; raises `OzonAntiBotError` if challenged.
    """
    import json

    driver = _create_chrome_driver(headless=headless, proxy=proxy)
    try:
        driver.get(api_url)  # type: ignore[attr-defined]
        deadline = time.time() + max(5, timeout)
        while time.time() < deadline:
            html_content = driver.page_source or ""  # type: ignore[attr-defined]
            low = html_content.lower()
            if any(ind in low for ind in _BLOCKED_INDICATORS):
                time.sleep(2.0)
                continue
            pre_match = re.search(r"<pre[^>]*>(.*?)</pre>", html_content, re.DOTALL | re.IGNORECASE)
            raw_json = pre_match.group(1).strip() if pre_match else None
            if not raw_json and "{" in html_content and "}" in html_content:
                raw_json = html_content[html_content.find("{") : html_content.rfind("}") + 1]
            if raw_json:
                try:
                    data = json.loads(raw_json)
                    if isinstance(data, dict) and "widgetStates" in data:
                        return data
                except json.JSONDecodeError:
                    pass
            time.sleep(1.5)
        raise OzonAntiBotError(
            "Browser fallback timed out or encountered an interactive anti-bot gate at Ozon.",
            status_code=403,
            url=api_url,
        )
    finally:
        try:
            driver.quit()  # type: ignore[attr-defined]
        except Exception:
            pass
