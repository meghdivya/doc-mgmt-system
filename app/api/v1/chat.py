from collections.abc import Iterator
import json
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import ChatSession, Document
from app.db.session import get_db
from app.schemas.chat import (
    AskQuestionResponse,
    ChatMessageCreate,
    ChatMessageRead,
    ChatSessionCreate,
    ChatSessionDetailRead,
    ChatSessionRead,
)
from app.services.quota import check_ai_quota
from app.services.rag import execute_chat_turn

router = APIRouter(prefix="/chat", tags=["Document Chat (RAG)"])


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
) -> ChatSession:
    if payload.document_ids:
        found_ids = {
            row[0]
            for row in db.query(Document.id).filter(Document.id.in_(payload.document_ids)).all()
        }
        missing = sorted(set(payload.document_ids) - found_ids)
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Documents not found: {missing}",
            )

    session = ChatSession(
        title=(payload.title or "Document Chat").strip() or "Document Chat",
        document_ids=payload.document_ids,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionRead])
def list_chat_sessions(db: Session = Depends(get_db)) -> list[ChatSession]:
    return db.query(ChatSession).order_by(ChatSession.id.desc()).all()


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailRead)
def get_chat_session(session_id: int, db: Session = Depends(get_db)) -> ChatSessionDetailRead:
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
    return ChatSessionDetailRead.model_validate(session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat_session(session_id: int, db: Session = Depends(get_db)) -> None:
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
    db.delete(session)
    db.commit()


@router.post("/sessions/{session_id}/messages", response_model=AskQuestionResponse)
def ask_question(
    session_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AskQuestionResponse:
    check_ai_quota(db, settings)
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")

    user_msg, assistant_msg, cached = execute_chat_turn(
        db=db,
        session=session,
        question=payload.question,
        top_k=payload.top_k,
        settings=settings,
    )
    return AskQuestionResponse(
        session_id=session.id,
        user_message=ChatMessageRead.model_validate(user_msg),
        assistant_message=ChatMessageRead.model_validate(assistant_msg),
        cached=cached,
    )


@router.post("/sessions/{session_id}/messages/stream")
def ask_question_stream(
    session_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    check_ai_quota(db, settings)
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")

    _user_msg, assistant_msg, cached = execute_chat_turn(
        db=db,
        session=session,
        question=payload.question,
        top_k=payload.top_k,
        settings=settings,
    )
    assistant_data = ChatMessageRead.model_validate(assistant_msg).model_dump(mode="json")

    def _event_generator() -> Iterator[str]:
        words = assistant_data["content"].split(" ")
        step = 4
        for idx in range(0, len(words), step):
            chunk_str = " ".join(words[idx : idx + step])
            if idx + step < len(words):
                chunk_str += " "
            yield f"event: token\ndata: {json.dumps({'delta': chunk_str})}\n\n"
        done_payload = {
            "message": assistant_data,
            "cached": cached,
        }
        yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(_event_generator(), media_type="text/event-stream")
