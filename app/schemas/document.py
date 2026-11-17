from datetime import datetime
from pydantic import BaseModel, ConfigDict


class DocumentInsightBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: str
    categories: list[str]
    sentiment: str


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    file_ext: str
    file_size: int
    sha256: str
    version: int
    status: str
    page_count: int
    word_count: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetailRead(DocumentRead):
    chunk_count: int = 0
    insight: DocumentInsightBrief | None = None


class DocumentListResponse(BaseModel):
    total: int
    items: list[DocumentRead]
