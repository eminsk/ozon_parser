<h1 align="center">Ozon SDK Pro (`ozon-sdk-pro`)</h1>
<p align="center">
  <b>Единая экосистема для Ozon: Sync/Async SDK + Composer API + ИНН продавца + Ozon Карта + Позиции (Rank) + Умные отзывы + Бесплатные/Платные AI (`g4f` / Ollama / OpenAI / DeepSeek / OpenRouter) + 13 команд CLI + 9 MCP-инструментов + 7-Tab GUI</b>
</p>

<p align="center">
  <a href="https://github.com/eminsk/ozon_parser/blob/main/README.md">🇬🇧 English</a> •
  <b>🇷🇺 Документация на русском</b>
</p>

> Современная переработка и расширение проекта `ozonparser` по единому стандарту **`wb-sdk-pro` / `avito-sdk-pro`**: чистая публикуемая библиотека (`pip` / `uv add ozon-sdk-pro`, `import ozon_parser`), CLI (`ozon-parser` / `ozon-sdk`), Native MCP-сервер (`ozon-mcp`), 7-вкладочный Desktop GUI (`ozon-gui`), Debian APT PPA (`python3-ozon-sdk-pro`) и рецепт `conda-forge` v1 (`packaging/conda-forge/recipe.yaml`).

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
3. **Трекер цен, позиции в поиске, экспорт и Telegram (`tracker.py`, `rank.py`, `export.py`, `telegram.py`):**
   - SQLite история цен (`ozon_latest_prices`, `ozon_price_history`) с учётом Ozon Карты и детектированием снижения цен (`price_drop`).
   - Проверка позиций по ключевым словам (`OzonRankTracker`) с историей и динамикой `▲`/`▼`.
   - Экспорт в **Excel `.xlsx`** (товары, отдельная выгрузка отзывов с AI-саммари, позиции), **CSV UTF-8 BOM**, **JSON**, **JSONL**, `pandas.DataFrame` (`[dataframe]`).
   - Отправка карточек, AI-сводок отзывов и отчётов в **Telegram** с отдельным SOCKS5/HTTP прокси.

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

### Запуск GUI (`ozon-gui`)

```bash
uv run ozon-gui
# или локально:
uv run python run_gui.py
```

Вкладки GUI: **🔍 Парсер**, **📦 Каталог товаров**, **📈 Позиции (Rank)**, **💬 Умные отзывы + AI** (с кнопкой **`⚡ Проверить AI`**, экспортом отзывов в `.xlsx` и отправкой в Telegram), **🌐 Прокси и Сессия** (включая **`🍪 Захватить Cookies`**), **✈️ Telegram**, **📋 Журнал**.

### Команды CLI (`ozon-parser` / `ozon-sdk` — 13 команд)

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
```

### MCP-сервер для AI-агентов (`ozon-mcp` — 9 инструментов)

Инструменты: `ozon_get_card`, `ozon_get_seller`, `ozon_search`, `ozon_get_seller_catalog`, `ozon_get_reviews`, `ozon_smart_reviews`, `ozon_price_drops`, `ozon_check_rank`, `ozon_ai_providers`.

---

## 🧪 Тесты (`pytest`)

```bash
uv run --with pytest pytest -v
```

## 📄 Лицензия

MIT License.
