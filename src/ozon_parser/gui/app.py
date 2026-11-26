"""
Ozon SDK Pro — Modern Dark 7-Tab Desktop GUI Application (`ozon-gui`).

Modular, thread-safe CustomTkinter interface (`uv add "ozon-sdk-pro[gui]"`) supporting:
- Parser tab: URL/SKU/category/seller/search targets, price/discount/rating filters, seller INN, 24/7 loop, optional [browser] fallback
- Catalog feed: live cards with regular price, Ozon Card checkout price, drops, seller INN & Excel/CSV/JSON export
- Search Rank Tracker tab: batch `SKU : query` checks across pages with SQLite deltas & .xlsx
- Smart Review Analyzer tab: buyer reviews + rating breakdown + pros/cons (Offline NLP, Free g4f, Local Ollama, Paid APIs + live ⚡ AI Check + Excel/TG export)
- Proxy & Session tab: HTTP/SOCKS5 proxy, rotation URL, cookies, optional [browser] cookie capture, API ping
- Decoupled Telegram alerts & live Logs tab
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from tkinter import filedialog
except ImportError:  # pragma: no cover
    filedialog = None  # type: ignore[assignment]

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover
    ctk = None

from ozon_parser import __version__
from ozon_parser.ai import AI_PROVIDER_PRESETS, test_ai_provider
from ozon_parser.browser import harvest_ozon_cookies, is_browser_available
from ozon_parser.client import OzonClient, filter_products
from ozon_parser.config import (
    DONATE_TRONSCAN_URL,
    DONATE_USDT_TRC20,
    ISSUES_URL,
    MOBILEPROXY_FREE_TRIAL_URL,
    MOBILEPROXY_REFERRAL_URL,
    REPO_URL,
    SORT_OPTIONS,
    TELEGRAM_CHANNEL_URL,
    resolve_proxy_change_url,
)
from ozon_parser.exceptions import OzonAntiBotError
from ozon_parser.export import rank_results_to_excel, reviews_to_excel, to_csv, to_excel, to_json
from ozon_parser.http import CURL_CFFI_AVAILABLE
from ozon_parser.models import OzonProduct, OzonReviewSummary
from ozon_parser.rank import OzonRankTracker, RankResult
from ozon_parser.telegram import TelegramNotifier

logger = logging.getLogger("ozon_parser.gui")


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent.parent


def _resolve_asset(filename: str) -> Optional[Path]:
    """Locate a bundled GUI asset cleanly across PyInstaller, wheel install, and source tree."""
    candidates: List[Path] = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(Path(getattr(sys, "_MEIPASS")) / "assets" / filename)
    candidates.extend([
        _get_base_dir() / "assets" / filename,
        Path(__file__).resolve().parent / "assets" / filename,
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


class OzonGUIConfig:
    """Persistent GUI settings stored in `storage/gui_config.json`."""

    CONFIG_PATH = _get_base_dir() / "storage" / "gui_config.json"

    def __init__(self) -> None:
        self.targets: List[str] = [
            "https://www.ozon.ru/product/1619925434/",
            "беспроводные наушники",
        ]
        self.max_pages: int = 2
        self.limit: int = 50
        self.interval_sec: int = 60
        self.min_price: str = ""
        self.max_price: str = ""
        self.min_discount: str = ""
        self.min_rating: str = ""
        self.white_keywords: str = ""
        self.black_keywords: str = ""
        self.with_seller: bool = True
        self.continuous_monitor: bool = False
        self.use_browser_fallback: bool = False
        self.proxy_string: str = ""
        self.proxy_change_url: str = ""
        self.cookies: str = ""
        self.user_agent: str = ""
        self.tg_token: str = ""
        self.tg_chat_id: str = ""
        self.tg_proxy: str = ""
        self.tg_notify: bool = False
        self.rank_pairs: List[str] = [
            "1619925434 : видеокарта rtx 4060",
        ]
        self.rank_pages: int = 3
        self.review_target: str = "1619925434"
        self.review_pages: int = 3
        self.review_sort: str = "published_at_desc"
        self.review_ai_mode: str = "auto"
        self.review_ai_provider: str = "Auto Free Pool (g4f)"
        self.review_ai_model: str = ""
        self.review_ai_key: str = ""
        self.review_ai_url: str = ""

    @classmethod
    def load(cls) -> "OzonGUIConfig":
        cfg = cls()
        if cls.CONFIG_PATH.exists():
            try:
                data = json.loads(cls.CONFIG_PATH.read_text(encoding="utf-8"))
                for key, val in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, val)
            except Exception as exc:
                logger.warning(f"Could not load gui_config.json: {exc}")
        return cfg

    def save(self) -> None:
        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.CONFIG_PATH.write_text(
                json.dumps(self.__dict__, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Could not save gui_config.json: {exc}")


class _QueueLogHandler(logging.Handler):
    """Thread-safe log forwarding into the GUI logs panel."""

    def __init__(self, target_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.target_queue = target_queue

    def emit(self, record: logging.LogRecord) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.target_queue.put(f"[{ts}] [{record.levelname}] {record.getMessage()}")


class OzonGUIApp:
    """Modern dark-themed Ozon SDK Pro Desktop App built on CustomTkinter."""

    def __init__(self) -> None:
        if ctk is None:  # pragma: no cover
            raise RuntimeError('customtkinter is required for GUI. Run: uv add "ozon-sdk-pro[gui]"')

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Ozon SDK Pro — Парсер, Отзывы, AI & Мониторинг Ozon")
        self.root.geometry("1180x800")
        self.root.minsize(980, 680)

        if sys.platform.startswith("win"):
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    f"eminsk.ozonsdkpro.desktop.{__version__}"
                )
            except Exception:
                pass

        self._app_photo_icon = None
        ico_path = _resolve_asset("icon.ico")
        if ico_path:
            try:
                self.root.iconbitmap(str(ico_path))
            except Exception:
                pass
        png_path = _resolve_asset("icon.png")
        if png_path:
            try:
                from PIL import Image, ImageTk

                self._app_photo_icon = ImageTk.PhotoImage(Image.open(png_path))
                self.root.iconphoto(True, self._app_photo_icon)
            except Exception:
                pass

        self.config = OzonGUIConfig.load()
        self.worker_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.is_running = False

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.item_queue: queue.Queue[OzonProduct] = queue.Queue()
        self.status_queue: queue.Queue[tuple[str, str, str]] = queue.Queue()

        self.seen_ids: Set[int] = set()
        self.discovered_items: List[OzonProduct] = []
        self.rank_results: List[RankResult] = []
        self.last_review_summary: Optional[OzonReviewSummary] = None
        self.stats_found = 0
        self.stats_discounts = 0
        self.stats_checks = 0
        self.stats_tg = 0

        self._attach_logger()
        self._build_ui()
        self._load_config_into_ui()
        self._start_pollers()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _attach_logger(self) -> None:
        handler = _QueueLogHandler(self.log_queue)
        root_logger = logging.getLogger("ozon_parser")
        root_logger.setLevel(logging.INFO)
        if not any(isinstance(h, _QueueLogHandler) for h in root_logger.handlers):
            root_logger.addHandler(handler)

    def _make_link_button(self, parent: Any, text: str, url: str, **kwargs: Any) -> Any:
        return ctk.CTkButton(parent, text=text, command=lambda: webbrowser.open(url), **kwargs)

    def _make_labeled_entry(
        self,
        parent: Any,
        label: str,
        placeholder: str,
        width: Optional[int] = None,
        expand: bool = False,
    ) -> Any:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(side="left", fill="x" if expand else "none", expand=expand, padx=4)
        ctk.CTkLabel(
            box, text=label, font=ctk.CTkFont(size=11), text_color="#94a3b8"
        ).pack(anchor="w", padx=2, pady=(0, 2))
        kw: Dict[str, Any] = {"placeholder_text": placeholder}
        if width is not None:
            kw["width"] = width
        entry = ctk.CTkEntry(box, **kw)
        entry.pack(fill="x" if expand else "none")
        return entry

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self.root, corner_radius=0, height=64, fg_color="#0b1530")
        header.pack(fill="x", side="top")

        self.header_logo = None
        logo_path = _resolve_asset("icon.png")
        if logo_path:
            try:
                from PIL import Image

                self.header_logo = ctk.CTkImage(
                    light_image=Image.open(logo_path),
                    dark_image=Image.open(logo_path),
                    size=(38, 38),
                )
            except Exception:
                pass

        if self.header_logo:
            ctk.CTkLabel(header, image=self.header_logo, text="").pack(side="left", padx=(16, 8), pady=12)

        ctk.CTkLabel(
            header,
            text="OZON SDK PRO",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#38bdf8",
        ).pack(side="left", padx=(0 if self.header_logo else 20, 8), pady=14)

        tls_label = "Chrome TLS (curl_cffi)" if CURL_CFFI_AVAILABLE else "HTTP/2 Client"
        browser_label = " + Browser Ready" if is_browser_available() else ""
        ctk.CTkLabel(
            header,
            text=f"v{__version__} • {tls_label}{browser_label}",
            font=ctk.CTkFont(size=11),
            text_color="#cbd5e1",
            fg_color="#1e3a8a",
            corner_radius=6,
            padx=10,
            pady=3,
        ).pack(side="left", padx=6, pady=18)

        self._make_link_button(
            header,
            text="🐛 GitHub",
            url=ISSUES_URL,
            width=110,
            height=28,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="right", padx=(6, 16), pady=16)

        self._make_link_button(
            header,
            text="✈️ Telegram",
            url=TELEGRAM_CHANNEL_URL,
            width=105,
            height=28,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="right", padx=(6, 0), pady=16)

        ctk.CTkButton(
            header,
            text="☕ Донат",
            width=95,
            height=28,
            fg_color="#ca8a04",
            hover_color="#a16207",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._show_donate_dialog,
        ).pack(side="right", padx=(6, 0), pady=16)

        self.status_pill = ctk.CTkLabel(
            header,
            text="● ГОТОВ К РАБОТЕ",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#22c55e",
            fg_color="#064e3b",
            corner_radius=12,
            padx=14,
            pady=4,
        )
        self.status_pill.pack(side="right", padx=(10, 6), pady=15)

        stats = ctk.CTkFrame(self.root, height=34, fg_color="#0f172a", corner_radius=0)
        stats.pack(fill="x", side="top")

        self.lbl_stats_found = ctk.CTkLabel(stats, text="📦 Найдено товаров: 0", text_color="#cbd5e1")
        self.lbl_stats_found.pack(side="left", padx=20, pady=4)
        self.lbl_stats_discounts = ctk.CTkLabel(stats, text="📉 Со скидкой / падением: 0", text_color="#cbd5e1")
        self.lbl_stats_discounts.pack(side="left", padx=20, pady=4)
        self.lbl_stats_checks = ctk.CTkLabel(stats, text="⏱️ Запусков: 0", text_color="#cbd5e1")
        self.lbl_stats_checks.pack(side="left", padx=20, pady=4)
        self.lbl_stats_tg = ctk.CTkLabel(stats, text="✈️ Отправлено в TG: 0", text_color="#cbd5e1")
        self.lbl_stats_tg.pack(side="left", padx=20, pady=4)

        self.tabview = ctk.CTkTabview(self.root, corner_radius=10, fg_color="#1e293b")
        self.tabview.pack(fill="both", expand=True, padx=16, pady=12)

        self.tab_parse = self.tabview.add("🔍 Парсер")
        self.tab_feed = self.tabview.add("📦 Каталог товаров")
        self.tab_rank = self.tabview.add("📈 Позиции (Rank)")
        self.tab_reviews = self.tabview.add("💬 Умные отзывы + AI")
        self.tab_proxy = self.tabview.add("🌐 Прокси и Сессия")
        self.tab_tg = self.tabview.add("✈️ Telegram")
        self.tab_logs = self.tabview.add("📋 Журнал")

        self._build_parse_tab()
        self._build_feed_tab()
        self._build_rank_tab()
        self._build_reviews_tab()
        self._build_proxy_tab()
        self._build_tg_tab()
        self._build_logs_tab()

    def _build_parse_tab(self) -> None:
        left = ctk.CTkFrame(self.tab_parse, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=10, pady=10)

        ctk.CTkLabel(
            left,
            text="Цели Ozon (ссылка на товар, /category/..., /seller/..., артикул SKU или поисковый запрос):",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=4, pady=(0, 4))

        self.txt_targets = ctk.CTkTextbox(left, height=195, font=ctk.CTkFont(size=12))
        self.txt_targets.pack(fill="x", padx=4, pady=(0, 10))

        filter_card = ctk.CTkFrame(left, fg_color="#0f172a", corner_radius=8)
        filter_card.pack(fill="x", padx=4, pady=4)

        ctk.CTkLabel(
            filter_card, text="Фильтры цен, скидок и ключевых слов:", font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(8, 4))

        row1 = ctk.CTkFrame(filter_card, fg_color="transparent")
        row1.pack(fill="x", padx=8, pady=4)
        self.entry_min_price = self._make_labeled_entry(row1, "Мин. цена (₽)", "0", width=120)
        self.entry_max_price = self._make_labeled_entry(row1, "Макс. цена (₽)", "100000", width=120)
        self.entry_min_discount = self._make_labeled_entry(row1, "Мин. скидка (%)", "0", width=120)
        self.entry_min_rating = self._make_labeled_entry(row1, "Мин. рейтинг", "4.5", width=120)

        row2 = ctk.CTkFrame(filter_card, fg_color="transparent")
        row2.pack(fill="x", padx=8, pady=(4, 10))
        self.entry_white = self._make_labeled_entry(row2, "Белый список слов", "rtx, ssd", expand=True)
        self.entry_black = self._make_labeled_entry(row2, "Минус-слова", "уценка, б/у", expand=True)

        right = ctk.CTkFrame(self.tab_parse, width=305, fg_color="#0f172a", corner_radius=8)
        right.pack(side="right", fill="y", padx=10, pady=10)
        right.pack_propagate(False)

        ctk.CTkLabel(right, text="Параметры сбора", font=ctk.CTkFont(size=14, weight="bold")).pack(
            anchor="w", padx=14, pady=(14, 10)
        )

        for lbl, attr in [
            ("Макс. страниц:", "entry_pages"),
            ("Лимит товаров:", "entry_limit"),
            ("Интервал монитор. (сек):", "entry_interval"),
        ]:
            row = ctk.CTkFrame(right, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)
            ctk.CTkLabel(row, text=lbl, font=ctk.CTkFont(size=12)).pack(side="left")
            entry = ctk.CTkEntry(row, width=75)
            entry.pack(side="right")
            setattr(self, attr, entry)

        self.var_with_seller = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(right, text="Догружать продавца + ИНН", variable=self.var_with_seller).pack(
            anchor="w", padx=14, pady=(10, 4)
        )

        self.var_browser_fallback = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(right, text="Chrome fallback ([browser])", variable=self.var_browser_fallback).pack(
            anchor="w", padx=14, pady=4
        )

        self.var_continuous = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(right, text="Цикличный мониторинг 24/7", variable=self.var_continuous).pack(
            anchor="w", padx=14, pady=4
        )

        self.btn_start = ctk.CTkButton(
            right,
            text="▶ ЗАПУСТИТЬ ПАРСЕР",
            height=42,
            fg_color="#005bff",
            hover_color="#0044cc",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._start_scrape,
        )
        self.btn_start.pack(fill="x", padx=14, pady=(18, 6))

        self.btn_stop = ctk.CTkButton(
            right,
            text="⏹ ОСТАНОВИТЬ",
            height=36,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            state="disabled",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._stop_scrape,
        )
        self.btn_stop.pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(
            right,
            text="💡 Совет: для обхода JS-проверки Ozon\nвставьте cookies во вкладке «Прокси»\nили включите Chrome fallback ([browser]).",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 6))

    def _build_feed_tab(self) -> None:
        bar = ctk.CTkFrame(self.tab_feed, fg_color="#0f172a", height=46, corner_radius=8)
        bar.pack(fill="x", padx=10, pady=(10, 6))

        ctk.CTkButton(
            bar, text="📊 Excel (.xlsx)", width=155, fg_color="#16a34a", hover_color="#15803d",
            font=ctk.CTkFont(size=12, weight="bold"), command=self._export_excel
        ).pack(side="left", padx=8, pady=8)

        ctk.CTkButton(
            bar, text="📄 CSV", width=110, fg_color="#2563eb", hover_color="#1d4ed8", command=self._export_csv
        ).pack(side="left", padx=4, pady=8)

        ctk.CTkButton(
            bar, text="{} JSON", width=90, fg_color="#475569", hover_color="#334155", command=self._export_json
        ).pack(side="left", padx=4, pady=8)

        ctk.CTkButton(
            bar, text="🗑 Очистить", width=95, fg_color="#7f1d1d", hover_color="#991b1b", command=self._clear_feed
        ).pack(side="right", padx=8, pady=8)

        self.feed_scroll = ctk.CTkScrollableFrame(self.tab_feed, fg_color="#0f172a", corner_radius=8)
        self.feed_scroll.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        self.lbl_empty_feed = ctk.CTkLabel(
            self.feed_scroll,
            text="Собранные товары Ozon появятся здесь. Введите SKU или ссылки во вкладке «Парсер».",
            text_color="#94a3b8",
            font=ctk.CTkFont(size=13),
        )
        self.lbl_empty_feed.pack(pady=40)

    def _build_rank_tab(self) -> None:
        left = ctk.CTkFrame(self.tab_rank, width=370, fg_color="#0f172a", corner_radius=8)
        left.pack(side="left", fill="y", padx=(10, 6), pady=10)
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="Позиции в поиске Ozon (SKU : запрос):", font=ctk.CTkFont(size=13, weight="bold")
        ).pack(anchor="w", padx=12, pady=(12, 4))

        self.txt_rank_pairs = ctk.CTkTextbox(left, height=220, font=ctk.CTkFont(size=12))
        self.txt_rank_pairs.pack(fill="x", padx=12, pady=(0, 10))

        row_opts = ctk.CTkFrame(left, fg_color="transparent")
        row_opts.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row_opts, text="Глубина (страниц):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.entry_rank_pages = ctk.CTkEntry(row_opts, width=65)
        self.entry_rank_pages.pack(side="right")

        row_sort = ctk.CTkFrame(left, fg_color="transparent")
        row_sort.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(row_sort, text="Сортировка:", font=ctk.CTkFont(size=12)).pack(side="left")
        self.opt_rank_sort = ctk.CTkOptionMenu(row_sort, values=list(SORT_OPTIONS.keys()), width=150)
        self.opt_rank_sort.pack(side="right")

        self.btn_rank_check = ctk.CTkButton(
            left, text="📈 Проверить позиции", height=40, fg_color="#005bff", hover_color="#0044cc",
            font=ctk.CTkFont(size=13, weight="bold"), command=self._run_rank_check
        )
        self.btn_rank_check.pack(fill="x", padx=12, pady=(14, 6))

        ctk.CTkButton(
            left, text="📊 Экспорт позиций (.xlsx)", height=34, fg_color="#16a34a", hover_color="#15803d",
            command=self._export_rank_excel
        ).pack(fill="x", padx=12, pady=4)

        self.rank_scroll = ctk.CTkScrollableFrame(self.tab_rank, fg_color="#0f172a", corner_radius=8)
        self.rank_scroll.pack(side="right", fill="both", expand=True, padx=(6, 10), pady=10)
        self.lbl_rank_placeholder = ctk.CTkLabel(
            self.rank_scroll, text="Результаты позиций по запросам появятся здесь.", text_color="#94a3b8"
        )
        self.lbl_rank_placeholder.pack(pady=40)

    def _build_reviews_tab(self) -> None:
        top = ctk.CTkFrame(self.tab_reviews, fg_color="#0f172a", corner_radius=8)
        top.pack(fill="x", padx=10, pady=(10, 6))

        row1 = ctk.CTkFrame(top, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(10, 6))

        self.entry_review_target = self._make_labeled_entry(
            row1, "Ссылка Ozon или артикул (SKU)", "1619925434 или https://www.ozon.ru/product/...", expand=True
        )
        self.entry_review_pages = self._make_labeled_entry(row1, "Страниц", "3", width=70)

        sort_box = ctk.CTkFrame(row1, fg_color="transparent")
        sort_box.pack(side="left", padx=4)
        ctk.CTkLabel(sort_box, text="Сортировка", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w")
        self.opt_review_sort = ctk.CTkOptionMenu(
            sort_box, values=["published_at_desc", "score_desc", "score_asc", "helpful"], width=155
        )
        self.opt_review_sort.pack()

        self.btn_review_run = ctk.CTkButton(
            row1, text="🧠 Анализировать отзывы", width=195, height=34,
            fg_color="#005bff", hover_color="#0044cc", font=ctk.CTkFont(size=13, weight="bold"),
            command=self._run_review_analysis
        )
        self.btn_review_run.pack(side="right", padx=(6, 0), pady=(14, 0))

        row2 = ctk.CTkFrame(top, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 6))

        mode_box = ctk.CTkFrame(row2, fg_color="transparent")
        mode_box.pack(side="left", padx=4)
        ctk.CTkLabel(mode_box, text="Режим AI", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w")
        self._ai_mode_labels = {
            "Авто (Ключ → Free → Оффлайн)": "auto",
            "Бесплатно (g4f)": "free",
            "Платный API (Key)": "paid",
            "Локальный (Ollama)": "local",
            "Оффлайн (Без AI)": "offline",
        }
        self._ai_mode_by_code = {v: k for k, v in self._ai_mode_labels.items()}
        self.opt_review_ai_mode = ctk.CTkOptionMenu(
            mode_box, values=list(self._ai_mode_labels.keys()), width=215, command=self._on_ai_mode_selected
        )
        self.opt_review_ai_mode.pack()

        prov_box = ctk.CTkFrame(row2, fg_color="transparent")
        prov_box.pack(side="left", padx=4)
        ctk.CTkLabel(prov_box, text="Провайдер (Free / Paid)", font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(anchor="w")
        self._ai_provider_map = {
            "Auto Free Pool (g4f)": "g4f",
            "g4f: Yqcloud": "Yqcloud",
            "g4f: Airforce": "Airforce",
            "g4f: LLM7": "LLM7",
            "g4f: GLM": "GLM",
            "g4f: DeepInfra": "DeepInfra",
            "g4f: Cerebras": "Cerebras",
            "g4f: Pollinations": "Pollinations",
            "OpenAI (Paid)": "openai",
            "DeepSeek (Paid)": "deepseek",
            "OpenRouter (Free + Paid)": "openrouter",
            "ProxyAPI (RU Paid)": "proxyapi",
            "Groq (Free/Paid)": "groq",
            "Google Gemini": "gemini",
            "Ollama (Local Free)": "ollama",
            "LM Studio (Local Free)": "lmstudio",
        }
        self.opt_review_ai_provider = ctk.CTkOptionMenu(
            prov_box, values=list(self._ai_provider_map.keys()), width=205, command=self._on_ai_provider_selected
        )
        self.opt_review_ai_provider.pack()

        self.entry_review_ai_model = self._make_labeled_entry(
            row2, "Модель (опц. / авто)", "авто по провайдеру", expand=True
        )

        self.btn_review_ai_test = ctk.CTkButton(
            row2, text="⚡ Проверить AI", width=135, height=30,
            fg_color="#0284c7", hover_color="#0369a1", command=self._test_review_ai
        )
        self.btn_review_ai_test.pack(side="right", padx=(6, 0), pady=(14, 0))

        row3 = ctk.CTkFrame(top, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 6))
        self.entry_review_ai_key = self._make_labeled_entry(
            row3, "API Key (для платных API — для Free g4f/Ollama пусто)", "sk-... или пусто", expand=True
        )
        self.entry_review_ai_url = self._make_labeled_entry(
            row3, "API Base URL", "https://api.openai.com/v1 или http://localhost:11434/v1", width=270
        )
        ctk.CTkButton(
            row3, text="📊 Excel", width=90, height=30, fg_color="#16a34a", hover_color="#15803d",
            command=self._export_reviews_excel
        ).pack(side="right", padx=(6, 0), pady=(14, 0))
        ctk.CTkButton(
            row3, text="✈ В TG", width=80, height=30, fg_color="#0284c7", hover_color="#0369a1",
            command=self._send_reviews_tg
        ).pack(side="right", padx=(6, 0), pady=(14, 0))

        self.lbl_review_ai_status = ctk.CTkLabel(
            top,
            text="💡 Бесплатные модели g4f ([ai]), локальный Ollama и платные API (OpenAI, DeepSeek, OpenRouter, ProxyAPI, Groq).",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        )
        self.lbl_review_ai_status.pack(anchor="w", padx=16, pady=(0, 8))

        self.lbl_review_kpi = ctk.CTkLabel(
            self.tab_reviews,
            text="Введите SKU/ссылку Ozon и нажмите «Анализировать отзывы»",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#cbd5e1",
            anchor="w",
            justify="left",
            wraplength=1100,
        )
        self.lbl_review_kpi.pack(anchor="w", fill="x", padx=14, pady=(2, 4))

        split = ctk.CTkFrame(self.tab_reviews, fg_color="transparent", height=180)
        split.pack(fill="x", padx=10, pady=4)
        split.pack_propagate(False)

        pros_card = ctk.CTkFrame(split, fg_color="#052e16", corner_radius=8)
        pros_card.pack(side="left", fill="both", expand=True, padx=(0, 5))
        ctk.CTkLabel(
            pros_card, text="✅ Главные плюсы", font=ctk.CTkFont(size=13, weight="bold"), text_color="#4ade80"
        ).pack(anchor="w", padx=12, pady=(8, 4))
        self.txt_review_pros = ctk.CTkTextbox(pros_card, fg_color="#052e16", font=ctk.CTkFont(size=12))
        self.txt_review_pros.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        cons_card = ctk.CTkFrame(split, fg_color="#450a0a", corner_radius=8)
        cons_card.pack(side="right", fill="both", expand=True, padx=(5, 0))
        ctk.CTkLabel(
            cons_card, text="❌ Главные минусы", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f87171"
        ).pack(anchor="w", padx=12, pady=(8, 4))
        self.txt_review_cons = ctk.CTkTextbox(cons_card, fg_color="#450a0a", font=ctk.CTkFont(size=12))
        self.txt_review_cons.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.reviews_scroll = ctk.CTkScrollableFrame(self.tab_reviews, fg_color="#0f172a", corner_radius=8)
        self.reviews_scroll.pack(fill="both", expand=True, padx=10, pady=(4, 10))

    def _build_proxy_tab(self) -> None:
        frame = ctk.CTkFrame(self.tab_proxy, fg_color="#0f172a", corner_radius=8)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame, text="Настройка прокси и браузерной сессии Ozon:", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(14, 4))

        ctk.CTkLabel(
            frame,
            text="Поддерживаются: Серверные IPv4/SOCKS5, AstroProxy, Asocks, MobileProxy.rent (4G/LTE модемы с ротацией) или прямой режим.",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        promo_frame = ctk.CTkFrame(frame, fg_color="#1e293b", corner_radius=8)
        promo_frame.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            promo_frame,
            text="🌐 Нужен надёжный мобильный 4G прокси с ротацией IP без блокировок Ozon?",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f8fafc",
        ).pack(side="left", padx=12, pady=8)
        self._make_link_button(
            promo_frame,
            text="MobileProxy.rent ↗",
            url=MOBILEPROXY_REFERRAL_URL,
            width=155,
            height=28,
            fg_color="#e11d48",
            hover_color="#be123c",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="right", padx=(6, 12), pady=8)
        self._make_link_button(
            promo_frame,
            text="🎁 Тест 3ч бесплатно",
            url=MOBILEPROXY_FREE_TRIAL_URL,
            width=150,
            height=28,
            fg_color="#0f766e",
            hover_color="#115e59",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="right", padx=(6, 0), pady=8)

        for label, attr, ph in [
            ("HTTP / SOCKS5 прокси:", "entry_proxy", "http://user:pass@ip:port или socks5://..."),
            ("URL или ключ MobileProxy:", "entry_proxy_rotate", "https://changeip.mobileproxy.space/?proxy_key=... или сам proxy_key"),
            ("Cookie строка (опц.):", "entry_cookies", "__cf_bm=...; ..."),
            ("User-Agent (опц.):", "entry_ua", "Mozilla/5.0 ..."),
        ]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(row, text=label, width=210, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, placeholder_text=ph, width=480)
            entry.pack(side="left", padx=6)
            setattr(self, attr, entry)

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkButton(
            btn_row, text="🔌 Проверить Ozon API (Ping)", width=230, fg_color="#0284c7", hover_color="#0369a1",
            command=self._test_proxy_connectivity
        ).pack(side="left")

        ctk.CTkButton(
            btn_row, text="🍪 Захватить Cookies (Chrome [browser])", width=265, fg_color="#7c3aed", hover_color="#6d28d9",
            command=self._capture_cookies_browser
        ).pack(side="left", padx=(10, 0))

        self.lbl_proxy_status = ctk.CTkLabel(btn_row, text="", text_color="#cbd5e1", font=ctk.CTkFont(size=12))
        self.lbl_proxy_status.pack(side="left", padx=14)

    def _build_tg_tab(self) -> None:
        frame = ctk.CTkFrame(self.tab_tg, fg_color="#0f172a", corner_radius=8)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame, text="Уведомления в Telegram (отдельный SOCKS5/HTTP прокси):", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(14, 10))

        for label, attr, ph in [
            ("Bot Token:", "entry_tg_token", "123456789:AAF..."),
            ("Chat / Channel ID:", "entry_tg_chat", "@channel или -100..."),
            ("Telegram Proxy (опц.):", "entry_tg_proxy", "socks5://127.0.0.1:1080"),
        ]:
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(row, text=label, width=200, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(row, placeholder_text=ph, width=440)
            entry.pack(side="left", padx=6)
            setattr(self, attr, entry)

        self.var_tg_notify = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(frame, text="Отправлять найденные товары в Telegram", variable=self.var_tg_notify).pack(
            anchor="w", padx=16, pady=12
        )
        ctk.CTkButton(
            frame, text="✈ Тест Telegram", width=200, fg_color="#0284c7", command=self._test_telegram
        ).pack(anchor="w", padx=16, pady=6)

    def _build_logs_tab(self) -> None:
        self.txt_logs = ctk.CTkTextbox(self.tab_logs, font=ctk.CTkFont(family="Consolas", size=12), fg_color="#0f172a")
        self.txt_logs.pack(fill="both", expand=True, padx=10, pady=10)

    def _load_config_into_ui(self) -> None:
        cfg = self.config
        self.txt_targets.delete("1.0", "end")
        self.txt_targets.insert("1.0", "\n".join(cfg.targets))
        self.entry_min_price.insert(0, cfg.min_price)
        self.entry_max_price.insert(0, cfg.max_price)
        self.entry_min_discount.insert(0, cfg.min_discount)
        self.entry_min_rating.insert(0, cfg.min_rating)
        self.entry_white.insert(0, cfg.white_keywords)
        self.entry_black.insert(0, cfg.black_keywords)
        self.entry_pages.insert(0, str(cfg.max_pages))
        self.entry_limit.insert(0, str(cfg.limit))
        self.entry_interval.insert(0, str(cfg.interval_sec))
        self.var_with_seller.set(cfg.with_seller)
        self.var_browser_fallback.set(cfg.use_browser_fallback)
        self.var_continuous.set(cfg.continuous_monitor)

        self.entry_proxy.insert(0, cfg.proxy_string)
        self.entry_proxy_rotate.insert(0, cfg.proxy_change_url)
        self.entry_cookies.insert(0, cfg.cookies)
        self.entry_ua.insert(0, cfg.user_agent)

        self.entry_tg_token.insert(0, cfg.tg_token)
        self.entry_tg_chat.insert(0, cfg.tg_chat_id)
        self.entry_tg_proxy.insert(0, cfg.tg_proxy)
        self.var_tg_notify.set(cfg.tg_notify)

        self.txt_rank_pairs.delete("1.0", "end")
        self.txt_rank_pairs.insert("1.0", "\n".join(cfg.rank_pairs))
        self.entry_rank_pages.insert(0, str(cfg.rank_pages))
        self.entry_review_target.insert(0, cfg.review_target)
        self.entry_review_pages.insert(0, str(cfg.review_pages))
        self.opt_review_sort.set(cfg.review_sort)
        self.opt_review_ai_mode.set(self._ai_mode_by_code.get(cfg.review_ai_mode, "Авто (Ключ → Free → Оффлайн)"))
        if cfg.review_ai_provider in self._ai_provider_map:
            self.opt_review_ai_provider.set(cfg.review_ai_provider)
        self.entry_review_ai_model.insert(0, cfg.review_ai_model)
        self.entry_review_ai_key.insert(0, cfg.review_ai_key)
        self.entry_review_ai_url.insert(0, cfg.review_ai_url)

    def _save_ui_to_config(self) -> OzonGUIConfig:
        cfg = self.config
        cfg.targets = [line.strip() for line in self.txt_targets.get("1.0", "end").splitlines() if line.strip()]
        cfg.min_price = self.entry_min_price.get().strip()
        cfg.max_price = self.entry_max_price.get().strip()
        cfg.min_discount = self.entry_min_discount.get().strip()
        cfg.min_rating = self.entry_min_rating.get().strip()
        cfg.white_keywords = self.entry_white.get().strip()
        cfg.black_keywords = self.entry_black.get().strip()
        cfg.max_pages = int(self.entry_pages.get().strip() or 2)
        cfg.limit = int(self.entry_limit.get().strip() or 50)
        cfg.interval_sec = int(self.entry_interval.get().strip() or 60)
        cfg.with_seller = bool(self.var_with_seller.get())
        cfg.use_browser_fallback = bool(self.var_browser_fallback.get())
        cfg.continuous_monitor = bool(self.var_continuous.get())
        cfg.proxy_string = self.entry_proxy.get().strip()
        cfg.proxy_change_url = self.entry_proxy_rotate.get().strip()
        cfg.cookies = self.entry_cookies.get().strip()
        cfg.user_agent = self.entry_ua.get().strip()
        cfg.tg_token = self.entry_tg_token.get().strip()
        cfg.tg_chat_id = self.entry_tg_chat.get().strip()
        cfg.tg_proxy = self.entry_tg_proxy.get().strip()
        cfg.tg_notify = bool(self.var_tg_notify.get())
        cfg.rank_pairs = [line.strip() for line in self.txt_rank_pairs.get("1.0", "end").splitlines() if line.strip()]
        cfg.rank_pages = int(self.entry_rank_pages.get().strip() or 3)
        cfg.review_target = self.entry_review_target.get().strip()
        cfg.review_pages = int(self.entry_review_pages.get().strip() or 3)
        cfg.review_sort = self.opt_review_sort.get()
        cfg.review_ai_mode = self._ai_mode_labels.get(self.opt_review_ai_mode.get(), "auto")
        cfg.review_ai_provider = self.opt_review_ai_provider.get()
        cfg.review_ai_model = self.entry_review_ai_model.get().strip()
        cfg.review_ai_key = self.entry_review_ai_key.get().strip()
        cfg.review_ai_url = self.entry_review_ai_url.get().strip()
        cfg.save()
        return cfg

    def _log(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{ts}] {text}")

    def _start_pollers(self) -> None:
        self._poll_queues()

    def _poll_queues(self) -> None:
        while not self.log_queue.empty():
            line = self.log_queue.get_nowait()
            self.txt_logs.insert("end", line + "\n")
            self.txt_logs.see("end")
        while not self.status_queue.empty():
            txt, fg, bg = self.status_queue.get_nowait()
            self.status_pill.configure(text=txt, text_color=fg, fg_color=bg)
        added = 0
        while not self.item_queue.empty() and added < 20:
            self._render_product_card(self.item_queue.get_nowait())
            added += 1
        self.lbl_stats_found.configure(text=f"📦 Найдено товаров: {self.stats_found}")
        self.lbl_stats_discounts.configure(text=f"📉 Со скидкой / падением: {self.stats_discounts}")
        self.lbl_stats_checks.configure(text=f"⏱️ Запусков: {self.stats_checks}")
        self.lbl_stats_tg.configure(text=f"✈️ Отправлено в TG: {self.stats_tg}")
        self.root.after(150, self._poll_queues)

    def _render_product_card(self, product: OzonProduct) -> None:
        if self.lbl_empty_feed.winfo_exists():
            self.lbl_empty_feed.destroy()

        card = ctk.CTkFrame(self.feed_scroll, fg_color="#1e293b", corner_radius=8)
        card.pack(fill="x", padx=6, pady=5)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))

        price_str = f"{product.price:,.0f} ₽" if product.price > 0 else "Цена н/д"
        if product.card_price:
            price_str += f" (💳 Ozon Карта: {product.card_price:,.0f} ₽)"
        if product.discount > 0:
            price_str += f" (-{product.discount}%)"
        if product.price_drop:
            price_str += f" (📉 -{product.price_drop:,.0f} ₽)"

        ctk.CTkLabel(
            top, text=product.name or f"SKU {product.id}",
            font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc", anchor="w"
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            top, text=price_str, font=ctk.CTkFont(size=13, weight="bold"), text_color="#38bdf8"
        ).pack(side="right", padx=6)

        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.pack(fill="x", padx=12, pady=(0, 8))
        seller_str = product.company_name or product.seller_name or "—"
        if product.company_inn:
            seller_str += f" (ИНН {product.company_inn})"
        info_text = f"🆔 {product.id} | 🏪 {seller_str} | ⭐ {product.rating or '—'} ({product.reviews_count} отз.)"
        ctk.CTkLabel(meta, text=info_text, font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(side="left")

        ctk.CTkButton(
            meta, text="Открыть на Ozon ↗", width=130, height=24, fg_color="#005bff", hover_color="#0044cc",
            font=ctk.CTkFont(size=11, weight="bold"), command=lambda u=product.url: webbrowser.open(u)
        ).pack(side="right", padx=4)

    def _build_client_from_cfg(self, cfg: OzonGUIConfig) -> OzonClient:
        return OzonClient(
            proxy=cfg.proxy_string or None,
            proxy_change_url=resolve_proxy_change_url(cfg.proxy_change_url),
            cookies=cfg.cookies or None,
            user_agent=cfg.user_agent or None,
            use_browser_fallback=cfg.use_browser_fallback,
            tracker_db=str(_get_base_dir() / "storage" / "ozon_prices.db"),
        )

    def _start_scrape(self) -> None:
        if self.is_running:
            return
        cfg = self._save_ui_to_config()
        if not cfg.targets:
            self._log("[!] Введите хотя бы один SKU, ссылку или запрос.")
            return
        self.is_running = True
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_queue.put(("● РАБОТАЕТ", "#38bdf8", "#0c4a6e"))
        self.worker_thread = threading.Thread(target=self._worker_loop, args=(cfg,), daemon=True)
        self.worker_thread.start()

    def _stop_scrape(self) -> None:
        self.stop_event.set()
        self._log("Остановка запрошена пользователем...")
        self.status_queue.put(("● ОСТАНОВКА...", "#f59e0b", "#451a03"))

    def _worker_loop(self, cfg: OzonGUIConfig) -> None:
        try:
            with self._build_client_from_cfg(cfg) as client:
                notifier = (
                    TelegramNotifier(cfg.tg_token, cfg.tg_chat_id, proxy=cfg.tg_proxy or None)
                    if (cfg.tg_notify and cfg.tg_token and cfg.tg_chat_id)
                    else None
                )
                while not self.stop_event.is_set():
                    self.stats_checks += 1
                    self._log(f"Запуск #{self.stats_checks}: {len(cfg.targets)} целей...")
                    try:
                        raw = client.scrape_targets(
                            cfg.targets,
                            max_pages=cfg.max_pages,
                            limit_per_target=cfg.limit,
                            with_seller=cfg.with_seller,
                        )
                        min_p = float(cfg.min_price.replace(",", ".")) if cfg.min_price else 0.0
                        max_p = float(cfg.max_price.replace(",", ".")) if cfg.max_price else 999_999_999.0
                        min_d = int(cfg.min_discount) if cfg.min_discount.isdigit() else 0
                        min_r = float(cfg.min_rating.replace(",", ".")) if cfg.min_rating else 0.0
                        whites = [x.strip() for x in cfg.white_keywords.split(",") if x.strip()]
                        blacks = [x.strip() for x in cfg.black_keywords.split(",") if x.strip()]

                        filtered = filter_products(
                            raw, min_price=min_p, max_price=max_p, min_discount=min_d,
                            min_rating=min_r, white_keywords=whites, black_keywords=blacks
                        )
                        added = 0
                        for item in filtered:
                            if item.id not in self.seen_ids:
                                self.seen_ids.add(item.id)
                                self.discovered_items.append(item)
                                self.stats_found += 1
                                if item.discount > 0 or item.price_drop:
                                    self.stats_discounts += 1
                                self.item_queue.put(item)
                                added += 1
                                if notifier and notifier.send_product(item):
                                    self.stats_tg += 1
                        self._log(f"Цикл завершён: получено {len(filtered)}, новых: {added}.")
                    except OzonAntiBotError as exc:
                        self._log(f"[Ozon Anti-Bot] {exc}")
                    except Exception as exc:
                        self._log(f"[Ошибка цикла] {exc}")
                    if not cfg.continuous_monitor:
                        break
                    self.stop_event.wait(max(5, cfg.interval_sec))
        finally:
            self.is_running = False
            self.root.after(0, lambda: self.btn_start.configure(state="normal"))
            self.root.after(0, lambda: self.btn_stop.configure(state="disabled"))
            self.status_queue.put(("● ГОТОВ К РАБОТЕ", "#22c55e", "#064e3b"))

    def _run_rank_check(self) -> None:
        cfg = self._save_ui_to_config()
        pairs: List[tuple[str, str]] = []
        for line in cfg.rank_pairs:
            if ":" in line:
                left, right = line.split(":", 1)
                pairs.append((left.strip(), right.strip()))
        if not pairs:
            self._log("[!] Укажите пары вида `SKU : запрос`.")
            return
        self.btn_rank_check.configure(state="disabled")
        sort_mode = self.opt_rank_sort.get()

        def worker() -> None:
            try:
                with self._build_client_from_cfg(cfg) as c:
                    tracker = OzonRankTracker(c, db_path=str(_get_base_dir() / "storage" / "ozon_prices.db"))
                    res = tracker.check_batch(pairs, max_pages=cfg.rank_pages, sort=sort_mode)
                self.rank_results = res
                self.root.after(0, lambda: self._render_rank_results(res))
            except Exception as exc:
                self._log(f"[Ошибка Rank] {exc}")
            finally:
                self.root.after(0, lambda: self.btn_rank_check.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_rank_results(self, results: List[RankResult]) -> None:
        for child in self.rank_scroll.winfo_children():
            child.destroy()
        if not results:
            ctk.CTkLabel(self.rank_scroll, text="Совпадений не найдено.", text_color="#94a3b8").pack(pady=30)
            return
        for r in results:
            card = ctk.CTkFrame(self.rank_scroll, fg_color="#1e293b", corner_radius=8)
            card.pack(fill="x", padx=6, pady=4)
            pos_str = f"#{r.position} (стр. {r.page}, слот {r.page_position})" if r.position else f"Не найден (проверено {r.total_scanned})"
            delta_str = ""
            if r.rank_delta is not None:
                delta_str = f"  ▲ +{r.rank_delta}" if r.rank_delta > 0 else (f"  ▼ {r.rank_delta}" if r.rank_delta < 0 else "  = 0")
            ctk.CTkLabel(card, text=f"🔎 «{r.query}» • SKU={r.sku}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f8fafc").pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(card, text=f"{pos_str}{delta_str}", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8" if r.position else "#ef4444").pack(side="right", padx=12, pady=8)

    def _export_rank_excel(self) -> None:
        if not self.rank_results or filedialog is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            rank_results_to_excel(self.rank_results, path)
            self._log(f"Позиции экспортированы: {path}")

    def _on_ai_mode_selected(self, label: str) -> None:
        code = self._ai_mode_labels.get(label, "auto")
        if code == "local":
            self.opt_review_ai_provider.set("Ollama (Local Free)")
            self._on_ai_provider_selected("Ollama (Local Free)")
        elif code == "free" and self.opt_review_ai_provider.get() in ("OpenAI (Paid)", "DeepSeek (Paid)", "ProxyAPI (RU Paid)"):
            self.opt_review_ai_provider.set("Auto Free Pool (g4f)")

    def _on_ai_provider_selected(self, label: str) -> None:
        slug = self._ai_provider_map.get(label, "")
        preset = AI_PROVIDER_PRESETS.get(slug)
        self.entry_review_ai_url.delete(0, "end")
        if preset:
            self.entry_review_ai_url.insert(0, str(preset["base_url"]))
            if not self.entry_review_ai_model.get().strip():
                self.entry_review_ai_model.configure(placeholder_text=f"по умолч.: {preset['default_model']}")
        else:
            self.entry_review_ai_model.configure(placeholder_text="авто по g4f-провайдеру")

    def _test_review_ai(self) -> None:
        cfg = self._save_ui_to_config()
        provider_id = self._ai_provider_map.get(cfg.review_ai_provider, cfg.review_ai_provider)
        self.btn_review_ai_test.configure(state="disabled")
        self.lbl_review_ai_status.configure(text="⏳ Проверка AI-провайдера...", text_color="#facc15")

        def worker() -> None:
            res = test_ai_provider(
                provider_id, mode=cfg.review_ai_mode, model=cfg.review_ai_model or None,
                api_key=cfg.review_ai_key or None, base_url=cfg.review_ai_url or None, timeout=12.0
            )
            if res.success:
                msg = f"✅ {res.provider} ({res.tier}/{res.model or 'default'}) • {res.latency_seconds}s: {res.response_text[:70]}"
                color = "#4ade80"
            else:
                hint = f" — {res.hint}" if res.hint else ""
                msg = f"❌ {res.provider} [{res.error_type}]: {(res.error_message or '')[:75]}{hint}"
                color = "#f87171"
            self.root.after(0, lambda: self.lbl_review_ai_status.configure(text=msg, text_color=color))
            self.root.after(0, lambda: self.btn_review_ai_test.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _run_review_analysis(self) -> None:
        cfg = self._save_ui_to_config()
        if not cfg.review_target:
            self._log("[!] Укажите SKU или ссылку во вкладке «Умные отзывы».")
            return
        provider_id = self._ai_provider_map.get(cfg.review_ai_provider, cfg.review_ai_provider)
        base_url_arg = (cfg.review_ai_url or None) if provider_id in AI_PROVIDER_PRESETS else None
        self.btn_review_run.configure(state="disabled")
        self.lbl_review_kpi.configure(text="⏳ Загрузка отзывов Ozon и AI-анализ...")

        def worker() -> None:
            try:
                with self._build_client_from_cfg(cfg) as c:
                    summary = c.analyze_reviews(
                        cfg.review_target,
                        max_pages=cfg.review_pages,
                        sort=cfg.review_sort,
                        limit=max(50, cfg.review_pages * 30),
                        ai_key=cfg.review_ai_key or None,
                        ai_base_url=base_url_arg,
                        ai_model=cfg.review_ai_model or None,
                        ai_mode=cfg.review_ai_mode,
                        ai_provider=provider_id,
                    )
                self.last_review_summary = summary
                self.root.after(0, lambda: self._render_review_summary(summary))
            except Exception as exc:
                self._log(f"[Ошибка Smart Review] {exc}")
                self.root.after(0, lambda: self.lbl_review_kpi.configure(text=f"❌ Ошибка: {exc}"))
            finally:
                self.root.after(0, lambda: self.btn_review_run.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_review_summary(self, s: OzonReviewSummary) -> None:
        tags = ", ".join(s.aspects_tags[:4]) if s.aspects_tags else "—"
        self.lbl_review_kpi.configure(
            text=(
                f"🔵 {s.product_name or f'SKU {s.sku}'} | ⭐ {s.avg_rating} | "
                f"Отзывов: {s.total_analyzed}/{s.total_available} | Фото: {s.photos_count} | Теги: {tags} | [{s.summary_mode}]"
            )
        )
        self.txt_review_pros.delete("1.0", "end")
        self.txt_review_pros.insert("1.0", "\n".join(f"• {x}" for x in s.top_pros) or "Нет выделенных плюсов")
        self.txt_review_cons.delete("1.0", "end")
        self.txt_review_cons.insert("1.0", "\n".join(f"• {x}" for x in s.top_cons) or "Существенных минусов не найдено")

        for child in self.reviews_scroll.winfo_children():
            child.destroy()
        for rev in s.reviews[:40]:
            box = ctk.CTkFrame(self.reviews_scroll, fg_color="#1e293b", corner_radius=6)
            box.pack(fill="x", padx=6, pady=4)
            parts = []
            if rev.pros:
                parts.append(f"+ {rev.pros}")
            if rev.cons:
                parts.append(f"- {rev.cons}")
            if rev.comment:
                parts.append(rev.comment)
            header_meta = f"[{rev.rating}★]" + (f" {rev.author}" if rev.author else "")
            if rev.photos:
                header_meta += f" 📷{len(rev.photos)}"
            if rev.has_reply:
                header_meta += " 💬Ответ"
            body = " | ".join(parts)
            ctk.CTkLabel(
                box, text=f"{header_meta}: {body[:300]}", anchor="w", justify="left",
                wraplength=1000, font=ctk.CTkFont(size=12), text_color="#e2e8f0"
            ).pack(fill="x", padx=10, pady=6)

    def _export_reviews_excel(self) -> None:
        if not self.last_review_summary or filedialog is None:
            self._log("Нет загруженного анализа отзывов для экспорта.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            reviews_to_excel(self.last_review_summary, path)
            self._log(f"Отзывы и AI-саммари сохранены в Excel: {path}")

    def _send_reviews_tg(self) -> None:
        if not self.last_review_summary:
            self._log("Сначала проанализируйте отзывы товара.")
            return
        cfg = self._save_ui_to_config()
        if not cfg.tg_token or not cfg.tg_chat_id:
            self._log("[!] Настройте Telegram Bot Token и Chat ID во вкладке Telegram.")
            return
        ok = TelegramNotifier(cfg.tg_token, cfg.tg_chat_id, proxy=cfg.tg_proxy or None).send_review_summary(
            self.last_review_summary
        )
        self._log("Сводка отзывов отправлена в Telegram!" if ok else "[!] Не удалось отправить сводку в Telegram.")

    def _test_proxy_connectivity(self) -> None:
        cfg = self._save_ui_to_config()
        self.lbl_proxy_status.configure(text="⏳ Проверка...", text_color="#facc15")

        def run_check() -> None:
            with self._build_client_from_cfg(cfg) as c:
                res = c.ping()
            if res["ok"]:
                msg = f"✅ OK • {res['latency_ms']} мс ({res['tls']}, {res['bytes']} байт)"
                color = "#22c55e"
            else:
                reason = "Anti-Bot Challenge" if res.get("blocked") else res.get("error", res["status_code"])
                msg = f"❌ HTTP {res['status_code']} ({reason}) • {res['tls']}"
                color = "#ef4444"
            self.root.after(0, lambda: self.lbl_proxy_status.configure(text=msg, text_color=color))

        threading.Thread(target=run_check, daemon=True).start()

    def _capture_cookies_browser(self) -> None:
        cfg = self._save_ui_to_config()
        if not is_browser_available():
            self._log('[!] Установите браузерный extra: uv add "ozon-sdk-pro[browser]"')
            self.lbl_proxy_status.configure(text="❌ Требуется [browser] extra", text_color="#ef4444")
            return
        self.lbl_proxy_status.configure(text="⏳ Открываю Chrome для сессии...", text_color="#facc15")

        def worker() -> None:
            try:
                cookie_str = harvest_ozon_cookies(headless=False, proxy=cfg.proxy_string or None)
                def _apply() -> None:
                    self.entry_cookies.delete(0, "end")
                    self.entry_cookies.insert(0, cookie_str)
                    self.lbl_proxy_status.configure(
                        text=f"✅ Получено cookies ({len(cookie_str)} байт)", text_color="#22c55e"
                    )
                self.root.after(0, _apply)
            except Exception as exc:
                self.root.after(0, lambda: self.lbl_proxy_status.configure(text=f"❌ {exc}", text_color="#ef4444"))

        threading.Thread(target=worker, daemon=True).start()

    def _test_telegram(self) -> None:
        cfg = self._save_ui_to_config()
        if not cfg.tg_token or not cfg.tg_chat_id:
            self._log("[!] Заполните Bot Token и Chat ID.")
            return
        ok = TelegramNotifier(cfg.tg_token, cfg.tg_chat_id, proxy=cfg.tg_proxy or None).send_message(
            "✅ <b>Ozon SDK Pro</b>: подключение Telegram работает!"
        )
        self._log("Тест Telegram успешен!" if ok else "[!] Ошибка отправки в Telegram.")

    def _export_excel(self) -> None:
        if not self.discovered_items or filedialog is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if path:
            to_excel(self.discovered_items, path)
            self._log(f"Экспортировано в Excel: {path}")

    def _export_csv(self) -> None:
        if not self.discovered_items or filedialog is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            to_csv(self.discovered_items, path)
            self._log(f"Экспортировано в CSV: {path}")

    def _export_json(self) -> None:
        if not self.discovered_items or filedialog is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            to_json(self.discovered_items, path)
            self._log(f"Экспортировано в JSON: {path}")

    def _show_donate_dialog(self) -> None:
        win = ctk.CTkToplevel(self.root)
        win.title("☕ Поддержать Ozon SDK Pro")
        win.geometry("540x285")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        if self._app_photo_icon:
            try:
                win.iconphoto(False, self._app_photo_icon)
            except Exception:
                pass

        ctk.CTkLabel(
            win,
            text="☕ Поддержать разработку Ozon SDK Pro",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#facc15",
        ).pack(pady=(16, 6))
        ctk.CTkLabel(
            win,
            text="Проект полностью открыт (MIT). Вы можете поддержать обновления и развитие:",
            font=ctk.CTkFont(size=12),
            text_color="#cbd5e1",
        ).pack(pady=(0, 12))

        ctk.CTkLabel(win, text="USDT (TRC-20):", font=ctk.CTkFont(size=12, weight="bold")).pack()
        addr = ctk.CTkEntry(win, width=410, justify="center")
        addr.insert(0, DONATE_USDT_TRC20)
        addr.configure(state="readonly")
        addr.pack(pady=6)

        lbl_copied = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=11), text_color="#22c55e")
        lbl_copied.pack(pady=2)

        def copy_addr() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(DONATE_USDT_TRC20)
            lbl_copied.configure(text="✅ Адрес USDT TRC-20 скопирован!")

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=10)
        ctk.CTkButton(row, text="📋 Скопировать USDT", width=155, fg_color="#16a34a", command=copy_addr).pack(
            side="left", padx=5
        )
        self._make_link_button(row, text="🔍 TronScan", url=DONATE_TRONSCAN_URL, width=110, fg_color="#0284c7").pack(
            side="left", padx=5
        )
        self._make_link_button(
            row, text="🎁 Прокси 3ч", url=MOBILEPROXY_FREE_TRIAL_URL, width=120, fg_color="#0f766e"
        ).pack(side="left", padx=5)

        row2 = ctk.CTkFrame(win, fg_color="transparent")
        row2.pack(pady=(2, 10))
        self._make_link_button(row2, text="✈ @avito_sdk_pro", url=TELEGRAM_CHANNEL_URL, width=150, fg_color="#334155").pack(
            side="left", padx=5
        )
        self._make_link_button(row2, text="⭐ GitHub Repo", url=REPO_URL, width=140, fg_color="#334155").pack(
            side="left", padx=5
        )

    def _clear_feed(self) -> None:
        for child in self.feed_scroll.winfo_children():
            child.destroy()
        self.discovered_items.clear()
        self.seen_ids.clear()
        self.stats_found = 0
        self.stats_discounts = 0

    def _on_close(self) -> None:
        self.stop_event.set()
        self._save_ui_to_config()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
