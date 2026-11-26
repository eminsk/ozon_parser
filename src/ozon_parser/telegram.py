"""
Telegram notification helper with separate proxy support (decoupled from Ozon proxies).
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from ozon_parser.models import OzonProduct, OzonReviewSummary

logger = logging.getLogger("ozon_parser.telegram")


class TelegramNotifier:
    """Lightweight Telegram Bot API client for sending Ozon deals, review summaries & Excel files."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        proxy: Optional[str] = None,
        timeout: float = 15.0,
    ) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip()
        self.proxy = proxy.strip() if proxy and proxy.strip() else None
        self.timeout = float(timeout)
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    @staticmethod
    def format_product_message(product: OzonProduct) -> str:
        """Build HTML Telegram card for an Ozon product."""
        title = html.escape(product.name or f"SKU {product.id}")
        price_line = f"<b>{product.price:,.0f} ₽</b>" if product.price > 0 else "<b>Цена уточняется</b>"
        if product.card_price:
            price_line += f" (💳 Ozon Карта: <b>{product.card_price:,.0f} ₽</b>)"
        if product.discount > 0:
            price_line += f" <i>(-{product.discount}%)</i>"
        if product.price_drop:
            price_line += f" 📉 <b>-{product.price_drop:,.0f} ₽</b>"

        lines = [
            f"🔵 <b>{title}</b>",
            f"🆔 SKU: <code>{product.id}</code> | ⭐ {product.rating or '—'} ({product.reviews_count} отз.)",
            f"💰 Цена: {price_line}",
        ]
        if product.company_name or product.seller_name:
            comp = html.escape(product.company_name or product.seller_name)
            inn_part = f" • ИНН <code>{html.escape(product.company_inn)}</code>" if product.company_inn else ""
            lines.append(f"🏪 Продавец: {comp}{inn_part}")
        lines.append(f"🔗 <a href=\"{html.escape(product.url)}\">Открыть на Ozon ↗</a>")
        return "\n".join(lines)

    @staticmethod
    def format_review_summary(summary: OzonReviewSummary) -> str:
        """Build HTML Telegram summary message for buyer review analytics."""
        title = html.escape(summary.product_name or f"SKU {summary.sku}")
        lines = [
            f"🧠 <b>Умные отзывы Ozon: {title}</b>",
            f"⭐ Рейтинг: <b>{summary.avg_rating}</b> | Отзывов: {summary.total_analyzed}/{summary.total_available} | [{html.escape(summary.summary_mode)}]",
            "",
            "✅ <b>Плюсы:</b>",
        ]
        for p in (summary.top_pros or ["Нет данных"]):
            lines.append(f"• {html.escape(p)}")
        lines.append("")
        lines.append("❌ <b>Минусы:</b>")
        for c in (summary.top_cons or ["Существенных минусов нет"]):
            lines.append(f"• {html.escape(c)}")
        return "\n".join(lines)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send an HTML/plain text message to the configured Telegram chat."""
        if not self.bot_token or not self.chat_id:
            return False
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }
        try:
            if httpx is not None:
                with httpx.Client(proxy=self.proxy, timeout=self.timeout) as client:
                    return client.post(url, json=payload).status_code == 200
            if requests is not None:
                proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
                return requests.post(url, json=payload, proxies=proxies, timeout=self.timeout).status_code == 200
            return False
        except Exception as exc:
            logger.warning(f"Telegram send_message failed: {exc}")
            return False

    def send_product(self, product: OzonProduct) -> bool:
        """Send formatted Ozon product alert card."""
        return self.send_message(self.format_product_message(product))

    def send_review_summary(self, summary: OzonReviewSummary) -> bool:
        """Send formatted AI review summary."""
        return self.send_message(self.format_review_summary(summary))

    def send_document(self, filepath: Path, caption: str = "") -> bool:
        """Upload an `.xlsx`/`.csv`/`.json` report to Telegram chat."""
        if not self.bot_token or not self.chat_id or not filepath.exists():
            return False
        url = f"{self.base_url}/sendDocument"
        data = {"chat_id": self.chat_id, "caption": caption[:1024]}
        try:
            if httpx is not None:
                with httpx.Client(proxy=self.proxy, timeout=max(30.0, self.timeout)) as client:
                    with open(filepath, "rb") as f:
                        return client.post(url, data=data, files={"document": (filepath.name, f)}).status_code == 200
            if requests is not None:
                proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
                with open(filepath, "rb") as f:
                    return (
                        requests.post(
                            url,
                            data=data,
                            files={"document": (filepath.name, f)},
                            proxies=proxies,
                            timeout=max(30.0, self.timeout),
                        ).status_code
                        == 200
                    )
            return False
        except Exception as exc:
            logger.warning(f"Telegram send_document failed: {exc}")
            return False
