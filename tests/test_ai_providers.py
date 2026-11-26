"""Tests for Unified Free (g4f/Ollama) + Paid (OpenAI/DeepSeek/OpenRouter/ProxyAPI/Groq) AI & Review Summaries."""

from __future__ import annotations

import json
import types

import pytest

from ozon_parser import ai
from ozon_parser.client import OzonClient
from ozon_parser.reviews import SmartOzonReviewAnalyzer


class _FakeReviewTransport:
    def get_json(self, url, params=None, headers=None):
        if "page=2" in url:
            return {"widgetStates": {"webListReviews-1": json.dumps({"reviews": []})}}
        return {
            "widgetStates": {
                "webStickyProducts-1": json.dumps({"id": 999, "name": "Наушники TWS"}),
                "webReviewProductScore-1": json.dumps({"totalScore": 4.7, "reviewsCount": 50}),
                "webListReviews-1": json.dumps(
                    {
                        "reviews": [
                            {
                                "id": "r1",
                                "itemId": 999,
                                "content": {"score": 5, "positive": "Чистый звук", "negative": "Скользкий кейс", "comment": "Отлично"},
                            },
                            {
                                "id": "r2",
                                "itemId": 999,
                                "content": {"score": 5, "positive": "Чистый звук", "negative": "", "comment": "Супер"},
                            },
                        ]
                    }
                ),
            }
        }

    def close(self):
        pass


def test_list_ai_providers_builtin_and_ollama_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    providers = ai.list_ai_providers(tier="local", include_g4f=False)
    slugs = [p.id for p in providers]
    assert "ollama" in slugs
    assert "lmstudio" in slugs
    _, _, url, _, _ = ai._resolve_openai_params(provider="ollama")
    assert url == "http://127.0.0.1:11434/v1"


def test_find_provider_and_g4f_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_g4f_prov = type(
        "OpenAI",
        (),
        {
            "working": True,
            "needs_auth": False,
            "supports_stream": True,
            "default_model": "gpt-free",
            "url": "https://example.free",
            "models": ["gpt-free"],
        },
    )

    fake_providers_mod = types.SimpleNamespace(__providers__=[fake_g4f_prov], OpenAI=fake_g4f_prov)
    fake_client_mod = types.SimpleNamespace(Client=lambda provider=None: None)
    monkeypatch.setattr(ai, "_load_g4f_modules", lambda: (fake_providers_mod, fake_client_mod))

    assert ai.find_ai_provider("g4f:OpenAI").backend == "g4f"
    assert ai.find_ai_provider("openai").backend == "openai_compat"


def test_free_g4f_fallback_and_nag_filtering(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_nag = type(
        "Airforce",
        (),
        {"working": True, "needs_auth": False, "default_model": "m1"},
    )
    good_prov = type(
        "Yqcloud",
        (),
        {"working": True, "needs_auth": False, "default_model": "gpt-4"},
    )

    def _make_client(provider=None):
        class _C:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        txt = (
                            "Please sign up and repeat your request"
                            if provider is bad_nag
                            else "Работает"
                        )
                        msg = types.SimpleNamespace(content=txt)
                        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])
        return _C()

    fake_providers = types.SimpleNamespace(__providers__=[bad_nag, good_prov], Airforce=bad_nag, Yqcloud=good_prov)
    monkeypatch.setattr(ai, "_load_g4f_modules", lambda: (fake_providers, _make_client))
    monkeypatch.setattr(ai, "FREE_G4F_CANDIDATES", ("Airforce", "Yqcloud"))

    res = ai.generate_completion("Привет", mode="free")
    assert res.ok is True
    assert res.provider == "Yqcloud"
    assert res.content == "Работает"


def test_error_diagnostics_and_paid_call(monkeypatch: pytest.MonkeyPatch) -> None:
    r401 = ai.test_ai_provider("openai", mode="paid", api_key="", timeout=2.0)
    assert r401.success is False
    assert "API key" in (r401.hint or "")

    captured = {}

    def _fake_post(prompt, *, base_url, api_key, model, temperature=0.2, timeout=25.0):
        captured.update({"base_url": base_url, "api_key": api_key, "model": model})
        return '{"plus": ["Звук"], "minus": ["Кейс"]}'

    monkeypatch.setattr(ai, "_post_openai_chat", _fake_post)
    client = OzonClient(transport=_FakeReviewTransport())
    summary = client.analyze_reviews(
        999,
        ai_mode="paid",
        ai_provider="deepseek",
        ai_key="sk-test-123",
    )
    assert captured["base_url"] == "https://api.deepseek.com/v1"
    assert summary.top_pros == ["Звук"]
    assert summary.top_cons == ["Кейс"]
    assert "deepseek" in summary.summary_mode

    # Offline fallback
    offline = SmartOzonReviewAnalyzer(client).fetch_reviews(999)
    assert offline.summary_mode == "offline"
    assert any("Чистый звук" in p for p in offline.top_pros)
    assert offline.rating_distribution[5] == 2
