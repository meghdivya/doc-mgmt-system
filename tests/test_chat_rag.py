def test_single_doc_rag_chat_and_multi_turn_context(client):
    handbook = (
        "Vault Operations Handbook.\n\n"
        "Backup Schedule: Database snapshots execute every 6 hours using encrypted storage.\n\n"
        "Backup Retention Policy: Encrypted database snapshots are retained for 90 days before archival."
    ).encode("utf-8")

    doc_id = client.post(
        "/api/v1/documents/upload",
        files={"file": ("ops_handbook.txt", handbook, "text/plain")},
    ).json()["id"]

    sess_res = client.post(
        "/api/v1/chat/sessions",
        json={"document_ids": [doc_id]},
    )
    assert sess_res.status_code == 201
    session_id = sess_res.json()["id"]

    # Turn 1
    turn1 = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"question": "How often do database backup snapshots execute?"},
    )
    assert turn1.status_code == 200
    msg1 = turn1.json()["assistant_message"]
    assert "6 hours" in msg1["content"]
    assert "[Source 1]" in msg1["content"]
    assert len(msg1["citations"]) >= 1
    assert msg1["citations"][0]["filename"] == "ops_handbook.txt"
    assert len(msg1["follow_up_questions"]) >= 1

    # Turn 2: Short pronoun follow-up relying on multi-turn context
    turn2 = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"question": "How long are they retained?"},
    )
    assert turn2.status_code == 200
    msg2 = turn2.json()["assistant_message"]
    assert "90 days" in msg2["content"]

    # Verify full session history persisted (2 user + 2 assistant = 4 messages)
    history = client.get(f"/api/v1/chat/sessions/{session_id}").json()
    assert len(history["messages"]) == 4
    assert history["title"] != "Document Chat"


def test_multi_document_chat_and_sse_streaming(client):
    d1 = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "sla_terms.txt",
                b"Enterprise SLA guarantees 99.95% uptime and 15-minute incident response.",
                "text/plain",
            )
        },
    ).json()["id"]
    d2 = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "pricing_tiers.txt",
                b"Pro Plan costs $49 per seat monthly and includes 500GB of vault storage.",
                "text/plain",
            )
        },
    ).json()["id"]

    # Vault-wide multi-doc session
    session_id = client.post(
        "/api/v1/chat/sessions",
        json={"title": "SLA & Pricing QA", "document_ids": [d1, d2]},
    ).json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages/stream",
        json={"question": "What is the Pro Plan seat price and SLA uptime guarantee?"},
    ) as stream_res:
        assert stream_res.status_code == 200
        assert "text/event-stream" in stream_res.headers["content-type"]
        body = "".join(stream_res.iter_text())
        assert "event: token" in body
        assert "event: done" in body

    sessions = client.get("/api/v1/chat/sessions").json()
    assert any(s["id"] == session_id for s in sessions)


def test_off_topic_questions_are_declined_without_outside_knowledge(client):
    doc_id = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "vault_policy.txt",
                b"Vault retention policy requires encrypted backups every 6 hours.",
                "text/plain",
            )
        },
    ).json()["id"]

    session_id = client.post(
        "/api/v1/chat/sessions",
        json={"document_ids": [doc_id]},
    ).json()["id"]

    for off_topic in ["What is the capital of France?", "Can you write code for LCA?"]:
        res = client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"question": off_topic},
        )
        assert res.status_code == 200
        answer = res.json()["assistant_message"]["content"]
        assert "help you with something else" in answer.lower()
        assert "paris" not in answer.lower()

