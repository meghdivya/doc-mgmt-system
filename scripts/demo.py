"""Runnable end-to-end demonstration of the AI-Powered Vault Document System.

Usage:
    python -m scripts.demo
"""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os
from fastapi.testclient import TestClient
from app.db.session import get_engine
from app.main import create_app


def run_demo() -> None:
    prev_db = os.environ.get("DATABASE_URL")
    prev_up = os.environ.get("UPLOAD_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            db_url = f"sqlite:///{Path(tmp, 'demo_vault.db').as_posix()}"
            os.environ["DATABASE_URL"] = db_url
            os.environ["UPLOAD_DIR"] = Path(tmp, "uploads").as_posix()

            app = create_app()
            with TestClient(app) as client:
                print("=" * 70)
                print("AI-POWERED VAULT DOCUMENT SYSTEM — END-TO-END DEMO")
                print("=" * 70)

                pdf_path = ROOT / "requirements" / "AI-Powered Vault Document System_  Case Study.pdf"
                if pdf_path.exists():
                    files = {"file": ("Case_Study.pdf", pdf_path.read_bytes(), "application/pdf")}
                else:
                    sample = (
                        "AI-Powered Vault Document System Specification.\n\n"
                        "Users upload PDF and DOCX files for async RAG indexing, automated insights, "
                        "multi-turn conversational Q&A with page citations, and processing metrics."
                    ).encode("utf-8")
                    files = {"file": ("Vault_Spec.txt", sample, "text/plain")}

                up = client.post("/api/v1/documents/upload", files=files).json()
                doc_id = up["id"]
                detail = client.get(f"/api/v1/documents/{doc_id}").json()
                print(
                    f"\n[1] Uploaded & Processed: {detail['filename']} "
                    f"(status={detail['status']}, pages={detail['page_count']}, chunks={detail['chunk_count']})"
                )

                insights = client.get(f"/api/v1/documents/{doc_id}/insights").json()
                print(f"\n[2] AI Categories : {', '.join(insights['categories'])}")
                print(f"    Sentiment     : {insights['sentiment']}")
                print(f"    Summary       : {insights['summary'][:240]}...")

                session = client.post(
                    "/api/v1/chat/sessions", json={"document_ids": [doc_id]}
                ).json()
                session_id = session["id"]

                questions = [
                    "What are the core objectives and required backend components?",
                    "What deliverables and bonus features are mentioned?",
                ]
                for idx, q in enumerate(questions, start=1):
                    ans = client.post(
                        f"/api/v1/chat/sessions/{session_id}/messages",
                        json={"question": q},
                    ).json()["assistant_message"]
                    print(f"\n[3.{idx}] Question: {q}")
                    print(ans["content"])
                    top_cite = ans["citations"][0]
                    print(
                        f"      Top Citation: {top_cite['filename']} p.{top_cite['page_number']} "
                        f"(chunk #{top_cite['chunk_index']}, score={top_cite['score']})"
                    )
                    print(f"      Suggested Follow-ups: {ans['follow_up_questions']}")

                proc = client.get("/api/v1/metrics/processing").json()
                docs_m = client.get("/api/v1/metrics/documents").json()
                print("\n[4] Monitoring Telemetry:")
                print(
                    f"    Documents={docs_m['total_documents']} | Chunks={docs_m['total_chunks']} | "
                    f"Pipeline Events={proc['total_events']} | Success Rate={proc['success_rate_pct']}%"
                )
                print("=" * 70)

            get_engine(db_url).dispose()
    finally:
        if prev_db is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_db
        if prev_up is None:
            os.environ.pop("UPLOAD_DIR", None)
        else:
            os.environ["UPLOAD_DIR"] = prev_up


if __name__ == "__main__":
    run_demo()
