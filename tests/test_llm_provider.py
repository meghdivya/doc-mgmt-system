from app.core.config import Settings
from app.services.ai_provider import _parse_json_object, build_llm_client


def test_openrouter_settings_and_client_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "openai/gpt-4o")
    monkeypatch.setenv("OPENROUTER_SITE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("OPENROUTER_SITE_NAME", "Vault AI")

    settings = Settings()
    assert settings.has_llm is True
    assert settings.ai_mode == "openrouter"
    assert settings.active_chat_model == "openai/gpt-4o"
    assert settings.active_embedding_model == "openai/text-embedding-3-small"

    client = build_llm_client(settings)
    assert "openrouter.ai/api/v1" in str(client.base_url)
    assert client.default_headers["HTTP-Referer"] == "http://127.0.0.1:8000"
    assert client.default_headers["X-Title"] == "Vault AI"


def test_parse_fenced_and_plain_json():
    fenced = '```json\n{"answer": "Grounded response [Source 1].", "follow_up_questions": ["Next?"]}\n```'
    parsed = _parse_json_object(fenced)
    assert parsed["answer"] == "Grounded response [Source 1]."
    assert parsed["follow_up_questions"] == ["Next?"]
