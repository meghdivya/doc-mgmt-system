def test_document_and_processing_metrics(client):
    up = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "telemetry_doc.txt",
                b"FastAPI async pipeline telemetry tracks latency, embeddings, and token cost.",
                "text/plain",
            )
        },
    )
    assert up.status_code == 201
    assert "X-Process-Time-Ms" in up.headers
    doc_id = up.json()["id"]

    sess_id = client.post("/api/v1/chat/sessions", json={"document_ids": [doc_id]}).json()["id"]
    client.post(
        f"/api/v1/chat/sessions/{sess_id}/messages",
        json={"question": "What does pipeline telemetry track?"},
    )

    doc_stats = client.get("/api/v1/metrics/documents")
    assert doc_stats.status_code == 200
    ds = doc_stats.json()
    assert ds["total_documents"] == 1
    assert ds["status_breakdown"]["completed"] == 1
    assert ds["file_type_breakdown"][".txt"] == 1
    assert ds["total_chunks"] >= 1
    assert ds["total_chat_sessions"] == 1
    assert ds["total_chat_messages"] == 2

    proc_stats = client.get("/api/v1/metrics/processing")
    assert proc_stats.status_code == 200
    ps = proc_stats.json()
    assert ps["total_events"] >= 4
    assert ps["success_rate_pct"] == 100.0
    for stage in ("parse_and_chunk", "embeddings", "ai_insights", "full_pipeline", "rag_query"):
        assert stage in ps["stage_latency_ms"]
    assert ps["http_performance"]["total_requests"] >= 4
    assert "hit_rate_pct" in ps["cache_stats"]


def test_rate_limiting_enforcement(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health").status_code == 200
    blocked = client.get("/api/v1/health")
    assert blocked.status_code == 429
