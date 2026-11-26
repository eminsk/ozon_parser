"""Tests for CLI subcommands (`ozon-parser`) and 9-tool Native MCP Server (`ozon-mcp`)."""

from __future__ import annotations

import json

from ozon_parser import OzonClient, OzonPriceTracker, OzonProduct
from ozon_parser.cli import main as cli_main
from ozon_parser.mcp_server import MCP_TOOLS_SCHEMA, OzonMCPServer


class _FakeMCPTransport:
    def get_json(self, url, params=None, headers=None):
        if "modal/shop-in-shop-info" in url:
            return {
                "widgetStates": {
                    "textBlock-1": json.dumps({"body": [{"type": "textAtom", "textAtom": {"text": 'ООО "ОзонСеллер"<br>7705556667'}}]}),
                    "cellList-1": json.dumps({"cells": [{"dsCell": {"centerBlock": {"title": {"text": "Заказов"}}, "rightBlock": {"badge": {"text": "999"}}}}]}),
                }
            }
        if "reviews" in url:
            return {
                "widgetStates": {
                    "webReviewProductScore-1": json.dumps({"totalScore": 4.9, "reviewsCount": 12}),
                    "webListReviews-1": json.dumps(
                        {"reviews": [{"id": "1", "itemId": 888, "content": {"score": 5, "positive": "Надёжный", "negative": "Нет", "comment": "Класс"}}]}
                    ),
                }
            }
        if "search" in url or "seller%2F" in url:
            return {"widgetStates": {"searchResultsV2-1": json.dumps({"items": [{"skuId": "888", "title": "Товар 888", "price": "3000 ₽"}]})}}
        return {
            "widgetStates": {
                "webStickyProducts-1": json.dumps({"id": 888, "name": "Товар 888", "seller": {"link": "/seller/55/"}}),
                "webPrice-1": json.dumps({"price": "3 000 ₽", "cardPrice": "2 700 ₽"}),
            }
        }

    def close(self):
        pass


def test_mcp_server_protocol_and_all_tools(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "mcp.db")
    tracker = OzonPriceTracker(db)
    tracker.track_products([OzonProduct.model_validate({"sku": 888, "name": "Товар 888", "price": 3500})])
    tracker.track_products([OzonProduct.model_validate({"sku": 888, "name": "Товар 888", "price": 3000})])

    monkeypatch.setenv("OZON_TRACKER_DB", db)
    fake_client = OzonClient(transport=_FakeMCPTransport(), tracker_db=db)
    srv = OzonMCPServer(client=fake_client)
    assert srv.tracker_db == db

    init_r = srv.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}})
    assert init_r["result"]["protocolVersion"] == "2025-11-25"
    assert init_r["result"]["serverInfo"]["name"] == "ozon-parser-mcp"

    tools_r = srv.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = [t["name"] for t in tools_r["result"]["tools"]]
    assert len(tool_names) == 9
    assert len(MCP_TOOLS_SCHEMA) == 9

    for tid, tname, targs in [
        (3, "ozon_get_card", {"target": "888", "with_seller": True}),
        (4, "ozon_get_seller", {"target": "55"}),
        (5, "ozon_search", {"query": "товар"}),
        (6, "ozon_get_seller_catalog", {"target": "55"}),
        (7, "ozon_get_reviews", {"target": "888"}),
        (8, "ozon_smart_reviews", {"target": "888", "ai_mode": "offline"}),
        (9, "ozon_price_drops", {}),
        (10, "ozon_check_rank", {"target": "888", "query": "товар"}),
        (11, "ozon_ai_providers", {"action": "list", "tier": "local"}),
    ]:
        res = srv.handle_request({"jsonrpc": "2.0", "id": tid, "method": "tools/call", "params": {"name": tname, "arguments": targs}})
        assert res["result"]["isError"] is False
        assert "structuredContent" in res["result"]


def test_cli_subcommands(capsys, tmp_path) -> None:
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["--help"])
    assert exc_info.value.code == 0
    assert "ozon-parser" in capsys.readouterr().out

    rc = cli_main(["card-discount", "5000", "4500"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["savings_rub"] == 500.0

    rc_ai = cli_main(["ai", "--list", "--local", "--json"])
    assert rc_ai == 0
    data = json.loads(capsys.readouterr().out)
    assert any(p["id"] == "ollama" for p in data["providers"])

    db_p = tmp_path / "cli_drops.db"
    rc_drops = cli_main(["drops", "--db", str(db_p)])
    assert rc_drops == 0
