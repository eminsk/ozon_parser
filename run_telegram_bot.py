#!/usr/bin/env python3
"""
Standalone Interactive Telegram Bot Controller for Ozon SDK Pro (`ozon-sdk-pro`).

Usage:
    set OZON_TG_TOKEN=123456789:AAF...
    set OZON_PROXY=http://user:pass@mproxy.site:port
    set MOBILEPROXY_KEY=your_mobileproxy_key
    uv run python run_telegram_bot.py
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ozon_parser import OzonTelegramBot, mask_proxy_url


def _setup_logging() -> logging.Logger:
    log_dir = Path("storage/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "ozon_bot.log"

    root = logging.getLogger("ozon_parser")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    if not root.handlers:
        root.addHandler(file_handler)
        root.addHandler(stream_handler)
    return logging.getLogger("ozon_parser.bot_runner")


def main() -> int:
    logger = _setup_logging()

    bot_token = os.getenv("OZON_TG_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN").strip()
    if not bot_token or bot_token == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] Укажите токен бота в переменной окружения OZON_TG_TOKEN или в файле run_telegram_bot.py")
        print("    Пример: set OZON_TG_TOKEN=123456789:AAH... && uv run python run_telegram_bot.py")
        return 1

    proxy = os.getenv("OZON_PROXY") or None
    mobileproxy_key = os.getenv("MOBILEPROXY_KEY") or None
    proxy_change_url = os.getenv("OZON_PROXY_CHANGE_URL") or None
    tg_proxy = os.getenv("OZON_TG_PROXY") or None
    channel_id = os.getenv("OZON_TG_CHANNEL") or None

    print("=" * 64)
    print("  Ozon SDK Pro — Interactive Telegram Bot Controller")
    print("=" * 64)
    print(f"[*] Ozon Proxy: {mask_proxy_url(proxy)}")
    print(f"[*] TG Proxy:   {mask_proxy_url(tg_proxy)}")
    print("[*] Logs:       storage/logs/ozon_bot.log (10MB x 5 rotation)")
    print("[*] Starting polling loop... Отправьте /start вашему боту в Telegram!")

    bot = OzonTelegramBot(
        bot_token=bot_token,
        proxy=proxy,
        proxy_change_url=proxy_change_url,
        mobileproxy_key=mobileproxy_key,
        tg_proxy=tg_proxy,
        channel_id=channel_id,
        workers=2,
        limit=50,
    )
    try:
        bot.run_polling()
    finally:
        logger.info("OzonTelegramBot stopped cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
