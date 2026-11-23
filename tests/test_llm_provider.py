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


def test_provider_token_exhaustion_returns_clear_error(client, monkeypatch):
    import httpx
    from openai import APIStatusError
    import app.services.ai_provider as ai_prov

    doc_id = client.post(
        "/api/v1/documents/upload",
        files={"file": ("tokens.txt", b"Vault AI document content for token error test.", "text/plain")},
    ).json()["id"]
    sess_id = client.post("/api/v1/chat/sessions", json={"document_ids": [doc_id]}).json()["id"]

    class _FakeCompletions:
        def create(self, **_kwargs):
            req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
            resp = httpx.Response(402, request=req)
            raise APIStatusError(
                "Error code: 402 - This request would exceed your available credits.",
                response=resp,
                body=None,
            )

    class _FakeEmbeddings:
        def create(self, **_kwargs):
            class _Item:
                embedding = [0.1] * 256

            class _Usage:
                total_tokens = 10
                cost = 0.0

            class _Resp:
                data = [_Item()]
                usage = _Usage()

            return _Resp()

    class _FakeClient:
        chat = type("_Chat", (), {"completions": _FakeCompletions()})()
        embeddings = _FakeEmbeddings()

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(ai_prov, "build_llm_client", lambda _s: _FakeClient())

    res = client.post(
        f"/api/v1/chat/sessions/{sess_id}/messages",
        json={"question": "Summarize this document"},
    )
    assert res.status_code == 402
    assert "exhausted your token limits" in res.json()["detail"].lower()
