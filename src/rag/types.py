"""Tipos Pydantic do módulo RAG."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    text: str
    char_start: int
    char_end: int
    position: int


IngestStatus = Literal["ingested", "skipped", "error"]


class IngestResult(BaseModel):
    status: IngestStatus
    source_path: str
    document_id: int | None = None
    chunk_count: int = 0
    reason: str | None = None
    error: str | None = None


class RetrievedChunk(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    text: str
    position: int
    distance: float


class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    no_relevant_context: bool = False
    threshold_used: float | None = None  # preenchido por retrieve.search
