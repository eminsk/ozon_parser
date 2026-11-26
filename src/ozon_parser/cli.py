"""
Command-Line Interface (CLI) for Ozon SDK Pro (`ozon-parser` / `ozon-sdk`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from ozon_parser import __version__
from ozon_parser.client import OzonClient, filter_products
from ozon_parser.config import DOCS_URL, ISSUES_URL, TELEGRAM_CHANNEL_URL
from ozon_parser.export import (
    rank_results_to_excel,
    reviews_to_excel,
    to_csv,
    to_excel,
    to_json,
    to_jsonl,
)
from ozon_parser.models import OzonProduct
from ozon_parser.telegram import OzonTelegramBot, TelegramNotifier
from ozon_parser.tracker import OzonPriceTracker


def _export_results(products: List[OzonProduct], output_path: Optional[str]) -> Optional[Path]:
    if not output_path:
        return None
    path = Path(output_path)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        to_excel(products, path)
    elif ext == ".csv":
        to_csv(products, path)
    elif ext == ".jsonl":
        to_jsonl(products, path)
    else:
        to_json(products, path)
    print(f"[+] Exported {len(products)} item(s) -> {path}")
    return path


def _add_tg_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--tg-token", default=None, help="Optional Telegram Bot Token to send results/Excel")
    subparser.add_argument("--tg-chat-id", default=None, help="Optional Telegram Chat or Channel ID")
    subparser.add_argument("--tg-proxy", default=None, help="Optional separate SOCKS5/HTTP proxy for Telegram API")


def _notify_cli_export(args: argparse.Namespace, products: List[OzonProduct], exported: Optional[Path], title: str) -> None:
    token = getattr(args, "tg_token", None)
    chat_id = getattr(args, "tg_chat_id", None)
    if not (token and chat_id):
        return
    notifier = TelegramNotifier(token, chat_id, proxy=getattr(args, "tg_proxy", None))
    if exported and exported.exists():
        notifier.send_excel(exported, caption=f"📊 {title} ({len(products)} шт.)")
    elif products:
        notifier.notify_many(products[:5])


def _print_products_table(products: List[OzonProduct]) -> None:
    if not products:
        print("No products found.")
        return
    for idx, p in enumerate(products, start=1):
        price_str = f"{p.price:,.0f} RUB" if p.price > 0 else "n/a"
        card_str = f" (Ozon Card: {p.card_price:,.0f} RUB)" if p.card_price else ""
        disc_str = f" (-{p.discount}%)" if p.discount > 0 else ""
        rev_str = f" | ★ {p.rating} ({p.reviews_count} reviews)" if (p.rating or p.reviews_count) else ""
        print(f"{idx:2d}. [{p.id}] {p.name[:60]} | {price_str}{card_str}{disc_str}{rev_str}")


def _build_client(args: argparse.Namespace) -> OzonClient:
    return OzonClient(
        proxy=getattr(args, "proxy", None),
        proxy_change_url=getattr(args, "proxy_change_url", None),
        mobileproxy_key=getattr(args, "mobileproxy_key", None),
        cookies=getattr(args, "cookies", None),
        user_agent=getattr(args, "user_agent", None),
        use_browser_fallback=bool(getattr(args, "browser", False)),
        tracker_db=getattr(args, "db", None),
    )


def _add_network_args(subparser: argparse.ArgumentParser, *, db_default: Optional[str] = "ozon_prices.db") -> None:
    subparser.add_argument("--proxy", default=None, help="Proxy URL (http://user:pass@ip:port or socks5://...)")
    subparser.add_argument("--proxy-change-url", default=None, help="Mobile proxy IP rotation URL")
    subparser.add_argument("--mobileproxy-key", default=None, help="MobileProxy.rent/space API rotation key")
    subparser.add_argument("--cookies", default=None, help="Browser Cookie header string for Ozon session")
    subparser.add_argument("--user-agent", default=None, help="Custom User-Agent override")
    subparser.add_argument("--browser", action="store_true", help="Enable optional [browser] Selenium fallback on anti-bot")
    subparser.add_argument("--db", default=db_default, help="SQLite price history path")


def _handle_ai_command(args: argparse.Namespace) -> int:
    """Handle `ozon-parser ai` (Free `g4f`/Ollama + Paid OpenAI/DeepSeek/OpenRouter/ProxyAPI/Groq)."""
    from ozon_parser.ai import (
        fetch_g4f_provider_models,
        find_ai_provider,
        generate_completion,
        is_g4f_available,
        list_ai_providers,
        quick_scan_ai_providers,
        test_ai_provider,
    )

    if args.quick_scan:
        results = quick_scan_ai_providers(timeout=min(args.timeout, 8.0))
        if args.json:
            print(json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2))
            return 0
        if not results:
            print('No live g4f or configured paid providers detected. Install free AI: uv add "ozon-sdk-pro[ai]"')
            return 0
        for r in results:
            tag = "LIVE" if r.success else "DEAD"
            detail = r.response_text[:60] if r.success else f"{r.error_type}: {r.error_message}"[:70]
            print(f"[{tag:4s}] {r.provider:<18} ({r.tier}/{r.model or 'default'}) {r.latency_seconds:>5.2f}s | {detail}")
        return 0

    if args.ask:
        res = generate_completion(
            args.ask,
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            api_key=args.key,
            base_url=args.url,
            timeout=args.timeout,
        )
        if args.json:
            print(res.model_dump_json(indent=2))
        elif res.ok:
            print(f"[{res.tier}:{res.provider}/{res.model} in {res.latency_seconds}s]\n{res.content}")
        else:
            print(f"[FAILED] {res.error}", file=sys.stderr)
        return 0 if res.ok else 1

    tier_filter = args.tier
    if args.local:
        tier_filter = "local"
    elif args.paid and tier_filter == "all":
        tier_filter = "paid"

    if args.list or (not args.provider):
        items = list_ai_providers(
            tier=tier_filter,
            only_working=args.working,
            only_free=args.free,
            search_query=args.search,
        )
        if args.json:
            print(json.dumps({
                "g4f_installed": is_g4f_available(),
                "count": len(items),
                "providers": [p.model_dump() for p in items],
            }, ensure_ascii=False, indent=2))
            return 0
        print(f"AI Providers ({len(items)}) | g4f installed: {is_g4f_available()}")
        for p in items:
            auth_flag = "KEY" if p.needs_auth else "FREE"
            cfg_flag = "ready" if p.configured else "needs-key"
            print(
                f"{p.index:3d}. [{p.tier:<6s}|{auth_flag:<4s}|{cfg_flag:<9s}] "
                f"{p.id:<18s} model={p.default_model or '-'}"
            )
        if not is_g4f_available():
            print('Tip: install free key-less AI providers via: uv add "ozon-sdk-pro[ai]"')
        return 0

    info = find_ai_provider(args.provider)
    if not info:
        print(f"Error: AI provider {args.provider!r} not found.", file=sys.stderr)
        return 1

    if args.test:
        res = test_ai_provider(
            info.id,
            mode=args.mode,
            model=args.model,
            api_key=args.key,
            base_url=args.url,
            prompt=args.prompt,
            timeout=args.timeout,
        )
        if args.json:
            print(res.model_dump_json(indent=2))
        elif res.success:
            print(f"[OK] {res.provider} ({res.model}) in {res.latency_seconds}s -> {res.response_text}")
        else:
            print(f"[FAIL] {res.provider}: {res.error_type}: {res.error_message}")
            if res.hint:
                print(f"Hint: {res.hint}")
        return 0 if res.success else 1

    models = (
        fetch_g4f_provider_models(info.id, timeout=min(args.timeout, 5.0))
        if info.backend == "g4f"
        else info.models
    )
    if args.json:
        print(json.dumps({**info.model_dump(), "models": models}, ensure_ascii=False, indent=2))
    else:
        print(f"Provider: {info.id} ({info.name}) | backend={info.backend} | tier={info.tier}")
        print(f"Default model: {info.default_model or '-'} | auth_required={info.needs_auth} | configured={info.configured}")
        if info.base_url or info.url:
            print(f"URL: {info.base_url or info.url}")
        print(f"Models ({len(models)}): {', '.join(models[:30]) or '(dynamic / pass --model)'}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="ozon-parser",
        description=(
            f"Ozon SDK Pro v{__version__} — Composer API Inspector, Seller INN Lookup, "
            "Ozon Card Math, Rank Tracker, Smart Reviews, Free/Paid AI, Search, MCP & GUI"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"Telegram Support: {TELEGRAM_CHANNEL_URL}\n"
            f"Docs: {DOCS_URL}\n"
            f"Issues: {ISSUES_URL}"
        ),
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 1. ping
    ping_p = subparsers.add_parser("ping", help="Check Ozon composer connectivity, anti-bot status, and TLS backend")
    _add_network_args(ping_p, db_default=None)

    # 2. card
    card_p = subparsers.add_parser("card", help="Fetch single Ozon product card (prices, Ozon Card, specs, seller)")
    card_p.add_argument("target", help="Ozon product URL or numeric SKU")
    card_p.add_argument("--with-seller", action="store_true", help="Enrich with Seller legal INN, orders, tenure")
    card_p.add_argument("-o", "--output", help="Save output (.json, .jsonl, .csv, .xlsx)")
    _add_network_args(card_p)

    # 3. seller
    seller_p = subparsers.add_parser("seller", help="Inspect Ozon seller INN/rating or scrape seller storefront catalog")
    seller_p.add_argument("target", help="Seller URL (/seller/123), seller ID, or product URL")
    seller_p.add_argument("--info-only", action="store_true", help="Only fetch seller legal info (company, INN, orders)")
    seller_p.add_argument("-p", "--pages", type=int, default=3, help="Max catalog pages")
    seller_p.add_argument("-n", "--limit", type=int, default=100, help="Max items")
    seller_p.add_argument("--sort", default="score", help="Sort order (score, price_asc, price_desc, rating, new)")
    seller_p.add_argument("--with-seller", action="store_true", help="Attach seller INN details to catalog rows")
    seller_p.add_argument("-o", "--output", help="Save catalog (.xlsx, .csv, .json, .jsonl)")
    _add_network_args(seller_p)
    _add_tg_args(seller_p)

    # 4. search
    search_p = subparsers.add_parser("search", help="Search Ozon catalog")
    search_p.add_argument("query", help="Search keyword")
    search_p.add_argument("-p", "--pages", type=int, default=2, help="Max pages")
    search_p.add_argument("-n", "--limit", type=int, default=50, help="Max items")
    search_p.add_argument("--sort", default="score", help="Sort order (score, price_asc, price_desc, rating, new)")
    search_p.add_argument("--min-price", type=float, default=0.0, help="Minimum price filter (RUB)")
    search_p.add_argument("--max-price", type=float, default=999_999_999.0, help="Maximum price filter (RUB)")
    search_p.add_argument("--min-discount", type=int, default=0, help="Minimum discount percentage")
    search_p.add_argument("--min-rating", type=float, default=0.0, help="Minimum rating filter")
    search_p.add_argument("--with-seller", action="store_true", help="Enrich items with seller modal metadata")
    search_p.add_argument("-o", "--output", help="Save output (.xlsx, .csv, .json, .jsonl)")
    _add_network_args(search_p)
    _add_tg_args(search_p)

    # 5. category
    cat_p = subparsers.add_parser("category", help="Parse products from an Ozon category URL or /category/... path")
    cat_p.add_argument("target", help="Ozon category URL or relative /category/... path")
    cat_p.add_argument("-p", "--pages", type=int, default=2, help="Max pages")
    cat_p.add_argument("-n", "--limit", type=int, default=50, help="Max items")
    cat_p.add_argument("--sort", default="score", help="Sort order")
    cat_p.add_argument("-o", "--output", help="Save output (.xlsx, .csv, .json, .jsonl)")
    _add_network_args(cat_p)
    _add_tg_args(cat_p)

    # 6. reviews
    rev_p = subparsers.add_parser("reviews", help="Smart Review Analyzer (offline NLP, free g4f/Ollama, or paid LLM)")
    rev_p.add_argument("target", help="Ozon product URL or numeric SKU")
    rev_p.add_argument("-p", "--pages", type=int, default=3, help="Max review pages")
    rev_p.add_argument("-n", "--limit", type=int, default=100, help="Max reviews to inspect")
    rev_p.add_argument("--sort", default="published_at_desc", help="Review sort (published_at_desc, score_desc, score_asc, helpful)")
    rev_p.add_argument("--mode", default="auto", choices=["auto", "free", "paid", "local", "offline"], help="AI mode")
    rev_p.add_argument("--provider", default=None, help="AI provider (g4f, Yqcloud, ollama, openai, deepseek, openrouter, proxyapi, groq)")
    rev_p.add_argument("--ai-key", default=None, help="Optional API key for paid OpenAI-compatible providers")
    rev_p.add_argument("--ai-url", default=None, help="Optional custom OpenAI-compatible base URL")
    rev_p.add_argument("--ai-model", default=None, help="Optional AI model name")
    rev_p.add_argument("--ai-timeout", type=float, default=25.0, help="AI completion timeout in seconds")
    rev_p.add_argument("-o", "--output", help="Save review summary (.json or .xlsx)")
    _add_network_args(rev_p)

    # 7. rank
    rank_p = subparsers.add_parser("rank", help="Check Ozon search rank position for a keyword query")
    rank_p.add_argument("target", help="Ozon product URL or numeric SKU")
    rank_p.add_argument("query", help="Search keyword query")
    rank_p.add_argument("-p", "--pages", type=int, default=3, help="Max search pages")
    rank_p.add_argument("--sort", default="score", help="Sort order")
    rank_p.add_argument("-o", "--output", help="Save rank report (.xlsx or .json)")
    _add_network_args(rank_p)

    # 8. drops
    drops_p = subparsers.add_parser("drops", help="Show tracked price drops from SQLite")
    drops_p.add_argument("--db", default="ozon_prices.db", help="Path to SQLite tracker DB")
    drops_p.add_argument("-n", "--limit", type=int, default=50, help="Max records")

    # 9. card-discount
    cd_p = subparsers.add_parser("card-discount", help="Calculate Ozon Card savings in RUB and percentage")
    cd_p.add_argument("price", type=float, help="Regular price in RUB")
    cd_p.add_argument("card_price", type=float, help="Ozon Card price in RUB")

    # 10. ai
    ai_p = subparsers.add_parser("ai", help="Discover, health-check, and query Free (g4f/Ollama) & Paid AI providers")
    ai_p.add_argument("--list", action="store_true", help="List available free & paid AI providers")
    ai_p.add_argument("--tier", default="all", choices=["all", "free", "paid", "local", "g4f"], help="Provider tier")
    ai_p.add_argument("--working", action="store_true", help="Show only working g4f/active providers")
    ai_p.add_argument("--free", action="store_true", help="Filter zero-key providers")
    ai_p.add_argument("--paid", action="store_true", help="Filter paid/key providers")
    ai_p.add_argument("--local", action="store_true", help="Filter local key-free providers (Ollama, LM Studio)")
    ai_p.add_argument("--search", default="", help="Search providers by name or URL")
    ai_p.add_argument("-p", "--provider", default=None, help="Select provider by index, slug, or g4f name")
    ai_p.add_argument("--models", action="store_true", help="Show supported models for --provider")
    ai_p.add_argument("-t", "--test", action="store_true", help="Run latency/error health-check")
    ai_p.add_argument("--quick-scan", action="store_true", help="Quick-scan popular free g4f + configured paid providers")
    ai_p.add_argument("--ask", default=None, help="Send a prompt using free, local, or paid models")
    ai_p.add_argument("--mode", default="auto", choices=["auto", "free", "paid", "local"], help="Execution mode")
    ai_p.add_argument("-m", "--model", default=None, help="Specific AI model name")
    ai_p.add_argument("--key", default=None, help="Optional API key for paid endpoint")
    ai_p.add_argument("--url", default=None, help="Optional OpenAI-compatible base URL")
    ai_p.add_argument("--prompt", default="Ответь одним словом: Работает", help="Health-check test prompt")
    ai_p.add_argument("--timeout", type=float, default=12.0, help="Timeout in seconds")
    ai_p.add_argument("--json", action="store_true", help="Emit structured JSON output")

    # 11. cookies
    ck_p = subparsers.add_parser("cookies", help="Harvest Ozon session cookies via optional [browser] Chrome helper")
    ck_p.add_argument("--url", default="https://www.ozon.ru", help="Target Ozon URL")
    ck_p.add_argument("--visible", action="store_true", help="Show visible Chrome window")
    ck_p.add_argument("--proxy", default=None, help="Optional Chrome proxy URL")
    ck_p.add_argument("-o", "--output", help="Save Cookie string to text file")

    # 12. mcp
    mcp_p = subparsers.add_parser("mcp", help="Start native JSON-RPC 2.0 MCP Server over stdio")
    _add_network_args(mcp_p, db_default=None)

    # 13. gui
    subparsers.add_parser("gui", help="Launch Dark-Themed 7-Tab Ozon SDK Pro Desktop GUI (requires [gui] extra)")

    # 14. bot
    bot_p = subparsers.add_parser(
        "bot",
        help="Start interactive OzonTelegramBot with live progress bars, /drops, /rank, /reviews, /seller & Excel export",
    )
    bot_p.add_argument("--tg-token", default=None, help="Telegram Bot Token (or set OZON_TG_TOKEN env var)")
    bot_p.add_argument("--tg-proxy", default=None, help="Optional SOCKS5/HTTP proxy for Telegram API (or OZON_TG_PROXY)")
    bot_p.add_argument("--channel-id", default=None, help="Optional channel/chat ID for forwarding reports")
    bot_p.add_argument("--workers", type=int, default=2, help="Parallel worker threads (1..16)")
    bot_p.add_argument("-n", "--limit", type=int, default=50, help="Default max items per search (1..5000)")
    bot_p.add_argument("-p", "--pages", type=int, default=2, help="Default search pages")
    bot_p.add_argument("--sort", default="score", help="Default search sort order")
    bot_p.add_argument("--no-seller", action="store_true", help="Disable seller legal/INN lookup during search")
    _add_network_args(bot_p)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    if args.command == "gui":
        from ozon_parser.gui import main_gui
        return main_gui()

    if args.command == "bot":
        import os

        token = (args.tg_token or os.getenv("OZON_TG_TOKEN", "")).strip()
        if not token:
            print("Error: --tg-token or OZON_TG_TOKEN environment variable is required.", file=sys.stderr)
            return 1
        bot = OzonTelegramBot(
            bot_token=token,
            proxy=args.proxy,
            proxy_change_url=args.proxy_change_url,
            mobileproxy_key=args.mobileproxy_key,
            tg_proxy=args.tg_proxy or os.getenv("OZON_TG_PROXY"),
            channel_id=args.channel_id or os.getenv("OZON_TG_CHANNEL"),
            workers=args.workers,
            limit=args.limit,
            max_pages=args.pages,
            sort=args.sort,
            with_seller=not args.no_seller,
            cookies=args.cookies,
            user_agent=args.user_agent,
            use_browser_fallback=bool(args.browser),
            tracker_db=args.db or "ozon_prices.db",
        )
        bot.run_polling()
        return 0

    if args.command == "mcp":
        from ozon_parser.mcp_server import OzonMCPServer
        srv = OzonMCPServer(
            proxy=args.proxy,
            proxy_change_url=args.proxy_change_url,
            mobileproxy_key=args.mobileproxy_key,
            cookies=args.cookies,
            user_agent=args.user_agent,
            use_browser_fallback=args.browser,
            tracker_db=args.db,
        )
        srv.run_stdio()
        return 0

    if args.command == "ai":
        return _handle_ai_command(args)

    if args.command == "card-discount":
        print(json.dumps(OzonClient.card_savings(args.price, args.card_price), indent=2))
        return 0

    if args.command == "cookies":
        from ozon_parser.browser import harvest_ozon_cookies
        cookie_str = harvest_ozon_cookies(args.url, headless=not args.visible, proxy=args.proxy)
        if args.output:
            Path(args.output).write_text(cookie_str, encoding="utf-8")
            print(f"[+] Saved cookies -> {args.output}")
        else:
            print(cookie_str)
        return 0

    if args.command == "drops":
        tracker = OzonPriceTracker(args.db)
        drops = tracker.get_price_drops(limit=args.limit)
        if not drops:
            print("No price drops recorded yet.")
            return 0
        for d in drops:
            diff = round((d.old_price or 0) - d.price, 2)
            print(f"[{d.sku}] {d.name}: {d.price:,.0f} RUB (was {d.old_price:,.0f}, -{diff:,.0f} RUB)")
        return 0

    with _build_client(args) as client:
        if args.command == "ping":
            print(json.dumps(client.ping(), indent=2))
            return 0

        if args.command == "card":
            prod = client.get_product(args.target, with_seller=args.with_seller)
            print(prod.to_json(indent=2))
            _export_results([prod], args.output)
            return 0

        if args.command == "seller":
            if args.info_only:
                seller = client.get_seller(args.target)
                print(seller.model_dump_json(indent=2))
                return 0
            products = client.get_seller_catalog(
                args.target,
                max_pages=args.pages,
                limit=args.limit,
                sort=args.sort,
                with_seller=args.with_seller,
            )
            _print_products_table(products)
            exported = _export_results(products, args.output)
            _notify_cli_export(args, products, exported, f"Ozon Продавец {args.target}")
            return 0

        if args.command == "search":
            raw = client.search(
                args.query,
                max_pages=args.pages,
                limit=args.limit,
                sort=args.sort,
                with_seller=args.with_seller,
            )
            products = filter_products(
                raw,
                min_price=args.min_price,
                max_price=args.max_price,
                min_discount=args.min_discount,
                min_rating=args.min_rating,
            )
            _print_products_table(products)
            exported = _export_results(products, args.output)
            _notify_cli_export(args, products, exported, f"Ozon Поиск: {args.query}")
            return 0

        if args.command == "category":
            products = client.get_category(
                args.target,
                max_pages=args.pages,
                limit=args.limit,
                sort=args.sort,
            )
            _print_products_table(products)
            exported = _export_results(products, args.output)
            _notify_cli_export(args, products, exported, f"Ozon Категория {args.target}")
            return 0

        if args.command == "reviews":
            summary = client.analyze_reviews(
                args.target,
                limit=args.limit,
                max_pages=args.pages,
                sort=args.sort,
                ai_key=args.ai_key,
                ai_base_url=args.ai_url,
                ai_model=args.ai_model,
                ai_mode=args.mode,
                ai_provider=args.provider,
                ai_timeout=args.ai_timeout,
            )
            print(f"[{summary.sku}] {summary.product_name}")
            print(f"Analyzed: {summary.total_analyzed} / {summary.total_available} | Avg: {summary.avg_rating} | Mode: {summary.summary_mode}")
            print("Pros (+):", summary.top_pros)
            print("Cons (-):", summary.top_cons)
            if args.output:
                out_p = Path(args.output)
                if out_p.suffix.lower() == ".xlsx":
                    reviews_to_excel(summary, out_p)
                else:
                    out_p.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
                print(f"[+] Saved review summary -> {out_p}")
            return 0

        if args.command == "rank":
            res = client.check_rank(args.target, args.query, max_pages=args.pages, sort=args.sort)
            print(res.model_dump_json(indent=2))
            if args.output:
                out_p = Path(args.output)
                if out_p.suffix.lower() == ".xlsx":
                    rank_results_to_excel([res], out_p)
                else:
                    out_p.write_text(res.model_dump_json(indent=2), encoding="utf-8")
                print(f"[+] Exported rank report -> {out_p}")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
