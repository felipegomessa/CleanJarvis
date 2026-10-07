"""Embeddings via multilingual-e5-small (lazy load) — D-004 / D-016 / RF-002.5."""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

import numpy as np
from loguru import logger

from src.core.config import get_settings

# Dimensão dos vetores do multilingual-e5-small; casa com `FLOAT[384]` da migration 002.
EMBEDDING_DIM = 384

_embedder: Any | None = None
_lock = Lock()


def get_embedder() -> Any:
    """Singleton do SentenceTransformer. Lazy: carrega na 1ª chamada."""
    global _embedder
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        logger.info(
            f"carregando modelo de embeddings: {settings.embed_model} "
            "(pode demorar ~5s na 1a invocacao)"
        )
        _embedder = SentenceTransformer(settings.embed_model)
        logger.info("modelo de embeddings carregado")
    return _embedder


def embed_passages(texts: list[str]) -> np.ndarray:
    """Embedda chunks (com prefixo 'passage: ' do e5)."""
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
    model = get_embedder()
    prefixed = [f"passage: {t}" for t in texts]
    emb = model.encode(prefixed, normalize_embeddings=True, convert_to_numpy=True)
    return emb.astype(np.float32)


def embed_query(text: str) -> np.ndarray:
    """Embedda uma query (com prefixo 'query: ' do e5)."""
    model = get_embedder()
    emb = model.encode(
        f"query: {text}", normalize_embeddings=True, convert_to_numpy=True
    )
    return emb.astype(np.float32)


async def embed_passages_async(texts: list[str]) -> np.ndarray:
    return await asyncio.to_thread(embed_passages, texts)


async def embed_query_async(text: str) -> np.ndarray:
    return await asyncio.to_thread(embed_query, text)


def reset_embedder_for_tests() -> None:
    """Limpa o singleton (apenas testes)."""
    global _embedder
    with _lock:
        _embedder = None
