"""Geração de provas a partir dos materiais (LLM aterrado) — Spec 007 / RF-007.5."""

from __future__ import annotations

import re

from loguru import logger
from pydantic import ValidationError

from src.core.config import get_settings
from src.core.db import get_connection
from src.domain.learning import Question, Quiz, add_questions, create_quiz, get_quiz
from src.domain.learning.models import MIN_MC_OPTIONS
from src.learning.errors import LearningError
from src.llm.json_utils import parse_json_response
from src.llm.types import Message
from src.rag.retrieve import RetrievedChunk, get_document_chunks

# Referência textual de um trecho no prompt: [T1], [T2], ...
RefMap = dict[str, RetrievedChunk]


def _collect_refs(document_ids: list[int], max_per_doc: int) -> tuple[list[tuple[str, RetrievedChunk]], RefMap]:
    """Lê os chunks (cota por documento) e os rotula globalmente como T1, T2, ..."""
    refs: list[tuple[str, RetrievedChunk]] = []
    ref_map: RefMap = {}
    ref_counter = 0
    for doc_id in document_ids:
        chunks = get_document_chunks(doc_id, limit=max_per_doc)
        if not chunks:
            logger.warning(f"documento {doc_id} sem chunks legíveis — ignorado na prova")
            continue
        for chunk in chunks:
            ref_counter += 1
            ref = f"T{ref_counter}"
            refs.append((ref, chunk))
            ref_map[ref] = chunk
    return refs, ref_map


def _language_instruction(idioma: str) -> str:
    """Instrução de idioma das questões. 'pt' força PT-BR; senão usa o idioma da fonte."""
    if idioma == "original":
        return (
            "Escreva as questões, alternativas e gabaritos no MESMO idioma dos "
            "trechos fornecidos."
        )
    return (
        "Escreva TODAS as questões, alternativas e gabaritos em PORTUGUÊS do Brasil, "
        "mesmo que os trechos estejam em inglês ou outro idioma (traduza os conceitos)."
    )


def build_generation_messages(
    refs: list[tuple[str, RetrievedChunk]],
    num_mc: int,
    num_open: int,
    idioma: str = "pt",
) -> list[Message]:
    """Monta as mensagens (system+user) para a geração — função pura (testável)."""
    context = "\n\n".join(
        f"[{ref}] (Documento: {ch.document_title})\n{ch.text}" for ref, ch in refs
    )
    system = (
        "Você é um gerador de provas acadêmicas. Gere questões SOMENTE com base nos "
        "trechos numerados fornecidos. NÃO invente fatos fora dos trechos. Distribua "
        "as questões entre documentos/tópicos diferentes. "
        f"{_language_instruction(idioma)} Responda APENAS com um "
        "único objeto JSON válido, sem texto antes ou depois, no formato:\n"
        '{"questions": [\n'
        '  {"type":"mc","topic":"<tópico curto>","prompt":"<enunciado>",'
        '"options":["a","b","c","d"],"correct_index":0,"source":"T1"},\n'
        '  {"type":"open","topic":"<tópico curto>","prompt":"<enunciado>",'
        '"answer_key":"<pontos esperados na resposta>","source":"T2"}\n'
        "]}\n"
        "Regras: questões 'mc' têm preferencialmente 4 alternativas "
        f"(mínimo {MIN_MC_OPTIONS}) e 1 "
        "correta — 'correct_index' é o índice da correta (começa em 0). "
        "Questões 'open' têm 'answer_key' com os pontos "
        "esperados. Cada questão indica em 'source' o trecho de origem (ex.: 'T3'). "
        'JSON válido: use somente aspas duplas, escape aspas internas como \\", e '
        "não use quebras de linha dentro das strings."
    )
    user = (
        f"Gere EXATAMENTE {num_mc} questões 'mc' e {num_open} questões 'open' a "
        f"partir dos trechos abaixo.\n\n{context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _normalize_ref(raw: object) -> str:
    """Normaliza 'T3' / '[T3]' / '3' / 't3' para a forma canônica 'T3'."""
    normalized = re.sub(r"[^0-9A-Za-z]", "", str(raw)).upper()
    if normalized.isdigit():
        normalized = "T" + normalized
    elif not normalized.startswith("T"):
        normalized = "T" + re.sub(r"\D", "", normalized)
    return normalized


def parse_quiz_questions(raw: str, ref_map: RefMap) -> list[Question]:
    """Faz parsing+validação do JSON gerado. Levanta LearningError se irrecuperável.

    Questões individualmente inválidas (campos faltando, MC sem 4 alternativas) são
    descartadas com warning; o restante é mantido. Se nada sobrar, levanta erro.
    """
    try:
        parsed = parse_json_response(raw)
    except ValueError as e:
        raise LearningError(f"JSON da prova inválido: {e}") from e

    items = parsed.get("questions")
    if not isinstance(items, list) or not items:
        raise LearningError("JSON da prova sem lista 'questions'")

    out: list[Question] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        chunk = ref_map.get(_normalize_ref(it.get("source", "")))
        try:
            q = Question(
                type=it.get("type"),
                prompt=str(it.get("prompt", "")).strip(),
                topic=str(it.get("topic", "")).strip(),
                options=it.get("options"),
                correct_index=it.get("correct_index"),
                answer_key=it.get("answer_key"),
                source_document_id=chunk.document_id if chunk else None,
                source_chunk_id=chunk.chunk_id if chunk else None,
            )
            if not q.prompt:
                raise ValueError("enunciado vazio")
            out.append(q)
        except (ValidationError, ValueError) as e:
            logger.warning(f"questão #{i} descartada (inválida): {e}")

    if not out:
        raise LearningError("nenhuma questão válida no JSON da prova")
    return out


def _split_by_type(questions: list[Question]) -> tuple[list[Question], list[Question]]:
    mc_questions = [q for q in questions if q.type == "mc"]
    open_questions = [q for q in questions if q.type == "open"]
    return mc_questions, open_questions


async def generate_quiz(
    gemma,  # GemmaClient | FakeLLM — tipado estruturalmente (complete_chat)
    document_ids: list[int],
    num_mc: int,
    num_open: int,
    *,
    title: str | None = None,
    idioma: str = "pt",
) -> Quiz:
    """Gera e persiste uma prova a partir de vários documentos. Retorna o Quiz.

    Aterrada nos chunks (cota por documento); 1 reparo se o JSON vier insuficiente;
    falhou → LearningError. `idioma`: 'pt' (PT-BR) ou 'original' (idioma do material).
    """
    if not document_ids:
        raise LearningError("selecione ao menos um documento para gerar a prova")
    if num_mc + num_open <= 0:
        raise LearningError("a prova precisa de ao menos 1 questão")

    settings = get_settings()
    refs, ref_map = _collect_refs(document_ids, settings.quiz_max_chunks_per_doc)
    if not refs:
        raise LearningError(
            "nenhum documento selecionado tem texto legível para gerar questões"
        )

    messages = build_generation_messages(refs, num_mc, num_open, idioma)
    raw = await gemma.complete_chat(messages)

    # Avalia a 1a resposta: pode vir com JSON malformado OU com poucas questões.
    mc_questions: list[Question] = []
    open_questions: list[Question] = []
    problema = ""
    try:
        mc_questions, open_questions = _split_by_type(parse_quiz_questions(raw, ref_map))
        if len(mc_questions) < num_mc or len(open_questions) < num_open:
            problema = (
                f"faltaram questões (mc={len(mc_questions)}/{num_mc}, "
                f"open={len(open_questions)}/{num_open})"
            )
    except LearningError as e:
        problema = f"JSON inválido ({e})"

    # 1 reparo cobrindo AMBOS os casos: JSON malformado ou contagem insuficiente
    # (RF-007.5 / §8). Se o reparo também falhar, o LearningError propaga como final.
    if problema:
        logger.warning(f"geração com problema: {problema}; tentando 1 reparo")
        repair: list[Message] = [
            *messages,
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"Sua resposta anterior teve um problema: {problema}. Gere "
                    f"NOVAMENTE apenas um JSON VÁLIDO com EXATAMENTE {num_mc} questões "
                    f"'mc' e {num_open} 'open'. Use somente aspas duplas; escape aspas "
                    'internas como \\"; não use quebras de linha dentro das strings; '
                    "não inclua nenhum texto fora do JSON."
                ),
            },
        ]
        raw = await gemma.complete_chat(repair)
        mc_questions, open_questions = _split_by_type(parse_quiz_questions(raw, ref_map))

    if len(mc_questions) < num_mc or len(open_questions) < num_open:
        raise LearningError(
            f"não foi possível gerar a prova solicitada "
            f"(obtido mc={len(mc_questions)}/{num_mc}, "
            f"open={len(open_questions)}/{num_open})"
        )

    final = mc_questions[:num_mc] + open_questions[:num_open]
    quiz_title = title or "Prova gerada dos materiais"

    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            quiz_id = create_quiz(conn, quiz_title, document_ids)
            add_questions(conn, quiz_id, final)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        quiz = get_quiz(conn, quiz_id)

    assert quiz is not None
    logger.info(
        f"prova {quiz_id} gerada: {len(final)} questões "
        f"({num_mc} MC + {num_open} dissertativas) de {len(document_ids)} doc(s)"
    )
    return quiz
