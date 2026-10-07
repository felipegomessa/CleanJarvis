"""Ingestão de documentos (PDF/TXT/MD) com dedupe por hash — RF-002.2/3/D-021."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pdfplumber
from loguru import logger

from src.core.config import get_settings
from src.core.db import get_connection
from src.rag.chunk import chunk_text
from src.rag.embed import embed_passages
from src.rag.types import Chunk, IngestResult

SUPPORTED_EXT = {".pdf", ".txt", ".md"}

# Meta-documentação que vive em /data mas NÃO é material de estudo. Indexá-la
# polui o retrieval (o README do dataset chegava a ranquear em #1 para perguntas
# conceituais, sem conter conteúdo real). Comparação por nome, case-insensitive.
EXCLUDED_FILENAMES = {"readme.md"}

# Fração mínima de "palavras reais" para o texto extraído ser considerado legível.
# Calibrado contra o dataset: documentos bons ficam em 0.53-0.69; um PDF cujas
# fontes não têm mapa de caracteres (sem ToUnicode) extrai apenas marcadores
# `(cid:N)` ou caracteres de controle e cai para ~0.00. O corte em 0.25 separa os
# dois casos com folga, sem rejeitar documentos parcialmente sujos (figuras/fórmulas).
MIN_REAL_WORD_RATIO = 0.25

# Um "token de palavra" é uma sequência de 2+ letras (inclui acentuadas PT-BR).
_WORD_RE = re.compile(r"^[A-Za-zÀ-ÿ]{2,}$")


def real_word_ratio(text: str) -> float:
    """Fração de tokens que parecem palavras reais (2+ letras) sobre o total.

    Métrica robusta para detectar lixo de extração: marcadores `(cid:1)` e
    caracteres de controle não casam com `_WORD_RE`, derrubando a razão a ~0.
    """
    tokens = text.split()
    if not tokens:
        return 0.0
    real = sum(1 for t in tokens if _WORD_RE.match(t))
    return real / len(tokens)


def is_readable_text(text: str) -> bool:
    """True se o texto extraído tem palavras reais suficientes para indexar.

    Cumpre a política do CLAUDE.md §8: um PDF sem texto extraível (fonte sem mapa
    de caracteres → `(cid:N)`/lixo binário) deve ser pulado, não indexado.
    """
    return real_word_ratio(text) >= MIN_REAL_WORD_RATIO


def _compute_sha256(path: Path, buf_size: int = 64 * 1024) -> str:
    """Hash SHA-256 do conteúdo (streaming)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(buf_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _extract_text(path: Path) -> str:
    """Extrai texto plano de um arquivo. Raises se tipo não suportado."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n\n".join(pages)
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"tipo não suportado: {ext}")


def _delete_document(conn: sqlite3.Connection, doc_id: int) -> None:
    """Remove um documento e limpa chunks + chunk_vecs orfaos."""
    chunk_ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM chunks WHERE document_id = ?", (doc_id,)
        ).fetchall()
    ]
    if chunk_ids:
        placeholders = ",".join("?" * len(chunk_ids))
        conn.execute(
            f"DELETE FROM chunk_vecs WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
    conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    # chunks sao removidos via ON DELETE CASCADE da FK


@dataclass
class PreparedContent:
    """Texto, chunks e embeddings de um documento, prontos para gravar."""

    text: str
    chunks: list[Chunk]
    embeddings: np.ndarray


def _error(source_path: str, reason: str, error: str) -> IngestResult:
    return IngestResult(status="error", source_path=source_path, reason=reason, error=error)


def _validate_input_file(path: Path) -> IngestResult | None:
    """Erro se a extensão não é suportada ou o caminho não é um arquivo regular."""
    if path.suffix.lower() not in SUPPORTED_EXT:
        return _error(str(path), "unsupported_type", f"extensão {path.suffix} não suportada")
    if not path.exists() or not path.is_file():
        return _error(
            str(path), "not_a_file", "arquivo não encontrado ou não é arquivo regular"
        )
    return None


def _find_document_by_hash(conn: sqlite3.Connection, content_hash: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return int(row["id"]) if row else None


def _find_document_by_path(conn: sqlite3.Connection, source_path: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM documents WHERE source_path = ?", (source_path,)
    ).fetchone()
    return int(row["id"]) if row else None


def _prepare_content(path: Path) -> PreparedContent | IngestResult:
    """Extrai, valida, chunkifica e embedda. Não toca no banco."""
    source_path = str(path)
    try:
        text = _extract_text(path)
    except Exception as e:
        # pdfplumber/pdfminer levantam tipos variados para PDF corrompido (§8: skip + log).
        logger.exception(f"falha ao extrair texto de {path}")
        return _error(source_path, "extract_failed", str(e))
    if not text.strip():
        return _error(source_path, "no_text", "texto extraído está vazio (PDF scaneado?)")

    # Valida a QUALIDADE do texto extraído (CLAUDE.md §8). PDFs cujas fontes não
    # têm mapa de caracteres extraem só lixo `(cid:N)`/controle — que não é vazio,
    # mas envenena o índice se for embeddado. Recusamos aqui.
    ratio = real_word_ratio(text)
    if ratio < MIN_REAL_WORD_RATIO:
        logger.warning(
            f"texto ilegível em {path.name} "
            f"(palavras reais={ratio:.0%} < {MIN_REAL_WORD_RATIO:.0%}); "
            "PDF sem texto extraível (fonte sem mapa de caracteres?) — pulado. "
            "Use OCR ou substitua por uma cópia com texto selecionável."
        )
        return _error(
            source_path,
            "unreadable_text",
            f"texto extraído ilegível ({ratio:.0%} de palavras reais); "
            "PDF sem texto selecionável — necessita OCR ou cópia limpa",
        )

    settings = get_settings()
    chunks = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        return _error(source_path, "no_chunks", "chunking produziu lista vazia")

    try:
        embeddings = embed_passages([chunk.text for chunk in chunks])
    except Exception as e:
        # Falha do modelo de embeddings (download, memória...) vira erro do arquivo.
        logger.exception(f"falha ao gerar embeddings de {path}")
        return _error(source_path, "embed_failed", str(e))
    return PreparedContent(text=text, chunks=chunks, embeddings=embeddings)


def _persist(
    conn: sqlite3.Connection,
    path: Path,
    content_hash: str,
    content: PreparedContent,
    previous_id: int | None,
) -> IngestResult:
    """Grava documento + chunks + vetores numa transação, substituindo a versão anterior.

    O DELETE da versão anterior fica DENTRO da transação (D-021, revisão Spec 008):
    se qualquer INSERT falhar, o ROLLBACK devolve o documento antigo intacto.
    """
    source_path = str(path)
    try:
        conn.execute("BEGIN")
        if previous_id is not None:
            logger.info(f"re-ingerindo {path.name} (conteúdo mudou)")
            _delete_document(conn, previous_id)
        document_cursor = conn.execute(
            """INSERT INTO documents
                   (title, source_path, type, char_count, chunk_count, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                path.stem,
                source_path,
                path.suffix.lower().lstrip("."),
                len(content.text),
                len(content.chunks),
                content_hash,
            ),
        )
        document_id = int(document_cursor.lastrowid or 0)
        for chunk, embedding in zip(content.chunks, content.embeddings, strict=True):
            chunk_cursor = conn.execute(
                """INSERT INTO chunks
                       (document_id, position, text, char_start, char_end)
                   VALUES (?, ?, ?, ?, ?)""",
                (document_id, chunk.position, chunk.text, chunk.char_start, chunk.char_end),
            )
            conn.execute(
                "INSERT INTO chunk_vecs (chunk_id, embedding) VALUES (?, ?)",
                (int(chunk_cursor.lastrowid or 0), embedding.tobytes()),
            )
        conn.execute("COMMIT")
    except Exception as e:
        # Qualquer falha de SQLite/sqlite-vec desfaz tudo, inclusive o DELETE.
        conn.execute("ROLLBACK")
        logger.exception(f"falha ao inserir {path}")
        return _error(source_path, "db_insert_failed", str(e))

    logger.info(
        f"ingerido: {path.name} (doc_id={document_id}, {len(content.chunks)} chunks, "
        f"{len(content.text)} chars)"
    )
    return IngestResult(
        status="ingested",
        source_path=source_path,
        document_id=document_id,
        chunk_count=len(content.chunks),
    )


def ingest_document(path: Path) -> IngestResult:
    """Ingere 1 documento. Idempotente via SHA-256 (D-021).

    - mesmo hash existente -> 'skipped' (no-op)
    - mesmo path com hash diferente -> substitui o antigo na mesma transação
    - novo -> insere

    Returns: IngestResult com status e detalhes.
    """
    source_path = str(path)
    invalid = _validate_input_file(path)
    if invalid is not None:
        return invalid

    try:
        content_hash = _compute_sha256(path)
    except OSError as e:
        return _error(source_path, "read_failed", str(e))

    with get_connection() as conn:
        existing_id = _find_document_by_hash(conn, content_hash)
        if existing_id is not None:
            logger.debug(f"skip: {path.name} (hash ja indexado, doc_id={existing_id})")
            return IngestResult(
                status="skipped",
                source_path=source_path,
                reason="hash_match",
                document_id=existing_id,
            )
        previous_id = _find_document_by_path(conn, source_path)

        prepared = _prepare_content(path)
        if isinstance(prepared, IngestResult):
            return prepared  # versão anterior (se houver) continua intacta
        return _persist(conn, path, content_hash, prepared, previous_id)


def ingest_directory(dir_path: Path, recursive: bool = False) -> list[IngestResult]:
    """Ingere todos os documentos suportados em um diretorio (best-effort).

    Falha em 1 arquivo NAO interrompe os demais.
    """
    if not dir_path.exists() or not dir_path.is_dir():
        logger.error(f"diretório não existe: {dir_path}")
        return []

    pattern = "**/*" if recursive else "*"
    candidates = [
        p
        for p in dir_path.glob(pattern)
        if p.is_file()
        and p.suffix.lower() in SUPPORTED_EXT
        and p.name.lower() not in EXCLUDED_FILENAMES
    ]

    results: list[IngestResult] = []
    for p in sorted(candidates):
        results.append(ingest_document(p))

    summary = {
        "ingested": sum(1 for r in results if r.status == "ingested"),
        "skipped": sum(1 for r in results if r.status == "skipped"),
        "error": sum(1 for r in results if r.status == "error"),
    }
    logger.info(
        f"ingest_directory: {summary['ingested']} ingested, "
        f"{summary['skipped']} skipped, {summary['error']} errors"
    )
    return results
