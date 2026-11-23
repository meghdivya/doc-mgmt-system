from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Document, DocumentChunk
from app.db.session import get_db
from app.schemas.document import (
    BatchUploadResponse,
    DocumentDetailRead,
    DocumentInsightBrief,
    DocumentListResponse,
    DocumentRead,
)
from app.schemas.insights import (
    CompareDocumentsRequest,
    CompareDocumentsResponse,
    CustomSummaryRequest,
    CustomSummaryResponse,
    DocumentInsightRead,
)
from app.services.ai_provider import generate_custom_summary
from app.services.quota import check_ai_quota, check_upload_quota
from app.services.storage import delete_stored_file, save_upload_file
from app.services.vector_store import get_vector_store
from app.workers.pipeline import enqueue_batch_processing, enqueue_document_processing

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("/upload", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Document:
    stored = await save_upload_file(file, settings)
    try:
        check_upload_quota(db, stored.file_size, 1, settings)
    except Exception:
        delete_stored_file(stored.storage_path)
        raise

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


@router.post("/upload/batch", response_model=BatchUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BatchUploadResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one file is required for batch upload.",
        )
    if len(files) > settings.max_batch_upload_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch upload exceeds maximum of {settings.max_batch_upload_files} files.",
        )

    stored_files = []
    try:
        for file in files:
            stored_files.append(await save_upload_file(file, settings))
        total_bytes = sum(s.file_size for s in stored_files)
        check_upload_quota(db, total_bytes, len(stored_files), settings)
    except Exception:
        for s in stored_files:
            delete_stored_file(s.storage_path)
        raise

    docs: list[Document] = []
    version_cache: dict[str, int] = {}
    for stored in stored_files:
        if stored.filename not in version_cache:
            latest_version = (
                db.query(func.max(Document.version))
                .filter(Document.filename == stored.filename)
                .scalar()
            )
            version_cache[stored.filename] = (latest_version or 0) + 1
        else:
            version_cache[stored.filename] += 1

        doc = Document(
            filename=stored.filename,
            content_type=stored.content_type,
            file_ext=stored.file_ext,
            file_size=stored.file_size,
            sha256=stored.sha256,
            storage_path=stored.storage_path,
            version=version_cache[stored.filename],
            status="pending",
        )
        db.add(doc)
        docs.append(doc)

    db.commit()
    for doc in docs:
        db.refresh(doc)

    queue_mode = enqueue_batch_processing(background_tasks, [d.id for d in docs], settings)
    return BatchUploadResponse(
        uploaded_count=len(docs),
        queue_mode=queue_mode,
        documents=[DocumentRead.model_validate(d) for d in docs],
    )


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
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    storage_path = doc.storage_path
    db.delete(doc)
    db.commit()
    get_vector_store(settings).delete_document_chunks(document_id)
    delete_stored_file(storage_path)


@router.get("/{document_id}/insights", response_model=DocumentInsightRead)
def get_document_insights(
    document_id: int,
    db: Session = Depends(get_db),
) -> DocumentInsightRead:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if doc.insight is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document insights not ready (current status: {doc.status}).",
        )
    return DocumentInsightRead.model_validate(doc.insight)


@router.post("/{document_id}/summarize", response_model=CustomSummaryResponse)
def customize_document_summary(
    document_id: int,
    payload: CustomSummaryRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CustomSummaryResponse:
    check_ai_quota(db, settings)
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document chunks not ready (current status: {doc.status}).",
        )

    full_text = "\n\n".join(c.content for c in chunks)
    res = generate_custom_summary(
        text=full_text,
        length=payload.length,
        focus=payload.focus,
        tone=payload.tone,
        settings=settings,
    )
    return CustomSummaryResponse(
        document_id=doc.id,
        filename=doc.filename,
        length=payload.length,
        focus=payload.focus,
        tone=payload.tone,
        summary=res.summary,
        model_used=res.model_used,
        tokens_used=res.tokens_used,
        estimated_cost_usd=res.estimated_cost_usd,
        cached=res.cached,
    )


@router.post("/compare", response_model=CompareDocumentsResponse)
def compare_documents(
    payload: CompareDocumentsRequest,
    db: Session = Depends(get_db),
) -> CompareDocumentsResponse:
    docs = db.query(Document).filter(Document.id.in_(payload.document_ids)).all()
    if len(docs) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="At least 2 valid completed documents are required for comparison.",
        )

    topic_sets: list[set[str]] = []
    cat_sets: list[set[str]] = []
    per_doc: list[dict] = []
    for doc in docs:
        ins = doc.insight
        topics = list(ins.topics) if ins else []
        cats = list(ins.categories) if ins else []
        topic_sets.append(set(topics))
        cat_sets.append(set(cats))
        per_doc.append(
            {
                "document_id": doc.id,
                "filename": doc.filename,
                "word_count": doc.word_count,
                "categories": cats,
                "topics": topics,
                "sentiment": ins.sentiment if ins else "neutral",
                "summary": ins.summary if ins else "",
            }
        )

    shared_topics = sorted(set.intersection(*topic_sets)) if topic_sets else []
    shared_cats = sorted(set.intersection(*cat_sets)) if cat_sets else []
    comp_lines = [
        f"- **{d['filename']}** ({d['word_count']} words, {d['sentiment']}): {d['summary']}"
        for d in per_doc
    ]
    overlap_note = (
        f"Shared themes: {', '.join(shared_topics or shared_cats)}."
        if (shared_topics or shared_cats)
        else "The documents cover distinct focus areas with minimal direct topic overlap."
    )
    comparative_summary = f"{overlap_note}\n" + "\n".join(comp_lines)

    return CompareDocumentsResponse(
        document_ids=[d.id for d in docs],
        shared_topics=shared_topics,
        shared_categories=shared_cats,
        per_document=per_doc,
        comparative_summary=comparative_summary,
    )
