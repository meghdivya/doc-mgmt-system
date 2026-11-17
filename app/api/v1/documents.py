from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Document, DocumentChunk
from app.db.session import get_db
from app.schemas.document import (
    DocumentDetailRead,
    DocumentInsightBrief,
    DocumentListResponse,
    DocumentRead,
)
from app.services.storage import delete_stored_file, save_upload_file
from app.workers.pipeline import enqueue_document_processing

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    stored = await save_upload_file(file, settings)

    latest_version = (
        db.query(func.max(Document.version))
        .filter(Document.filename == stored.filename)
        .scalar()
    )
    next_version = (latest_version or 0) + 1

    doc = Document(
        filename=stored.filename,
        content_type=stored.content_type,
        file_ext=stored.file_ext,
        file_size=stored.file_size,
        sha256=stored.sha256,
        storage_path=stored.storage_path,
        version=next_version,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    enqueue_document_processing(background_tasks, doc.id, settings)
    return doc


@router.get("", response_model=DocumentListResponse)
def list_documents(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    query = db.query(Document)
    if status_filter:
        query = query.filter(Document.status == status_filter)
    if search:
        query = query.filter(Document.filename.ilike(f"%{search}%"))

    total = query.count()
    items = query.order_by(Document.id.desc()).offset(offset).limit(limit).all()
    return DocumentListResponse(total=total, items=items)


@router.get("/{document_id}", response_model=DocumentDetailRead)
def get_document(document_id: int, db: Session = Depends(get_db)) -> DocumentDetailRead:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    chunk_count = (
        db.query(func.count(DocumentChunk.id))
        .filter(DocumentChunk.document_id == doc.id)
        .scalar()
        or 0
    )
    insight_brief = (
        DocumentInsightBrief.model_validate(doc.insight) if doc.insight is not None else None
    )
    base = DocumentRead.model_validate(doc).model_dump()
    return DocumentDetailRead(**base, chunk_count=chunk_count, insight=insight_brief)


@router.post("/{document_id}/reprocess", response_model=DocumentRead)
def reprocess_document(
    document_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    doc.status = "pending"
    doc.error_message = None
    db.commit()
    db.refresh(doc)

    enqueue_document_processing(background_tasks, doc.id, settings)
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, db: Session = Depends(get_db)) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    storage_path = doc.storage_path
    db.delete(doc)
    db.commit()
    delete_stored_file(storage_path)
