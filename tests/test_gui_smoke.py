"""Smoke tests for OzonGUIConfig persistence and GUI module graceful import handling."""

from __future__ import annotations

import pytest

from ozon_parser import browser
from ozon_parser.exceptions import OzonAntiBotError
from ozon_parser.gui import app as gui_app


def test_gui_config_persistence_and_missing_ctk(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "storage" / "gui_config.json"
    monkeypatch.setattr(gui_app.OzonGUIConfig, "CONFIG_PATH", cfg_path)

    cfg = gui_app.OzonGUIConfig()
    cfg.review_target = "1619925434"
    cfg.review_ai_mode = "free"
    cfg.save()

    loaded = gui_app.OzonGUIConfig.load()
    assert loaded.review_target == "1619925434"
    assert loaded.review_ai_mode == "free"

    monkeypatch.setattr(gui_app, "ctk", None)
    with pytest.raises(RuntimeError, match="customtkinter"):
        gui_app.OzonGUIApp()


def test_browser_helper_raises_friendly_error_without_selenium(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _mock_import(name, *args, **kwargs):
        if name.startswith("selenium"):
            raise ImportError("No module named 'selenium'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _mock_import)
    assert browser.is_browser_available() is False
    with pytest.raises(OzonAntiBotError, match=r"ozon-sdk-pro\[browser\]"):
        browser.harvest_ozon_cookies()
