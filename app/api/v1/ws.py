import asyncio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import ChatSession, Document
from app.db.session import get_db
from app.schemas.chat import ChatMessageRead
from app.services.ai_provider import AIProviderError
from app.services.rag import execute_chat_turn
from app.services.ws_manager import ws_manager

router = APIRouter(prefix="/ws", tags=["WebSockets"])


@router.websocket("/documents")
async def ws_all_documents(websocket: WebSocket) -> None:
    await ws_manager.connect("documents:all", websocket)
    try:
        while True:
            # Keep connection alive; clients can send ping/noop text
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect("documents:all", websocket)


@router.websocket("/documents/{document_id}")
async def ws_single_document(
    websocket: WebSocket,
    document_id: int,
    db: Session = Depends(get_db),
) -> None:
    topic = f"document:{document_id}"
    await ws_manager.connect(topic, websocket)
    doc = db.get(Document, document_id)
    if doc is not None:
        await websocket.send_json(
            {
                "event": "status",
                "document_id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "page_count": doc.page_count,
                "word_count": doc.word_count,
                "error_message": doc.error_message,
            }
        )
    else:
        await websocket.send_json({"event": "error", "detail": "Document not found."})

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(topic, websocket)


@router.websocket("/chat/{session_id}")
async def ws_chat_stream(
    websocket: WebSocket,
    session_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    await websocket.accept()
    session = db.get(ChatSession, session_id)
    if session is None:
        await websocket.send_json({"event": "error", "detail": "Chat session not found."})
        await websocket.close(code=1008)
        return

    try:
        while True:
            payload = await websocket.receive_json()
            question = str(payload.get("question", "")).strip()
            if not question:
                await websocket.send_json({"event": "error", "detail": "Question must not be empty."})
                continue
            top_k = payload.get("top_k")

            try:
                _user_msg, assistant_msg, cached = await asyncio.to_thread(
                    execute_chat_turn,
                    db=db,
                    session=session,
                    question=question,
                    top_k=int(top_k) if top_k is not None else None,
                    settings=settings,
                )
            except AIProviderError as exc:
                await websocket.send_json({"event": "error", "detail": exc.detail})
                continue
            assistant_data = ChatMessageRead.model_validate(assistant_msg).model_dump(mode="json")

            words = assistant_data["content"].split(" ")
            step = 4
            for idx in range(0, len(words), step):
                chunk_str = " ".join(words[idx : idx + step])
                if idx + step < len(words):
                    chunk_str += " "
                await websocket.send_json({"event": "token", "delta": chunk_str})

            await websocket.send_json(
                {
                    "event": "done",
                    "session_id": session.id,
                    "message": assistant_data,
                    "cached": cached,
                }
            )
    except WebSocketDisconnect:
        pass
