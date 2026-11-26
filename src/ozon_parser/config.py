"""
Configuration defaults, sort mappings, and settings loader for Ozon SDK Pro.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

OZON_BASE_URL = "https://www.ozon.ru"
COMPOSER_API_URL = f"{OZON_BASE_URL}/api/composer-api.bx/page/json/v2"
ENTRYPOINT_API_URL = f"{OZON_BASE_URL}/api/entrypoint-api.bx/page/json/v2"

TELEGRAM_CHANNEL_URL = "https://t.me/avito_sdk_pro"
DOCS_URL = "https://eminsk.github.io/"
ISSUES_URL = "https://github.com/eminsk/ozon_parser/issues"
REPO_URL = "https://github.com/eminsk/ozon_parser"

MOBILEPROXY_REFERRAL_URL = "https://mobileproxy.rent/?p=279117"
MOBILEPROXY_FREE_TRIAL_URL = "https://mobileproxy.rent/user.html?free&p=279117"
MOBILEPROXY_CHANGEIP_BASE = "https://changeip.mobileproxy.space/"
ASTROPROXY_URL = "https://astroproxy.com"
ASOCKS_URL = "https://asocks.com"
DONATE_USDT_TRC20 = "TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P"
DONATE_TRONSCAN_URL = "https://tronscan.org/#/address/TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P"


def resolve_proxy_change_url(
    proxy_change_url: Optional[str] = None,
    mobileproxy_key: Optional[str] = None,
) -> Optional[str]:
    """Normalize a full proxy rotation URL or expand a bare `mobileproxy_key`."""
    raw = (proxy_change_url or "").strip()
    if raw:
        if "://" in raw:
            return raw
        mobileproxy_key = raw

    key = (mobileproxy_key or "").strip()
    if not key:
        return None
    if "://" in key:
        return key
    if "proxy_key=" in key:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(key).query)
        key = (qs.get("proxy_key") or [key])[0].strip()
    return f"{MOBILEPROXY_CHANGEIP_BASE}?proxy_key={urllib.parse.quote(key)}&format=json"

SORT_OPTIONS: Dict[str, str] = {
    "score": "score",
    "popular": "score",
    "price_asc": "price",
    "price_desc": "price_desc",
    "rating": "rating",
    "new": "new",
    "discount": "discount",
}

REVIEW_SORT_OPTIONS: Dict[str, str] = {
    "published_at_desc": "published_at_desc",
    "newest": "published_at_desc",
    "score_desc": "score_desc",
    "positive": "score_desc",
    "score_asc": "score_asc",
    "negative": "score_asc",
    "helpful": "usefulness_desc",
}


@dataclass
class OzonConfig:
    """Configuration container for CLI, GUI, and programmatic Ozon scraping."""

    targets: List[str] = field(default_factory=list)
    proxy: Optional[str] = None
    proxy_change_url: Optional[str] = None
    mobileproxy_key: Optional[str] = None
    cookies: Optional[str] = None
    user_agent: Optional[str] = None
    use_browser_fallback: bool = False
    browser_headless: bool = True
    min_price: float = 0.0
    max_price: float = 999_999_999.0
    min_discount: int = 0
    min_rating: float = 0.0
    white_keywords: List[str] = field(default_factory=list)
    black_keywords: List[str] = field(default_factory=list)
    with_seller: bool = True
    with_reviews: bool = True
    max_pages: int = 3
    limit: int = 100
    interval_sec: int = 60
    pause_sec: float = 1.5
    timeout: float = 15.0
    force_ipv4: bool = True
    tg_token: Optional[str] = None
    tg_chat_id: Optional[str] = None
    tg_proxy: Optional[str] = None
    tracker_db: str = "ozon_prices.db"
    output_dir: Path = Path("result")

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "OzonConfig":
        """Load configuration from JSON or TOML file."""
        cfg_path = Path(path)
        if not cfg_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {cfg_path}")

        suffix = cfg_path.suffix.lower()
        if suffix == ".json":
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[no-redef]
                except ImportError as exc:  # pragma: no cover
                    raise RuntimeError(
                        "TOML parsing on Python <3.11 requires `tomli`: uv add tomli"
                    ) from exc
            loaded = tomllib.loads(cfg_path.read_bytes().decode("utf-8"))
            raw = loaded.get("ozon", loaded) if isinstance(loaded, dict) else {}
        else:
            raise ValueError(f"Unsupported config format: {suffix}")

        cfg = cls()
        if isinstance(raw, dict):
            for key, value in raw.items():
                if hasattr(cfg, key):
                    if key == "output_dir":
                        value = Path(value)
                    setattr(cfg, key, value)
        return cfg

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config into a JSON-safe dictionary."""
        data = dict(self.__dict__)
        data["output_dir"] = str(self.output_dir)
        return data
