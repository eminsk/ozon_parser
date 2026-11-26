"""Tests for Sync & Async OzonClient, seller enrichment, filters, card savings & ParseOzon."""

from __future__ import annotations

import asyncio
import json

from ozon_parser import AsyncOzonClient, OzonClient, ParseOzon, filter_products


class _FakeSyncTransport:
    def get_json(self, url, params=None, headers=None):
        if "shop-in-shop-info" in url:
            return {
                "widgetStates": {
                    "textBlock-1": json.dumps({"body": [{"type": "textAtom", "textAtom": {"text": 'ООО "МегаСтор"<br>7712345678'}}]}),
                    "cellList-1": json.dumps(
                        {
                            "cells": [
                                {"dsCell": {"centerBlock": {"title": {"text": "Заказов"}}, "rightBlock": {"badge": {"text": "5K"}}}},
                                {"dsCell": {"centerBlock": {"title": {"text": "Средняя оценка"}}, "rightBlock": {"badge": {"text": "4.9"}}}},
                            ]
                        }
                    ),
                }
            }
        if "search" in url or "seller%2F500" in url or "category" in url:
            return {
                "widgetStates": {
                    "searchResultsV2-1": json.dumps(
                        {
                            "items": [
                                {
                                    "skuId": "111",
                                    "title": "SSD NVMe 1TB",
                                    "price": "5990 ₽",
                                    "cardPrice": "5490 ₽",
                                    "originalPrice": "7990 ₽",
                                    "sellerId": 500,
                                },
                                {
                                    "skuId": "222",
                                    "title": "Кабель USB уценка",
                                    "price": "200 ₽",
                                },
                            ]
                        }
                    )
                }
            }
        return {
            "widgetStates": {
                "webStickyProducts-1": json.dumps(
                    {
                        "id": 111,
                        "name": "SSD NVMe 1TB",
                        "seller": {"name": "MegaStore", "link": "https://www.ozon.ru/seller/megastore-500/"},
                    }
                ),
                "webPrice-1": json.dumps({"price": "5 990 ₽", "cardPrice": "5 490 ₽", "originalPrice": "7 990 ₽"}),
            }
        }

    def ping(self):
        return {"ok": True, "status_code": 200, "latency_ms": 12.3, "bytes": 100, "tls": "httpx"}

    def close(self):
        pass


class _FakeAsyncTransport:
    async def get_json(self, url, params=None, headers=None):
        if "reviews" in url:
            return {
                "widgetStates": {
                    "webListReviews-1": json.dumps(
                        {"reviews": [{"id": "a1", "itemId": 111, "content": {"score": 5, "positive": "Быстрый", "comment": "Ок"}}]}
                    )
                }
            }
        return {
            "widgetStates": {
                "webStickyProducts-1": json.dumps({"id": 111, "name": "SSD Async"}),
                "webPrice-1": json.dumps({"price": "5 000 ₽", "cardPrice": "4 500 ₽"}),
            }
        }

    async def close(self):
        pass


def test_sync_client_seller_and_filters(tmp_path) -> None:
    db_file = tmp_path / "prices.db"
    with OzonClient(transport=_FakeSyncTransport(), tracker_db=db_file) as ozon:
        prod = ozon.get_product("https://www.ozon.ru/product/ssd-111/", with_seller=True)
        assert prod.id == 111
        assert prod.company_inn == "7712345678"
        assert prod.seller_info is not None
        assert prod.seller_info.orders_count == "5K"

        found = ozon.scrape_targets(["ssd"], max_pages=1)
        filtered = filter_products(found, min_price=500, black_keywords=["уценка"])
        assert len(filtered) == 1
        assert filtered[0].id == 111

        savings = ozon.card_savings(5990, 5490)
        assert savings["savings_rub"] == 500.0
        assert savings["discount_pct"] == 8.35


def test_async_client_gather_and_reviews(tmp_path) -> None:
    async def _run():
        async with AsyncOzonClient(transport=_FakeAsyncTransport(), tracker_db=tmp_path / "a.db") as ozon:
            prods = await ozon.gather_products([111, 222])
            assert len(prods) == 2
            rev = await ozon.fetch_reviews(111, max_pages=1)
            assert rev.total_analyzed == 1
            assert rev.top_pros == ["Быстрый"]

    asyncio.run(_run())


def test_parse_ozon_wrapper(tmp_path) -> None:
    out_csv = tmp_path / "out.csv"
    helper = ParseOzon("https://www.ozon.ru/seller/500/", output_path=str(out_csv), max_pages=1)
    helper.client = OzonClient(transport=_FakeSyncTransport())
    items = helper.parse()
    assert len(items) == 2
    assert out_csv.exists()
