from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict


class DocumentStatisticsResponse(BaseModel):
    total_documents: int
    status_breakdown: dict[str, int]
    file_type_breakdown: dict[str, int]
    category_distribution: dict[str, int]
    total_storage_bytes: int
    total_pages: int
    total_words: int
    total_chunks: int
    total_chat_sessions: int
    total_chat_messages: int


class StageLatencySummary(BaseModel):
    count: int
    avg_duration_ms: float
    max_duration_ms: float


class ProcessingEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int | None
    stage: str
    status: str
    duration_ms: float
    chunks_created: int
    tokens_used: int
    estimated_cost_usd: float
    error_message: str | None = None
    created_at: datetime


class ProcessingMetricsResponse(BaseModel):
    total_events: int
    completed_events: int
    failed_events: int
    success_rate_pct: float
    stage_latency_ms: dict[str, StageLatencySummary]
    ai_usage: dict[str, Any]
    cache_stats: dict[str, Any]
    http_performance: dict[str, Any]
    recent_events: list[ProcessingEventRead]


class QuotaMetricItem(BaseModel):
    used: int | float
    limit: int | float
    remaining: int | float


class QuotaStatusResponse(BaseModel):
    documents: QuotaMetricItem
    storage_bytes: QuotaMetricItem
    daily_tokens: QuotaMetricItem
    daily_cost_usd: QuotaMetricItem
