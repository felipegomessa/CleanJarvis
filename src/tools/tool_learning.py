"""Tools de aprendizado: provas, dificuldades, plano de estudos, leitura de doc.

Spec 007 / RF-007.8. Importa APENAS `learning/` (e `core`/`rag` para utilidades) —
nunca `llm/` ou `ui/`. O LLM é resolvido pelo client default dentro de `learning/`.
"""

from __future__ import annotations

import asyncio
import sqlite3
import unicodedata
from typing import Any

from loguru import logger

from src.core.config import get_settings
from src.core.db import get_connection
from src.domain.learning import get_attempt, get_quiz
from src.learning import difficulty_report, generate, grade_attempt
from src.rag.retrieve import get_document_chunks
from src.tools.registry import ToolDefinition, get_registry


def _norm(s: str) -> str:
    no_accents = "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )
    return no_accents.casefold().strip()


def _resolve_document_ids(conn: sqlite3.Connection, documentos: list[Any]) -> list[int]:
    """Resolve uma lista de ids/títulos para document_ids existentes."""
    rows = conn.execute("SELECT id, title FROM documents").fetchall()
    by_id = {int(r["id"]): str(r["title"]) for r in rows}
    resolved_ids: list[int] = []
    for reference in documentos:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            document_id = int(reference)
            if document_id in by_id:
                resolved_ids.append(document_id)
            continue
        target_title = _norm(str(reference))
        match = [i for i, t in by_id.items() if target_title == _norm(t)] or [
            i for i, t in by_id.items() if target_title in _norm(t)
        ]
        resolved_ids.extend(match[:1])
    return list(dict.fromkeys(resolved_ids))  # dedup preservando ordem


async def _gerar_prova(args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    documentos = args.get("documentos") or args.get("documento") or []
    if isinstance(documentos, (str, int)):
        documentos = [documentos]
    num_mc = int(args.get("num_mc", settings.quiz_default_mc))
    num_open = int(args.get("num_dissertativas", settings.quiz_default_open))
    idioma = "original" if _norm(str(args.get("idioma", "pt"))).startswith(
        ("orig", "ingl", "english")
    ) else "pt"

    def _resolve() -> list[int]:
        with get_connection() as conn:
            return _resolve_document_ids(conn, list(documentos))

    doc_ids = await asyncio.to_thread(_resolve)
    if not doc_ids:
        raise ValueError(
            "nenhum documento reconhecido. Use `listar_materiais` para ver os títulos."
        )

    quiz = await generate(doc_ids, num_mc, num_open, idioma=idioma)
    return {
        "quiz_id": quiz.id,
        "titulo": quiz.title,
        "num_questoes": len(quiz.questions),
        "questoes": [
            {
                "n": i,
                "tipo": q.type,
                "enunciado": q.prompt,
                "alternativas": q.options if q.type == "mc" else None,
            }
            for i, q in enumerate(quiz.questions, start=1)
        ],
        "instrucao": (
            "Prova criada. Para RESPONDER e receber a nota, abra "
            "'Estudar / Prova' no menu '+'. Apresente as questões ao usuário."
        ),
    }


async def _corrigir_prova(args: dict[str, Any]) -> dict[str, Any]:
    attempt_id = args.get("attempt_id")
    respostas = args.get("respostas") or {}
    if attempt_id is None:
        raise ValueError("informe `attempt_id` da tentativa a corrigir")
    if not isinstance(respostas, dict):
        raise ValueError("`respostas` deve ser um objeto {question_id: resposta}")

    def _load() -> Any:
        with get_connection() as conn:
            att = get_attempt(conn, int(attempt_id))
            if att is None:
                raise ValueError(f"tentativa {attempt_id} não encontrada")
            quiz = get_quiz(conn, att.quiz_id)
        return quiz

    quiz = await asyncio.to_thread(_load)
    norm = {int(k): str(v) for k, v in respostas.items()}
    attempt = await grade_attempt(quiz, int(attempt_id), norm)
    return {
        "attempt_id": attempt.id,
        "nota": attempt.score,
        "respostas": [
            {
                "question_id": a.question_id,
                "pontos": a.awarded_points,
                "feedback": a.feedback,
            }
            for a in attempt.answers
        ],
    }


def _report_to_dict(report: Any) -> dict[str, Any]:
    return {
        "positivo": report.positive,
        "topicos_fracos": [
            {"topico": t.topic, "aproveitamento": round(t.ratio, 2)}
            for t in report.weak_topics
        ],
        "recomendacoes": report.recommendations,
        "plano_estudos": [
            {
                "topico": it.topic,
                "acao": it.action,
                "material": it.material,
                "minutos": it.minutes,
                "dia": it.day,
                "hora": it.time,
            }
            for it in report.plan.items
        ],
    }


async def _identificar_dificuldades(args: dict[str, Any]) -> dict[str, Any]:
    attempt_id = args.get("attempt_id")
    report = await difficulty_report(int(attempt_id) if attempt_id is not None else None)
    if report is None:
        return {"mensagem": "nenhuma prova concluída ainda — faça uma prova primeiro."}
    report_dict = _report_to_dict(report)
    return {
        "positivo": report_dict["positivo"],
        "topicos_fracos": report_dict["topicos_fracos"],
        "recomendacoes": report_dict["recomendacoes"],
    }


async def _montar_plano_estudos(args: dict[str, Any]) -> dict[str, Any]:
    attempt_id = args.get("attempt_id")
    report = await difficulty_report(int(attempt_id) if attempt_id is not None else None)
    if report is None:
        return {"mensagem": "nenhuma prova concluída ainda — faça uma prova primeiro."}
    report_dict = _report_to_dict(report)
    return {
        "plano_estudos": report_dict["plano_estudos"],
        "recomendacoes": report_dict["recomendacoes"],
    }


async def _ler_documento(args: dict[str, Any]) -> dict[str, Any]:
    documento = args.get("document_id") or args.get("titulo") or args.get("documento")
    if documento is None:
        raise ValueError("informe `document_id` ou `titulo` do documento")
    limit = args.get("limit")

    def _run() -> dict[str, Any]:
        with get_connection() as conn:
            ids = _resolve_document_ids(conn, [documento])
        if not ids:
            raise ValueError(
                f"documento {documento!r} não encontrado. Veja `listar_materiais`."
            )
        chunks = get_document_chunks(ids[0], limit=int(limit) if limit else None)
        if not chunks:
            return {"document_id": ids[0], "conteudo": "", "aviso": "documento sem texto."}
        full = "\n\n".join(c.text for c in chunks)
        truncated = len(full) > 8000
        return {
            "document_id": ids[0],
            "titulo": chunks[0].document_title,
            "total_trechos": len(chunks),
            "conteudo": full[:8000],
            "truncado": truncated,
        }

    out = await asyncio.to_thread(_run)
    logger.info(f"ler_documento: doc={out.get('document_id')} trechos={out.get('total_trechos')}")
    return out


def _register() -> None:
    reg = get_registry()
    reg.register(
        ToolDefinition(
            name="gerar_prova",
            description=(
                "Gera uma prova (questões de múltipla escolha + dissertativas) a "
                "partir de um ou mais materiais de estudo. Use quando o usuário pedir "
                "'me faça uma prova', 'quero exercícios sobre X', 'teste meus "
                "conhecimentos'. Informe os documentos por título ou id."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "documentos": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Títulos (ou ids) dos materiais-fonte. Aceita vários.",
                    },
                    "num_mc": {"type": "integer", "description": "Nº de múltipla escolha (default 5)."},
                    "num_dissertativas": {
                        "type": "integer",
                        "description": "Nº de dissertativas (default 3).",
                    },
                    "idioma": {
                        "type": "string",
                        "enum": ["pt", "original"],
                        "description": (
                            "Idioma das questões: 'pt' (português, default) ou "
                            "'original' (idioma do material)."
                        ),
                    },
                },
                "required": ["documentos"],
            },
            handler=_gerar_prova,
            examples=[
                {"tool": "gerar_prova", "args": {"documentos": ["aula-KNN"], "num_mc": 4, "num_dissertativas": 2}},
            ],
        )
    )
    reg.register(
        ToolDefinition(
            name="corrigir_prova",
            description=(
                "Corrige as respostas de uma tentativa de prova e retorna a nota 0-10. "
                "Normalmente a correção é feita pela interface 'Estudar / Prova'; use "
                "esta tool apenas se tiver o `attempt_id` e o mapa de respostas."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "integer"},
                    "respostas": {
                        "type": "object",
                        "description": "Mapa {question_id: resposta}. MC: índice como string.",
                    },
                },
                "required": ["attempt_id", "respostas"],
            },
            handler=_corrigir_prova,
        )
    )
    reg.register(
        ToolDefinition(
            name="identificar_dificuldades",
            description=(
                "Analisa o desempenho na última prova concluída (ou na informada) e "
                "aponta os tópicos com maior dificuldade. Use quando o usuário "
                "perguntar 'onde tenho mais dificuldade', 'no que fui mal'."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "integer", "description": "Opcional; default = última prova."},
                },
            },
            handler=_identificar_dificuldades,
        )
    )
    reg.register(
        ToolDefinition(
            name="montar_plano_estudos",
            description=(
                "Monta um plano de estudos focado nas dificuldades da última prova "
                "(ou da informada), com ações de revisão. Use para 'monte um plano de "
                "estudos', 'o que devo revisar'."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "attempt_id": {"type": "integer", "description": "Opcional; default = última prova."},
                },
            },
            handler=_montar_plano_estudos,
        )
    )
    reg.register(
        ToolDefinition(
            name="ler_documento",
            description=(
                "Lê o conteúdo de UM documento específico inteiro, em ordem (diferente "
                "de `buscar_material_rag`, que busca trechos soltos). Use para 'leia o "
                "documento X', 'me dê o índice do material X', 'resuma o documento X'."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "titulo": {"type": "string", "description": "Título (ou parte) do documento."},
                    "document_id": {"type": "integer", "description": "Alternativa ao título."},
                    "limit": {"type": "integer", "description": "Opcional: nº máx. de trechos."},
                },
            },
            handler=_ler_documento,
            examples=[
                {"tool": "ler_documento", "args": {"titulo": "aula-KNN"}},
            ],
        )
    )


_register()
