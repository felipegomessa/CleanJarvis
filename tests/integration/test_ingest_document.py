"""Integração: ingest_document — Spec 008 / RF-008.3.

O modelo de embedding é substituído por um fake determinístico (sem download).
Foco: a re-ingestão de um documento alterado só remove o antigo quando o novo
foi inteiramente preparado e gravado na mesma transação.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

from src.core.config import get_settings
from src.core.db import apply_migrations, get_connection
from src.rag import ingest
from src.rag.embed import EMBEDDING_DIM
from src.rag.ingest import ingest_document

ORIGINAL_TEXT = (
    "A regressão logística é um modelo estatístico usado para classificação "
    "binária. Ela estima a probabilidade de uma classe com a função sigmoide."
)
CHANGED_TEXT = (
    "Redes neurais são compostas por camadas de neurônios artificiais que "
    "aprendem representações a partir dos dados de treinamento disponíveis."
)
CID_GARBAGE = "(cid:1)(cid:2)(cid:3)(cid:4)(cid:5) " * 50


def _fake_embed(texts: list[str]) -> np.ndarray:
    return np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)


def _wrong_dimension_embed(texts: list[str]) -> np.ndarray:
    # float64 dobra o tamanho do blob: o vec0 FLOAT[384] rejeita no INSERT.
    return np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float64)


def _failing_embed(texts: list[str]) -> np.ndarray:
    raise RuntimeError("modelo indisponível")


@pytest.fixture
def ingest_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("JARVIS_DB_PATH", str(tmp_path / "ingest.db"))
    monkeypatch.setenv("JARVIS_LLM_API_KEY", "fake")
    get_settings.cache_clear()
    with get_connection() as conn:
        apply_migrations(conn)
    monkeypatch.setattr(ingest, "embed_passages", _fake_embed)
    yield tmp_path
    get_settings.cache_clear()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _stored_documents() -> list[tuple[str, int]]:
    """(content_hash, nº de vetores) de cada documento gravado."""
    with get_connection() as conn:
        rows = conn.execute("SELECT id, content_hash FROM documents").fetchall()
        return [
            (
                str(r["content_hash"]),
                conn.execute(
                    "SELECT COUNT(*) FROM chunk_vecs WHERE chunk_id IN "
                    "(SELECT id FROM chunks WHERE document_id = ?)",
                    (r["id"],),
                ).fetchone()[0],
            )
            for r in rows
        ]


def test_new_document_is_ingested(ingest_db: Path) -> None:
    result = ingest_document(_write(ingest_db / "doc.txt", ORIGINAL_TEXT))

    assert result.status == "ingested"
    assert result.chunk_count == 1
    stored = _stored_documents()
    assert len(stored) == 1 and stored[0][1] == 1


def test_same_content_is_skipped(ingest_db: Path) -> None:
    path = _write(ingest_db / "doc.txt", ORIGINAL_TEXT)
    first = ingest_document(path)

    second = ingest_document(path)

    assert second.status == "skipped"
    assert second.reason == "hash_match"
    assert second.document_id == first.document_id


def test_changed_document_replaces_previous(ingest_db: Path) -> None:
    path = _write(ingest_db / "doc.txt", ORIGINAL_TEXT)
    ingest_document(path)
    old_hash = _stored_documents()[0][0]

    result = ingest_document(_write(path, CHANGED_TEXT))

    assert result.status == "ingested"
    stored = _stored_documents()
    assert len(stored) == 1
    assert stored[0][0] != old_hash


@pytest.mark.parametrize(
    ("new_text", "embed", "expected_reason"),
    [
        (CHANGED_TEXT, _failing_embed, "embed_failed"),
        (CID_GARBAGE, _fake_embed, "unreadable_text"),
        (CHANGED_TEXT, _wrong_dimension_embed, "db_insert_failed"),
    ],
    ids=["embed_failed", "unreadable_text", "db_insert_failed"],
)
def test_failed_reingestion_keeps_previous_document(
    ingest_db: Path,
    monkeypatch: pytest.MonkeyPatch,
    new_text: str,
    embed: object,
    expected_reason: str,
) -> None:
    path = _write(ingest_db / "doc.txt", ORIGINAL_TEXT)
    ingest_document(path)
    before = _stored_documents()

    monkeypatch.setattr(ingest, "embed_passages", embed)
    result = ingest_document(_write(path, new_text))

    assert result.status == "error"
    assert result.reason == expected_reason
    assert _stored_documents() == before


@pytest.mark.parametrize(
    ("filename", "content", "expected_reason"),
    [
        ("doc.docx", b"qualquer", "unsupported_type"),
        ("corrompido.pdf", b"isto nao e um pdf", "extract_failed"),
        ("vazio.txt", b"   \n\n  ", "no_text"),
        ("lixo.txt", CID_GARBAGE.encode(), "unreadable_text"),
    ],
)
def test_error_reasons(
    ingest_db: Path, filename: str, content: bytes, expected_reason: str
) -> None:
    path = ingest_db / filename
    path.write_bytes(content)

    result = ingest_document(path)

    assert result.status == "error"
    assert result.reason == expected_reason
    assert _stored_documents() == []


def test_missing_file_reason(ingest_db: Path) -> None:
    result = ingest_document(ingest_db / "nao_existe.txt")

    assert result.status == "error"
    assert result.reason == "not_a_file"


def test_embedding_failure_reason(
    ingest_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest, "embed_passages", _failing_embed)

    result = ingest_document(_write(ingest_db / "doc.txt", ORIGINAL_TEXT))

    assert result.status == "error"
    assert result.reason == "embed_failed"
