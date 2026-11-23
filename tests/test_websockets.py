from fastapi.testclient import TestClient


def test_ws_document_status_initial_snapshot(client: TestClient) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("ws_doc.txt", b"WebSocket status tracking test document.", "text/plain")},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    with client.websocket_connect(f"/api/v1/ws/documents/{doc_id}") as ws:
        msg = ws.receive_json()
        assert msg["event"] == "status"
        assert msg["document_id"] == doc_id
        assert msg["status"] == "completed"


def test_ws_all_documents_receives_pipeline_events(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/ws/documents") as ws:
        upload = client.post(
            "/api/v1/documents/upload",
            files={"file": ("live.txt", b"Live WebSocket event streaming during ingestion.", "text/plain")},
        )
        assert upload.status_code == 201
        doc_id = upload.json()["id"]

        events = []
        for _ in range(3):
            events.append(ws.receive_json())
        statuses = [e["status"] for e in events]
        assert all(e["document_id"] == doc_id for e in events)
        assert "processing" in statuses
        assert "completed" in statuses


def test_ws_chat_streaming(client: TestClient) -> None:
    upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "rag_ws.txt",
                b"Vault AI supports real-time WebSocket chat streaming with source citations.",
                "text/plain",
            )
        },
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]

    sess = client.post("/api/v1/chat/sessions", json={"document_ids": [doc_id]})
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    with client.websocket_connect(f"/api/v1/ws/chat/{session_id}") as ws:
        ws.send_json({"question": "What does Vault AI support?"})
        tokens = []
        done_msg = None
        while True:
            frame = ws.receive_json()
            if frame["event"] == "token":
                tokens.append(frame["delta"])
            elif frame["event"] == "done":
                done_msg = frame
                break

        assert tokens
        assert done_msg is not None
        assert done_msg["session_id"] == session_id
        assert done_msg["message"]["role"] == "assistant"
        assert len(done_msg["message"]["citations"]) >= 1
