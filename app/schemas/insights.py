from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class DocumentInsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: int
    summary: str
    key_insights: list[str]
    categories: list[str]
    topics: list[str]
    sentiment: str
    model_used: str
    tokens_used: int
    estimated_cost_usd: float
    created_at: datetime


class CustomSummaryRequest(BaseModel):
    length: Literal["short", "medium", "detailed"] = "medium"
    focus: Literal["general", "technical", "action_items", "risks"] = "general"
    tone: Literal["professional", "executive", "simple"] = "professional"


class CustomSummaryResponse(BaseModel):
    document_id: int
    filename: str
    length: str
    focus: str
    tone: str
    summary: str
    model_used: str
    tokens_used: int
    estimated_cost_usd: float
    cached: bool


class CompareDocumentsRequest(BaseModel):
    document_ids: list[int] = Field(..., min_length=2, max_length=10)


class CompareDocumentsResponse(BaseModel):
    document_ids: list[int]
    shared_topics: list[str]
    shared_categories: list[str]
    per_document: list[dict]
    comparative_summary: str
