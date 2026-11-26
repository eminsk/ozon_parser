"""
Ozon URL, SKU, Seller ID, Composer API routing, and normalization helpers (`ozon_parser.endpoints`).
"""

from __future__ import annotations

import html
import re
from typing import Optional, Tuple, Union
from urllib.parse import parse_qs, quote, urlencode, urlparse

from ozon_parser.config import (
    COMPOSER_API_URL,
    ENTRYPOINT_API_URL,
    OZON_BASE_URL,
    REVIEW_SORT_OPTIONS,
    SORT_OPTIONS,
)
from ozon_parser.exceptions import OzonValidationError

_SKU_IN_PATH_RE = re.compile(r"/product/(?:[^/?#]*-)?(\d+)(?:/|\?|$)")
_SELLER_IN_PATH_RE = re.compile(r"/seller/(?:[^/?#]*-)?(\d+)(?:/|\?|$)")
_CATEGORY_RE = re.compile(r"(/category/[^?#]+)")
_INN_RE = re.compile(r"\b(\d{10,15})\b")
_TRAILING_INN_RE = re.compile(r"(\d{10,15})$")
_DUP_LEGAL_RE = re.compile(r"^(ООО|ИП|АО|ЗАО|ПАО)\s+(ООО|ИП|АО|ЗАО|ПАО)\s+")


def is_short_ozon_url(value: str) -> bool:
    """Return True if URL uses Ozon short link format (`ozon.ru/t/...`)."""
    lowered = value.strip().lower()
    return "ozon.ru/t/" in lowered or "ozon.by/t/" in lowered


def extract_sku(url_or_sku: Union[str, int]) -> int:
    """
    Extract numeric Ozon product SKU (`article`) from an integer, string ID, or product URL.

    Examples:
        - `1619925434` -> `1619925434`
        - `https://www.ozon.ru/product/videokarta-rtx-4060-1619925434/` -> `1619925434`
        - `https://www.ozon.ru/product/1619925434/reviews/?page=2` -> `1619925434`
    """
    if isinstance(url_or_sku, int) and not isinstance(url_or_sku, bool):
        if url_or_sku <= 0:
            raise OzonValidationError(f"Invalid positive Ozon SKU: {url_or_sku}")
        return url_or_sku

    raw = str(url_or_sku).strip()
    if not raw:
        raise OzonValidationError("Empty Ozon product URL or SKU")
    if raw.isdigit():
        sku = int(raw)
        if sku <= 0:
            raise OzonValidationError(f"Invalid positive Ozon SKU: {raw}")
        return sku

    if is_short_ozon_url(raw):
        raise OzonValidationError(
            f"Short Ozon link {raw!r} must be resolved to full /product/...-<sku>/ URL first."
        )

    match = _SKU_IN_PATH_RE.search(raw)
    if match:
        return int(match.group(1))

    raise OzonValidationError(f"Could not extract Ozon SKU from {url_or_sku!r}")


def extract_product_path(url_or_sku: Union[str, int]) -> str:
    """Normalize input into a clean relative Ozon product path (`/product/.../`)."""
    if isinstance(url_or_sku, int):
        return f"/product/{extract_sku(url_or_sku)}/"
    raw = str(url_or_sku).strip()
    if raw.isdigit():
        return f"/product/{extract_sku(raw)}/"
    parsed = urlparse(raw)
    if "/product/" in parsed.path:
        path = parsed.path
        if not path.endswith("/"):
            path += "/"
        return re.sub(r"/reviews/?$", "/", path)
    return f"/product/{extract_sku(raw)}/"


def extract_seller_id(url_or_id: Union[str, int]) -> Optional[int]:
    """Extract numeric `seller_id` from a seller URL or numeric string, returning None otherwise."""
    if isinstance(url_or_id, int) and not isinstance(url_or_id, bool):
        return url_or_id if url_or_id > 0 else None
    raw = str(url_or_id).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw) if int(raw) > 0 else None
    match = _SELLER_IN_PATH_RE.search(raw)
    if match:
        return int(match.group(1))
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query)
    if "seller_id" in qs and qs["seller_id"][0].isdigit():
        return int(qs["seller_id"][0])
    return None


def classify_target(target: str) -> Tuple[str, str]:
    """
    Classify mixed user input target into `("product"|"seller"|"category"|"search", value)`.
    """
    raw = target.strip()
    if not raw:
        raise OzonValidationError("Empty target")

    if raw.isdigit():
        return ("product", raw)

    lowered = raw.lower()
    if "/product/" in lowered:
        return ("product", str(extract_sku(raw)))

    seller_id = extract_seller_id(raw)
    if seller_id is not None and "/seller/" in lowered:
        return ("seller", str(seller_id))

    if "/category/" in lowered:
        parsed = urlparse(raw)
        path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
        if parsed.query:
            return ("category", f"{path}?{parsed.query}")
        return ("category", path)

    if "/search" in lowered and "text=" in lowered:
        qs = parse_qs(urlparse(raw).query)
        text_val = (qs.get("text") or [""])[0].strip()
        if text_val:
            return ("search", text_val)

    return ("search", raw)


def product_page_url(sku: Union[int, str]) -> str:
    """Return canonical buyer-facing Ozon product URL."""
    return f"{OZON_BASE_URL}/product/{extract_sku(sku)}/"


def composer_page_url(
    relative_url: str,
    *,
    entrypoint: bool = False,
    with_rr: bool = True,
) -> str:
    """Build Ozon composer-api v2 URL for a relative page or modal route."""
    base = ENTRYPOINT_API_URL if entrypoint else COMPOSER_API_URL
    rel = relative_url if relative_url.startswith("/") else f"/{relative_url}"
    params = {"url": rel}
    if with_rr:
        params["__rr"] = "1"
    return f"{base}?{urlencode(params)}"


def product_api_url(url_or_sku: Union[str, int]) -> str:
    """Return Ozon composer JSON API URL for product metadata & pricing."""
    rel = extract_product_path(url_or_sku)
    return composer_page_url(rel, entrypoint=False, with_rr=True)


def reviews_api_url(
    url_or_sku: Union[str, int],
    *,
    page: int = 1,
    sort: str = "published_at_desc",
    next_page_path: Optional[str] = None,
) -> str:
    """Return Ozon composer JSON API URL for paginated buyer reviews."""
    if next_page_path:
        return composer_page_url(next_page_path, entrypoint=False, with_rr=True)
    prod_path = extract_product_path(url_or_sku)
    sort_code = REVIEW_SORT_OPTIONS.get(sort.strip().lower(), sort.strip())
    q = urlencode({"page": max(1, int(page)), "sort": sort_code})
    return composer_page_url(f"{prod_path}reviews/?{q}", entrypoint=False, with_rr=True)


def seller_modal_api_url(seller_id: int) -> str:
    """Return Ozon entrypoint JSON API URL for seller details (company, INN, orders, rating)."""
    return composer_page_url(f"/modal/shop-in-shop-info?seller_id={int(seller_id)}", entrypoint=True, with_rr=True)


def seller_catalog_api_url(
    seller_id: int,
    *,
    page: int = 1,
    sort: str = "score",
    next_page_path: Optional[str] = None,
) -> str:
    """Return Ozon composer JSON API URL for a seller storefront catalog page."""
    if next_page_path:
        return composer_page_url(next_page_path, entrypoint=False, with_rr=True)
    sort_code = SORT_OPTIONS.get(sort.strip().lower(), sort.strip())
    q = urlencode({"page": max(1, int(page)), "sorting": sort_code})
    return composer_page_url(f"/seller/{int(seller_id)}/products/?{q}", entrypoint=False, with_rr=True)


def search_api_url(
    query: str,
    *,
    page: int = 1,
    sort: str = "score",
    next_page_path: Optional[str] = None,
) -> str:
    """Return Ozon composer JSON API URL for catalog search pagination."""
    if next_page_path:
        return composer_page_url(next_page_path, entrypoint=False, with_rr=True)
    sort_code = SORT_OPTIONS.get(sort.strip().lower(), sort.strip())
    q = urlencode({"text": query.strip(), "page": max(1, int(page)), "sorting": sort_code})
    return composer_page_url(f"/search/?{q}&from_global=true", entrypoint=False, with_rr=True)


def category_api_url(
    category_path: str,
    *,
    page: int = 1,
    sort: str = "score",
    next_page_path: Optional[str] = None,
) -> str:
    """Return Ozon composer JSON API URL for a category listing page."""
    if next_page_path:
        return composer_page_url(next_page_path, entrypoint=False, with_rr=True)
    parsed = urlparse(category_path)
    base_path = parsed.path if parsed.path else category_path
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    if not base_path.endswith("/"):
        base_path = f"{base_path}/"
    sort_code = SORT_OPTIONS.get(sort.strip().lower(), sort.strip())
    extra_qs = f"&{parsed.query}" if parsed.query else ""
    rel = f"{base_path}?page={max(1, int(page))}&sorting={quote(sort_code)}{extra_qs}"
    return composer_page_url(rel, entrypoint=False, with_rr=True)


def parse_price_number(raw_price: Union[str, int, float, None]) -> float:
    """
    Convert Ozon formatted price strings (`'4 990 ₽'`, `'4\\u2009990,50\\xa0₽'`) or numbers to float.
    """
    if raw_price is None or isinstance(raw_price, bool):
        return 0.0
    if isinstance(raw_price, (int, float)):
        return float(raw_price) if raw_price > 0 else 0.0
    cleaned = str(raw_price).replace("\u2009", "").replace("\xa0", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    if not match:
        return 0.0
    try:
        val = float(match.group(1))
        return val if val > 0 else 0.0
    except ValueError:
        return 0.0


def clean_company_name(company: str) -> str:
    """Normalize Ozon seller legal entity name (deduplicate ООО/ИП, strip HTML `<br>` & punctuation)."""
    if not company:
        return ""
    text = html.unescape(str(company))
    for br in ("<br>", "<br/>", "<br />"):
        if br in text:
            text = text.split(br, 1)[0]
    text = re.sub(r"\\+\"", '"', text)
    text = _TRAILING_INN_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _DUP_LEGAL_RE.sub(r"\1 ", text)
    return re.sub(r"[,\s]+$", "", text)


def extract_inn(text: str) -> str:
    """Extract 10–15 digit Russian/CIS INN or OGRN from seller metadata text."""
    if not text:
        return ""
    match = _INN_RE.search(str(text))
    return match.group(1) if match else ""
