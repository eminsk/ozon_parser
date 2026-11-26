"""
Native Model Context Protocol (MCP) Server for Ozon SDK Pro (`ozon-mcp`).

Exposes 9 JSON-RPC 2.0 stdio tools for Ozon product cards, seller legal/INN info,
catalog search, seller catalogs, paginated reviews, AI review summaries (`g4f`/Ollama/Paid),
SQLite price-drop history, search rank tracking, and AI provider discovery/testing.
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, Dict, List, Optional

from ozon_parser.client import OzonClient, filter_products
from ozon_parser.export import to_excel
from ozon_parser.tracker import OzonPriceTracker

SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2024-11-05",
)
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

MCP_TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "ozon_get_card",
        "description": "Fetch Ozon product metadata, regular & Ozon Card prices, specs, images, and optional seller INN/rating.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Ozon product URL or numeric SKU"},
                "with_seller": {"type": "boolean", "default": False, "description": "Fetch seller modal INN, orders, tenure"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ozon_get_seller",
        "description": "Fetch Ozon seller company name, INN, orders count, working time, average rating, and reviews count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Seller URL (/seller/123), seller ID, or product URL"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ozon_search",
        "description": "Search Ozon catalog with price, discount, rating filters and optional Excel export.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'беспроводные наушники')"},
                "min_price": {"type": "number", "default": 0},
                "max_price": {"type": "number", "default": 999999999},
                "min_discount": {"type": "integer", "default": 0},
                "min_rating": {"type": "number", "default": 0.0},
                "sort": {"type": "string", "default": "score"},
                "limit": {"type": "integer", "default": 20},
                "max_pages": {"type": "integer", "default": 1},
                "excel_path": {"type": "string", "description": "Optional .xlsx output path"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "ozon_get_seller_catalog",
        "description": "Scrape product listings for a specific Ozon seller storefront.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Seller URL, seller ID, or sample product URL"},
                "max_pages": {"type": "integer", "default": 3},
                "limit": {"type": "integer", "default": 100},
                "excel_path": {"type": "string", "description": "Optional .xlsx output path"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ozon_get_reviews",
        "description": "Fetch paginated raw Ozon buyer reviews, rating histogram, photo count, and deterministic offline pros/cons.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Ozon product URL or numeric SKU"},
                "max_pages": {"type": "integer", "default": 3},
                "limit": {"type": "integer", "default": 50},
                "sort": {"type": "string", "default": "published_at_desc"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ozon_smart_reviews",
        "description": "Extract Ozon product reviews & summarize top pros/cons via offline NLP, free (`g4f`/Ollama), or paid LLM APIs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Ozon product URL or numeric SKU"},
                "max_pages": {"type": "integer", "default": 3},
                "limit": {"type": "integer", "default": 100},
                "sort": {"type": "string", "default": "published_at_desc"},
                "ai_mode": {"type": "string", "default": "auto", "description": "auto, free, paid, local, or offline"},
                "ai_provider": {"type": "string", "description": "Provider slug/name (g4f, Yqcloud, ollama, openai, deepseek, openrouter, proxyapi, groq)"},
                "ai_model": {"type": "string"},
                "ai_base_url": {"type": "string"},
                "ai_key": {"type": "string"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "ozon_price_drops",
        "description": "Query SQLite price tracker for Ozon price drops or price history of a SKU.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "integer", "description": "Optional product SKU for chronological history"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "ozon_check_rank",
        "description": "Check an Ozon product's organic search rank for a keyword query and log SQLite history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Ozon product URL or numeric SKU"},
                "query": {"type": "string", "description": "Search keyword"},
                "max_pages": {"type": "integer", "default": 3},
                "sort": {"type": "string", "default": "score"},
            },
            "required": ["target", "query"],
        },
    },
    {
        "name": "ozon_ai_providers",
        "description": "List, inspect, health-check, or prompt Free (`g4f`/Ollama) and Paid AI providers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "default": "list", "description": "list, models, test, quick_scan, or chat"},
                "tier": {"type": "string", "default": "all"},
                "only_working": {"type": "boolean", "default": False},
                "only_free": {"type": "boolean", "default": False},
                "search": {"type": "string", "default": ""},
                "provider": {"type": "string"},
                "model": {"type": "string"},
                "mode": {"type": "string", "default": "auto"},
                "prompt": {"type": "string", "default": "Ответь одним словом: Работает"},
                "timeout": {"type": "number", "default": 12.0},
            },
        },
    },
]


class OzonMCPServer:
    """Native Model Context Protocol (MCP) JSON-RPC 2.0 stdio server (`ozon-parser-mcp`)."""

    def __init__(
        self,
        *,
        proxy: Optional[str] = None,
        proxy_change_url: Optional[str] = None,
        cookies: Optional[str] = None,
        user_agent: Optional[str] = None,
        use_browser_fallback: Optional[bool] = None,
        tracker_db: Optional[str] = None,
        client: Optional[OzonClient] = None,
    ) -> None:
        self.proxy = proxy or os.environ.get("OZON_PROXY")
        self.proxy_change_url = proxy_change_url or os.environ.get("OZON_PROXY_CHANGE_URL")
        self.cookies = cookies or os.environ.get("OZON_COOKIES")
        self.user_agent = user_agent or os.environ.get("OZON_USER_AGENT")
        env_bf = (os.environ.get("OZON_BROWSER_FALLBACK") or "").strip().lower() in ("1", "true", "yes")
        self.use_browser_fallback = env_bf if use_browser_fallback is None else bool(use_browser_fallback)
        self.tracker_db = tracker_db or os.environ.get("OZON_TRACKER_DB") or "ozon_prices.db"
        self._client = client

    @property
    def client(self) -> OzonClient:
        if self._client is None:
            self._client = OzonClient(
                proxy=self.proxy,
                proxy_change_url=self.proxy_change_url,
                cookies=self.cookies,
                user_agent=self.user_agent,
                use_browser_fallback=self.use_browser_fallback,
                tracker_db=self.tracker_db,
            )
        return self._client

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC 2.0 request or notification."""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params") or {}

        if req_id is None and method.startswith("notifications/"):
            return None

        try:
            if method == "initialize":
                from ozon_parser import __version__
                client_ver = params.get("protocolVersion")
                negotiated = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": negotiated,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "ozon-parser-mcp", "version": __version__},
                    },
                }

            if method == "ping":
                return {"jsonrpc": "2.0", "id": req_id, "result": {}}

            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS_SCHEMA}}

            if method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments") or {}
                output = self._call_tool(tool_name, args)
                call_result: Dict[str, Any] = {
                    "content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False, indent=2)}],
                    "isError": False,
                }
                if isinstance(output, dict):
                    call_result["structuredContent"] = output
                return {"jsonrpc": "2.0", "id": req_id, "result": call_result}

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            }

    def _call_tool(self, name: str, args: Dict[str, Any]) -> Any:
        if name == "ozon_get_card":
            prod = self.client.get_product(args["target"], with_seller=bool(args.get("with_seller", False)))
            return prod.to_dict()

        if name == "ozon_get_seller":
            return self.client.get_seller(args["target"]).model_dump()

        if name == "ozon_search":
            raw = self.client.search(
                str(args["query"]),
                max_pages=int(args.get("max_pages", 1)),
                limit=int(args.get("limit", 20)),
                sort=str(args.get("sort", "score")),
            )
            items = filter_products(
                raw,
                min_price=float(args.get("min_price", 0)),
                max_price=float(args.get("max_price", 999_999_999)),
                min_discount=int(args.get("min_discount", 0)),
                min_rating=float(args.get("min_rating", 0.0)),
            )
            if args.get("excel_path"):
                to_excel(items, args["excel_path"])
            return {"count": len(items), "items": [p.to_dict() for p in items]}

        if name == "ozon_get_seller_catalog":
            items = self.client.get_seller_catalog(
                args["target"],
                max_pages=int(args.get("max_pages", 3)),
                limit=int(args.get("limit", 100)),
            )
            if args.get("excel_path"):
                to_excel(items, args["excel_path"])
            return {"count": len(items), "items": [p.to_dict() for p in items]}

        if name == "ozon_get_reviews":
            summary = self.client.fetch_reviews(
                args["target"],
                max_pages=int(args.get("max_pages", 3)),
                limit=int(args.get("limit", 50)),
                sort=str(args.get("sort", "published_at_desc")),
            )
            data = summary.model_dump()
            data["reviews"] = data["reviews"][:20]
            return data

        if name == "ozon_smart_reviews":
            summary = self.client.analyze_reviews(
                args["target"],
                max_pages=int(args.get("max_pages", 3)),
                limit=int(args.get("limit", 100)),
                sort=str(args.get("sort", "published_at_desc")),
                ai_key=args.get("ai_key"),
                ai_mode=args.get("ai_mode"),
                ai_provider=args.get("ai_provider"),
                ai_model=args.get("ai_model"),
                ai_base_url=args.get("ai_base_url"),
            )
            data = summary.model_dump()
            data["reviews"] = data["reviews"][:15]
            return data

        if name == "ozon_price_drops":
            tracker = self.client.tracker or OzonPriceTracker(self.tracker_db)
            if args.get("sku") is not None:
                sku = int(args["sku"])
                return {"sku": sku, "history": [h.model_dump() for h in tracker.get_history(sku)]}
            drops = tracker.get_price_drops(limit=int(args.get("limit", 50)))
            return {"count": len(drops), "drops": [d.model_dump() for d in drops]}

        if name == "ozon_check_rank":
            res = self.client.check_rank(
                args["target"],
                str(args["query"]),
                max_pages=int(args.get("max_pages", 3)),
                sort=str(args.get("sort", "score")),
            )
            return res.model_dump()

        if name == "ozon_ai_providers":
            from ozon_parser.ai import (
                fetch_g4f_provider_models,
                find_ai_provider,
                generate_completion,
                is_g4f_available,
                list_ai_providers,
                quick_scan_ai_providers,
                test_ai_provider,
            )

            action = str(args.get("action") or "list").strip().lower()
            if action == "list":
                items = list_ai_providers(
                    tier=str(args.get("tier") or "all"),
                    only_working=bool(args.get("only_working", False)),
                    only_free=bool(args.get("only_free", False)),
                    search_query=str(args.get("search") or ""),
                )
                return {
                    "g4f_installed": is_g4f_available(),
                    "count": len(items),
                    "providers": [p.model_dump() for p in items],
                }
            if action == "models":
                info = find_ai_provider(str(args.get("provider") or ""))
                if info is None:
                    raise ValueError(f"Unknown AI provider: {args.get('provider')!r}")
                models = (
                    fetch_g4f_provider_models(info.id, timeout=float(args.get("timeout", 3.0)))
                    if info.backend == "g4f"
                    else list(info.models)
                )
                return {"provider": info.id, "backend": info.backend, "tier": info.tier, "models": models}
            if action == "test":
                return test_ai_provider(
                    args.get("provider"),
                    mode=str(args.get("mode") or "auto"),
                    model=args.get("model"),
                    prompt=str(args.get("prompt") or "Ответь одним словом: Работает"),
                    timeout=float(args.get("timeout", 12.0)),
                ).model_dump()
            if action == "quick_scan":
                scanned = quick_scan_ai_providers(timeout=float(args.get("timeout", 6.0)))
                return {"count": len(scanned), "results": [r.model_dump() for r in scanned]}
            if action == "chat":
                return generate_completion(
                    str(args.get("prompt") or ""),
                    mode=args.get("mode"),
                    provider=args.get("provider"),
                    model=args.get("model"),
                    timeout=float(args.get("timeout", 25.0)),
                ).model_dump()
            raise ValueError(f"Unknown ozon_ai_providers action: {action!r}")

        raise ValueError(f"Unknown MCP tool: {name}")

    def run_stdio(self) -> None:
        """Serve JSON-RPC 2.0 messages line by line over UTF-8 stdio."""
        stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8") if hasattr(sys.stdin, "buffer") else sys.stdin
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass

        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def main_mcp(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for `ozon-mcp`."""
    import argparse

    parser = argparse.ArgumentParser(description="Start Ozon SDK Pro Model Context Protocol (MCP) Server")
    parser.add_argument("--proxy", default=None)
    parser.add_argument("--proxy-change-url", default=None)
    parser.add_argument("--cookies", default=None)
    parser.add_argument("--user-agent", default=None)
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    srv = OzonMCPServer(
        proxy=args.proxy,
        proxy_change_url=args.proxy_change_url,
        cookies=args.cookies,
        user_agent=args.user_agent,
        use_browser_fallback=True if args.browser else None,
        tracker_db=args.db,
    )
    srv.run_stdio()
    return 0


if __name__ == "__main__":
    sys.exit(main_mcp())
