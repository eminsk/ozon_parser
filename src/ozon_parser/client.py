"""
Core Sync & Async Ozon Clients (`OzonClient`, `AsyncOzonClient`) + `filter_products` + `ParseOzon`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from ozon_parser.endpoints import (
    category_api_url,
    classify_target,
    extract_seller_id,
    extract_sku,
    product_api_url,
    reviews_api_url,
    search_api_url,
    seller_catalog_api_url,
    seller_modal_api_url,
)
from ozon_parser.exceptions import OzonNetworkError, OzonNotFoundError, OzonValidationError
from ozon_parser.export import to_csv, to_excel, to_json
from ozon_parser.http import AsyncOzonTransport, SyncOzonTransport
from ozon_parser.models import OzonProduct, OzonReviewItem, OzonReviewSummary, SellerInfo
from ozon_parser.reviews import SmartOzonReviewAnalyzer
from ozon_parser.tracker import OzonPriceTracker
from ozon_parser.widgets import (
    parse_catalog_composer,
    parse_product_composer,
    parse_reviews_composer,
    parse_seller_modal,
)

logger = logging.getLogger("ozon_parser.client")


def _apply_seller_info(product: OzonProduct, seller: Optional[SellerInfo]) -> OzonProduct:
    """Attach resolved `SellerInfo` details (INN, company name, orders, rating) onto `OzonProduct`."""
    if seller is None:
        return product
    product.seller_info = seller
    if seller.company_name:
        product.company_name = seller.company_name
    if seller.name and not product.seller_name:
        product.seller_name = seller.name
    if seller.inn and not product.company_inn:
        product.company_inn = seller.inn
    if seller.seller_url and not product.seller_link:
        product.seller_link = seller.seller_url
    return product


def filter_products(
    products: Iterable[OzonProduct],
    *,
    min_price: float = 0.0,
    max_price: float = 999_999_999.0,
    min_discount: int = 0,
    min_rating: float = 0.0,
    white_keywords: Sequence[str] = (),
    black_keywords: Sequence[str] = (),
) -> List[OzonProduct]:
    """Filter parsed Ozon products by price range, discount %, rating, and keywords."""
    whites = [w.strip().lower() for w in white_keywords if w.strip()]
    blacks = [b.strip().lower() for b in black_keywords if b.strip()]

    matched: List[OzonProduct] = []
    for p in products:
        eff_price = p.card_price if (p.card_price and p.card_price > 0 and p.price <= 0) else p.price
        if eff_price > 0 and (eff_price < min_price or eff_price > max_price):
            continue
        if min_discount > 0 and p.discount < min_discount:
            continue
        if min_rating > 0 and p.rating < min_rating:
            continue

        haystack = f"{p.name} {p.brand} {p.company_name} {p.seller_name} {p.description}".lower()
        if whites and not any(w in haystack for w in whites):
            continue
        if blacks and any(b in haystack for b in blacks):
            continue
        matched.append(p)
    return matched


class OzonClient:
    """Synchronous high-level Ozon SDK client."""

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
        use_browser_fallback: bool = False,
        browser_headless: bool = True,
        tracker_db: Optional[Union[str, Path]] = None,
        transport: Optional[SyncOzonTransport] = None,
    ) -> None:
        self.transport = transport or SyncOzonTransport(
            proxy=proxy,
            proxy_change_url=proxy_change_url,
            cookies=cookies,
            user_agent=user_agent,
            timeout=timeout,
            max_retries=max_retries,
            force_ipv4=force_ipv4,
            use_browser_fallback=use_browser_fallback,
            browser_headless=browser_headless,
        )
        self.tracker = OzonPriceTracker(tracker_db) if tracker_db else None
        self._tracker_db_path = str(tracker_db) if tracker_db else "ozon_prices.db"

    def __enter__(self) -> "OzonClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close underlying HTTP client resources."""
        self.transport.close()

    def ping(self) -> Dict[str, Any]:
        """Verify Ozon composer API reachability, anti-bot state, and latency."""
        return self.transport.ping()

    @staticmethod
    def card_savings(price: float, card_price: Optional[float]) -> Dict[str, float]:
        """Compute Ozon Card savings in RUB and percentage."""
        if not card_price or price <= card_price or card_price <= 0:
            return {"price": float(price), "card_price": float(card_price or price), "savings_rub": 0.0, "discount_pct": 0.0}
        savings = round(price - card_price, 2)
        pct = round((savings / price) * 100.0, 2)
        return {"price": float(price), "card_price": float(card_price), "savings_rub": savings, "discount_pct": pct}

    def get_seller(self, seller_id_or_url: Union[int, str]) -> SellerInfo:
        """Fetch seller legal name, INN, order volume, rating, and Ozon tenure."""
        seller_id = extract_seller_id(seller_id_or_url)
        if seller_id is None:
            product = self.get_product(seller_id_or_url, with_seller=False)
            if product.seller_id <= 0:
                raise OzonValidationError(f"Could not resolve seller_id from {seller_id_or_url!r}")
            seller_id = product.seller_id

        payload = self.transport.get_json(seller_modal_api_url(seller_id))
        return parse_seller_modal(payload, seller_id=seller_id)

    def get_product(
        self,
        url_or_sku: Union[str, int],
        *,
        with_seller: bool = False,
    ) -> OzonProduct:
        """
        Fetch complete Ozon product metadata, Ozon Card & regular pricing, specs, images,
        and optional deep seller profile (`inn`, `orders_count`, `working_time`).
        """
        sku = extract_sku(url_or_sku)
        payload = self.transport.get_json(product_api_url(url_or_sku))
        product = parse_product_composer(payload, sku=sku)

        if with_seller and product.seller_id > 0:
            try:
                seller_info = self.get_seller(product.seller_id)
                _apply_seller_info(product, seller_info)
            except Exception as exc:
                logger.debug(f"Seller enrichment skipped for seller={product.seller_id}: {exc}")

        if self.tracker and product.price > 0:
            self.tracker.track_products([product])
        return product

    def _paginate_listing(
        self,
        first_url_builder: Callable[[int, Optional[str]], str],
        *,
        max_pages: int = 3,
        limit: int = 100,
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        collected: List[OzonProduct] = []
        seen: set = set()
        next_page: Optional[str] = None
        seller_cache: Dict[int, SellerInfo] = {}

        for page in range(1, max(1, int(max_pages)) + 1):
            url = first_url_builder(page, next_page if page > 1 else None)
            payload = self.transport.get_json(url)
            page_items, next_page = parse_catalog_composer(payload)
            if not page_items:
                break

            added = 0
            for prod in page_items:
                if prod.id in seen:
                    continue
                seen.add(prod.id)
                if with_seller and prod.seller_id > 0:
                    if prod.seller_id not in seller_cache:
                        try:
                            seller_cache[prod.seller_id] = self.get_seller(prod.seller_id)
                        except Exception:
                            pass
                    _apply_seller_info(prod, seller_cache.get(prod.seller_id))
                collected.append(prod)
                added += 1
                if len(collected) >= limit:
                    break

            if len(collected) >= limit or added == 0 or not next_page:
                break

        if self.tracker and collected:
            self.tracker.track_products(collected)
        return collected

    def fetch_search_page(
        self,
        query: str,
        *,
        page: int = 1,
        sort: str = "score",
        next_page_path: Optional[str] = None,
    ) -> Tuple[List[OzonProduct], Optional[str]]:
        """Fetch a single search result page `(products, next_page_relative_url)`."""
        payload = self.transport.get_json(
            search_api_url(query, page=page, sort=sort, next_page_path=next_page_path)
        )
        return parse_catalog_composer(payload)

    def search(
        self,
        query: str,
        *,
        max_pages: int = 3,
        limit: int = 100,
        sort: str = "score",
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        """Search Ozon catalog across paginated composer results."""
        return self._paginate_listing(
            lambda pg, np: search_api_url(query, page=pg, sort=sort, next_page_path=np),
            max_pages=max_pages,
            limit=limit,
            with_seller=with_seller,
        )

    def get_category(
        self,
        category_url_or_path: str,
        *,
        max_pages: int = 3,
        limit: int = 100,
        sort: str = "score",
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        """Parse Ozon category products across pages."""
        return self._paginate_listing(
            lambda pg, np: category_api_url(category_url_or_path, page=pg, sort=sort, next_page_path=np),
            max_pages=max_pages,
            limit=limit,
            with_seller=with_seller,
        )

    def get_seller_catalog(
        self,
        seller_id_or_url: Union[int, str],
        *,
        max_pages: int = 5,
        limit: int = 200,
        sort: str = "score",
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        """Parse products belonging to an Ozon seller."""
        seller_id = extract_seller_id(seller_id_or_url)
        if seller_id is None:
            seller_id = self.get_product(seller_id_or_url, with_seller=False).seller_id
        if seller_id <= 0:
            raise OzonValidationError(f"Could not determine seller_id for {seller_id_or_url!r}")

        return self._paginate_listing(
            lambda pg, np: seller_catalog_api_url(seller_id, page=pg, sort=sort, next_page_path=np),
            max_pages=max_pages,
            limit=limit,
            with_seller=with_seller,
        )

    def scrape_targets(
        self,
        targets: Sequence[str],
        *,
        max_pages: int = 2,
        limit_per_target: int = 100,
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        """Dispatch mixed list of Ozon product URLs, SKUs, categories, seller URLs, or queries."""
        seen: set = set()
        results: List[OzonProduct] = []

        for raw in targets:
            target = str(raw).strip()
            if not target:
                continue
            kind, value = classify_target(target)
            if kind == "product":
                batch = [self.get_product(int(value), with_seller=with_seller)]
            elif kind == "seller":
                batch = self.get_seller_catalog(
                    int(value),
                    max_pages=max_pages,
                    limit=limit_per_target,
                    with_seller=with_seller,
                )
            elif kind == "category":
                batch = self.get_category(
                    value,
                    max_pages=max_pages,
                    limit=limit_per_target,
                    with_seller=with_seller,
                )
            else:
                batch = self.search(
                    value,
                    max_pages=max_pages,
                    limit=limit_per_target,
                    with_seller=with_seller,
                )

            for item in batch:
                if item.id not in seen:
                    seen.add(item.id)
                    results.append(item)
        return results

    def fetch_reviews(
        self,
        url_or_sku: Union[str, int],
        *,
        limit: int = 100,
        max_pages: int = 5,
        sort: str = "published_at_desc",
        product_name: str = "",
    ) -> OzonReviewSummary:
        """Fetch paginated Ozon buyer reviews & compute offline pros/cons/ratings breakdown."""
        return SmartOzonReviewAnalyzer(self).fetch_reviews(
            url_or_sku,
            limit=limit,
            max_pages=max_pages,
            sort=sort,
            product_name=product_name,
        )

    def analyze_reviews(
        self,
        url_or_sku: Union[str, int],
        *,
        limit: int = 100,
        max_pages: int = 5,
        sort: str = "published_at_desc",
        ai_key: Optional[str] = None,
        ai_base_url: Optional[str] = None,
        ai_model: Optional[str] = None,
        ai_mode: Optional[str] = None,
        ai_provider: Optional[str] = None,
        ai_timeout: float = 25.0,
    ) -> OzonReviewSummary:
        """Extract buyer reviews and summarize pros/cons using Offline NLP, Free AI (`g4f`/Ollama), or Paid LLMs."""
        analyzer = SmartOzonReviewAnalyzer(self)
        summary = analyzer.fetch_reviews(url_or_sku, limit=limit, max_pages=max_pages, sort=sort)
        return analyzer.summarize_with_llm(
            summary,
            api_key=ai_key,
            base_url=ai_base_url,
            model=ai_model,
            mode=ai_mode,
            provider=ai_provider,
            timeout=ai_timeout,
        )

    def check_rank(
        self,
        sku_or_url: Union[int, str],
        query: str,
        *,
        max_pages: int = 3,
        sort: str = "score",
    ):
        """Find product search rank across `1..max_pages` pages and store history in SQLite."""
        from ozon_parser.rank import OzonRankTracker

        return OzonRankTracker(self, db_path=self._tracker_db_path).check_rank(
            sku_or_url, query, max_pages=max_pages, sort=sort
        )

    def list_ai_providers(
        self,
        *,
        tier: str = "all",
        only_working: bool = False,
        only_free: bool = False,
        search_query: str = "",
    ):
        """List Free (`g4f`/local Ollama) and Paid (`OpenAI`/`DeepSeek`/etc.) AI providers."""
        from ozon_parser.ai import list_ai_providers

        return list_ai_providers(
            tier=tier,
            only_working=only_working,
            only_free=only_free,
            search_query=search_query,
        )

    def test_ai_provider(
        self,
        provider: Optional[str] = None,
        *,
        mode: str = "auto",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 12.0,
    ):
        """Run health-check diagnostics on a free or paid AI provider."""
        from ozon_parser.ai import test_ai_provider

        return test_ai_provider(
            provider,
            mode=mode,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    def ask_ai(
        self,
        prompt: str,
        *,
        mode: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 25.0,
    ):
        """Generate an AI completion via Free (`g4f`/Ollama) or Paid LLM backends."""
        from ozon_parser.ai import generate_completion

        return generate_completion(
            prompt,
            mode=mode,
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )


class AsyncOzonClient:
    """Asynchronous high-throughput Ozon SDK client."""

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
        concurrency: int = 12,
        tracker_db: Optional[Union[str, Path]] = None,
        transport: Optional[AsyncOzonTransport] = None,
    ) -> None:
        self.transport = transport or AsyncOzonTransport(
            proxy=proxy,
            proxy_change_url=proxy_change_url,
            cookies=cookies,
            user_agent=user_agent,
            timeout=timeout,
            max_retries=max_retries,
            force_ipv4=force_ipv4,
        )
        self._sem = asyncio.Semaphore(max(1, int(concurrency)))
        self.tracker = OzonPriceTracker(tracker_db) if tracker_db else None

    async def __aenter__(self) -> "AsyncOzonClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self.transport.close()

    async def get_seller(self, seller_id: int) -> SellerInfo:
        async with self._sem:
            payload = await self.transport.get_json(seller_modal_api_url(seller_id))
            return parse_seller_modal(payload, seller_id=seller_id)

    async def get_product(
        self,
        url_or_sku: Union[str, int],
        *,
        with_seller: bool = False,
    ) -> OzonProduct:
        sku = extract_sku(url_or_sku)
        async with self._sem:
            payload = await self.transport.get_json(product_api_url(url_or_sku))
        product = parse_product_composer(payload, sku=sku)
        if with_seller and product.seller_id > 0:
            try:
                seller = await self.get_seller(product.seller_id)
                _apply_seller_info(product, seller)
            except Exception:
                pass
        return product

    async def gather_products(
        self,
        targets: Sequence[Union[str, int]],
        *,
        with_seller: bool = False,
    ) -> List[OzonProduct]:
        """Concurrently fetch multiple Ozon product cards."""
        tasks = [self.get_product(t, with_seller=with_seller) for t in targets]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        products = [r for r in raw_results if isinstance(r, OzonProduct)]
        if self.tracker and products:
            self.tracker.track_products(products)
        return products

    async def fetch_reviews(
        self,
        url_or_sku: Union[str, int],
        *,
        limit: int = 100,
        max_pages: int = 5,
        sort: str = "published_at_desc",
    ) -> OzonReviewSummary:
        """Asynchronously fetch paginated Ozon buyer reviews and offline summary."""
        sku = extract_sku(url_or_sku)
        reviews: List[OzonReviewItem] = []
        seen: set = set()
        next_page: Optional[str] = None
        avg_hint = 0.0
        total_avail = 0
        aspects: List[str] = []

        for page in range(1, max(1, int(max_pages)) + 1):
            async with self._sem:
                payload = await self.transport.get_json(
                    reviews_api_url(url_or_sku, page=page, sort=sort, next_page_path=next_page if page > 1 else None)
                )
            items, p_rating, p_total, p_next, p_aspects = parse_reviews_composer(payload, sku=sku)
            total_avail = max(total_avail, p_total)
            if avg_hint == 0.0 and p_rating > 0:
                avg_hint = p_rating
            for tag in p_aspects:
                if tag not in aspects:
                    aspects.append(tag)
            if not items:
                break
            added = 0
            for item in items:
                key = item.id or f"{item.rating}:{item.pros[:30]}:{item.comment[:40]}"
                if key in seen:
                    continue
                seen.add(key)
                reviews.append(item)
                added += 1
                if len(reviews) >= limit:
                    break
            next_page = p_next
            if len(reviews) >= limit or added == 0 or not next_page:
                break

        return SmartOzonReviewAnalyzer._build_offline_summary(
            sku=sku,
            product_name="",
            total_available=total_avail or len(reviews),
            avg_rating_hint=avg_hint,
            aspect_tags=aspects,
            reviews=reviews,
        )


class ParseOzon:
    """High-level one-shot convenience wrapper to scrape any Ozon URL/query to Excel, CSV, or JSON."""

    def __init__(
        self,
        target: str,
        output_path: str = "result/ozon_data.xlsx",
        *,
        max_pages: int = 3,
        limit: int = 100,
        with_seller: bool = False,
        proxy: Optional[str] = None,
        cookies: Optional[str] = None,
        use_browser_fallback: bool = False,
    ) -> None:
        self.target = target
        self.output_path = output_path
        self.max_pages = max_pages
        self.limit = limit
        self.with_seller = with_seller
        self.client = OzonClient(
            proxy=proxy,
            cookies=cookies,
            use_browser_fallback=use_browser_fallback,
        )

    def parse(self) -> List[OzonProduct]:
        """Execute target scrape and export directly to `.xlsx`, `.csv`, or `.json`."""
        with self.client as client:
            products = client.scrape_targets(
                [self.target],
                max_pages=self.max_pages,
                limit_per_target=self.limit,
                with_seller=self.with_seller,
            )
            out = Path(self.output_path)
            ext = out.suffix.lower()
            if ext == ".csv":
                to_csv(products, out)
            elif ext == ".json":
                to_json(products, out)
            else:
                to_excel(products, out)
            return products
