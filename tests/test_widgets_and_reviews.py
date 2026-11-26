"""Tests for Ozon Composer widget parsing (product, seller modal, catalog grid, and HTML/JSON reviews)."""

from __future__ import annotations

import html
import json

from ozon_parser.widgets import (
    parse_catalog_composer,
    parse_product_composer,
    parse_reviews_composer,
    parse_seller_modal,
)


def test_parse_product_composer() -> None:
    payload = {
        "widgetStates": {
            "webStickyProducts-123": json.dumps(
                {
                    "id": 555666,
                    "name": "Клавиатура механическая",
                    "coverImageUrl": "https://ir.ozone.ru/s3/multimedia-1/cover.jpg",
                    "seller": {
                        "name": 'ООО "ТехноМир"',
                        "inn": "7701112233",
                        "link": "https://www.ozon.ru/seller/tehnomir-998877/",
                    },
                }
            ),
            "webPrice-456": json.dumps(
                {
                    "cardPrice": "4 290 ₽",
                    "price": "4 990 ₽",
                    "originalPrice": "6 990 ₽",
                    "isAvailable": True,
                }
            ),
            "webCharacteristics-789": json.dumps(
                {
                    "characteristics": [
                        {
                            "short": [
                                {"name": "Бренд", "values": [{"text": "KeyPro"}]},
                                {"name": "Подключение", "values": [{"text": "USB-C"}, {"text": "Bluetooth"}]},
                            ]
                        }
                    ]
                }
            ),
            "webReviewProductScore-111": json.dumps({"totalScore": "4.9", "reviewsCount": 240}),
        }
    }
    prod = parse_product_composer(payload, sku=555666)
    assert prod.name == "Клавиатура механическая"
    assert prod.price == 4990.0
    assert prod.card_price == 4290.0
    assert prod.original_price == 6990.0
    assert prod.seller_id == 998877
    assert prod.company_inn == "7701112233"
    assert prod.brand == "KeyPro"
    assert prod.specs["Подключение"] == "USB-C, Bluetooth"
    assert prod.rating == 4.9
    assert prod.reviews_count == 240


def test_parse_seller_modal_scoring() -> None:
    payload = {
        "widgetStates": {
            "textBlock-1": json.dumps({"body": [{"type": "textAtom", "textAtom": {"text": "О магазине"}}]}),
            "textBlock-2": json.dumps(
                {
                    "body": [
                        {"type": "textAtom", "textAtom": {"text": 'ООО "СитиЛайн"<br>7709988776'}},
                        {"type": "textAtom", "textAtom": {"text": "График работы согласно Ozon"}},
                    ]
                }
            ),
            "cellList-5": json.dumps(
                {
                    "cells": [
                        {"dsCell": {"centerBlock": {"title": {"text": "Заказов"}}, "rightBlock": {"badge": {"text": "15K+"}}}},
                        {"dsCell": {"centerBlock": {"title": {"text": "Работает с Ozon"}}, "rightBlock": {"badge": {"text": "3 года"}}}},
                        {"dsCell": {"centerBlock": {"title": {"text": "Средняя оценка товаров"}}, "rightBlock": {"badge": {"text": "4.8"}}}},
                        {"dsCell": {"centerBlock": {"title": {"text": "Количество отзывов"}}, "rightBlock": {"badge": {"text": "4 120"}}}},
                    ]
                }
            ),
        }
    }
    seller = parse_seller_modal(payload, seller_id=101)
    assert seller.company_name == 'ООО "СитиЛайн"'
    assert seller.inn == "7709988776"
    assert seller.orders_count == "15K+"
    assert seller.working_time == "3 года"
    assert seller.average_rating == "4.8"
    assert seller.reviews_count == "4 120"


def test_parse_catalog_composer() -> None:
    payload = {
        "nextPage": "/search/?text=mouse&page=2",
        "widgetStates": {
            "searchResultsV2-1": json.dumps(
                {
                    "items": [
                        {
                            "skuId": "777111",
                            "action": {"link": "/product/mish-besprovodnaya-777111/?from=search"},
                            "tileImage": {"items": [{"image": {"link": "https://ir.ozone.ru/img1.jpg"}}]},
                            "mainState": [
                                {"id": "name", "type": "textAtom", "textAtom": {"text": "Мышь беспроводная Pro"}},
                                {
                                    "type": "priceV2",
                                    "priceV2": {"price": [{"text": "1 990 ₽"}, {"text": "2 990 ₽"}], "cardPrice": "1 790 ₽"},
                                },
                                {
                                    "type": "labelList",
                                    "labelList": {"items": [{"title": "4.8"}, {"title": "320 отзывов"}]},
                                },
                            ],
                        }
                    ]
                }
            )
        },
    }
    items, next_page = parse_catalog_composer(payload)
    assert len(items) == 1
    assert items[0].id == 777111
    assert items[0].name == "Мышь беспроводная Pro"
    assert items[0].price == 1990.0
    assert items[0].card_price == 1790.0
    assert items[0].original_price == 2990.0
    assert items[0].rating == 4.8
    assert items[0].reviews_count == 320
    assert next_page == "/search/?text=mouse&page=2"


def test_parse_reviews_composer_json_and_html_data_state() -> None:
    reviews_state = {
        "reviews": [
            {
                "id": "rev-1",
                "itemId": "555666",
                "createdAt": 1700000000,
                "author": {"firstName": "Иван"},
                "content": {
                    "score": 5,
                    "positive": "Тихие клавиши; Яркая подсветка",
                    "negative": "",
                    "comment": "Очень удобная клавиатура",
                    "photos": [{"url": "https://ir.ozone.ru/s3/photo1.jpg"}],
                },
                "usefulness": {"useful": 12, "unuseful": 1},
                "reply": {"text": "Спасибо за отзыв!"},
            },
            {
                "id": "rev-2",
                "itemId": "555666",
                "content": {
                    "score": 2,
                    "positive": "Хорошая сборка",
                    "negative": "Короткий кабель",
                    "comment": "В целом норм, но провод короткий",
                },
            },
        ],
        "paging": {"nextButton": {"link": "/product/555666/reviews/?page=2"}},
    }
    score_state = {"totalScore": 4.6, "reviewsCount": 88}
    aspects_state = {"aspects": [{"name": "Подсветка"}, {"name": "Тишина"}]}

    # Test 1: Composer JSON
    items, rating, total, next_pg, tags = parse_reviews_composer(
        {
            "widgetStates": {
                "webListReviews-1": json.dumps(reviews_state),
                "webReviewProductScore-2": json.dumps(score_state),
                "webAspects-3": json.dumps(aspects_state),
            }
        },
        sku=555666,
    )
    assert len(items) == 2
    assert rating == 4.6
    assert total == 88
    assert next_pg == "/product/555666/reviews/?page=2"
    assert tags == ["Подсветка", "Тишина"]
    assert items[0].has_reply is True
    assert items[0].photos == ["https://ir.ozone.ru/s3/photo1.jpg"]

    # Test 2: HTML data-state fallback
    escaped_reviews = html.escape(json.dumps(reviews_state))
    html_doc = f'<div id="state-webListReviews-123" data-state="{escaped_reviews}"></div>'
    h_items, _, _, h_next, _ = parse_reviews_composer(html_doc, sku=555666)
    assert len(h_items) == 2
    assert h_next == "/product/555666/reviews/?page=2"
