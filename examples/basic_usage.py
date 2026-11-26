"""
Basic usage example for Ozon SDK Pro (`ozon_parser`).
Run: uv run python examples/basic_usage.py
"""

from ozon_parser import AIClient, OzonClient, extract_sku, list_ai_providers, to_excel


def main() -> None:
    sku = extract_sku("https://www.ozon.ru/product/videokarta-rtx-4060-1619925434/")
    print(f"Resolved SKU: {sku}")

    # Inspect configured Free (g4f / local Ollama) + Paid AI providers without network calls
    providers = list_ai_providers(tier="all")
    print(f"Discovered {len(providers)} AI provider presets/entries.")

    # Direct Ozon card, seller INN, reviews, and Excel export (supply cookies/proxy when running live)
    with OzonClient(tracker_db="ozon_prices.db") as ozon:
        ping = ozon.ping()
        print("Ping:", ping)
        if ping.get("ok"):
            item = ozon.get_product(sku, with_seller=True)
            print(item.name, item.price, "Ozon Card:", item.card_price, "INN:", item.company_inn)
            summary = ozon.analyze_reviews(sku, ai_mode="free", ai_provider="g4f")
            print("Pros:", summary.top_pros, "Cons:", summary.top_cons)
            to_excel([item], "result/demo_ozon.xlsx")

    ai = AIClient(mode="auto")
    print("AI default mode:", ai.mode)


if __name__ == "__main__":
    main()
