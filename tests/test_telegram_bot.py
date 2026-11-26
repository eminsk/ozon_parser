"""Tests for OzonTelegramBot, upgraded TelegramNotifier, and CLI `bot` command."""

from __future__ import annotations

from pathlib import Path

from ozon_parser import (
    BotInstanceLock,
    OzonPriceTracker,
    OzonProduct,
    OzonReviewItem,
    OzonReviewSummary,
    OzonTelegramBot,
    TelegramNotifier,
    mask_proxy_url,
    normalize_tg_proxy,
    render_progress_bar,
    render_telegram_progress_bar,
    reviews_to_excel,
)
from ozon_parser.cli import main as cli_main


def test_ozon_tg_helpers_and_progress_bars() -> None:
    assert "50%" in render_progress_bar(5, 10, width=10)
    assert "🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜ 50%" in render_telegram_progress_bar(5, 10, width=10)
    assert normalize_tg_proxy("u:p@127.0.0.1:1080") == "http://u:p@127.0.0.1:1080"

    masked = mask_proxy_url("http://ozuser:mySecret99@mproxy.site:12411")
    assert "mySecret99" not in masked
    assert "mproxy.site:12411" in masked
    assert mask_proxy_url("") == "НЕ ПОДКЛЮЧЕН (прямой IP)"


def test_ozon_notifier_progress_and_excel(tmp_path: Path, monkeypatch) -> None:
    posts = []

    def fake_post(self, method, *, json_payload=None, data=None, files=None, timeout=None):
        posts.append((method, json_payload, data, bool(files), self.proxy))
        if method == "sendMessage":
            return True, {"ok": True, "result": {"message_id": 200 + len(posts)}}
        return True, {"ok": True}

    monkeypatch.setattr(TelegramNotifier, "_post", fake_post)

    notifier = TelegramNotifier("456:XYZ", "333, 444", proxy="socks5://127.0.0.1:1080")
    assert notifier.chat_ids == ["333", "444"]
    assert notifier.send_message("hello ozon") is True

    pids = notifier.start_progress("rtx 4060", total=20, use_mobile_proxy=True, workers=2)
    assert pids == {"333": 203, "444": 204}
    notifier.update_progress(pids, "rtx 4060", 10, 20, use_mobile_proxy=True, workers=2, drops_count=1, ip_rotations=2)

    xlsx = tmp_path / "ozon_report.xlsx"
    xlsx.write_bytes(b"PK\x03\x04")
    notifier.finish_progress(pids, "rtx 4060", 10, excel_path=xlsx)
    assert any(p[0] == "sendDocument" and p[3] is True for p in posts)

    summary = OzonReviewSummary(
        sku=1619925434,
        product_name="Тест Ozon",
        total_available=5,
        total_analyzed=1,
        avg_rating=5.0,
        top_pros=["Быстрый"],
        top_cons=["Нет"],
        reviews=[OzonReviewItem(id="r1", sku=1619925434, rating=5, pros="Быстрый", comment="Топ")],
    )
    rev_path = reviews_to_excel(summary, tmp_path / "oz_rev.xlsx")
    assert rev_path.exists()
    assert notifier.send_review_summary(summary) is True


def test_ozon_telegram_bot_commands_callbacks_and_batch(tmp_path: Path, monkeypatch) -> None:
    db_file = tmp_path / "ozon_bot.db"
    tracker = OzonPriceTracker(db_file)
    tracker.track_products([OzonProduct.model_validate({"sku": 1619925434, "name": "Наушники", "price": 5000})])
    tracker.track_products([OzonProduct.model_validate({"sku": 1619925434, "name": "Наушники", "price": 3900})])

    sent_texts = []
    edited_texts = []

    monkeypatch.setattr(
        TelegramNotifier,
        "send_message",
        lambda self, text, parse_mode="HTML", **kw: sent_texts.append((text, self.proxy)) or True,
    )
    monkeypatch.setattr(
        TelegramNotifier,
        "_send_message_impl",
        lambda self, text, **kw: (sent_texts.append((text, self.proxy)) or {cid: 77 for cid in self.chat_ids}, True),
    )
    monkeypatch.setattr(
        TelegramNotifier,
        "edit_message",
        lambda self, cid, mid, text, **kw: edited_texts.append(text) or True,
    )
    monkeypatch.setattr(TelegramNotifier, "answer_callback", lambda self, cb_id, text=None, **kw: True)
    monkeypatch.setattr(TelegramNotifier, "send_excel", lambda self, fp, caption="", **kw: True)

    bot = OzonTelegramBot(
        bot_token="888:OZON_TEST_TOKEN",
        tg_proxy="socks5://127.0.0.1:1080",
        tracker_db=db_file,
    )

    bot.handle_update({"message": {"chat": {"id": 555}, "text": "/start"}})
    bot.handle_update({"message": {"chat": {"id": 555}, "text": "/drops"}})
    bot.handle_update({"message": {"chat": {"id": 555}, "text": "/proxy http://oz1:secretOzon@1.2.3.4:8080 OZKEY55"}})
    assert bot.proxy == "http://oz1:secretOzon@1.2.3.4:8080"
    assert bot.proxy_change_url == "https://changeip.mobileproxy.space/?proxy_key=OZKEY55&format=json"
    assert not any("secretOzon" in txt for txt, _ in sent_texts)
    assert any("1,100" in txt or "3,900" in txt for txt, _ in sent_texts)
    assert all(proxy == "socks5://127.0.0.1:1080" for _, proxy in sent_texts)

    bot.handle_update({"message": {"chat": {"id": 555}, "text": "/workers 8"}})
    assert bot.workers == 8
    bot.handle_update({"message": {"chat": {"id": 555}, "text": "/limit 7000"}})
    assert bot.limit == 5000

    bot.handle_callback({"id": "c1", "message": {"chat": {"id": 555}, "message_id": 22}, "data": "set_workers:2"})
    assert bot.workers == 2
    bot.handle_callback({"id": "c2", "message": {"chat": {"id": 555}, "message_id": 22}, "data": "set_limit:500"})
    assert bot.limit == 500
    bot.handle_callback({"id": "c3", "message": {"chat": {"id": 555}, "message_id": 22}, "data": "toggle_seller"})
    assert bot.with_seller is False

    flow_calls = []
    dummy_xlsx = tmp_path / "dummy_oz.xlsx"
    dummy_xlsx.write_bytes(b"PK\x03\x04")
    monkeypatch.setattr(
        bot,
        "_run_search_flow",
        lambda cid, q, on_progress=None, suppress_individual_progress=False: (flow_calls.append(q) or (4, dummy_xlsx)),
    )
    bot.handle_update({
        "message": {
            "chat": {"id": 555},
            "text": "https://www.ozon.ru/product/1619925434/\nhttps://www.ozon.ru/category/naushniki-15500/",
        }
    })
    if bot._last_worker_thread:
        bot._last_worker_thread.join(timeout=3.0)
    assert len(flow_calls) == 2
    assert "1619925434" in flow_calls[0]
    assert "naushniki" in flow_calls[1]


def test_ozon_bot_lock_and_cli_bot_validation(monkeypatch, capsys) -> None:
    lock = BotInstanceLock("unique_test_token_ozon_12345")
    lock.acquire()
    try:
        assert lock.acquired is True
    finally:
        lock.release()
    assert lock.acquired is False

    monkeypatch.delenv("OZON_TG_TOKEN", raising=False)
    rc = cli_main(["bot"])
    assert rc == 1
    assert "OZON_TG_TOKEN" in capsys.readouterr().err


def test_ozon_bot_seller_rank_reviews_and_cli_tg_export(tmp_path: Path, monkeypatch) -> None:
    from ozon_parser.client import OzonClient
    from ozon_parser.models import SellerInfo
    from ozon_parser.rank import RankResult

    messages = []
    excels = []
    monkeypatch.setattr(TelegramNotifier, "send_message", lambda self, txt, **kw: messages.append(txt) or True)
    monkeypatch.setattr(TelegramNotifier, "send_review_summary", lambda self, s: messages.append(s.product_name) or True)
    monkeypatch.setattr(TelegramNotifier, "send_excel", lambda self, fp, caption="", **kw: excels.append(Path(fp).name) or True)

    monkeypatch.setattr(
        OzonClient,
        "get_seller",
        lambda self, target: SellerInfo(
            seller_id=55, name="Магазин", company_name="ООО Тест", inn="7700112233", average_rating="4.9"
        ),
    )
    monkeypatch.setattr(
        OzonClient,
        "check_rank",
        lambda self, target, query, **kw: RankResult(
            sku=1619925434, query=query, position=2, page=1, page_position=2, total_scanned=36, price=32000.0
        ),
    )
    monkeypatch.setattr(
        OzonClient,
        "analyze_reviews",
        lambda self, target, **kw: OzonReviewSummary(
            sku=1619925434, product_name="RTX 4060", avg_rating=4.9, top_pros=["Тихая"]
        ),
    )
    monkeypatch.setattr(
        OzonClient,
        "search",
        lambda self, q, **kw: [OzonProduct.model_validate({"sku": 1619925434, "name": "RTX 4060", "price": 32000})],
    )

    bot = OzonTelegramBot(bot_token="888:OZ_FLOW", tracker_db=tmp_path / "oz_flow.db")
    bot.handle_update({"message": {"chat": {"id": 999}, "text": "/seller 55"}})
    if bot._last_worker_thread:
        bot._last_worker_thread.join(timeout=3.0)
    bot.handle_update({"message": {"chat": {"id": 999}, "text": "/rank 1619925434 видеокарта"}})
    if bot._last_worker_thread:
        bot._last_worker_thread.join(timeout=3.0)
    bot.handle_update({"message": {"chat": {"id": 999}, "text": "/reviews 1619925434"}})
    if bot._last_worker_thread:
        bot._last_worker_thread.join(timeout=3.0)
    assert any("7700112233" in m for m in messages)

    out_xlsx = tmp_path / "cli_ozon.xlsx"
    rc = cli_main([
        "search", "rtx", "-o", str(out_xlsx),
        "--db", str(tmp_path / "cli_oz.db"),
        "--tg-token", "888:CLI", "--tg-chat-id", "999",
    ])
    assert rc == 0
    assert out_xlsx.exists()
    assert len(excels) >= 3
