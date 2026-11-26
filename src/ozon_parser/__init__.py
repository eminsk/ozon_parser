"""
Ozon SDK Pro (`ozon_parser` / `ozon-sdk-pro`).

Modular Python Sync/Async SDK, CLI (`ozon-parser` / `ozon-sdk`), Native MCP Server (`ozon-mcp`),
and optional 7-Tab CustomTkinter Desktop GUI (`ozon-gui`) for:
- Direct Composer API v2 product, seller (company + INN + orders + rating), search & category scraping
- Ozon Card discount math & SQLite price-drop history (`OzonPriceTracker`)
- Multi-page Search Rank Tracking with SQLite history deltas (`OzonRankTracker`)
- Smart Review Extractor & Hybrid AI Engine (`SmartOzonReviewAnalyzer` + `ozon_parser.ai`):
  Offline NLP, Free zero-key AI (`g4f` / local `Ollama`), Hybrid (`OpenRouter` `:free` / `Groq` / `Gemini`),
  and Paid APIs (`OpenAI` / `DeepSeek` / `ProxyAPI`) with built-in health diagnostics
- Resilient HTTP transport (`curl_cffi` -> `httpx` -> `requests`, IPv4, proxy rotation) + optional `[browser]` Chrome fallback
- Telegram alerts & styled Excel / CSV / JSON / JSONL / Pandas exports

Supports CPython 3.8-3.16, PyPy 3.8-3.12, and Free-Threaded No-GIL (3.13t-3.16t).
"""

from __future__ import annotations

__version__ = "1.0.0"

from ozon_parser.ai import (
    AI_PROVIDER_PRESETS,
    AIChatResult,
    AIClient,
    AIProviderInfo,
    AIProviderResult,
    FREE_G4F_CANDIDATES,
    find_ai_provider,
    generate_completion,
    is_g4f_available,
    list_ai_providers,
    quick_scan_ai_providers,
    test_ai_provider,
)
from ozon_parser.client import AsyncOzonClient, OzonClient, ParseOzon, filter_products
from ozon_parser.config import OzonConfig, REVIEW_SORT_OPTIONS, SORT_OPTIONS
from ozon_parser.endpoints import (
    category_api_url,
    classify_target,
    extract_inn,
    extract_seller_id,
    extract_sku,
    parse_price_number,
    product_api_url,
    product_page_url,
    reviews_api_url,
    search_api_url,
    seller_catalog_api_url,
    seller_modal_api_url,
)
from ozon_parser.exceptions import (
    OzonAntiBotError,
    OzonError,
    OzonNetworkError,
    OzonNotFoundError,
    OzonRateLimitError,
    OzonValidationError,
)
from ozon_parser.export import (
    rank_results_to_excel,
    reviews_to_excel,
    to_csv,
    to_dataframe,
    to_excel,
    to_json,
    to_jsonl,
)
from ozon_parser.models import (
    OzonProduct,
    OzonReviewItem,
    OzonReviewSummary,
    PriceRecord,
    SellerInfo,
)
from ozon_parser.rank import OzonRankTracker, RankResult
from ozon_parser.reviews import SmartOzonReviewAnalyzer
from ozon_parser.telegram import TelegramNotifier
from ozon_parser.tracker import OzonPriceTracker

__all__ = [
    "__version__",
    "AI_PROVIDER_PRESETS",
    "AIChatResult",
    "AIClient",
    "AIProviderInfo",
    "AIProviderResult",
    "AsyncOzonClient",
    "FREE_G4F_CANDIDATES",
    "OzonAntiBotError",
    "OzonClient",
    "OzonConfig",
    "OzonError",
    "OzonNetworkError",
    "OzonNotFoundError",
    "OzonPriceTracker",
    "OzonProduct",
    "OzonRankTracker",
    "OzonRateLimitError",
    "OzonReviewItem",
    "OzonReviewSummary",
    "OzonValidationError",
    "ParseOzon",
    "PriceRecord",
    "REVIEW_SORT_OPTIONS",
    "RankResult",
    "SORT_OPTIONS",
    "SellerInfo",
    "SmartOzonReviewAnalyzer",
    "TelegramNotifier",
    "category_api_url",
    "classify_target",
    "extract_inn",
    "extract_seller_id",
    "extract_sku",
    "filter_products",
    "find_ai_provider",
    "generate_completion",
    "is_g4f_available",
    "list_ai_providers",
    "parse_price_number",
    "product_api_url",
    "product_page_url",
    "quick_scan_ai_providers",
    "rank_results_to_excel",
    "reviews_api_url",
    "reviews_to_excel",
    "search_api_url",
    "seller_catalog_api_url",
    "seller_modal_api_url",
    "test_ai_provider",
    "to_csv",
    "to_dataframe",
    "to_excel",
    "to_json",
    "to_jsonl",
]
