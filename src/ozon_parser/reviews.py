"""
Ozon Smart Review Extractor & Hybrid Free/Paid AI Summarizer (`ozon_parser.reviews`).

Extracts real buyer reviews (`comment`, `pros`, `cons`, ratings, photos, seller replies, aspects)
from Ozon Composer API / `webListReviews` state with multi-page cursor pagination, builds instant
offline pros/cons clustering, and optionally enriches summaries via Free (`g4f`/Ollama) or Paid LLMs.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Union

from ozon_parser.ai import _detect_any_paid_env, generate_completion, parse_json_payload
from ozon_parser.endpoints import extract_sku, reviews_api_url
from ozon_parser.models import OzonReviewItem, OzonReviewSummary
from ozon_parser.widgets import parse_product_composer, parse_reviews_composer

if TYPE_CHECKING:
    from ozon_parser.client import OzonClient

logger = logging.getLogger("ozon_parser.reviews")


def _extract_phrases(texts: List[str], top_k: int = 5) -> List[str]:
    """Extract normalized, de-duplicated top review highlights cleanly."""
    counter: Counter = Counter()
    originals: Dict[str, str] = {}

    for raw in texts:
        cleaned = str(raw).strip()
        if not cleaned or len(cleaned) < 3:
            continue
        for chunk in re.split(r"[\n;]+", cleaned):
            part = chunk.strip(" .,-!—")
            if len(part) < 3 or len(part) > 120:
                continue
            norm = re.sub(r"\s+", " ", part.lower())
            counter[norm] += 1
            if norm not in originals:
                originals[norm] = part[0].upper() + part[1:]

    result: List[str] = []
    for norm, count in counter.most_common(top_k):
        label = originals[norm]
        result.append(f"{label} ({count}x)" if count > 1 else label)
    return result


class SmartOzonReviewAnalyzer:
    """Fetches paginated Ozon buyer reviews and produces offline & AI pros/cons summaries."""

    def __init__(self, client: "OzonClient") -> None:
        self.client = client

    def fetch_reviews(
        self,
        url_or_sku: Union[str, int],
        *,
        limit: int = 100,
        max_pages: int = 5,
        sort: str = "published_at_desc",
        product_name: str = "",
    ) -> OzonReviewSummary:
        """
        Fetch Ozon buyer reviews across up to `max_pages` pages and compute an instant
        offline summary of top pros, top cons, rating histogram, photo count, and aspect tags.
        """
        sku = extract_sku(url_or_sku)
        resolved_name = product_name.strip()

        reviews: List[OzonReviewItem] = []
        seen_ids: Set[str] = set()
        next_page: Optional[str] = None
        total_available = 0
        avg_rating_hint = 0.0
        aspect_tags: List[str] = []

        for page in range(1, max(1, int(max_pages)) + 1):
            api_url = reviews_api_url(
                url_or_sku,
                page=page,
                sort=sort,
                next_page_path=next_page if page > 1 else None,
            )
            payload = self.client.transport.get_json(api_url)
            if not resolved_name and isinstance(payload, dict):
                try:
                    resolved_name = parse_product_composer(payload, sku=sku).name
                except Exception:
                    pass

            page_items, p_rating, p_total, p_next, p_aspects = parse_reviews_composer(payload, sku=sku)
            if p_total > total_available:
                total_available = p_total
            if p_rating > 0 and avg_rating_hint == 0.0:
                avg_rating_hint = p_rating
            for tag in p_aspects:
                if tag not in aspect_tags:
                    aspect_tags.append(tag)

            if not page_items:
                break

            added = 0
            for item in page_items:
                dedup_key = item.id or f"{item.rating}:{item.pros[:30]}:{item.comment[:40]}"
                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)
                reviews.append(item)
                added += 1
                if len(reviews) >= limit:
                    break

            next_page = p_next
            if len(reviews) >= limit or added == 0 or not next_page:
                break

        return self._build_offline_summary(
            sku=sku,
            product_name=resolved_name,
            total_available=total_available or len(reviews),
            avg_rating_hint=avg_rating_hint,
            aspect_tags=aspect_tags,
            reviews=reviews,
        )

    @staticmethod
    def _build_offline_summary(
        *,
        sku: int,
        product_name: str,
        total_available: int,
        avg_rating_hint: float,
        aspect_tags: List[str],
        reviews: List[OzonReviewItem],
    ) -> OzonReviewSummary:
        """Build deterministic offline insights from review pros, cons, ratings, and photos."""
        rating_dist: Dict[int, int] = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        pros_pool: List[str] = []
        cons_pool: List[str] = []
        photos_count = 0
        replies_count = 0
        rating_sum = 0

        for r in reviews:
            val = min(5, max(1, int(r.rating or 5)))
            rating_dist[val] = rating_dist.get(val, 0) + 1
            rating_sum += val
            photos_count += len(r.photos)
            if r.has_reply:
                replies_count += 1

            if r.pros:
                pros_pool.append(r.pros)
            elif val == 5 and r.comment:
                pros_pool.append(r.comment[:100])

            if r.cons:
                cons_pool.append(r.cons)
            elif val <= 2 and r.comment:
                cons_pool.append(r.comment[:100])

        computed_avg = round(rating_sum / len(reviews), 2) if reviews else avg_rating_hint
        top_pros = _extract_phrases(pros_pool, top_k=5)
        top_cons = _extract_phrases(cons_pool, top_k=5)

        return OzonReviewSummary(
            sku=sku,
            product_name=product_name,
            total_available=total_available,
            total_analyzed=len(reviews),
            avg_rating=computed_avg or avg_rating_hint,
            rating_distribution=rating_dist,
            photos_count=photos_count,
            replies_count=replies_count,
            aspects_tags=aspect_tags,
            top_pros=top_pros,
            top_cons=top_cons,
            reviews=reviews,
            ai_summary={"plus": top_pros, "minus": top_cons},
            summary_mode="offline",
        )

    def summarize_with_llm(
        self,
        summary: OzonReviewSummary,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        mode: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: float = 25.0,
    ) -> OzonReviewSummary:
        """
        Enrich an `OzonReviewSummary` via Free (`g4f` / local `Ollama`), Hybrid (`OpenRouter`/
        `Groq`/`Gemini`), or Paid (`OpenAI`/`DeepSeek`/`ProxyAPI`) LLMs.
        Leaves the offline summary intact if disabled or on backend failure.
        """
        if not summary.reviews:
            return summary

        eff_mode = (mode or os.environ.get("OZON_AI_MODE") or "auto").strip().lower()
        eff_provider = (provider or os.environ.get("OZON_AI_PROVIDER") or "").strip() or None
        eff_model = (model or os.environ.get("OZON_AI_MODEL") or "").strip() or None
        eff_url = (base_url or os.environ.get("OZON_AI_BASE_URL") or "").strip() or None
        eff_key = (api_key or "").strip() or None

        if eff_mode == "offline":
            return summary
        if eff_mode == "auto" and not any((eff_key, eff_provider, eff_url, _detect_any_paid_env())):
            return summary

        snippets = []
        for r in summary.reviews[:60]:
            parts = []
            if r.pros:
                parts.append(f"+ {r.pros}")
            if r.cons:
                parts.append(f"- {r.cons}")
            if r.comment:
                parts.append(r.comment[:200])
            if parts:
                snippets.append(f"[{r.rating}★] " + " | ".join(parts))

        prompt = (
            "На основе отзывов покупателей Ozon кратко выдели главные плюсы и минусы товара "
            "(до 5 пунктов в каждом списке, на русском). Верни ТОЛЬКО валидный JSON формата:\n"
            '{"plus": ["..."], "minus": ["..."]}\n\n'
            f"Товар: {summary.product_name or summary.sku}\n"
            "Отзывы:\n" + "\n".join(snippets)
        )

        res = generate_completion(
            prompt,
            mode=eff_mode,
            provider=eff_provider,
            model=eff_model,
            api_key=eff_key,
            base_url=eff_url,
            temperature=0.2,
            timeout=timeout,
        )
        if not res.ok:
            logger.warning(f"LLM review summarization skipped ({res.error}); using offline summary.")
            return summary

        try:
            parsed = parse_json_payload(res.content)
            plus = [str(x).strip() for x in (parsed.get("plus") or []) if str(x).strip()]
            minus = [str(x).strip() for x in (parsed.get("minus") or []) if str(x).strip()]
            summary.ai_summary = {"plus": plus, "minus": minus}
            if plus:
                summary.top_pros = plus
            if minus:
                summary.top_cons = minus
            summary.ai_provider = res.provider
            summary.ai_model = res.model
            summary.summary_mode = f"{res.tier}:{res.provider}/{res.model}"
        except Exception as exc:
            logger.warning(f"LLM review JSON parse skipped ({exc}); using offline summary.")
        return summary
