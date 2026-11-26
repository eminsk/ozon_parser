<p align="center">
  <img src="assets/logo.png" width="140" alt="Ozon SDK Pro Logo">
</p>
<h1 align="center">Ozon SDK Pro (`ozon-sdk-pro`)</h1>
<p align="center">
  <b>All-in-One Ozon Sync/Async SDK + Interactive Telegram Bot (`OzonTelegramBot`) + Standalone Windows .exe GUI + Composer API + Seller INN Lookup + Ozon Card + Rank Tracker + Smart Reviews + Free/Paid AI (`g4f` / Ollama / OpenAI / DeepSeek / OpenRouter) + 14 CLI Commands + 9 MCP Tools</b>
</p>

<p align="center">
  <b>🇬🇧 English</b> •
  <a href="https://github.com/eminsk/ozon_parser/blob/main/README_RU.md">🇷🇺 Документация на русском</a>
</p>

[![Release](https://img.shields.io/badge/release-v1.2.0-005BFF.svg?style=flat&logo=github)](https://github.com/eminsk/ozon_parser/releases/tag/v1.2.0)
[![Free 3h Proxy Trial](https://img.shields.io/badge/Mobile_Proxy-Free_3h_Trial_(No_VPN)-00C853?style=flat&logo=cloudflare&logoColor=white)](https://mobileproxy.rent/user.html?free&p=279117)
[![PyPI Version](https://img.shields.io/pypi/v/ozon-sdk-pro.svg?style=flat&logo=pypi&color=005BFF)](https://pypi.org/project/ozon-sdk-pro/)
[![Python Versions](https://img.shields.io/badge/python-3.8%20--%203.16+%20%7C%20PyPy%20%7C%20No--GIL-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![uv Powered](https://img.shields.io/badge/uv-package%20manager-DE5FE9.svg?style=flat)](https://github.com/astral-sh/uv)
[![Tests](https://img.shields.io/badge/pytest-29%20passed%20%C3%97%2018%20runtimes-2ea44f.svg?style=flat&logo=pytest&logoColor=white)](https://github.com/eminsk/ozon_parser/tree/main/tests)
[![Desktop GUI](https://img.shields.io/badge/Desktop%20GUI-Windows%20.exe%20%7C%207%20Tabs-005BFF.svg?style=flat)](https://github.com/eminsk/ozon_parser#desktop-gui)
[![MCP Server](https://img.shields.io/badge/MCP-9%20Tools%20JSON--RPC%202.0-00C853.svg?style=flat)](https://github.com/eminsk/ozon_parser#mcp-server-for-ai-agents)
[![Telegram Channel](https://img.shields.io/badge/Telegram_Channel-@avito__sdk__pro-26A5E4?style=flat&logo=telegram&logoColor=white)](https://t.me/avito_sdk_pro)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](https://opensource.org/licenses/MIT)

> **Unified Ozon Ecosystem (`ozon-sdk-pro` / `import ozon_parser`)** combining fast HTTP/Composer API v2 extraction, seller legal & INN lookups, buyer review harvesting & **Free/Paid AI summarization (`g4f`, Ollama, OpenAI, DeepSeek, OpenRouter, ProxyAPI, Groq, Gemini)**, Ozon Card savings math, SQLite price & search rank tracking, **Interactive Telegram Bot (`OzonTelegramBot`)**, 14-command CLI (`ozon-parser` / `ozon-sdk`), 9-tool MCP Server (`ozon-mcp`), 7-tab CustomTkinter Desktop GUI (`ozon-gui`), **Standalone Windows `x64` `.exe` App (`OzonSDK_Pro.exe`)**, Debian APT PPA packaging, and a `conda-forge` v1 recipe.

> ### 🤝 Community, Mobile Proxies & Support
> - 🌐 **Hitting Ozon anti-bot challenges or 429 limits?** Claim a [3-Hour Free Mobile Proxy Trial](https://mobileproxy.rent/user.html?free&p=279117) ([MobileProxy Portal](https://mobileproxy.rent/?p=279117) — works in Russia without VPN).
> - 📢 **Releases, proxy setups & community chat:** Join our [Telegram Channel (@avito_sdk_pro)](https://t.me/avito_sdk_pro).
> - 🐛 **Found a bug or composer widget layout change?** Please [Open an Issue](https://github.com/eminsk/ozon_parser/issues) — parser fixes are prioritized!
> - ⭐ **Find this SDK useful?** Give it a star on GitHub — it helps more developers discover the library!
> - ☕ **Support development (USDT TRC-20):** `TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P` ([Verify on TronScan](https://tronscan.org/#/address/TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P))

<p align="center">
  <img src="docs/images/gui_parser.png" alt="Ozon SDK Pro Desktop GUI — Parser & Filters" width="820">
</p>

---

## 🐍 Python Compatibility

| Runtime | Versions | Support |
|---|---|---|
| **CPython** | 3.8 – 3.16 | ✅ Pure-Python core + zero C/Rust build deps |
| **Free-Threaded (No-GIL)** | 3.13t – 3.16t | ✅ Thread-safe (`RLock` + `ozon_parser._model`) |
| **PyPy** | 3.8 – 3.12 | ✅ Pure-Python core & async/sync clients |

Core HTTP transport selects **`curl_cffi` (`[tls]`) → `httpx[http2]` → `requests`** automatically, and optionally delegates to Selenium Chrome (`[browser]`) only when enabled (`use_browser_fallback=True` or `ozon-parser cookies`).

---

## 🚀 Key Modules & Features

| Module | Capabilities | Highlights |
|---|---|---|
| **Composer API & Widgets** (`endpoints.py`, `widgets.py`) | Parses Ozon `/product/...`, `/search/`, `/category/...`, `/seller/...` & `/modal/shop-in-shop-info` | Handles JSON `widgetStates` (`webStickyProducts`, `webPrice`, `webCharacteristics`, `webGallery`, `searchResultsV2`, `tileGrid`) and HTML `data-state` blocks |
| **Seller INN & Legal Profiling** (`widgets.py`, `client.py`) | Extracts `company_name`, 10–15 digit `inn`, `orders_count`, `working_time`, `average_rating` | Heuristic `textBlock-*` scorer + `<br>` / legal form normalization |
| **Sync & Async Clients** (`OzonClient`, `AsyncOzonClient`, `ParseOzon`) | High-throughput batch scraping, category/search pagination & one-liner exports | `filter_products` (price/discount/rating/whitelist/blacklist), `scrape_targets` for mixed lists, `OzonClient.card_savings()` for Ozon Card |
| **Smart Reviews & Free/Paid AI** (`reviews.py`, `ai.py`) | Paginated `webListReviews` extraction + pros/cons clustering & LLM summarization | **Offline NLP** (ratings `1★–5★`, photos, replies, aspects), **Free `g4f`** (`Yqcloud`, `Airforce`, `LLM7`, `GLM`...) & **Ollama/LM Studio**, **Hybrid** (`OpenRouter` `:free`, `Groq`, `Gemini`), **Paid** (`OpenAI`, `DeepSeek`, `ProxyAPI`) + health checks (`test_ai_provider`, `quick_scan_ai_providers`) |
| **Price & Rank Trackers** (`tracker.py`, `rank.py`) | Tracks regular & Ozon Card price drops + search position movement | Thread-safe SQLite (`ozon_latest_prices`, `ozon_price_history`, `ozon_rank_history`) with `▲`/`▼` deltas |
| **Exports, Config & Interactive Telegram Bot** (`export.py`, `config.py`, `telegram.py`) | Excel reports, TOML/JSON config & `OzonTelegramBot` | `.xlsx` (products, reviews+AI tabs, rank reports), `.csv` (UTF-8 BOM + Excel formula guard), `.json`, `.jsonl`, `pandas.DataFrame` (`[dataframe]`), `TelegramNotifier` + interactive **`OzonTelegramBot`** (`/search`, `/drops`, `/rank`, `/reviews`, `/seller`, live progress bars & auto Excel uploads via decoupled `tg_proxy`) |
| **Desktop GUI (`ozon-gui`)** | 7-tab dark `CustomTkinter` control center (`[gui]`) | Parser, Catalog Feed + `✈ Excel → TG`, Search Rank Tracker + `✈ Excel → TG`, Smart Reviews + AI Check + `✈ В TG`, Proxy/Cookie Capture (`[browser]`), Telegram + Bot Start/Stop, Logs |
| **Native MCP Server (`ozon-mcp`)** | Connects AI coding agents & assistants to Ozon market data | 9 JSON-RPC 2.0 tools (`2025-11-25` / `2025-06-18` / `2024-11-05`) |

---

## 📦 Installation

### PyPI (`uv` / `pip`)

```bash
# Core SDK, 14-command CLI (ozon-parser / ozon-sdk), and 9-tool MCP Server (ozon-mcp)
uv add ozon-sdk-pro

# Run Desktop GUI directly without installing into your project (requires [gui])
uvx --from "ozon-sdk-pro[gui]" ozon-gui

# Or via pip
pip install ozon-sdk-pro
```

### Optional Extras

```bash
# Free zero-key AI providers via g4f (Yqcloud, Airforce, LLM7, GLM, Cerebras...)
uv add "ozon-sdk-pro[ai]"          # alias: "ozon-sdk-pro[free-ai]"

# 7-Tab CustomTkinter Desktop GUI (+ Pillow & curl_cffi)
uv add "ozon-sdk-pro[gui]"

# Chrome TLS/HTTP2 impersonation (curl_cffi)
uv add "ozon-sdk-pro[tls]"

# Optional Selenium + selenium-stealth browser fallback / cookie helper
uv add "ozon-sdk-pro[browser]"

# Pandas DataFrame export via to_dataframe()
uv add "ozon-sdk-pro[dataframe]"   # or "ozon-sdk-pro[pandas]"

# Core + GUI + Free AI (g4f) + Chrome TLS + pandas
uv add "ozon-sdk-pro[all]"
```

### Debian / Ubuntu (APT PPA)

Packaging metadata is ready in [`debian/`](https://github.com/eminsk/ozon_parser/tree/main/debian) for building `python3-ozon-sdk-pro`:

```bash
curl -sS https://eminsk.github.io/ppa/setup.sh | sudo bash
sudo apt install python3-ozon-sdk-pro
```

### Conda / Pixi (`conda-forge` v1 Recipe)

The `rattler-build` / `conda-forge` v1 recipe lives at [`packaging/conda-forge/recipe.yaml`](https://github.com/eminsk/ozon_parser/blob/main/packaging/conda-forge/recipe.yaml):

```bash
# Once published to conda-forge:
conda install -c conda-forge ozon-sdk-pro
```

### From Source

```bash
git clone https://github.com/eminsk/ozon_parser.git
cd ozon_parser
uv sync                    # core SDK + CLI + MCP
uv sync --extra ai         # + Free g4f AI backend
uv sync --extra gui        # + Desktop GUI + Chrome TLS
uv sync --extra browser    # + Optional Selenium fallback
uv sync --all-extras       # GUI + g4f + TLS + pandas
```

---

## ⚡ Quick Start — Python Library

### 1. Product Metadata, Seller INN, Ozon Card & Export

```python
from ozon_parser import OzonClient, to_csv, to_excel, to_json

with OzonClient(
    cookies="__cf_bm=...",  # or proxy="http://user:pass@ip:port", use_browser_fallback=True
    tracker_db="ozon_prices.db",
) as ozon:
    item = ozon.get_product("https://www.ozon.ru/product/1619925434/", with_seller=True)
    print(item.name, f"{item.price} ₽ (Ozon Card: {item.card_price} ₽)")
    print("Seller:", item.company_name, "INN:", item.company_inn)

    to_excel([item], "result/ozon_catalog.xlsx")
    to_csv([item], "result/ozon_catalog.csv")
    to_json([item], "result/ozon_catalog.json")
```

### 2. Async Batch Fetching (`AsyncOzonClient`)

```python
import asyncio
from ozon_parser import AsyncOzonClient

async def main():
    async with AsyncOzonClient(concurrency=8, tracker_db="ozon_prices.db") as ozon:
        products = await ozon.gather_products([1619925434, 141217830], with_seller=True)
        for p in products:
            print(p.sku, p.name, p.price, p.card_price)

asyncio.run(main())
```

### 3. Smart Reviews + Free (`g4f` / Ollama) & Paid AI (`ozon_parser.reviews` & `ozon_parser.ai`)

```python
from ozon_parser import AIClient, OzonClient, list_ai_providers, reviews_to_excel, test_ai_provider

with OzonClient(cookies="...") as ozon:
    # A) Instant Zero-API Offline NLP clustering
    offline = ozon.analyze_reviews(1619925434, max_pages=3, ai_mode="offline")
    print(offline.avg_rating, offline.top_pros, offline.top_cons)

    # B) 100% Free zero-key AI via g4f auto-fallback (`uv add "ozon-sdk-pro[ai]"`)
    free_res = ozon.analyze_reviews(1619925434, ai_mode="free", ai_provider="g4f")

    # C) Local Free Ollama (`http://localhost:11434/v1`)
    local_res = ozon.analyze_reviews(1619925434, ai_mode="local", ai_provider="ollama", ai_model="llama3.2")

    # D) Paid / Hybrid APIs (DeepSeek, OpenAI, OpenRouter, ProxyAPI, Groq, Gemini)
    paid_res = ozon.analyze_reviews(
        1619925434,
        ai_mode="paid",
        ai_provider="deepseek",
        ai_key="sk-...",
    )
    reviews_to_excel(paid_res, "result/reviews_1619925434.xlsx")

# AI Provider Discovery & Health Diagnostics
providers = list_ai_providers(tier="all")
health = test_ai_provider("Yqcloud", mode="free", timeout=10.0)
print(health.success, health.latency_seconds, health.hint)

ai = AIClient(mode="auto")
print(ai.chat("Дай 3 совета по увеличению конверсии карточки на Ozon").content)
```

Supported built-in AI presets: `g4f` (`Yqcloud`, `Airforce`, `LLM7`, `GLM`, `DeepInfra`, `Cerebras`, `Pollinations`...), `ollama` (`OLLAMA_BASE_URL`), `lmstudio` (`LMSTUDIO_BASE_URL`), `openrouter` (`OPENROUTER_API_KEY`), `groq` (`GROQ_API_KEY`), `gemini` (`GEMINI_API_KEY`), `openai` (`OPENAI_API_KEY`), `deepseek` (`DEEPSEEK_API_KEY`), `proxyapi` (`PROXYAPI_API_KEY`).

### 4. Search Rank Tracking & Interactive Telegram Bot (`OzonTelegramBot`)

```python
from ozon_parser import OzonClient, OzonTelegramBot, TelegramNotifier, rank_results_to_excel

with OzonClient(cookies="...", tracker_db="ozon_prices.db") as ozon:
    rank = ozon.check_rank(1619925434, "видеокарта rtx 4060", max_pages=3)
    print(f"Position: #{rank.position} (Page {rank.page}, Delta: {rank.rank_delta})")
    rank_results_to_excel([rank], "result/ozon_ranks.xlsx")

    summary = ozon.analyze_reviews(1619925434, ai_mode="offline")

tg = TelegramNotifier(bot_token="...", chat_id="...", proxy="socks5://127.0.0.1:1080")
tg.send_review_summary(summary)

# Interactive polling bot (/start, /search, /drops, /rank, /reviews, /seller + Excel uploads):
bot = OzonTelegramBot(
    bot_token="123456789:AAF...",
    proxy="http://login:password@proxy-domain.space:port",
    mobileproxy_key="YOUR_MOBILEPROXY_KEY",
    tg_proxy="socks5://127.0.0.1:1080",
)
# bot.run_polling()  # or run: uv run python run_telegram_bot.py / uv run ozon-parser bot --tg-token ...
```

---

<a id="desktop-gui"></a>
## 🖥️ Desktop GUI (`Ozon SDK Pro` — Standalone `.exe` + 7 Tabs)

### 1. Download Standalone Windows App (No Python Required):
1. Download **[OzonSDK_Pro_Windows_x64.zip](https://github.com/eminsk/ozon_parser/releases/latest)** from [Releases](https://github.com/eminsk/ozon_parser/releases).
2. Unpack and launch `OzonSDK_Pro.exe` (includes bundled Chrome TLS `curl_cffi` and Free `g4f` AI engine out of the box!).

### 2. Or Launch via Python / PyPI:
Install `[gui]` (`uv add "ozon-sdk-pro[gui]"` or `uv sync --extra gui`) and run:

```bash
uvx --from "ozon-sdk-pro[gui]" ozon-gui
# or from cloned repo:
uv run python run_gui.py
# or double-click run_gui.bat
```

1. **🔍 Парсер**: Mixed Ozon targets (product URLs, SKUs, categories, seller storefronts, search keywords), price/discount/rating/keyword filters, seller INN lookup, `[browser]` fallback toggle, 24/7 loop.
2. **📦 Каталог товаров**: Live cards with price, `💳 Ozon Карта`, price drop indicators (`📉`), seller + INN, *«Открыть на Ozon ↗»*, and 1-click **Excel `.xlsx`**, **✈ Excel → TG**, **CSV**, and **JSON** export.
3. **📈 Позиции (Rank)**: Batch `SKU : keyword` scanning across pages `1..N`, sort selection, SQLite `▲`/`▼` deltas, Excel export & **✈ Позиции → TG**.
4. **💬 Умные отзывы + AI**: Extract paginated buyer reviews & pros/cons using **Offline**, **Free `g4f`**, **Local `Ollama`**, or **Paid APIs**, with built-in **`⚡ Проверить AI`**, **Excel export**, and **Telegram** summary + `.xlsx` upload button.
5. **🌐 Прокси и Сессия**: HTTP/SOCKS5 proxy, **MobileProxy.rent 4G rotation URL/key** (with 1-click 3h Free Trial button), Cookies/User-Agent, 1-click **Chrome Cookie Capture (`[browser]`)**, and API Ping test.
6. **✈️ Telegram & 📋 Журнал**: Isolated Telegram SOCKS5/HTTP proxy, **1-click interactive `🤖 Запустить Telegram-бота`** (`OzonTelegramBot` polling), live execution log (`storage/gui_config.json`), and **`☕ Донат`** support dialog in the top bar.

<p align="center">
  <img src="docs/images/gui_catalog.png" alt="Ozon SDK Pro Desktop GUI — Catalog Feed, Ozon Card & Seller INN" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_reviews_ai.png" alt="Ozon SDK Pro Desktop GUI — Smart Reviews & Free/Paid AI Engine" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_telegram.png" alt="Ozon SDK Pro Desktop GUI — Interactive Telegram Bot & Alerts" width="820">
</p>
<p align="center">
  <img src="docs/images/gui_proxy.png" alt="Ozon SDK Pro Desktop GUI — Proxy, MobileProxy & Cookie Capture" width="820">
</p>

---

## 🌐 Choosing & Configuring Proxies

* **Static Server IPv4 / SOCKS5 (~$0.50/mo):** Suitable for light single-worker tasks alongside captured browser cookies (`--cookies` or `[browser]`).
* **Pay-As-You-Go Mobile Proxies (~$2.50/GB):** [AstroProxy](https://astroproxy.com) or [Asocks](https://asocks.com) — billed only for compact Composer JSON payloads.
* **Dedicated 4G/LTE Modems with Instant IP Rotation (Recommended):** [MobileProxy.rent / MobileProxy.space](https://mobileproxy.rent/?p=279117) ([Claim Free 3-Hour Trial](https://mobileproxy.rent/user.html?free&p=279117)):
  ```python
  from ozon_parser import OzonClient

  with OzonClient(
      proxy="http://login:password@proxy-domain.space:port",
      mobileproxy_key="YOUR_ROTATION_KEY",  # expands to changeip.mobileproxy.space automatically
  ) as ozon:
      products = ozon.search("видеокарта rtx 4060", max_pages=2)
  ```

---

## 💻 CLI Commands (`ozon-parser` / `ozon-sdk` — 14 Subcommands)

```bash
uv run ozon-parser ping
uv run ozon-parser card 1619925434 --with-seller -o item.xlsx
uv run ozon-parser seller 123456 --info-only
uv run ozon-parser seller https://www.ozon.ru/seller/shop-123456/ --pages 3 -o seller.xlsx
uv run ozon-parser search "ноутбук" --pages 2 --min-discount 15 -o search.xlsx
uv run ozon-parser category https://www.ozon.ru/category/elektronika-15500/ --pages 2 -o cat.xlsx
uv run ozon-parser reviews 1619925434 --mode free --pages 3 -o reviews.xlsx
uv run ozon-parser rank 1619925434 "видеокарта rtx 4060" --pages 3 -o ranks.xlsx
uv run ozon-parser drops --db ozon_prices.db
uv run ozon-parser card-discount 5990 5490
uv run ozon-parser ai --list
uv run ozon-parser ai --quick-scan
uv run ozon-parser ai --ask "Выдели главные плюсы" --mode free
uv run ozon-parser cookies --visible -o ozon_cookies.txt
uv run ozon-parser mcp
uv run ozon-parser gui
uv run ozon-parser bot --tg-token "123:AAF..." --mobileproxy-key "KEY" --tg-proxy "socks5://127.0.0.1:1080"
uv run ozon-parser search "ноутбук" -o search.xlsx --tg-token "123:AAF..." --tg-chat-id "999"
```

---

<a id="mcp-server-for-ai-agents"></a>
## 🤖 Native MCP Server (`ozon-mcp` — 9 Tools)

Supports MCP protocol versions `2025-11-25`, `2025-06-18`, and `2024-11-05` (`serverInfo.name = "ozon-parser-mcp"`):

```json
{
  "mcpServers": {
    "ozon": {
      "command": "uvx",
      "args": ["--from", "ozon-sdk-pro", "ozon-mcp"],
      "env": {
        "OZON_TRACKER_DB": "ozon_prices.db",
        "OZON_AI_MODE": "auto"
      }
    }
  }
}
```

Tools: `ozon_get_card`, `ozon_get_seller`, `ozon_search`, `ozon_get_seller_catalog`, `ozon_get_reviews`, `ozon_smart_reviews`, `ozon_price_drops`, `ozon_check_rank`, `ozon_ai_providers`.

---

## 🧪 Tests (`pytest`)

```bash
uv sync --all-extras
uv run --with pytest pytest -v
```

**29 tests passing** across **18 Python runtimes** in CI on **Linux, Windows & macOS** (CPython 3.8–3.16, Free-Threaded 3.13t–3.16t, PyPy 3.8–3.12), including `OzonTelegramBot` commands, callbacks, batch multi-URL scraping, Excel uploads, and `BotInstanceLock`.

## ☕ Support & Donations

If `ozon-sdk-pro` helps automate your analytics or saves development time:
* ⭐ Star the repository on [GitHub](https://github.com/eminsk/ozon_parser)
* 🌐 Use our partner link for [3-Hour Free Mobile Proxy Trial (No VPN)](https://mobileproxy.rent/user.html?free&p=279117)
* 💎 **USDT (TRC-20):** `TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P` ([Verify on TronScan](https://tronscan.org/#/address/TDVbEdnpgNgoAhNcn1EwXxWHiR3RKLit5P))

## 📄 License

MIT License.
