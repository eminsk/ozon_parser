<p align="center">
  <img src="assets/logo.png" width="140" alt="Ozon SDK Pro Logo">
</p>
<h1 align="center">Ozon SDK Pro (`ozon-sdk-pro`)</h1>
<p align="center">
  <b>Единая экосистема для Ozon: Sync/Async SDK + Интерактивный Telegram-бот (`OzonTelegramBot`) + Автономное Windows .exe приложение + Composer API + ИНН продавца + Ozon Карта + Позиции (Rank) + Умные отзывы + Бесплатные/Платные AI (`g4f` / Ollama / OpenAI / DeepSeek / OpenRouter) + 14 команд CLI + 9 MCP-инструментов</b>
</p>

<p align="center">
  <a href="https://github.com/eminsk/ozon_parser/blob/main/README.md">🇬🇧 English</a> •
  <b>🇷🇺 Документация на русском</b>
</p>

[![Release](https://img.shields.io/badge/релиз-v1.2.0-005BFF.svg?style=flat&logo=github)](https://github.com/eminsk/ozon_parser/releases/tag/v1.2.0)
[![Бесплатный тест прокси 3 часа](https://img.shields.io/badge/Прокси_без_VPN-Тест_3_часа_бесплатно-00C853?style=flat&logo=cloudflare&logoColor=white)](https://mobileproxy.rent/user.html?free&p=279117)
[![PyPI Version](https://img.shields.io/pypi/v/ozon-sdk-pro.svg?style=flat&logo=pypi&color=005BFF)](https://pypi.org/project/ozon-sdk-pro/)
[![Python Versions](https://img.shields.io/badge/python-3.8%20--%203.16+%20%7C%20PyPy%20%7C%20No--GIL-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Desktop GUI](https://img.shields.io/badge/Desktop%20GUI-Windows%20.exe%20%7C%207%20Вкладок-005BFF.svg?style=flat)](https://github.com/eminsk/ozon_parser/blob/main/README_RU.md#%D0%B7%D0%B0%D0%BF%D1%83%D1%81%D0%BA-gui-%D0%B8-%D0%B0%D0%B2%D1%82%D0%BE%D0%BD%D0%BE%D0%BC%D0%BD%D0%BE%D0%B3%D0%BE-windows-exe-ozon-gui)
[![Telegram Канал](https://img.shields.io/badge/Telegram_Канал-@avito__sdk__pro-26A5E4?style=flat&logo=telegram&logoColor=white)](https://t.me/avito_sdk_pro)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)

> Современная переработка и расширение проекта `ozonparser` по единому стандарту **`wb-sdk-pro` / `avito-sdk`**: чистая публикуемая библиотека (`pip` / `uv add ozon-sdk-pro`, `import ozon_parser`), **интерактивный Telegram-бот (`OzonTelegramBot`)**, CLI на 14 команд (`ozon-parser` / `ozon-sdk`), Native MCP-сервер (`ozon-mcp`), 7-вкладочный Desktop GUI (`ozon-gui`), **автономный Windows `.exe` (`OzonSDK_Pro.exe`)**, Debian APT PPA (`python3-ozon-sdk-pro`) и рецепт `conda-forge` v1 (`packaging/conda-forge/recipe.yaml`).

> ### 🤝 Сообщество, мобильные прокси и поддержка
> - 🌐 **Антибот Ozon или 429 при парсинге?** Возьмите [бесплатный тест мобильного прокси на 3 часа](https://mobileproxy.rent/user.html?free&p=279117) ([личный кабинет MobileProxy](https://mobileproxy.rent/?p=279117) — работает в РФ без VPN).
> - 📢 **Релизы, настройка прокси и чат:** подписывайтесь на [Telegram-канал @avito_sdk_pro](https://t.me/avito_sdk_pro).
> - 🐛 **Нашли баг или изменились виджеты Ozon?** [Откройте Issue](https://github.com/eminsk/ozon_parser/issues) — исправления выходят оперативно!
> - ⭐ **Полезен проект?** Поставьте звезду репозиторию на GitHub!
> - ☕ **Поддержать разработку (USDT TRC-20):** `TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P` ([Проверить в TronScan](https://tronscan.org/#/address/TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P))

<p align="center">
  <img src="docs/images/gui_parser.png" alt="Ozon SDK Pro Desktop GUI — Вкладка Парсер" width="820">
</p>

---

## 🐍 Совместимость с Python

| Среда | Версии | Статус |
|---|---|---|
| **CPython** | 3.8 – 3.16 | ✅ Ядро на чистом Python без обязательных C/Rust-зависимостей |
| **Free-Threaded (No-GIL)** | 3.13t – 3.16t | ✅ Потокобезопасно (`RLock` + `ozon_parser._model`) |
| **PyPy** | 3.8 – 3.12 | ✅ Полная совместимость Sync/Async SDK и CLI |

Транспорт автоматически выбирает **`curl_cffi` (`[tls]`) → `httpx[http2]` → `requests`**, а при включении `use_browser_fallback=True` (или `ozon-parser cookies`) может задействовать опциональный Chrome через `[browser]`.

---

## 🚀 Основные модули (`import ozon_parser`)

1. **Composer API парсер (`endpoints.py`, `widgets.py`, `client.py`):**
   - Извлечение карточек товаров (`/product/...`), поиска (`/search/`), категорий (`/category/...`) и витрин продавцов (`/seller/...`) через Composer API v2 и HTML `data-state`.
   - Поддержка `webStickyProducts`, `webPrice` (**цена по Ozon Карте `card_price`**, текущая, старая, скидка `%`), `webCharacteristics`, `webGallery`, `webDetailDescription`, `searchResultsV2`, `tileGrid`.
   - Профилирование продавцов (`/modal/shop-in-shop-info`): компания (очистка дублей юрформ/HTML `<br>`), ИНН (`10–15` цифр), количество заказов, срок работы на Ozon, средний рейтинг и отзывы.
   - Синхронный `OzonClient` (`scrape_targets`, `card_savings`), асинхронный `AsyncOzonClient` (`gather_products`, `fetch_reviews`) и удобная обёртка `ParseOzon`.
2. **Умные отзывы + Бесплатные/Платные AI (`reviews.py`, `ai.py`):**
   - Постраничный сбор реальных отзывов покупателей (`webListReviews` + `webReviewProductScore` + `webAspects`): плюсы (`pros`), минусы (`cons`), текст, рейтинг `1★–5★`, фото, ответы продавцов.
   - **Оффлайн-анализ без ключей и интернета:** статистика оценок и частых плюсов/минусов.
   - **Бесплатные модели без API-ключей (`ozon-sdk-pro[ai]`):** движок **`g4f`** (`Yqcloud`, `Airforce`, `LLM7`, `GLM`, `DeepInfra`, `Cerebras`, `Pollinations` и др.) с диагностикой ошибок и автоперебором живых провайдеров + локальный **Ollama** (`OLLAMA_BASE_URL`) и **LM Studio** (`LMSTUDIO_BASE_URL`).
   - **Платные и гибридные API:** **OpenAI**, **DeepSeek**, **OpenRouter** (`:free` + платные), **ProxyAPI**, **Groq**, **Google Gemini** или любой OpenAI-совместимый `base_url`.
3. **Трекер цен, позиции в поиске, Excel и интерактивный Telegram-бот (`tracker.py`, `rank.py`, `export.py`, `telegram.py`):**
   - SQLite история цен (`ozon_latest_prices`, `ozon_price_history`) с учётом Ozon Карты и детектированием снижения цен (`price_drop`).
   - Проверка позиций по ключевым словам (`OzonRankTracker`) с историей и динамикой `▲`/`▼`.
   - Экспорт в **Excel `.xlsx`** (товары, отдельная выгрузка отзывов с AI-саммари, позиции), **CSV UTF-8 BOM**, **JSON**, **JSONL**, `pandas.DataFrame` (`[dataframe]`).
   - **`TelegramNotifier`** + полноценный интерактивный бот **`OzonTelegramBot`** (`/start`, `/search`, `/drops`, `/rank`, `/reviews`, `/seller`, `/workers`, `/limit`, `/proxy`, живые прогресс-бары и выгрузка `.xlsx` в чат через отдельный прокси + `run_telegram_bot.py`).

---

## 📦 Установка

### PyPI (`uv` / `pip`)

```bash
# Базовый SDK, 13 команд CLI и 9-инструментный MCP-сервер
uv add ozon-sdk-pro

# Быстрый запуск GUI напрямую через uvx
uvx --from "ozon-sdk-pro[gui]" ozon-gui

# Или через pip
pip install ozon-sdk-pro
```

### Дополнительные опции (Extras)

```bash
uv add "ozon-sdk-pro[ai]"          # Бесплатные модели g4f без API-ключей (алиас: [free-ai])
uv add "ozon-sdk-pro[gui]"         # 7-вкладочный Desktop GUI (customtkinter, Pillow, curl_cffi)
uv add "ozon-sdk-pro[tls]"         # Chrome 124 TLS-отпечаток (curl_cffi)
uv add "ozon-sdk-pro[browser]"     # Опциональный Chrome-фолбэк / сборщик cookies (selenium + selenium-stealth)
uv add "ozon-sdk-pro[dataframe]"   # Экспорт в pandas.DataFrame (алиас: [pandas])
uv add "ozon-sdk-pro[all]"         # GUI + g4f + Chrome TLS + pandas
```

### Debian / Ubuntu (APT PPA)

Репозиторий содержит готовый каталог [`debian/`](https://github.com/eminsk/ozon_parser/tree/main/debian) и workflow сборки `.deb`-пакета `python3-ozon-sdk-pro`:

```bash
curl -sS https://eminsk.github.io/ppa/setup.sh | sudo bash
sudo apt install python3-ozon-sdk-pro
```

### Conda / Pixi (`conda-forge`)

В [`packaging/conda-forge/recipe.yaml`](https://github.com/eminsk/ozon_parser/blob/main/packaging/conda-forge/recipe.yaml) подготовлен v1-рецепт для `conda-forge/staged-recipes`:

```bash
# После публикации в conda-forge:
conda install -c conda-forge ozon-sdk-pro
```

### Из исходников

```bash
git clone https://github.com/eminsk/ozon_parser.git
cd ozon_parser
uv sync --all-extras --group dev
```

---

## ⚡ Примеры использования

### Python SDK (товары, отзывы + Free `g4f` / Paid AI, экспорт)

```python
from ozon_parser import AIClient, OzonClient, reviews_to_excel, to_excel

with OzonClient(cookies="__cf_bm=...", tracker_db="ozon_prices.db") as ozon:
    item = ozon.get_product("https://www.ozon.ru/product/1619925434/", with_seller=True)
    print(item.name, item.price, "Ozon Карта:", item.card_price, "ИНН:", item.company_inn)
    to_excel([item], "result/ozon_catalog.xlsx")

    # Умный анализ отзывов: Оффлайн / Бесплатно g4f / Локальный Ollama / Платный DeepSeek
    summary = ozon.analyze_reviews(1619925434, max_pages=3, ai_mode="free", ai_provider="g4f")
    print("Плюсы:", summary.top_pros)
    print("Минусы:", summary.top_cons)
    reviews_to_excel(summary, "result/ozon_reviews.xlsx")

# Прямое обращение к AI
ai = AIClient(mode="free", provider="g4f")
print(ai.chat("Дай 3 совета по карточке товара на Ozon").content)
```

### Запуск GUI и автономного Windows `.exe` (`ozon-gui`)

#### 1. Готовое приложение для Windows (без установки Python):
1. Скачайте **[OzonSDK_Pro_Windows_x64.zip](https://github.com/eminsk/ozon_parser/releases/latest)** из раздела [Releases](https://github.com/eminsk/ozon_parser/releases).
2. Распакуйте архив и запустите `OzonSDK_Pro.exe` (внутри уже вшиты Chrome TLS `curl_cffi` и бесплатный AI `g4f`).

#### 2. Или запуск через Python / PyPI:
```bash
uvx --from "ozon-sdk-pro[gui]" ozon-gui
# или локально:
uv run python run_gui.py
# или двойным кликом по run_gui.bat
```

Вкладки GUI: **🔍 Парсер**, **📦 Каталог товаров** (+ **✈ Excel → TG**), **📈 Позиции (Rank)** (+ **✈ Позиции → TG**), **💬 Умные отзывы + AI** (кнопка **`⚡ Проверить AI`**, экспорт отзывов в `.xlsx` и отправка в Telegram), **🌐 Прокси и Сессия** (баннер **MobileProxy + 3ч тест** и **`🍪 Захватить Cookies`**), **✈️ Telegram** (**запуск интерактивного `OzonTelegramBot` одной кнопкой**), **📋 Журнал** и **`☕ Донат`** в шапке окна.

<p align="center">
  <img src="docs/images/gui_catalog.png" alt="Ozon SDK Pro Desktop GUI — Каталог товаров, Ozon Карта и ИНН" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_reviews_ai.png" alt="Ozon SDK Pro Desktop GUI — Умные отзывы и бесплатный AI g4f" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_telegram.png" alt="Ozon SDK Pro Desktop GUI — Интерактивный Telegram-бот" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_proxy.png" alt="Ozon SDK Pro Desktop GUI — Прокси, MobileProxy и захват Cookies" width="820">
</p>

### Выбор и настройка сетевых прокси
1. **Серверные (IPv4 / SOCKS5 — от 30–50 ₽/мес):** для лёгкого мониторинга совместно с cookies Chrome (`--cookies` / `[browser]`).
2. **Оплата за трафик (Pay-As-You-Go — ~200 ₽/ГБ):** [AstroProxy](https://astroproxy.com), [Asocks](https://asocks.com).
3. **Выделенные мобильные 4G/LTE модемы с ротацией (рекомендуется):** [MobileProxy (mobileproxy.rent)](https://mobileproxy.rent/?p=279117) ([бесплатный тест 3 часа без VPN](https://mobileproxy.rent/user.html?free&p=279117)):
   ```python
   from ozon_parser import OzonClient

   with OzonClient(
       proxy="http://login:password@proxy-domain.space:port",
       mobileproxy_key="ВАШ_КЛЮЧ_РОТАЦИИ",
   ) as ozon:
       products = ozon.search("видеокарта rtx 4060", max_pages=2)
   ```

### Команды CLI (`ozon-parser` / `ozon-sdk` — 14 команд)

```bash
uv run ozon-parser ping
uv run ozon-parser card 1619925434 --with-seller -o item.xlsx
uv run ozon-parser seller 123456 --info-only
uv run ozon-parser search "ноутбук" --pages 2 --min-discount 15 -o search.xlsx
uv run ozon-parser reviews 1619925434 --mode free --pages 3 -o reviews.xlsx
uv run ozon-parser rank 1619925434 "видеокарта rtx 4060" --pages 3 -o ranks.xlsx
uv run ozon-parser card-discount 5990 5490
uv run ozon-parser drops --db ozon_prices.db
uv run ozon-parser ai --list
uv run ozon-parser ai --quick-scan
uv run ozon-parser ai --ask "Выдели плюсы товара" --mode free
uv run ozon-parser cookies --visible -o ozon_cookies.txt
uv run ozon-parser mcp
uv run ozon-parser gui
uv run ozon-parser bot --tg-token "123:AAF..." --mobileproxy-key "KEY" --tg-proxy "socks5://127.0.0.1:1080"
# или автономный скрипт:
uv run python run_telegram_bot.py
```

### MCP-сервер для AI-агентов (`ozon-mcp` — 9 инструментов)

Инструменты: `ozon_get_card`, `ozon_get_seller`, `ozon_search`, `ozon_get_seller_catalog`, `ozon_get_reviews`, `ozon_smart_reviews`, `ozon_price_drops`, `ozon_check_rank`, `ozon_ai_providers`.

---

## 🧪 Тесты (`pytest`)

```bash
uv run --with pytest pytest -v
```

**29 тестов** пройдены в CI на **Linux, Windows и macOS** (CPython 3.8–3.16, Free-Threaded 3.13t–3.16t, PyPy 3.8–3.12), включая команды `OzonTelegramBot`, колбэки, пакетный сбор и загрузку Excel.

---

## ☕ Поддержать проект (Донат)

Если библиотека помогает в работе или экономит время разработки:
* ⭐ Поставьте звезду на [GitHub](https://github.com/eminsk/ozon_parser)
* 🌐 Воспользуйтесь партнёрской ссылкой: [MobileProxy — 3 часа бесплатно без VPN](https://mobileproxy.rent/user.html?free&p=279117)
* 💎 **USDT (TRC-20):** `TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P` ([Проверить в TronScan](https://tronscan.org/#/address/TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P))

## 📄 Лицензия

MIT License.
