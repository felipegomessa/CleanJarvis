"""Recursive Character Splitter para chunking — D-006 / RF-002.4."""

from __future__ import annotations

from src.rag.types import Chunk

_SEPARATORS: list[str] = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

# Defaults da função pura (D-006); a ingestão passa `Settings.chunk_size/overlap`.
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 150


def _recursive_split(text: str, size: int, seps: list[str], depth: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    if depth >= len(seps) or seps[depth] == "":
        return [text[i : i + size] for i in range(0, len(text), size)]
    sep = seps[depth]
    parts = text.split(sep)
    out: list[str] = []
    buf = ""
    for p in parts:
        candidate = (buf + sep + p) if buf else p
        if len(candidate) <= size:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            if len(p) > size:
                out.extend(_recursive_split(p, size, seps, depth + 1))
                buf = ""
            else:
                buf = p
    if buf:
        out.append(buf)
    return out


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Quebra `text` em chunks de tamanho-alvo `chunk_size` com overlap real.

    Contrato (D-006):
    - Cada `Chunk.text` é uma **fatia contígua exata** do texto original
      (`text[char_start:char_end]`) — sem caracteres injetados.
    - `char_start`/`char_end` são offsets **corretos** no texto original.
    - Chunks consecutivos se sobrepõem em até `overlap` chars: o chunk i (i>0)
      inclui como prefixo os `overlap` chars que antecedem seu trecho na fonte.
    - `position` é 0-based e sequencial.

    O `_recursive_split` define as fronteiras semânticas (parágrafo > sentença >
    palavra); aqui localizamos cada trecho no original para recuperar os offsets
    e aplicar o overlap a partir da própria fonte.
    """
    if not text or not text.strip():
        return []
    parts = _recursive_split(text, chunk_size, _SEPARATORS, 0)
    if not parts:
        return []

    out: list[Chunk] = []
    search_from = 0
    for i, part in enumerate(parts):
        # Os parts vêm na ordem do texto e são substrings exatas dele; localizamos
        # cada um avançando o cursor para lidar com trechos repetidos.
        idx = text.find(part, search_from)
        if idx < 0:  # defensivo: não deve ocorrer (part é substring de text)
            idx = search_from
        part_end = idx + len(part)
        search_from = part_end

        # Overlap real: prefixo de até `overlap` chars que antecede o trecho na
        # fonte (0 no primeiro chunk ou quando overlap desativado).
        chunk_start = max(0, idx - overlap) if (overlap > 0 and i > 0) else idx

        out.append(
            Chunk(
                text=text[chunk_start:part_end],
                char_start=chunk_start,
                char_end=part_end,
                position=i,
            )
        )
    return out
