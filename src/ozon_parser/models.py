"""
Typed data models for Ozon SDK Pro (`ozon_parser`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ozon_parser._model import BaseModel, ConfigDict, Field, model_validator


class SellerInfo(BaseModel):
    """Seller legal & reputation details extracted from `/modal/shop-in-shop-info`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    seller_id: int = 0
    name: str = ""
    company_name: str = ""
    inn: str = ""
    orders_count: str = ""
    reviews_count: str = ""
    working_time: str = ""
    average_rating: str = ""
    seller_url: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_seller(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        sid = int(data.get("seller_id") or 0)
        data["seller_id"] = sid
        if sid > 0 and not data.get("seller_url"):
            data["seller_url"] = f"https://www.ozon.ru/seller/{sid}/"
        return data


class OzonProduct(BaseModel):
    """Unified Ozon product representation combining composer metadata, Ozon Card prices, and seller INN."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int = Field(alias="sku")
    name: str = ""
    brand: str = ""
    category: str = ""
    description: str = ""

    price: float = 0.0
    card_price: Optional[float] = Field(default=None, alias="cardPrice")
    original_price: float = Field(default=0.0, alias="originalPrice")
    old_price: Optional[float] = None
    discount: int = 0

    rating: float = 0.0
    reviews_count: int = 0
    in_stock: bool = True

    seller_id: int = 0
    seller_name: str = ""
    company_name: str = ""
    company_inn: str = Field(default="", alias="inn")
    seller_link: str = ""
    seller_info: Optional[SellerInfo] = None

    url: str = ""
    image_url: str = ""
    image_links: List[str] = Field(default_factory=list)
    specs: Dict[str, str] = Field(default_factory=dict)
    collected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_product(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        sku = int(data.get("id") or data.get("sku") or data.get("article") or 0)
        data["id"] = sku
        data["sku"] = sku

        if not data.get("url") and sku > 0:
            data["url"] = f"https://www.ozon.ru/product/{sku}/"

        price = float(data.get("price") or 0.0)
        orig = float(data.get("original_price") or data.get("originalPrice") or 0.0)
        card = data.get("card_price") if data.get("card_price") is not None else data.get("cardPrice")
        card_f = float(card) if card not in (None, "", 0, 0.0) else None
        if card_f is not None and card_f <= 0:
            card_f = None
        data["card_price"] = card_f

        if not data.get("discount") and orig > price > 0:
            data["discount"] = round((1.0 - (price / orig)) * 100)

        img_links = list(data.get("image_links") or [])
        img_url = str(data.get("image_url") or "")
        if not img_url and img_links:
            img_url = img_links[0]
        elif img_url and img_url not in img_links:
            img_links.insert(0, img_url)
        data["image_url"] = img_url
        data["image_links"] = img_links

        sid = int(data.get("seller_id") or 0)
        if sid > 0 and not data.get("seller_link"):
            data["seller_link"] = f"https://www.ozon.ru/seller/{sid}/"

        return data

    @property
    def sku(self) -> int:
        """Numeric Ozon SKU alias."""
        return self.id

    @property
    def article(self) -> str:
        """Legacy string article alias compatible with `ozonparser.ProductInfo.article`."""
        return str(self.id)

    @property
    def price_drop(self) -> Optional[float]:
        """Amount the regular price dropped compared to recorded `old_price`."""
        if self.old_price is not None and self.old_price > self.price > 0:
            return round(self.old_price - self.price, 2)
        return None

    @property
    def card_discount_pct(self) -> Optional[float]:
        """Extra savings percent when paying with Ozon Card."""
        if self.card_price and self.price > self.card_price > 0:
            return round((1.0 - (self.card_price / self.price)) * 100.0, 2)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dict including derived Ozon Card & drop fields."""
        d = self.model_dump()
        d["sku"] = self.id
        d["price_drop"] = self.price_drop
        d["card_discount_pct"] = self.card_discount_pct
        return d

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize product to UTF-8 JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class OzonReviewItem(BaseModel):
    """Single buyer review parsed from Ozon `webListReviews` composer state."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = ""
    sku: int = Field(default=0, alias="itemId")
    author: str = ""
    rating: int = 5
    comment: str = ""
    pros: str = ""
    cons: str = ""
    created_at: str = ""
    variant_text: str = ""
    photos: List[str] = Field(default_factory=list)
    useful_count: int = 0
    unuseful_count: int = 0
    has_reply: bool = False
    reply_text: str = ""


class OzonReviewSummary(BaseModel):
    """Aggregated Ozon review analytics (offline NLP summary + optional Free/Paid AI pros/cons)."""

    sku: int
    product_name: str = ""
    total_available: int = 0
    total_analyzed: int = 0
    avg_rating: float = 0.0
    rating_distribution: Dict[int, int] = Field(default_factory=dict)
    photos_count: int = 0
    replies_count: int = 0
    aspects_tags: List[str] = Field(default_factory=list)
    top_pros: List[str] = Field(default_factory=list)
    top_cons: List[str] = Field(default_factory=list)
    reviews: List[OzonReviewItem] = Field(default_factory=list)
    ai_summary: Optional[Dict[str, List[str]]] = None
    summary_mode: str = "offline"
    ai_provider: str = ""
    ai_model: str = ""


class PriceRecord(BaseModel):
    """Historical price snapshot stored in SQLite price tracker."""

    sku: int
    name: str
    price: float
    card_price: Optional[float] = None
    original_price: float = 0.0
    old_price: Optional[float] = None
    discount: int = 0
    seller_id: int = 0
    recorded_at: str
