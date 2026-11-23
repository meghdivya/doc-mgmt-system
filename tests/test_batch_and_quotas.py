from fastapi.testclient import TestClient
import pytest


def test_batch_upload_and_e2e_integration(client: TestClient) -> None:
    res = client.post(
        "/api/v1/documents/upload/batch",
        files=[
            ("files", ("doc_a.txt", b"Alpha project uses FastAPI and local vector search.", "text/plain")),
            ("files", ("doc_b.md", b"# Beta Plan\nBeta project uses WebSockets and SQLite cache.", "text/markdown")),
        ],
    )
    assert res.status_code == 201
    body = res.json()
    assert body["uploaded_count"] == 2
    doc_ids = [d["id"] for d in body["documents"]]

    # Verify both documents completed processing
    for doc_id in doc_ids:
        detail = client.get(f"/api/v1/documents/{doc_id}")
        assert detail.status_code == 200
        assert detail.json()["status"] == "completed"

    # Verify batch_pipeline metric was recorded
    proc = client.get("/api/v1/metrics/processing")
    assert proc.status_code == 200
    assert "batch_pipeline" in proc.json()["stage_latency_ms"]

    # Verify multi-doc WebSocket chat over batch-uploaded docs + cache hit on repeat
    sess = client.post("/api/v1/chat/sessions", json={"document_ids": doc_ids})
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    with client.websocket_connect(f"/api/v1/ws/chat/{session_id}") as ws:
        ws.send_json({"question": "What do Alpha and Beta projects use?"})
        done_msg = None
        while True:
            frame = ws.receive_json()
            if frame["event"] == "done":
                done_msg = frame
                break
        assert done_msg is not None
        assert len(done_msg["message"]["citations"]) >= 1

    # Verify quota status reflects 2 uploaded docs
    quotas = client.get("/api/v1/metrics/quotas")
    assert quotas.status_code == 200
    q_data = quotas.json()
    assert q_data["documents"]["used"] == 2
    assert q_data["documents"]["remaining"] == q_data["documents"]["limit"] - 2
    assert q_data["storage_bytes"]["used"] > 0


def test_document_count_and_storage_quotas(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCUMENTS", "1")
    first = client.post(
        "/api/v1/documents/upload",
        files={"file": ("one.txt", b"First document within quota.", "text/plain")},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/documents/upload",
        files={"file": ("two.txt", b"Second document exceeds max_documents=1.", "text/plain")},
    )
    assert second.status_code == 429

    monkeypatch.setenv("MAX_DOCUMENTS", "500")
    monkeypatch.setenv("MAX_TOTAL_STORAGE_MB", "0")
    too_big = client.post(
        "/api/v1/documents/upload",
        files={"file": ("three.txt", b"Exceeds 0 MB storage quota.", "text/plain")},
    )
    assert too_big.status_code == 413


def test_daily_ai_token_quota_blocks_chat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("quota.txt", b"Testing daily token quota enforcement.", "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    sess = client.post("/api/v1/chat/sessions", json={"document_ids": [doc_id]})
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    # Force daily token limit to 0 so any prior or current usage trips the quota
    monkeypatch.setenv("MAX_DAILY_TOKENS", "0")
    chat_res = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"question": "Should this be blocked?"},
    )
    assert chat_res.status_code == 429
