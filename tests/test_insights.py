def test_auto_insights_and_categories(client):
    sample_doc = (
        "AI Backend Architecture Specification.\n\n"
        "The system uses FastAPI, PostgreSQL, and Redis async workers to process PDF documents. "
        "Embeddings are indexed for accurate RAG retrieval and source citations. "
        "Clean error handling and efficient caching improve response latency across endpoints."
    ).encode("utf-8")

    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("ai_spec.txt", sample_doc, "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    insights_res = client.get(f"/api/v1/documents/{doc_id}/insights")
    assert insights_res.status_code == 200
    insights = insights_res.json()
    assert insights["document_id"] == doc_id
    assert len(insights["summary"]) > 20
    assert len(insights["key_insights"]) >= 1
    assert any(
        cat in insights["categories"]
        for cat in ("AI & Machine Learning", "Software Engineering")
    )
    assert insights["sentiment"] in ("positive", "neutral", "negative")


def test_custom_summary_and_caching(client):
    text = (
        "Incident Risk & Action Report.\n\n"
        "Action item 1: Implement rate limiting across public upload endpoints immediately. "
        "Risk analysis shows large unvalidated payloads could delay background queue workers. "
        "Technical architecture will add SHA-256 deduplication and Redis TTL caching."
    ).encode("utf-8")

    doc_id = client.post(
        "/api/v1/documents/upload",
        files={"file": ("risk_report.md", text, "text/markdown")},
    ).json()["id"]

    res1 = client.post(
        f"/api/v1/documents/{doc_id}/summarize",
        json={"length": "detailed", "focus": "action_items", "tone": "executive"},
    )
    assert res1.status_code == 200
    body1 = res1.json()
    assert "Executive Brief:" in body1["summary"]
    assert body1["cached"] is False

    # Repeat identical request -> served from SmartCache
    res2 = client.post(
        f"/api/v1/documents/{doc_id}/summarize",
        json={"length": "detailed", "focus": "action_items", "tone": "executive"},
    )
    assert res2.status_code == 200
    assert res2.json()["cached"] is True


def test_comparative_document_analysis(client):
    d1 = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "rag_design.txt",
                b"FastAPI backend service using vector embeddings and RAG pipelines for document chat.",
                "text/plain",
            )
        },
    ).json()["id"]
    d2 = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "rag_scaling.txt",
                b"Scaling FastAPI RAG pipelines with PostgreSQL pgvector embeddings and Redis caching.",
                "text/plain",
            )
        },
    ).json()["id"]

    cmp_res = client.post("/api/v1/documents/compare", json={"document_ids": [d1, d2]})
    assert cmp_res.status_code == 200
    cmp_body = cmp_res.json()
    assert len(cmp_body["per_document"]) == 2
    assert len(cmp_body["shared_categories"]) >= 1
    assert "rag_design.txt" in cmp_body["comparative_summary"]
