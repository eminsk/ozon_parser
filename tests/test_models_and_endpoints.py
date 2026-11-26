"""Tests for Ozon endpoints, text cleaners, and thread-safe pure-Python data models."""

from __future__ import annotations

import concurrent.futures
import json

import pytest

from ozon_parser import (
    OzonConfig,
    OzonProduct,
    OzonValidationError,
    SellerInfo,
    classify_target,
    extract_inn,
    extract_seller_id,
    extract_sku,
    parse_price_number,
    product_api_url,
    reviews_api_url,
    seller_modal_api_url,
)
from ozon_parser.endpoints import clean_company_name


def test_extract_sku_variants() -> None:
    assert extract_sku(1619925434) == 1619925434
    assert extract_sku("1619925434") == 1619925434
    assert extract_sku("https://www.ozon.ru/product/videokarta-rtx-4060-1619925434/?asb=abc") == 1619925434
    assert extract_sku("https://ozon.ru/product/1619925434/reviews/?page=2") == 1619925434

    with pytest.raises(OzonValidationError):
        extract_sku("https://ozon.ru/t/AbCdEf")
    with pytest.raises(OzonValidationError):
        extract_sku("not-an-ozon-link")


def test_extract_seller_and_classify_target() -> None:
    assert extract_seller_id("https://www.ozon.ru/seller/kompaniya-987654/products/") == 987654
    assert extract_seller_id(555111) == 555111
    assert classify_target("https://www.ozon.ru/product/item-12345/") == ("product", "12345")
    assert classify_target("https://www.ozon.ru/seller/shop-777/") == ("seller", "777")
    assert classify_target("https://www.ozon.ru/category/elektronika-15500/") == ("category", "/category/elektronika-15500/")
    assert classify_target("https://www.ozon.ru/search/?text=laptop") == ("search", "laptop")
    assert classify_target("видеокарта") == ("search", "видеокарта")


def test_composer_url_builders_and_cleaners() -> None:
    assert "url=%2Fproduct%2F12345%2F" in product_api_url(12345)
    rev_url = reviews_api_url(12345, page=2, sort="positive")
    assert "reviews" in rev_url
    assert "score_desc" in rev_url
    assert "seller_id%3D999" in seller_modal_api_url(999)

    assert parse_price_number("14\u2009990\xa0₽") == 14990.0
    assert parse_price_number("0") == 0.0
    assert clean_company_name('ООО ООО «РобоКомп»<br>ИНН 7701234567') == 'ООО «РобоКомп»'
    assert extract_inn("ОГРН 12345 ИНН 7701234567") == "7701234567"


def test_ozon_product_derived_fields_and_thread_safety() -> None:
    prod = OzonProduct.model_validate(
        {
            "sku": 1619925434,
            "name": "Видеокарта RTX 4060",
            "price": 32990,
            "cardPrice": 30990,
            "originalPrice": 39990,
            "old_price": 35990,
            "seller_id": 444,
        }
    )
    assert prod.id == 1619925434
    assert prod.article == "1619925434"
    assert prod.discount == 18
    assert prod.price_drop == 3000.0
    assert prod.card_discount_pct == 6.06
    assert "ozon.ru/product/1619925434/" in prod.url
    assert json.loads(prod.to_json())["sku"] == 1619925434

    def _validate_one(idx: int) -> int:
        item = OzonProduct.model_validate({"sku": 1000 + idx, "name": f"T-{idx}", "price": 100 + idx})
        return item.id

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(_validate_one, range(60)))
    assert len(ids) == 60
    assert ids[0] == 1000


def test_config_from_toml_and_json(tmp_path) -> None:
    toml_file = tmp_path / "ozon.toml"
    toml_file.write_text('[ozon]\ntargets = ["123"]\nlimit = 40\ntracker_db = "c.db"\n', encoding="utf-8")
    cfg = OzonConfig.from_file(toml_file)
    assert cfg.targets == ["123"]
    assert cfg.limit == 40
    assert cfg.to_dict()["tracker_db"] == "c.db"

    seller = SellerInfo.model_validate({"seller_id": 77, "company_name": "ООО Тест", "inn": "7700000000"})
    assert seller.seller_url == "https://www.ozon.ru/seller/77/"
