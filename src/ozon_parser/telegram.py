"""
Telegram notification engine (`TelegramNotifier`) and interactive Telegram Bot
Controller (`OzonTelegramBot`) for Ozon SDK Pro:
- Separate SOCKS5/HTTP proxy support for Telegram (`tg_proxy`), decoupled from Ozon proxies
- Live emoji progress bars (`🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜ 50%`) and automatic styled Excel (`.xlsx`) upload
- Batch multi-link / multi-query queue with dual progress bars
- Full interactive menus & commands (`/start`, `/search`, `/drops`, `/rank`, `/reviews`,
  `/seller`, `/workers`, `/limit`, `/proxy`, `/code`, `/status`, `/help`)
- Cross-platform single-instance lock (`BotInstanceLock`) preventing `409 Conflict` duplicate pollers
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from ozon_parser.config import (
    MOBILEPROXY_FREE_TRIAL_URL,
    TELEGRAM_CHANNEL_URL,
    resolve_proxy_change_url,
)
from ozon_parser.endpoints import classify_target
from ozon_parser.export import rank_results_to_excel, reviews_to_excel, to_excel
from ozon_parser.models import OzonProduct, OzonReviewSummary
from ozon_parser.tracker import OzonPriceTracker

logger = logging.getLogger("ozon_parser.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def normalize_tg_proxy(proxy: Optional[str]) -> Optional[str]:
    """Normalize a Telegram proxy string (supports `user:pass@host:port`, `http://`, `socks5://`)."""
    raw = (proxy or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        return f"http://{raw}"
    return raw


def mask_proxy_url(proxy: Optional[str]) -> str:
    """Mask proxy credentials so tokens, logins, and passwords never leak in logs or Telegram UI."""
    raw = (proxy or "").strip()
    if not raw:
        return "НЕ ПОДКЛЮЧЕН (прямой IP)"
    masked = re.sub(r"://([^:\s]{1,3})[^:\s]*:([^@\s]+)@", r"://\1***:***@", raw)
    if masked == raw and "@" in raw:
        masked = re.sub(r"^([^:\s]{1,3})[^:\s]*:([^@\s]+)@", r"\1***:***@", raw)
    return masked


def render_progress_bar(current: int, total: int, width: int = 16) -> str:
    """Render an ASCII progress bar for terminal output."""
    if total <= 0:
        return f"[{'█' * width}] {current} шт."
    ratio = min(max(current / total, 0.0), 1.0)
    filled = int(round(width * ratio))
    bar = "█" * filled + "░" * (width - filled)
    pct = int(round(ratio * 100))
    return f"[{bar}] {pct}% ({current}/{total})"


def render_telegram_progress_bar(current: int, total: int, width: int = 10) -> str:
    """Render an emoji progress bar tailored for Telegram proportional fonts."""
    if total <= 0:
        return f"{'🟩' * width} {current} шт."
    ratio = min(max(current / total, 0.0), 1.0)
    filled = int(round(width * ratio))
    bar = "🟩" * filled + "⬜" * (width - filled)
    pct = int(round(ratio * 100))
    return f"{bar} {pct}% ({current}/{total})"


def _parse_chat_ids(chat_id: Union[str, int, Sequence[Union[str, int]], None]) -> List[str]:
    if chat_id is None:
        return []
    if isinstance(chat_id, (int, str)):
        parts = re.split(r"[,;\s]+", str(chat_id).strip())
        return [p for p in parts if p]
    return [str(cid).strip() for cid in chat_id if str(cid).strip()]


def _mode_description(workers: int) -> str:
    if workers <= 2:
        return "Safe Mode"
    if workers <= 4:
        return "Fast Mode ⚡"
    return "Turbo Mode 🚀"


class BotInstanceLock:
    """
    Lightweight cross-platform OS lock keyed by bot token hash to prevent running
    multiple `getUpdates` pollers (`409 Conflict`) simultaneously.
    """

    def __init__(self, token: str, app_tag: str = "ozonsdkpro_bot") -> None:
        token_hash = hashlib.sha256((token or "default").encode("utf-8")).hexdigest()[:12]
        self.lock_name = f"{app_tag}_{token_hash}"
        self.lock_path = Path(tempfile.gettempdir()) / f".{self.lock_name}.lock"
        self._win_mutex = None
        self._fd = None
        self.acquired = False

    def acquire(self) -> None:
        if self.acquired:
            return
        if sys.platform.startswith("win"):
            import ctypes

            kernel32 = ctypes.windll.kernel32
            mutex_name = f"Local\\{self.lock_name}"
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            last_err = kernel32.GetLastError()
            if not handle:
                raise RuntimeError(f"Failed to create Windows mutex {mutex_name}")
            if last_err == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                raise RuntimeError(
                    "Другой экземпляр Telegram-бота с этим токеном уже запущен на этом ПК."
                )
            self._win_mutex = handle
            self.acquired = True
            return

        import fcntl

        fd = open(self.lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fd.close()
            raise RuntimeError(
                "Another Telegram bot instance with this token is already running."
            ) from exc
        self._fd = fd
        self.acquired = True

    def release(self) -> None:
        if not self.acquired:
            return
        if sys.platform.startswith("win") and self._win_mutex is not None:
            try:
                import ctypes

                ctypes.windll.kernel32.ReleaseMutex(self._win_mutex)
                ctypes.windll.kernel32.CloseHandle(self._win_mutex)
            except Exception:
                pass
            self._win_mutex = None
        elif self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None
        self.acquired = False

    def __enter__(self) -> "BotInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


class TelegramNotifier:
    """Telegram Bot API client for Ozon deals, review summaries, live progress bars & Excel files."""

    def __init__(
        self,
        bot_token: str,
        chat_id: Union[str, int, Sequence[Union[str, int]]] = "",
        *,
        proxy: Optional[str] = None,
        timeout: float = 15.0,
        max_retries: int = 3,
    ) -> None:
        self.bot_token = (bot_token or "").strip()
        self.chat_ids: List[str] = _parse_chat_ids(chat_id)
        self.chat_id: str = self.chat_ids[0] if self.chat_ids else ""
        self.proxy = normalize_tg_proxy(proxy)
        self.timeout = float(timeout)
        self.max_retries = max(1, int(max_retries))
        self.base_url = f"{TELEGRAM_API_BASE}{self.bot_token}"

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

    @staticmethod
    def format_price_drops(drops: Sequence[Any], *, limit: int = 15) -> str:
        """Build HTML report of SQLite price drops recorded by `OzonPriceTracker`."""
        if not drops:
            return "📉 <b>Снижения цен Ozon:</b> пока не зафиксированы (выполните повторный поиск товаров)."
        lines = ["📉 <b>Зафиксированные снижения цен Ozon:</b>", ""]
        for d in list(drops)[:limit]:
            sku = getattr(d, "sku", "")
            name = html.escape(str(getattr(d, "name", "") or f"SKU {sku}")[:65])
            price = float(getattr(d, "price", 0) or 0)
            old_price = float(getattr(d, "old_price", 0) or 0)
            card_price = getattr(d, "card_price", None)
            diff = max(0.0, old_price - price)
            card_str = f" | 💳 Карта: {float(card_price):,.0f} ₽" if card_price else ""
            lines.append(
                f"• <a href=\"https://www.ozon.ru/product/{sku}/\">{name}</a>\n"
                f"  <b>{price:,.0f} ₽</b> <s>{old_price:,.0f} ₽</s> (<b>-{diff:,.0f} ₽</b>){card_str} | 🆔 <code>{sku}</code>"
            )
        return "\n".join(lines)

    def _post(
        self,
        method: str,
        *,
        json_payload: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        if not self.bot_token:
            return False, None
        url = f"{self.base_url}/{method}"
        req_timeout = float(timeout or self.timeout)

        for attempt in range(1, self.max_retries + 1):
            try:
                if httpx is not None:
                    with httpx.Client(proxy=self.proxy, timeout=req_timeout) as client:
                        r = client.post(url, json=json_payload, data=data, files=files)
                elif requests is not None:
                    proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
                    r = requests.post(
                        url,
                        json=json_payload,
                        data=data,
                        files=files,
                        proxies=proxies,
                        timeout=req_timeout,
                    )
                else:  # pragma: no cover
                    return False, None

                if r.status_code == 429 and attempt < self.max_retries:
                    retry_after = 1.5 * attempt
                    try:
                        retry_after = float(r.json().get("parameters", {}).get("retry_after", retry_after))
                    except Exception:
                        pass
                    time.sleep(min(retry_after, 10.0))
                    continue

                if 200 <= r.status_code < 300:
                    try:
                        parsed = r.json()
                    except Exception:
                        parsed = {"ok": True}
                    return True, parsed if isinstance(parsed, dict) else {"ok": True}

                if r.status_code == 400:
                    logger.warning(f"Telegram {method} HTTP 400: {getattr(r, 'text', '')[:200]}")
                    return False, None
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
            except Exception as exc:
                logger.warning(f"Telegram {method} failed (attempt {attempt}): {exc}")
                if files is not None:
                    return False, None
                if attempt < self.max_retries:
                    time.sleep(0.5 * attempt)
        return False, None

    def _send_message_impl(
        self,
        text: str,
        *,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = False,
    ) -> Tuple[Dict[str, int], bool]:
        if not self.bot_token or not self.chat_ids:
            return {}, False
        msg_ids: Dict[str, int] = {}
        any_ok = False
        for cid in self.chat_ids:
            payload: Dict[str, Any] = {
                "chat_id": cid,
                "text": text,
                "disable_web_page_preview": disable_web_page_preview,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            ok, parsed = self._post("sendMessage", json_payload=payload)
            if ok:
                any_ok = True
                if isinstance(parsed, dict):
                    mid = parsed.get("result", {}).get("message_id")
                    if isinstance(mid, int):
                        msg_ids[cid] = mid
        return msg_ids, any_ok

    def send_message_ids(
        self,
        text: str,
        *,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = False,
    ) -> Dict[str, int]:
        """Send an HTML/plain message and return `{chat_id: message_id}` for live editing."""
        msg_ids, _ = self._send_message_impl(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return msg_ids

    def send_message(
        self,
        text: str,
        parse_mode: Optional[str] = "HTML",
        *,
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = False,
    ) -> bool:
        """Send an HTML/plain text message to configured Telegram chat(s)."""
        _, any_ok = self._send_message_impl(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return any_ok

    def edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        parse_mode: Optional[str] = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None,
        disable_web_page_preview: bool = True,
    ) -> bool:
        """Edit an existing message in Telegram (menus & live progress bars)."""
        if not self.bot_token or not chat_id or not message_id:
            return False
        payload: Dict[str, Any] = {
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        ok, _ = self._post("editMessageText", json_payload=payload, timeout=min(self.timeout, 10.0))
        return ok

    def answer_callback(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        *,
        show_alert: bool = False,
    ) -> bool:
        """Acknowledge an inline button press."""
        if not self.bot_token or not callback_query_id:
            return False
        payload: Dict[str, Any] = {"callback_query_id": str(callback_query_id)}
        if text:
            payload["text"] = text[:200]
            payload["show_alert"] = show_alert
        ok, _ = self._post("answerCallbackQuery", json_payload=payload, timeout=8.0)
        return ok

    def set_bot_commands(self, commands: Optional[List[Dict[str, str]]] = None) -> bool:
        """Register interactive commands in Telegram UI."""
        cmd_list = commands or [
            {"command": "start", "description": "🏠 Главное меню и статус"},
            {"command": "search", "description": "🔍 Поиск Ozon и выгрузка в Excel"},
            {"command": "drops", "description": "📉 Зафиксированные снижения цен"},
            {"command": "rank", "description": "📈 Позиция товара в выдаче Ozon"},
            {"command": "reviews", "description": "💬 Отзывы и AI-разбор (+ Excel)"},
            {"command": "seller", "description": "🏪 Информация и ИНН продавца"},
            {"command": "workers", "description": "🧵 Потоки парсинга (1..16)"},
            {"command": "limit", "description": "📦 Лимит товаров (10..5000)"},
            {"command": "proxy", "description": "🌐 Настройка мобильного прокси"},
            {"command": "code", "description": "💻 Готовый Python-код SDK"},
            {"command": "status", "description": "📊 Текущие параметры бота"},
            {"command": "help", "description": "ℹ️ Инструкция и примеры"},
        ]
        ok, _ = self._post("setMyCommands", json_payload={"commands": cmd_list}, timeout=8.0)
        return ok

    def send_product(self, product: OzonProduct) -> bool:
        """Send formatted Ozon product alert card."""
        return self.send_message(self.format_product_message(product))

    def send_review_summary(self, summary: OzonReviewSummary) -> bool:
        """Send formatted AI review summary."""
        return self.send_message(self.format_review_summary(summary))

    def send_price_drops(self, drops: Sequence[Any], *, limit: int = 15) -> bool:
        """Send formatted SQLite price-drop summary."""
        return self.send_message(self.format_price_drops(drops, limit=limit), disable_web_page_preview=True)

    def send_document(
        self,
        filepath: Union[str, Path],
        caption: str = "",
        *,
        target_chat_ids: Optional[Sequence[str]] = None,
    ) -> bool:
        """Upload an `.xlsx`/`.csv`/`.json` report to Telegram chat(s)."""
        path = Path(filepath)
        chats = [str(c).strip() for c in target_chat_ids if str(c).strip()] if target_chat_ids else self.chat_ids
        if not self.bot_token or not chats:
            return False
        if not path.exists():
            if path.suffix.lower() == ".xlsx" and path.with_suffix(".csv").exists():
                path = path.with_suffix(".csv")
            elif path.suffix.lower() == ".csv" and path.with_suffix(".xlsx").exists():
                path = path.with_suffix(".xlsx")
            else:
                return False

        suffix = path.suffix.lower()
        if suffix == ".csv":
            mime_type = "text/csv"
        elif suffix == ".json":
            mime_type = "application/json"
        else:
            mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

        any_ok = False
        for cid in chats:
            data: Dict[str, Any] = {"chat_id": cid}
            if caption:
                data["caption"] = caption[:1024]
            with open(path, "rb") as f:
                ok, _ = self._post(
                    "sendDocument",
                    data=data,
                    files={"document": (path.name, f, mime_type)},
                    timeout=max(45.0, self.timeout),
                )
            if ok:
                any_ok = True
        return any_ok

    def send_excel(
        self,
        filepath: Union[str, Path],
        caption: str = "",
        *,
        target_chat_ids: Optional[Sequence[str]] = None,
    ) -> bool:
        """Upload an `.xlsx` (or `.csv` fallback) Excel report directly into Telegram chat."""
        return self.send_document(filepath, caption=caption, target_chat_ids=target_chat_ids)

    def notify(self, product: Optional[OzonProduct] = None, message: Optional[str] = None) -> bool:
        """Send an `OzonProduct` alert card or text notice."""
        if product is not None:
            return self.send_product(product)
        if message:
            return self.send_message(html.escape(message))
        return False

    def notify_many(self, products: Sequence[OzonProduct]) -> int:
        """Send multiple `OzonProduct` alerts."""
        return sum(1 for item in products if self.send_product(item))

    def start_progress(
        self,
        query: str,
        *,
        total: int = 0,
        use_mobile_proxy: bool = False,
        workers: int = 2,
    ) -> Dict[str, int]:
        """Send initial live emoji progress bar message to Telegram."""
        bar = render_telegram_progress_bar(0, total)
        proxy_status = "Подключен (Mobile 4G LTE)" if use_mobile_proxy else "Прямое соединение / без прокси"
        text = (
            "🔵 <b>Сбор данных с Ozon</b>\n\n"
            f"🔍 <b>Цель:</b> <code>{html.escape(query)}</code>\n"
            f"📊 <b>Прогресс:</b> {bar}\n\n"
            f"🌐 <b>Прокси:</b> {proxy_status}\n"
            f"🧵 <b>Потоков:</b> {workers} <i>({_mode_description(workers)})</i>\n"
            "⚡ <i>Запрос Composer API v2 и формирование Excel (.xlsx)...</i>"
        )
        return self.send_message_ids(text, parse_mode="HTML", disable_web_page_preview=True)

    def update_progress(
        self,
        progress_ids: Dict[str, int],
        query: str,
        current: int,
        total: int,
        *,
        use_mobile_proxy: bool = False,
        workers: int = 2,
        drops_count: int = 0,
        ip_rotations: int = 0,
    ) -> None:
        """Update the live Telegram progress bar message."""
        if not progress_ids:
            return
        bar = render_telegram_progress_bar(current, total)
        proxy_status = f"Активен (ротаций IP: {ip_rotations})" if use_mobile_proxy else "Прямой канал"
        text = (
            "⏳ <b>Сбор Ozon в процессе...</b>\n\n"
            f"🔍 <b>Цель:</b> <code>{html.escape(query)}</code>\n"
            f"📊 <b>Прогресс:</b> {bar}\n\n"
            f"🌐 <b>Прокси:</b> {proxy_status}\n"
            f"🧵 <b>Потоков:</b> {workers}  |  📉 <b>Снижений цен:</b> {drops_count}\n"
            "⚡ <i>Обогащение Ozon Карты / ИНН и сохранение Excel...</i>"
        )
        for cid, mid in progress_ids.items():
            self.edit_message(cid, mid, text, parse_mode="HTML")

    def finish_progress(
        self,
        progress_ids: Dict[str, int],
        query: str,
        total_found: int,
        *,
        use_mobile_proxy: bool = False,
        workers: int = 2,
        drops_count: int = 0,
        ip_rotations: int = 0,
        excel_path: Optional[Union[str, Path]] = None,
    ) -> None:
        """Mark progress complete and optionally upload generated Excel `.xlsx` file."""
        bar = render_telegram_progress_bar(total_found, max(total_found, 1))
        proxy_status = f"Активен (ротаций IP: {ip_rotations})" if use_mobile_proxy else "Прямой канал"
        text = (
            "✅ <b>Сбор Ozon успешно завершён!</b>\n\n"
            f"🔍 <b>Цель:</b> <code>{html.escape(query)}</code>\n"
            f"📊 <b>Прогресс:</b> {bar}\n\n"
            f"📉 <b>Снижений цен:</b> {drops_count}\n"
            f"🌐 <b>Прокси:</b> {proxy_status}\n"
            f"🧵 <b>Потоков:</b> {workers} ({_mode_description(workers)})\n\n"
            "📊 <i>Готовый отчёт Excel (.xlsx) с ИНН и Ozon Картой загружается ниже 👇</i>"
        )
        for cid, mid in progress_ids.items():
            self.edit_message(cid, mid, text, parse_mode="HTML")

        if excel_path:
            p = Path(excel_path)
            if p.exists() or p.with_suffix(".csv").exists():
                caption = f"📊 Ozon Отчёт Excel: {query[:55]} ({total_found} товаров, снижений: {drops_count})"
                chats = list(progress_ids.keys()) if progress_ids else None
                self.send_excel(p, caption=caption, target_chat_ids=chats)


class OzonTelegramBot:
    """
    Interactive Telegram Bot controller for Ozon SDK Pro (`ozon-sdk-pro`):
    - Inline keyboards, slash commands, and privacy-masked MobileProxy setup
    - Search queries, SKU cards, categories, seller stores (+ ИНН), and batch queues
    - Live emoji progress bars + automatic `.xlsx` Excel uploads directly into Telegram
    - Built-in `/drops`, `/rank`, `/reviews` (AI + `.xlsx`), `/seller` workflows
    """

    def __init__(
        self,
        bot_token: str,
        proxy: Optional[str] = None,
        proxy_change_url: Optional[str] = None,
        mobileproxy_key: Optional[str] = None,
        *,
        tg_proxy: Optional[str] = None,
        channel_id: Optional[Union[str, int]] = None,
        workers: int = 2,
        limit: int = 50,
        max_pages: int = 2,
        sort: str = "score",
        with_seller: bool = True,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        use_browser_fallback: bool = False,
        tracker_db: Union[str, Path] = "ozon_prices.db",
    ) -> None:
        self.bot_token = (bot_token or "").strip()
        self.proxy = proxy.strip() if proxy and proxy.strip() else None
        self.mobileproxy_key = (mobileproxy_key or "").strip() or None
        self.proxy_change_url = resolve_proxy_change_url(proxy_change_url, self.mobileproxy_key)
        self.tg_proxy = normalize_tg_proxy(tg_proxy)
        self.channel_id = str(channel_id).strip() if channel_id else None
        self.workers = min(max(1, int(workers)), 16)
        self.limit = min(max(1, int(limit)), 5000)
        self.max_pages = max(1, int(max_pages))
        self.sort = sort or "score"
        self.with_seller = bool(with_seller)
        self.cookies = cookies
        self.user_agent = user_agent
        self.use_browser_fallback = bool(use_browser_fallback)
        self.tracker_db = str(tracker_db)

        self._offset = 0
        self._stop_event = threading.Event()
        self._is_scraping = False
        self._current_task_info = ""
        self._current_link_idx = 0
        self._total_links = 0
        self._current_url = ""
        self._current_collected = 0
        self._current_limit = 0
        self._scrape_lock = threading.Lock()
        self._last_worker_thread: Optional[threading.Thread] = None

    def stop(self) -> None:
        """Signal the polling loop to stop cleanly."""
        self._stop_event.set()

    def _new_notifier(self, chat_id: Union[str, int, Sequence[Union[str, int]]] = "") -> TelegramNotifier:
        return TelegramNotifier(bot_token=self.bot_token, chat_id=chat_id, proxy=self.tg_proxy)

    def _build_client(self):
        from ozon_parser.client import OzonClient

        return OzonClient(
            proxy=self.proxy,
            proxy_change_url=self.proxy_change_url,
            mobileproxy_key=self.mobileproxy_key,
            cookies=self.cookies,
            user_agent=self.user_agent,
            use_browser_fallback=self.use_browser_fallback,
            tracker_db=self.tracker_db,
        )

    def _main_keyboard(self) -> Dict[str, Any]:
        seller_icon = "✅ ВКЛ" if self.with_seller else "❌ ВЫКЛ"
        return {
            "inline_keyboard": [
                [
                    {"text": "🔍 Начать поиск Ozon", "callback_data": "menu_search"},
                    {"text": "📉 Снижения цен", "callback_data": "menu_drops"},
                ],
                [
                    {"text": f"🧵 Потоки: {self.workers}", "callback_data": "menu_workers"},
                    {"text": f"📦 Лимит: {self.limit} шт", "callback_data": "menu_limit"},
                ],
                [
                    {"text": f"🏪 ИНН продавца: {seller_icon}", "callback_data": "toggle_seller"},
                    {"text": "🌐 Мобильный прокси", "callback_data": "menu_proxy"},
                ],
                [
                    {"text": "💻 Готовый код SDK", "callback_data": "menu_code"},
                    {"text": "ℹ️ Инструкция", "callback_data": "menu_help"},
                ],
                [
                    {"text": "🎁 Прокси 3ч бесплатно", "url": MOBILEPROXY_FREE_TRIAL_URL},
                    {"text": "📢 Канал @avito_sdk_pro", "url": TELEGRAM_CHANNEL_URL},
                ],
            ]
        }

    def _workers_keyboard(self) -> Dict[str, Any]:
        def _wm(n: int) -> str:
            return " ✅" if self.workers == n else ""

        return {
            "inline_keyboard": [
                [
                    {"text": f"🧵 1 поток{_wm(1)}", "callback_data": "set_workers:1"},
                    {"text": f"🧵 2 потока (Safe){_wm(2)}", "callback_data": "set_workers:2"},
                ],
                [
                    {"text": f"⚡ 4 потока (Fast){_wm(4)}", "callback_data": "set_workers:4"},
                    {"text": f"🚀 8 потоков (Turbo){_wm(8)}", "callback_data": "set_workers:8"},
                ],
                [{"text": "« Назад в главное меню", "callback_data": "menu_main"}],
            ]
        }

    def _limit_keyboard(self) -> Dict[str, Any]:
        def _mark(n: int) -> str:
            return " ✅" if self.limit == n else ""

        return {
            "inline_keyboard": [
                [
                    {"text": f"10 шт{_mark(10)}", "callback_data": "set_limit:10"},
                    {"text": f"50 шт{_mark(50)}", "callback_data": "set_limit:50"},
                    {"text": f"100 шт{_mark(100)}", "callback_data": "set_limit:100"},
                ],
                [
                    {"text": f"200 шт{_mark(200)}", "callback_data": "set_limit:200"},
                    {"text": f"500 шт{_mark(500)}", "callback_data": "set_limit:500"},
                    {"text": f"1000 шт{_mark(1000)}", "callback_data": "set_limit:1000"},
                ],
                [{"text": "« Назад в главное меню", "callback_data": "menu_main"}],
            ]
        }

    def _search_prompt_keyboard(self) -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "💻 ноутбук", "callback_data": "quick_search:ноутбук"},
                    {"text": "🎧 беспроводные наушники", "callback_data": "quick_search:беспроводные наушники"},
                ],
                [
                    {"text": "🎮 видеокарта rtx 4060", "callback_data": "quick_search:видеокарта rtx 4060"},
                    {"text": "🆔 SKU 1619925434", "callback_data": "quick_search:1619925434"},
                ],
                [{"text": "« Назад в главное меню", "callback_data": "menu_main"}],
            ]
        }

    def _back_keyboard(self) -> Dict[str, Any]:
        return {"inline_keyboard": [[{"text": "« Назад в главное меню", "callback_data": "menu_main"}]]}

    def _status_text(self) -> str:
        proxy_state = f"✅ {html.escape(mask_proxy_url(self.proxy))}" if self.proxy else "❌ Не задан"
        rot_state = "✅ Активна (MobileProxy)" if self.proxy_change_url else "❌ Не задана"
        tg_p_state = f"✅ {html.escape(mask_proxy_url(self.tg_proxy))}" if self.tg_proxy else "Прямой"
        seller_state = "ВКЛ (юридическое лицо + ИНН)" if self.with_seller else "ВЫКЛ (только цены и рейтинг)"
        chan_state = html.escape(self.channel_id) if self.channel_id else "Текущий диалог"

        if self._is_scraping:
            bar = render_telegram_progress_bar(self._current_collected, self._current_limit or self.limit)
            link_desc = (
                f"🔗 <b>Задача {self._current_link_idx}/{self._total_links}:</b> "
                f"<code>{html.escape(self._current_url[:45])}</code>\n"
                if self._total_links > 1
                else f"🔍 <b>Цель:</b> <code>{html.escape(self._current_task_info[:45])}</code>\n"
            )
            task_state = (
                "⏳ <b>Фоновый сбор Ozon в процессе:</b>\n"
                f"{link_desc}"
                f"📊 <b>Прогресс:</b> {bar}\n\n"
            )
        else:
            task_state = "💤 <b>Статус:</b> Ожидание команд (готов к сбору Ozon)\n\n"

        return (
            "🔵 <b>Панель управления Ozon SDK Pro Bot</b>\n\n"
            f"{task_state}"
            f"🌐 <b>Прокси Ozon:</b> {proxy_state}\n"
            f"🔄 <b>Автосмена IP:</b> {rot_state}\n"
            f"✈ <b>Прокси Telegram:</b> {tg_p_state}\n"
            f"🧵 <b>Потоков:</b> <code>{self.workers}</code> <i>({_mode_description(self.workers)})</i>\n"
            f"📦 <b>Лимит выдачи:</b> <code>{self.limit}</code> товаров\n"
            f"🏪 <b>Продавец / ИНН:</b> {seller_state}\n"
            f"📢 <b>Канал отчётов:</b> {chan_state}\n\n"
            "💡 <i>Отправьте запрос (например <code>видеокарта rtx 4060</code>), SKU <code>1619925434</code>, "
            "ссылку на товар / категорию / магазин Ozon или несколько строк — бот соберёт данные и пришлёт Excel (.xlsx)!</i>"
        )

    def _proxy_info_text(self) -> str:
        proxy_state = f"✅ {html.escape(mask_proxy_url(self.proxy))}" if self.proxy else "❌ Не задан"
        rot_state = "✅ Активна (MobileProxy)" if self.proxy_change_url else "❌ Не задана"
        return (
            "🌐 <b>Мобильные прокси Ozon SDK Pro</b>\n\n"
            f"• <b>Текущий прокси:</b> {proxy_state}\n"
            f"• <b>Автосмена IP:</b> {rot_state}\n"
            "• <b>Маскировка паролей:</b> 🔒 включена\n\n"
            "💡 <b>Смена прокси прямо в Telegram:</b>\n"
            "<code>/proxy http://user:pass@ip:port [ключ_mobileproxy_или_url]</code>\n\n"
            f"🎁 <a href=\"{MOBILEPROXY_FREE_TRIAL_URL}\">Получить бесплатный тест 4G/LTE прокси на 3 часа (РФ без VPN)</a>"
        )

    def _code_text(self) -> str:
        return (
            "💻 <b>Минимальный Python-код (`ozon-sdk-pro`):</b>\n\n"
            "📦 <b>Установка:</b>\n"
            "<code>uv add \"ozon-sdk-pro[tls,ai]\"</code>\n\n"
            "<pre><code class=\"language-python\">from ozon_parser import OzonClient, OzonTelegramBot, to_excel\n\n"
            "with OzonClient(\n"
            "    proxy=\"http://login:pass@host:port\",\n"
            "    mobileproxy_key=\"YOUR_KEY\",\n"
            ") as ozon:\n"
            "    items = ozon.search(\"ноутбук\", limit=50, with_seller=True)\n"
            "    to_excel(items, \"ozon_catalog.xlsx\")\n"
            "    rev = ozon.analyze_reviews(1619925434, ai_mode=\"free\")\n\n"
            "# Запуск интерактивного Telegram-бота:\n"
            "# OzonTelegramBot(bot_token=\"...\", mobileproxy_key=\"...\").run_polling()"
            "</code></pre>"
        )

    def _help_text(self) -> str:
        return (
            "📖 <b>Инструкция Ozon SDK Pro Bot</b>\n\n"
            "1️⃣ <b>Поиск и выгрузка в Excel (.xlsx):</b>\n"
            "Отправьте запрос, SKU, ссылку на товар/категорию/продавца Ozon или сразу несколько ссылок.\n\n"
            "2️⃣ <b>Команды:</b>\n"
            "• <code>/search запрос</code> — поиск Ozon + Excel в чат\n"
            "• <code>/drops</code> — снижения цен из SQLite-трекера\n"
            "• <code>/rank 1619925434 rtx 4060</code> — позиция SKU в выдаче (+ Excel)\n"
            "• <code>/reviews 1619925434</code> — умные отзывы + AI (+ Excel)\n"
            "• <code>/seller 12345</code> — реквизиты продавца (компания, ИНН, заказы)\n"
            "• <code>/workers 4</code> | <code>/limit 200</code> — потоки и лимит\n"
            "• <code>/proxy http://user:pass@ip:port [key]</code> — сменить прокси"
        )

    def _run_search_flow(
        self,
        chat_id: str,
        query: str,
        on_progress: Optional[Callable[[int, int, int], None]] = None,
        suppress_individual_progress: bool = False,
    ) -> Tuple[int, Optional[Path]]:
        target_chats = [chat_id]
        if self.channel_id and self.channel_id != chat_id:
            target_chats.append(self.channel_id)

        notifier = self._new_notifier(target_chats)
        use_mob = bool(self.proxy or self.proxy_change_url)
        progress_ids: Dict[str, int] = {}
        if not suppress_individual_progress:
            progress_ids = notifier.start_progress(
                query,
                total=self.limit,
                use_mobile_proxy=use_mob,
                workers=self.workers,
            )

        reports_dir = Path("storage/reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        excel_path = reports_dir / f"ozon_results_{timestamp}_{int(time.time() * 1000) % 1000}.xlsx"

        try:
            with self._build_client() as client:
                kind, value = classify_target(query)
                pages_needed = max(self.max_pages, (self.limit + 35) // 36)

                if kind == "product":
                    items = [client.get_product(int(value), with_seller=self.with_seller)]
                elif kind == "seller":
                    items = client.get_seller_catalog(
                        int(value),
                        max_pages=pages_needed,
                        limit=self.limit,
                        sort=self.sort,
                        with_seller=self.with_seller,
                    )
                elif kind == "category":
                    items = client.get_category(
                        value,
                        max_pages=pages_needed,
                        limit=self.limit,
                        sort=self.sort,
                        with_seller=self.with_seller,
                    )
                else:
                    items = client.search(
                        value,
                        max_pages=pages_needed,
                        limit=self.limit,
                        sort=self.sort,
                        with_seller=self.with_seller,
                    )

                ip_rotations = int(getattr(client.transport, "ip_rotations", 0))
                self._current_collected = len(items)
                self._current_limit = max(len(items), self.limit)
                if on_progress:
                    try:
                        on_progress(len(items), self._current_limit, ip_rotations)
                    except Exception:
                        pass

                drops = [p for p in items if (p.price_drop or 0) > 0]
                if not items:
                    if not suppress_individual_progress:
                        if progress_ids:
                            notifier.edit_message(
                                chat_id,
                                progress_ids[chat_id],
                                f"ℹ️ По запросу <code>{html.escape(query)}</code> товары Ozon не найдены "
                                "(или требуется RU мобильный прокси / куки сессии).",
                                parse_mode="HTML",
                            )
                        else:
                            notifier.send_message(f"ℹ️ По запросу «{html.escape(query)}» товары не найдены.")
                    return 0, None

                to_excel(items, excel_path)
                if not suppress_individual_progress:
                    if progress_ids:
                        notifier.finish_progress(
                            progress_ids,
                            query,
                            len(items),
                            use_mobile_proxy=use_mob,
                            workers=self.workers,
                            drops_count=len(drops),
                            ip_rotations=ip_rotations,
                            excel_path=excel_path,
                        )
                    else:
                        notifier.send_excel(
                            excel_path,
                            caption=f"📊 Ozon Отчёт Excel: {query[:55]} ({len(items)} товаров)",
                        )
                return len(items), excel_path
        except Exception as exc:
            logger.error(f"OzonTelegramBot search flow error: {exc}")
            notifier.send_message(f"❌ <b>Ошибка при сборе Ozon:</b> <code>{html.escape(str(exc))}</code>")
            return 0, None

    def _run_rank_flow(self, chat_id: str, target: str, query: str) -> None:
        notifier = self._new_notifier(chat_id)
        try:
            with self._build_client() as client:
                res = client.check_rank(target, query, max_pages=max(self.max_pages, 3), sort=self.sort)
            pos_str = f"<b>#{res.position}</b> (стр. {res.page}, слот {res.page_position})" if res.position else f"Не найден (проверено {res.total_scanned})"
            delta_str = ""
            if res.rank_delta is not None:
                delta_str = f" | Динамика: {'▲ +' if res.rank_delta > 0 else '▼ '}{res.rank_delta}"
            msg = (
                f"📈 <b>Позиция Ozon по запросу:</b> <code>{html.escape(query)}</code>\n"
                f"🆔 SKU: <code>{res.sku}</code>\n"
                f"📍 Позиция: {pos_str}{delta_str}\n"
                f"💰 Цена: <b>{res.price:,.0f} ₽</b>"
            )
            if getattr(res, "card_price", None):
                msg += f" (💳 Ozon Карта: <b>{res.card_price:,.0f} ₽</b>)"
            notifier.send_message(msg)

            reports_dir = Path("storage/reports")
            reports_dir.mkdir(parents=True, exist_ok=True)
            out_xlsx = reports_dir / f"ozon_rank_{res.sku}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
            rank_results_to_excel([res], out_xlsx)
            notifier.send_excel(out_xlsx, caption=f"📈 Позиция Ozon: {query[:45]} ({res.sku})")
        except Exception as exc:
            notifier.send_message(f"❌ <b>Ошибка проверки позиции Ozon:</b> <code>{html.escape(str(exc))}</code>")

    def _run_reviews_flow(self, chat_id: str, target: str) -> None:
        notifier = self._new_notifier(chat_id)
        try:
            with self._build_client() as client:
                summary = client.analyze_reviews(target, limit=min(120, self.limit))
            notifier.send_review_summary(summary)
            reports_dir = Path("storage/reports")
            reports_dir.mkdir(parents=True, exist_ok=True)
            out_xlsx = reports_dir / f"ozon_reviews_{summary.sku}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
            reviews_to_excel(summary, out_xlsx)
            notifier.send_excel(
                out_xlsx,
                caption=f"💬 Отзывы Ozon SKU {summary.sku} ({summary.total_analyzed} шт, ⭐ {summary.avg_rating})",
            )
        except Exception as exc:
            notifier.send_message(f"❌ <b>Ошибка анализа отзывов Ozon:</b> <code>{html.escape(str(exc))}</code>")

    def _run_seller_flow(self, chat_id: str, target: str) -> None:
        notifier = self._new_notifier(chat_id)
        try:
            with self._build_client() as client:
                seller = client.get_seller(target)
            msg = (
                f"🏪 <b>Продавец Ozon ID {seller.seller_id}</b>\n\n"
                f"• <b>Магазин:</b> {html.escape(seller.name or '—')}\n"
                f"• <b>Юр. лицо:</b> {html.escape(seller.company_name or '—')}\n"
                f"• <b>ИНН:</b> <code>{html.escape(seller.inn or '—')}</code>\n"
                f"• <b>Рейтинг / Заказы:</b> ⭐ {html.escape(seller.average_rating or '—')} | {html.escape(seller.orders_count or '—')}"
            )
            notifier.send_message(msg)
        except Exception as exc:
            notifier.send_message(f"❌ <b>Ошибка загрузки продавца Ozon:</b> <code>{html.escape(str(exc))}</code>")

    def _busy_reply(self, notifier: TelegramNotifier) -> None:
        bar = render_telegram_progress_bar(self._current_collected, self._current_limit or self.limit)
        notifier.send_message(
            "⏳ <b>Сбор Ozon уже выполняется:</b>\n\n"
            f"🔍 <b>Задача:</b> <code>{html.escape(self._current_task_info[:50])}</code>\n"
            f"📊 <b>Прогресс:</b> {bar}\n\n"
            "💡 <i>Excel-отчёт загрузится автоматически после завершения.</i>",
            disable_web_page_preview=True,
        )

    def _launch_scrape_targets(self, chat_id: str, targets: List[str]) -> None:
        notifier = self._new_notifier(chat_id)
        if len(targets) > 1:
            with self._scrape_lock:
                if self._is_scraping:
                    self._busy_reply(notifier)
                    return
                self._is_scraping = True
                self._current_task_info = f"Пакетный сбор {len(targets)} задач Ozon"
                self._total_links = len(targets)
                self._current_link_idx = 1
                self._current_url = targets[0]
                self._current_collected = 0
                self._current_limit = self.limit

            def _render_dual(
                idx: int,
                target_item: str,
                curr_cnt: int,
                curr_lim: int,
                total_done: int,
                rotations: int,
                finished: bool = False,
            ) -> str:
                total_tasks = max(1, len(targets))
                done_tasks = max(0, idx - 1)
                curr_bar = render_telegram_progress_bar(curr_cnt, max(1, curr_lim))
                overall_bar = render_telegram_progress_bar(
                    total_tasks if finished else done_tasks,
                    total_tasks,
                )
                if finished:
                    return (
                        "🎉 <b>Пакетный сбор Ozon завершён!</b>\n\n"
                        f"📊 <b>Общий прогресс ({total_tasks}/{total_tasks}):</b> {overall_bar}\n"
                        f"📦 <b>Всего собрано:</b> {total_done + curr_cnt} товаров\n"
                        f"🔄 <b>Ротаций IP:</b> {rotations}\n"
                        "📁 <i>Все Excel-файлы (.xlsx) загружены в чат.</i>"
                    )
                return (
                    f"🔵 <b>Пакетный сбор Ozon ({total_tasks} задач)</b>\n\n"
                    f"📊 <b>1. Общий прогресс:</b> {overall_bar}\n\n"
                    f"🔗 <b>2. Текущая цель [{idx}/{total_tasks}]:</b> <code>{html.escape(target_item[:55])}</code>\n"
                    f"{curr_bar}\n\n"
                    f"🧵 <b>Потоков:</b> {self.workers} | 🔄 <b>Ротаций IP:</b> {rotations}"
                )

            init_ids = notifier.send_message_ids(
                _render_dual(1, targets[0], 0, self.limit, 0, 0),
                disable_web_page_preview=True,
            )
            master_mid = init_ids.get(chat_id)

            def _bg_multi() -> None:
                total_collected = 0
                rotations_max = 0
                last_edit = [0.0]
                try:
                    for idx, item in enumerate(targets, 1):
                        self._current_link_idx = idx
                        self._current_url = item
                        self._current_collected = 0
                        self._current_limit = self.limit

                        if master_mid:
                            notifier.edit_message(
                                chat_id,
                                master_mid,
                                _render_dual(idx, item, 0, self.limit, total_collected, rotations_max),
                            )

                        def _on_prog(curr: int, tot: int, rot: int) -> None:
                            nonlocal rotations_max
                            rotations_max = max(rotations_max, rot)
                            now = time.time()
                            if master_mid and now - last_edit[0] >= 1.2:
                                last_edit[0] = now
                                notifier.edit_message(
                                    chat_id,
                                    master_mid,
                                    _render_dual(idx, item, curr, tot or self.limit, total_collected, rotations_max),
                                )

                        res = self._run_search_flow(
                            chat_id,
                            item,
                            on_progress=_on_prog,
                            suppress_individual_progress=True,
                        )
                        cnt, out_xlsx = res if isinstance(res, tuple) else (int(res or 0), None)
                        total_collected += cnt
                        if cnt > 0 and out_xlsx and Path(out_xlsx).exists():
                            notifier.send_excel(
                                out_xlsx,
                                caption=f"📊 [{idx}/{len(targets)}] Ozon Excel: {item[:40]} ({cnt} шт.)",
                                target_chat_ids=[chat_id],
                            )
                        elif cnt == 0:
                            notifier.send_message(
                                f"⚠️ <b>[{idx}/{len(targets)}]</b> По цели <code>{html.escape(item[:45])}</code> товары не найдены."
                            )

                    if master_mid:
                        notifier.edit_message(
                            chat_id,
                            master_mid,
                            _render_dual(len(targets), "", 0, self.limit, total_collected, rotations_max, finished=True),
                        )
                finally:
                    with self._scrape_lock:
                        self._is_scraping = False
                        self._current_task_info = ""
                        self._current_link_idx = 0
                        self._total_links = 0
                        self._current_url = ""
                        self._current_collected = 0
                        self._current_limit = 0

            t = threading.Thread(target=_bg_multi, daemon=True)
            self._last_worker_thread = t
            t.start()
            return

        target = targets[0]
        with self._scrape_lock:
            if self._is_scraping:
                self._busy_reply(notifier)
                return
            self._is_scraping = True
            self._current_task_info = target[:60]
            self._total_links = 1
            self._current_link_idx = 1
            self._current_url = target
            self._current_collected = 0
            self._current_limit = self.limit

        def _bg_single() -> None:
            try:
                self._run_search_flow(chat_id, target, suppress_individual_progress=False)
            finally:
                with self._scrape_lock:
                    self._is_scraping = False
                    self._current_task_info = ""
                    self._current_link_idx = 0
                    self._total_links = 0
                    self._current_url = ""
                    self._current_collected = 0
                    self._current_limit = 0

        t = threading.Thread(target=_bg_single, daemon=True)
        self._last_worker_thread = t
        t.start()

    def handle_callback(self, cb: Dict[str, Any]) -> None:
        """Handle Telegram inline keyboard button callbacks."""
        cb_id = str(cb.get("id", ""))
        msg = cb.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        mid = msg.get("message_id")
        data = str(cb.get("data", "")).strip()
        if not chat_id or not mid:
            return

        notifier = self._new_notifier(chat_id)

        if data in ("menu_main", "menu_status"):
            notifier.answer_callback(cb_id)
            notifier.edit_message(chat_id, mid, self._status_text(), reply_markup=self._main_keyboard())
            return

        if data == "menu_drops":
            notifier.answer_callback(cb_id)
            drops = OzonPriceTracker(self.tracker_db).get_price_drops(limit=15)
            notifier.edit_message(
                chat_id,
                mid,
                TelegramNotifier.format_price_drops(drops),
                reply_markup=self._back_keyboard(),
            )
            return

        if data == "menu_workers":
            notifier.answer_callback(cb_id)
            text = (
                "🧵 <b>Настройка параллельных потоков</b>\n\n"
                f"Текущее значение: <b>{self.workers}</b> ({_mode_description(self.workers)})\n"
                "💡 <i>Команда:</i> <code>/workers 4</code>"
            )
            notifier.edit_message(chat_id, mid, text, reply_markup=self._workers_keyboard())
            return

        if data.startswith("set_workers:"):
            self.workers = min(max(1, int(data.split(":", 1)[1])), 16)
            notifier.answer_callback(cb_id, text=f"✅ Потоков: {self.workers} ({_mode_description(self.workers)})")
            text = f"🧵 <b>Текущие потоки:</b> <b>{self.workers}</b> ({_mode_description(self.workers)})"
            notifier.edit_message(chat_id, mid, text, reply_markup=self._workers_keyboard())
            return

        if data == "menu_limit":
            notifier.answer_callback(cb_id)
            text = (
                "📦 <b>Лимит товаров для поиска Ozon:</b>\n\n"
                f"Текущий лимит: <b>{self.limit} шт</b>\n"
                "💡 <i>Команда:</i> <code>/limit 500</code>"
            )
            notifier.edit_message(chat_id, mid, text, reply_markup=self._limit_keyboard())
            return

        if data.startswith("set_limit:"):
            self.limit = min(max(1, int(data.split(":", 1)[1])), 5000)
            notifier.answer_callback(cb_id, text=f"✅ Лимит: {self.limit} шт")
            text = f"📦 <b>Текущий лимит:</b> <b>{self.limit} шт</b>"
            notifier.edit_message(chat_id, mid, text, reply_markup=self._limit_keyboard())
            return

        if data == "toggle_seller":
            self.with_seller = not self.with_seller
            notifier.answer_callback(cb_id, text=f"Сбор ИНН продавца: {'ВКЛ' if self.with_seller else 'ВЫКЛ'}")
            notifier.edit_message(chat_id, mid, self._status_text(), reply_markup=self._main_keyboard())
            return

        if data == "menu_proxy":
            notifier.answer_callback(cb_id)
            notifier.edit_message(chat_id, mid, self._proxy_info_text(), reply_markup=self._back_keyboard())
            return

        if data == "menu_code":
            notifier.answer_callback(cb_id)
            notifier.edit_message(chat_id, mid, self._code_text(), reply_markup=self._back_keyboard())
            return

        if data == "menu_help":
            notifier.answer_callback(cb_id)
            notifier.edit_message(chat_id, mid, self._help_text(), reply_markup=self._back_keyboard())
            return

        if data == "menu_search":
            notifier.answer_callback(cb_id)
            text = (
                "🔍 <b>Поиск и выгрузка Ozon</b>\n\n"
                "Отправьте название товара, SKU, ссылку на карточку / категорию / магазин Ozon или выберите пример:"
            )
            notifier.edit_message(chat_id, mid, text, reply_markup=self._search_prompt_keyboard())
            return

        if data.startswith("quick_search:"):
            q = data.split(":", 1)[1].strip()
            notifier.answer_callback(cb_id, text=f"🚀 Запуск Ozon: {q}")
            self._launch_scrape_targets(chat_id, [q])

    def handle_update(self, update: Dict[str, Any]) -> None:
        """Process a single incoming Telegram `message` or `channel_post` update."""
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            return
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return

        notifier = self._new_notifier(chat_id)

        if text.startswith(("/start", "/status")):
            notifier.send_message(self._status_text(), reply_markup=self._main_keyboard(), disable_web_page_preview=True)
            return

        if text.startswith("/help"):
            notifier.send_message(self._help_text(), reply_markup=self._back_keyboard(), disable_web_page_preview=True)
            return

        if text.startswith("/code"):
            notifier.send_message(self._code_text(), reply_markup=self._back_keyboard(), disable_web_page_preview=True)
            return

        if text.startswith("/drops"):
            drops = OzonPriceTracker(self.tracker_db).get_price_drops(limit=15)
            notifier.send_price_drops(drops, limit=15)
            return

        if text.startswith("/seller"):
            target = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            if not target:
                notifier.send_message("💡 <b>Использование:</b> <code>/seller 12345</code> или ссылка на магазин/товар Ozon")
                return
            t = threading.Thread(target=self._run_seller_flow, args=(chat_id, target), daemon=True)
            self._last_worker_thread = t
            t.start()
            return

        if text.startswith("/rank"):
            args_str = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            parts = args_str.split(None, 1)
            if len(parts) < 2:
                notifier.send_message("💡 <b>Использование:</b> <code>/rank 1619925434 видеокарта rtx 4060</code>")
                return
            notifier.send_message(f"📈 Проверяю позицию SKU <code>{html.escape(parts[0])}</code> по запросу «{html.escape(parts[1])}»...")
            t = threading.Thread(target=self._run_rank_flow, args=(chat_id, parts[0], parts[1]), daemon=True)
            self._last_worker_thread = t
            t.start()
            return

        if text.startswith("/reviews"):
            target = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            if not target:
                notifier.send_message("💡 <b>Использование:</b> <code>/reviews 1619925434</code> или ссылка на товар Ozon")
                return
            notifier.send_message(f"💬 Анализирую отзывы Ozon для <code>{html.escape(target[:60])}</code>...")
            t = threading.Thread(target=self._run_reviews_flow, args=(chat_id, target), daemon=True)
            self._last_worker_thread = t
            t.start()
            return

        if text.startswith("/proxy"):
            parts = text.split()
            if len(parts) >= 2:
                self.proxy = parts[1].strip()
                if len(parts) >= 3:
                    rot_arg = parts[2].strip()
                    self.proxy_change_url = resolve_proxy_change_url(rot_arg, rot_arg)
                rot_str = "✅ Активна" if self.proxy_change_url else "❌ Не настроена"
                notifier.send_message(
                    "✅ <b>Прокси Ozon обновлён!</b>\n\n"
                    f"🌐 <b>Прокси:</b> <code>{html.escape(mask_proxy_url(self.proxy))}</code>\n"
                    f"🔄 <b>Ротация IP:</b> {rot_str}\n"
                    "🔒 <i>Учётные данные скрыты для безопасности.</i>",
                    reply_markup=self._main_keyboard(),
                )
            else:
                notifier.send_message(self._proxy_info_text(), reply_markup=self._back_keyboard(), disable_web_page_preview=True)
            return

        if text.startswith("/workers"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                self.workers = min(max(1, int(parts[1])), 16)
                notifier.send_message(
                    f"✅ <b>Потоки установлены: {self.workers}</b> ({_mode_description(self.workers)})",
                    reply_markup=self._workers_keyboard(),
                )
            else:
                notifier.send_message(
                    f"🧵 Текущее число потоков: <b>{self.workers}</b> ({_mode_description(self.workers)})",
                    reply_markup=self._workers_keyboard(),
                )
            return

        if text.startswith("/limit"):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                self.limit = min(max(1, int(parts[1])), 5000)
                notifier.send_message(
                    f"✅ Лимит товаров установлен: <b>{self.limit}</b>",
                    reply_markup=self._limit_keyboard(),
                )
            else:
                notifier.send_message(
                    f"📦 Текущий лимит: <b>{self.limit}</b>",
                    reply_markup=self._limit_keyboard(),
                )
            return

        query = text[len("/search"):].strip() if text.startswith("/search") else text
        if not query or query.startswith("/"):
            return

        urls = re.findall(r"https?://[^\s]+", query)
        if urls:
            targets = urls
        else:
            targets = [ln.strip() for ln in query.splitlines() if ln.strip() and not ln.strip().startswith("/")]
        if targets:
            self._launch_scrape_targets(chat_id, targets)

    def _poll_once(self, *, poll_timeout: int = 25) -> List[Dict[str, Any]]:
        """Poll Telegram `getUpdates` once using optional separate `tg_proxy`."""
        url = f"{TELEGRAM_API_BASE}{self.bot_token}/getUpdates"
        params = {"offset": self._offset, "timeout": poll_timeout}
        try:
            if httpx is not None:
                with httpx.Client(proxy=self.tg_proxy, timeout=poll_timeout + 10.0) as client:
                    r = client.get(url, params=params)
            elif requests is not None:
                proxies = {"http": self.tg_proxy, "https": self.tg_proxy} if self.tg_proxy else None
                r = requests.get(url, params=params, proxies=proxies, timeout=poll_timeout + 10.0)
            else:  # pragma: no cover
                return []
            if r.status_code == 200:
                payload = r.json()
                return list(payload.get("result", [])) if isinstance(payload, dict) else []
        except Exception as exc:
            logger.warning(f"OzonTelegramBot polling error: {exc}")
        return []

    def run_polling(
        self,
        poll_interval: float = 1.0,
        *,
        lock: bool = True,
        max_updates: Optional[int] = None,
    ) -> None:
        """Run interactive long-polling loop until `stop()` or `KeyboardInterrupt`."""
        if not self.bot_token:
            raise ValueError("bot_token is required to start OzonTelegramBot")

        guard = BotInstanceLock(self.bot_token, app_tag="ozonsdkpro_bot") if lock else None
        if guard is not None:
            guard.acquire()

        self._stop_event.clear()
        processed = 0
        try:
            self._new_notifier("").set_bot_commands()
            logger.info(
                f"OzonTelegramBot started (workers={self.workers}, limit={self.limit}, "
                f"proxy={mask_proxy_url(self.proxy)}, tg_proxy={mask_proxy_url(self.tg_proxy)})"
            )
            while not self._stop_event.is_set():
                try:
                    updates = self._poll_once(poll_timeout=25)
                    for upd in updates:
                        uid = upd.get("update_id")
                        if isinstance(uid, int):
                            self._offset = max(self._offset, uid + 1)
                        if "callback_query" in upd:
                            self.handle_callback(upd["callback_query"])
                        elif "message" in upd or "channel_post" in upd:
                            self.handle_update(upd)
                        processed += 1
                        if max_updates is not None and processed >= max_updates:
                            return
                except KeyboardInterrupt:
                    logger.info("OzonTelegramBot stopped by KeyboardInterrupt.")
                    break
                if self._stop_event.wait(poll_interval if not updates else 0.05):
                    break
        finally:
            if guard is not None:
                guard.release()
