from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class SourceCitation(BaseModel):
    source_index: int
    document_id: int
    filename: str
    page_number: int
    chunk_index: int
    score: float
    excerpt: str


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    document_ids: list[int] = Field(
        default_factory=list,
        description="Target document IDs. Empty list queries across all completed vault documents.",
    )


class ChatMessageCreate(BaseModel):
    question: str = Field(..., min_length=2, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=15)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    citations: list[SourceCitation] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    latency_ms: float
    model_used: str
    tokens_used: int
    estimated_cost_usd: float
    created_at: datetime


class ChatSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    document_ids: list[int]
    created_at: datetime
    updated_at: datetime


class ChatSessionDetailRead(ChatSessionRead):
    messages: list[ChatMessageRead] = Field(default_factory=list)


class AskQuestionResponse(BaseModel):
    session_id: int
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead
    cached: bool = False
