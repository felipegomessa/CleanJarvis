"""Identificação de dificuldades + plano de estudos didático e consciente da
agenda — Spec 007 / RF-007.7."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from loguru import logger

from src.core.config import get_settings
from src.domain.agenda import list_all_events
from src.domain.learning import (
    DifficultyReport,
    StudyPlan,
    StudyPlanItem,
    TopicScore,
    topic_breakdown,
)
from src.domain.learning.models import DEFAULT_STUDY_MINUTES
from src.llm.json_utils import parse_json_response
from src.llm.types import Message
from src.rag.retrieve import search

# Horizonte de planejamento e janela de estudo considerada "livre" por padrão.
PLAN_HORIZON_DAYS = 7


def topic_scores(conn: sqlite3.Connection, attempt_id: int) -> list[TopicScore]:
    return topic_breakdown(conn, attempt_id)


def select_weak(scores: list[TopicScore], threshold: float) -> list[TopicScore]:
    """Tópicos com aproveitamento abaixo do limiar (mais fraco primeiro)."""
    weak = [s for s in scores if s.possible > 0 and s.ratio < threshold]
    return sorted(weak, key=lambda s: s.ratio)


def _agenda_summary(conn: sqlite3.Connection, now: datetime) -> str:
    """Compromissos dos próximos dias (para o LLM achar tempo livre)."""
    horizon = now + timedelta(days=PLAN_HORIZON_DAYS)
    busy = []
    for event in list_all_events(conn):
        start = event.starts_at.replace(tzinfo=None)
        if now <= start <= horizon:
            fim = f"-{event.ends_at:%H:%M}" if event.ends_at else ""
            busy.append(f"- {start:%a %d/%m %H:%M}{fim} {event.title} ({event.kind})")
    if not busy:
        return f"(sem compromissos nos próximos {PLAN_HORIZON_DAYS} dias)"
    return "\n".join(busy)


def build_coach_messages(
    weak: list[TopicScore],
    contexts: dict[str, str],
    *,
    today: str,
    horizon: str,
    agenda: str,
) -> list[Message]:
    """Mensagens para o LLM gerar um plano didático e agendado — função pura (testável)."""
    blocos = []
    for topic_score in weak:
        topic_context = contexts.get(topic_score.topic, "")
        blocos.append(
            f"- Tópico: {topic_score.topic} (aproveitamento {topic_score.ratio:.0%} — "
            f"quanto menor, mais profundidade/tempo precisa)\n"
            f"  Trechos do material:\n{topic_context}"
        )
    corpo = "\n\n".join(blocos)
    system = (
        "Você é um tutor acadêmico que monta planos de estudo DIDÁTICOS e realistas. "
        "Para cada tópico fraco, escreva ações de estudo CONCRETAS e progressivas "
        "(ex.: 'reler a seção X', 'resumir com suas palavras', 'fazer 5 exercícios', "
        "'explicar em voz alta') citando a fonte como [Doc N] quando houver. "
        "DIMENSIONE pela dificuldade: tópicos com menor aproveitamento recebem MAIS "
        "sessões e/ou mais minutos. DIVIDA o estudo em várias sessões curtas em DIAS "
        "e HORÁRIOS diferentes, encaixadas no tempo LIVRE do aluno — NÃO marque "
        "sessões que conflitem com os compromissos listados. Use blocos de 30 a 90 min. "
        "Responda em português, APENAS um JSON: "
        '{"recommendations": ["..."], "plan": [{"topic":"...","action":"...",'
        '"material":"...","day":"YYYY-MM-DD","time":"HH:MM","minutes":45}]}'
    )
    user = (
        f"Hoje é {today}. Planeje os estudos entre {today} e {horizon}.\n\n"
        f"Compromissos já na agenda (evite esses horários):\n{agenda}\n\n"
        f"Tópicos fracos e material de apoio:\n\n{corpo}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_coach_json(raw: str, weak: list[TopicScore]) -> tuple[list[str], StudyPlan]:
    """Parseia recomendações + plano (com dia/hora). Em falha, plano genérico."""
    try:
        parsed = parse_json_response(raw)
        recs = [str(x) for x in parsed.get("recommendations", []) if str(x).strip()]
        items: list[StudyPlanItem] = []
        for plan_entry in parsed.get("plan", []):
            if not isinstance(plan_entry, dict):
                continue
            items.append(
                StudyPlanItem(
                    topic=str(plan_entry.get("topic", "")).strip() or "(geral)",
                    action=str(plan_entry.get("action", "Revisar o tópico")).strip(),
                    material=(
                        str(plan_entry["material"]).strip()
                        if plan_entry.get("material")
                        else None
                    ),
                    minutes=int(plan_entry.get("minutes", DEFAULT_STUDY_MINUTES)),
                    day=(str(plan_entry["day"]).strip() if plan_entry.get("day") else None),
                    time=(str(plan_entry["time"]).strip() if plan_entry.get("time") else None),
                )
            )
        if not items:
            raise ValueError("plano vazio")
        return recs, StudyPlan(items=items)
    except (ValueError, TypeError) as e:
        logger.warning(f"plano do coach inválido ({e}); usando fallback genérico")
        items = [
            StudyPlanItem(
                topic=topic_score.topic,
                action=f"Revisar '{topic_score.topic}' no material",
                minutes=DEFAULT_STUDY_MINUTES,
            )
            for topic_score in weak
        ]
        return [], StudyPlan(items=items)


async def build_difficulty_report(
    gemma,  # GemmaClient | FakeLLM (complete_chat)
    conn: sqlite3.Connection,
    attempt_id: int,
    threshold: float | None = None,
) -> DifficultyReport:
    """Gera o relatório de dificuldades + plano de estudos agendado de uma tentativa."""
    thr = threshold if threshold is not None else get_settings().quiz_weak_threshold
    scores = topic_breakdown(conn, attempt_id)
    weak = select_weak(scores, thr)

    if not weak:
        return DifficultyReport(
            weak_topics=[],
            recommendations=[
                "Parabéns! Você foi bem em todos os tópicos avaliados. "
                "Considere aprofundar com exercícios mais avançados."
            ],
            plan=StudyPlan(items=[]),
            positive=True,
        )

    # Contexto do material por tópico fraco (RAG) para aterrar as ações.
    contexts: dict[str, str] = {}
    for topic_score in weak:
        try:
            retrieval = search(topic_score.topic, top_k=2)
            contexts[topic_score.topic] = "\n".join(
                f"[Doc {i}] {c.text[:500]}" for i, c in enumerate(retrieval.chunks, start=1)
            )
        except Exception as e:
            logger.warning(f"retrieval do coach falhou para '{topic_score.topic}': {e}")
            contexts[topic_score.topic] = ""

    now = datetime.now()
    agenda = _agenda_summary(conn, now)
    messages = build_coach_messages(
        weak,
        contexts,
        today=now.strftime("%Y-%m-%d (%A)"),
        horizon=(now + timedelta(days=PLAN_HORIZON_DAYS)).strftime("%Y-%m-%d"),
        agenda=agenda,
    )
    try:
        raw = await gemma.complete_chat(messages)
        recs, plan = parse_coach_json(raw, weak)
    except Exception as e:
        logger.warning(f"coach LLM falhou: {e}; usando plano genérico")
        recs, plan = parse_coach_json("", weak)

    return DifficultyReport(
        weak_topics=weak, recommendations=recs, plan=plan, positive=False
    )
