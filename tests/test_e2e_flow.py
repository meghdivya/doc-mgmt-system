from pathlib import Path
from scripts.demo import run_demo


def test_local_web_ui_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Vault AI" in res.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    js = client.get("/static/app.js")
    assert js.status_code == 200


def test_full_end_to_end_lifecycle(client):
    pdf_path = Path("requirements/AI-Powered Vault Document System_  Case Study.pdf")
    if pdf_path.exists():
        files = {"file": ("case_study.pdf", pdf_path.read_bytes(), "application/pdf")}
    else:
        files = {
            "file": (
                "vault_guide.txt",
                b"Vault AI supports RAG chat with citations, async ingestion, and monitoring metrics.",
                "text/plain",
            )
        }

    # 1. Upload
    upload = client.post("/api/v1/documents/upload", files=files)
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    # 2. Retrieve status + insights + custom summary
    detail = client.get(f"/api/v1/documents/{doc_id}").json()
    assert detail["status"] == "completed"
    assert detail["chunk_count"] >= 1

    insights = client.get(f"/api/v1/documents/{doc_id}/insights")
    assert insights.status_code == 200
    assert len(insights.json()["categories"]) >= 1

    custom_sum = client.post(
        f"/api/v1/documents/{doc_id}/summarize",
        json={"length": "short", "focus": "technical", "tone": "professional"},
    )
    assert custom_sum.status_code == 200

    # 3. Start chat & ask multi-turn questions
    session_id = client.post(
        "/api/v1/chat/sessions", json={"document_ids": [doc_id]}
    ).json()["id"]

    q1 = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"question": "What are the main backend components and RAG chat features?"},
    )
    assert q1.status_code == 200
    assert len(q1.json()["assistant_message"]["citations"]) >= 1

    # 4. Verify monitoring endpoints
    assert client.get("/api/v1/metrics/documents").json()["total_documents"] == 1
    assert client.get("/api/v1/metrics/processing").json()["success_rate_pct"] == 100.0


def test_demo_script_runs_cleanly(capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    run_demo()
    captured = capsys.readouterr().out
    assert "AI-POWERED VAULT DOCUMENT SYSTEM" in captured
    assert "Top Citation:" in captured
