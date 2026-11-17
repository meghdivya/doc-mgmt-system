import io
from pathlib import Path
from docx import Document as DocxDocument


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_upload_txt_and_version_tracking(client):
    content_v1 = (
        "Vault Security Policy v1.\n\n"
        "All uploaded documents are hashed with SHA-256 and indexed asynchronously. "
        "Access tokens expire every 24 hours."
    ).encode("utf-8")

    res1 = client.post(
        "/api/v1/documents/upload",
        files={"file": ("security_policy.txt", content_v1, "text/plain")},
    )
    assert res1.status_code == 201
    doc1 = res1.json()
    assert doc1["filename"] == "security_policy.txt"
    assert doc1["version"] == 1

    detail1 = client.get(f"/api/v1/documents/{doc1['id']}").json()
    assert detail1["status"] == "completed"
    assert detail1["chunk_count"] >= 1
    assert detail1["word_count"] > 10

    # Upload v2 of same filename -> version auto-increments
    content_v2 = content_v1 + b"\n\nMulti-factor authentication is mandatory for admins."
    res2 = client.post(
        "/api/v1/documents/upload",
        files={"file": ("security_policy.txt", content_v2, "text/plain")},
    )
    assert res2.status_code == 201
    assert res2.json()["version"] == 2

    listing = client.get("/api/v1/documents?search=security_policy").json()
    assert listing["total"] == 2


def test_upload_docx_and_delete(client):
    docx_bytes = _make_docx_bytes(
        [
            "Quarterly Architecture Review",
            "We migrated document ingestion to an asynchronous worker pipeline with hybrid RAG.",
        ]
    )
    res = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "arch_review.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == 201
    doc_id = res.json()["id"]

    detail = client.get(f"/api/v1/documents/{doc_id}").json()
    assert detail["status"] == "completed"
    assert detail["chunk_count"] >= 1

    del_res = client.delete(f"/api/v1/documents/{doc_id}")
    assert del_res.status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}").status_code == 404


def test_upload_real_pdf_if_present(client):
    pdf_path = Path("requirements/AI-Powered Vault Document System_  Case Study.pdf")
    if not pdf_path.exists():
        return
    res = client.post(
        "/api/v1/documents/upload",
        files={"file": ("case_study.pdf", pdf_path.read_bytes(), "application/pdf")},
    )
    assert res.status_code == 201
    doc_id = res.json()["id"]
    detail = client.get(f"/api/v1/documents/{doc_id}").json()
    assert detail["status"] == "completed"
    assert detail["page_count"] == 4
    assert detail["chunk_count"] >= 4


def test_upload_validation_errors(client):
    bad_ext = client.post(
        "/api/v1/documents/upload",
        files={"file": ("malware.exe", b"binary", "application/octet-stream")},
    )
    assert bad_ext.status_code == 400

    empty_file = client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert empty_file.status_code == 400
