"""Tests for SQLite OzonPriceTracker, OzonRankTracker, Excel/CSV/JSON exporters & TelegramNotifier."""

from __future__ import annotations

import json
from pathlib import Path

from ozon_parser import (
    OzonClient,
    OzonPriceTracker,
    OzonProduct,
    OzonRankTracker,
    OzonReviewItem,
    OzonReviewSummary,
    TelegramNotifier,
    rank_results_to_excel,
    reviews_to_excel,
    to_csv,
    to_excel,
    to_json,
    to_jsonl,
)


def test_price_tracker_detects_drop_and_history(tmp_path) -> None:
    db = tmp_path / "tracker.db"
    tracker = OzonPriceTracker(db)

    p1 = OzonProduct.model_validate({"sku": 333, "name": "Монитор", "price": 25000, "card_price": 23500})
    tracker.track_products([p1])
    assert p1.old_price is None

    p2 = OzonProduct.model_validate({"sku": 333, "name": "Монитор", "price": 21000, "card_price": 19900})
    tracker.track_products([p2])
    assert p2.old_price == 25000.0
    assert p2.price_drop == 4000.0

    drops = tracker.get_price_drops()
    assert len(drops) == 1
    assert drops[0].sku == 333
    assert len(tracker.get_history(333)) == 2


def test_rank_tracker_multi_page_and_delta(tmp_path) -> None:
    class _RankTransport:
        def get_json(self, url, params=None, headers=None):
            if "page%3D1" in url:
                return {
                    "nextPage": "/search/?text=monitor&page=2",
                    "widgetStates": {"searchResultsV2-1": json.dumps({"items": [{"skuId": "10"}, {"skuId": "20"}]})},
                }
            return {
                "widgetStates": {"searchResultsV2-1": json.dumps({"items": [{"skuId": "30"}, {"skuId": "444", "title": "Target", "price": 15000}]})}
            }

        def close(self):
            pass

    client = OzonClient(transport=_RankTransport())
    tracker = OzonRankTracker(client, db_path=tmp_path / "rank.db")
    r1 = tracker.check_rank(444, "монитор", max_pages=2)
    assert r1.position == 4
    assert r1.page == 2
    assert r1.page_position == 2
    assert r1.rank_delta is None

    r2 = tracker.check_rank(444, "монитор", max_pages=2)
    assert r2.previous_position == 4
    assert r2.rank_delta == 0


def test_all_exporters_and_telegram_formatter(tmp_path) -> None:
    prod = OzonProduct.model_validate(
        {
            "sku": 1001,
            "name": "=CMD() Тест товар",
            "price": 1200,
            "card_price": 1050,
            "original_price": 1500,
            "old_price": 1400,
            "company_name": "ООО Ромашка",
            "company_inn": "7700112233",
        }
    )
    xlsx_p = to_excel([prod], tmp_path / "items.xlsx")
    csv_p = to_csv([prod], tmp_path / "items.csv")
    json_p = to_json([prod], tmp_path / "items.json")
    jsonl_p = to_jsonl([prod], tmp_path / "items.jsonl")
    assert xlsx_p.exists() and xlsx_p.stat().st_size > 1000
    assert "';'=CMD()" not in csv_p.read_text(encoding="utf-8-sig")
    assert "'=CMD()" in csv_p.read_text(encoding="utf-8-sig")
    assert json_p.exists() and jsonl_p.exists()

    summary = OzonReviewSummary(
        sku=1001,
        product_name="Тест",
        total_available=2,
        total_analyzed=1,
        avg_rating=5.0,
        top_pros=["Быстрый"],
        top_cons=["Нет"],
        reviews=[OzonReviewItem(id="r1", sku=1001, rating=5, pros="Быстрый", comment="Хорошо")],
    )
    rev_xlsx = reviews_to_excel(summary, tmp_path / "rev.xlsx")
    assert Path(rev_xlsx).exists()

    msg = TelegramNotifier.format_product_message(prod)
    assert "Ozon Карта" in msg
    rev_msg = TelegramNotifier.format_review_summary(summary)
    assert "Быстрый" in rev_msg
