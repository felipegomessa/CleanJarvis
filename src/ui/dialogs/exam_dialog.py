"""Dialog modal: prova eletrônica interativa (gerar→responder→corrigir→plano).

Spec 007 / RF-007.9. Usa `learning/` injetando `state.gemma` (UI tem o client).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from loguru import logger
from nicegui import ui

from src.core.config import get_settings
from src.core.db import get_connection
from src.domain.agenda import EventCreate, create_event
from src.domain.learning import Question, Quiz
from src.domain.tasks import TaskCreate, create_task
from src.learning import difficulty_report, generate, grade_attempt, start_attempt
from src.ui.state import get_state

_CARD = "background:#0a0a0a; color:#f5f5f5"


def _parse_when(item: Any) -> datetime | None:
    """Converte day (YYYY-MM-DD) + time (HH:MM) do plano em datetime, se válidos."""
    if not getattr(item, "day", None):
        return None
    try:
        return datetime.fromisoformat(f"{item.day}T{item.time or '19:00'}")
    except (ValueError, TypeError):
        return None


def _fmt_when(item: Any) -> str:
    """Rótulo amigável '🗓️ dd/mm HH:MM · ' para o plano (vazio se sem data)."""
    dt = _parse_when(item)
    if dt is None:
        return ""
    return f"🗓️ {dt:%d/%m %H:%M} · "


def _list_documents() -> dict[int, str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title FROM documents ORDER BY title"
        ).fetchall()
    return {int(r["id"]): str(r["title"]) for r in rows}


def open_exam_dialog() -> None:
    state = get_state()
    settings = get_settings()
    docs = _list_documents()

    # Estado mutável do fluxo
    flow: dict[str, Any] = {"quiz": None, "attempt_id": None, "inputs": []}

    with ui.dialog().props("persistent") as dialog, ui.card().classes(
        "w-full max-w-3xl"
    ).style(_CARD):
        with ui.row().classes("items-center justify-between w-full px-2"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("school").classes("text-cyan-400")
                ui.label("Estudar / Prova").style("font-size:20px; font-weight:600")
            ui.button(icon="close", on_click=dialog.close).props(
                "flat round size=sm color=white"
            )

        body = ui.column().classes("w-full gap-3 px-2").style(
            "max-height:65vh; overflow-y:auto"
        )

        # ---------- Passo 1: configurar ----------
        def render_config() -> None:
            body.clear()
            with body:
                if not state.online or state.gemma is None:
                    ui.label(
                        "LLM indisponível — não é possível gerar provas agora."
                    ).style("color:#ffb3b3")
                    return
                if not docs:
                    ui.label(
                        "Nenhum material indexado. Envie materiais primeiro."
                    ).style("color:#ffb3b3")
                    return

                ui.label("1. Configure sua prova").style(
                    "font-size:16px; font-weight:600"
                )
                doc_sel = ui.select(
                    docs, multiple=True, label="Materiais-fonte (escolha 1 ou mais)"
                ).classes("w-full").props("use-chips")
                with ui.row().classes("gap-3 w-full items-end"):
                    mc_in = ui.number(
                        "Múltipla escolha", value=settings.quiz_default_mc, min=0, max=20
                    ).classes("w-40")
                    op_in = ui.number(
                        "Dissertativas", value=settings.quiz_default_open, min=0, max=10
                    ).classes("w-40")
                    lang_in = ui.select(
                        {"pt": "Português", "original": "Original do material"},
                        value="pt",
                        label="Idioma da prova",
                    ).classes("w-52")

                async def on_generate() -> None:
                    sel = list(doc_sel.value or [])
                    if not sel:
                        ui.notify("Selecione ao menos um material", type="warning")
                        return
                    nmc, nop = int(mc_in.value or 0), int(op_in.value or 0)
                    if nmc + nop <= 0:
                        ui.notify("Defina ao menos 1 questão", type="warning")
                        return
                    body.clear()
                    with body:
                        ui.spinner(size="lg").classes("self-center")
                        ui.label("Gerando prova a partir dos materiais…").classes(
                            "self-center"
                        ).style("color:#888")
                    try:
                        quiz = await generate(
                            sel, nmc, nop, idioma=lang_in.value, gemma=state.gemma
                        )
                        flow["quiz"] = quiz
                        flow["attempt_id"] = start_attempt(quiz.id)
                        render_exam()
                    except Exception as e:
                        logger.exception("falha ao gerar prova")
                        body.clear()
                        with body:
                            ui.label(f"Não foi possível gerar a prova: {e}").style(
                                "color:#ffb3b3"
                            )
                            ui.button("Voltar", on_click=render_config).props("flat")

                ui.button("Gerar prova", icon="auto_awesome", on_click=on_generate).props(
                    "color=primary"
                )

        # ---------- Passo 2: responder ----------
        def render_exam() -> None:
            quiz: Quiz = flow["quiz"]
            flow["inputs"] = []
            body.clear()
            with body:
                ui.label(quiz.title).style("font-size:16px; font-weight:600")
                ui.label("2. Responda as questões").style("color:#888; font-size:13px")
                for i, question in enumerate(quiz.questions, start=1):
                    with ui.card().classes("w-full").style("background:#141414"):
                        tag = "Múltipla escolha" if question.type == "mc" else "Dissertativa"
                        ui.label(f"Q{i} · {tag} · {question.topic}").style(
                            "color:#7fd; font-size:11px"
                        )
                        ui.label(question.prompt).style("font-weight:600")
                        if question.type == "mc" and question.options:
                            answer_input = ui.radio(
                                {j: opt for j, opt in enumerate(question.options)}
                            ).props("color=cyan")
                        else:
                            answer_input = ui.textarea("Sua resposta").classes("w-full")
                        flow["inputs"].append((question, answer_input))

                async def on_submit() -> None:
                    responses: dict[int, str] = {}
                    for question, answer_input in flow["inputs"]:
                        answer_value = answer_input.value
                        responses[question.id] = "" if answer_value is None else str(answer_value)
                    body.clear()
                    with body:
                        ui.spinner(size="lg").classes("self-center")
                        ui.label("Corrigindo…").classes("self-center").style("color:#888")
                    try:
                        attempt = await grade_attempt(
                            quiz, flow["attempt_id"], responses, gemma=state.gemma
                        )
                        render_results(attempt)
                    except Exception as e:
                        logger.exception("falha ao corrigir prova")
                        body.clear()
                        with body:
                            ui.label(f"Erro ao corrigir: {e}").style("color:#ffb3b3")

                ui.button("Enviar respostas", icon="send", on_click=on_submit).props(
                    "color=primary"
                )

        # ---------- Passo 3: resultado ----------
        def render_results(attempt: Any) -> None:
            quiz: Quiz = flow["quiz"]
            qmap: dict[int, Question] = {question.id: question for question in quiz.questions}
            body.clear()
            with body:
                with ui.row().classes("items-center gap-3"):
                    ui.label("Nota:").style("font-size:18px")
                    cor = (
                        "lime" if (attempt.score or 0) >= 7
                        else "amber" if (attempt.score or 0) >= 5 else "red"
                    )
                    ui.badge(f"{attempt.score:.1f} / 10", color=cor).style(
                        "font-size:18px; padding:8px 14px"
                    )
                ui.label("3. Gabarito comentado").style(
                    "font-size:15px; font-weight:600; padding-top:6px"
                )
                for i, ans in enumerate(attempt.answers, start=1):
                    question = qmap.get(ans.question_id)
                    if question is None:
                        continue
                    ok = ans.is_correct
                    border = (
                        "#1f4d1f" if ok else "#4d1f1f" if ok is False else "#3a3a1f"
                    )
                    with ui.card().classes("w-full").style(
                        f"background:#141414; border-left:4px solid {border}"
                    ):
                        ui.label(f"Q{i} · {question.topic}").style("color:#7fd; font-size:11px")
                        ui.label(question.prompt).style("font-weight:600")

                        # Resposta DO ALUNO (MC: texto da alternativa marcada).
                        if question.type == "mc" and question.options:
                            try:
                                sel = int(ans.response)
                                sua = (
                                    question.options[sel]
                                    if 0 <= sel < len(question.options)
                                    else "(inválida)"
                                )
                            except (ValueError, TypeError):
                                sua = "(não respondida)"
                        else:
                            sua = ans.response.strip() or "(não respondida)"
                        cor_sua = (
                            "#9f9" if ok else "#f99" if ok is False else "#cde"
                        )
                        ui.label(f"Sua resposta: {sua}").style(
                            f"color:{cor_sua}; font-size:13px"
                        )

                        if question.type == "mc" and question.options:
                            certa = (
                                question.options[question.correct_index]
                                if question.correct_index is not None
                                else "?"
                            )
                            ui.label(f"Resposta correta: {certa}").style(
                                "color:#9f9; font-size:12px"
                            )
                        pts = ans.awarded_points if ans.awarded_points is not None else 0
                        rotulo = " (nota sugerida)" if question.type == "open" else ""
                        ui.label(
                            f"Pontos: {pts:.2f}/{question.max_points:.0f}{rotulo} — "
                            f"{ans.feedback}"
                        ).style("color:#bbb; font-size:12px")

                async def on_coach() -> None:
                    body.clear()
                    with body:
                        ui.spinner(size="lg").classes("self-center")
                        ui.label("Analisando dificuldades…").classes(
                            "self-center"
                        ).style("color:#888")
                    try:
                        report = await difficulty_report(
                            flow["attempt_id"], gemma=state.gemma
                        )
                        render_coach(report)
                    except Exception as e:
                        logger.exception("falha no coach")
                        body.clear()
                        with body:
                            ui.label(f"Erro: {e}").style("color:#ffb3b3")

                with ui.row().classes("gap-2"):
                    ui.button(
                        "Ver dificuldades & plano", icon="insights", on_click=on_coach
                    ).props("color=primary")
                    ui.button("Nova prova", icon="refresh", on_click=render_config).props(
                        "flat color=white"
                    )

        # ---------- Passo 4: dificuldades + plano ----------
        def render_coach(report: Any) -> None:
            body.clear()
            with body:
                ui.label("4. Dificuldades & plano de estudos").style(
                    "font-size:15px; font-weight:600"
                )
                if report is None or report.positive:
                    ui.label(
                        "Parabéns! Você foi bem em todos os tópicos avaliados."
                    ).style("color:#9f9")
                for t in getattr(report, "weak_topics", []) or []:
                    ui.label(
                        f"• {t.topic} — aproveitamento {t.ratio:.0%}"
                    ).style("color:#fb9")
                for rec in getattr(report, "recommendations", []) or []:
                    ui.label(f"- {rec}").style("color:#ddd; font-size:13px")

                items = list(getattr(getattr(report, "plan", None), "items", []) or [])
                if items:
                    ui.label("Plano de estudos:").style(
                        "font-weight:600; padding-top:6px"
                    )
                    for it in items:
                        mat = f" · {it.material}" if it.material else ""
                        ui.label(
                            f"📚 {_fmt_when(it)}{it.topic}: {it.action} "
                            f"(~{it.minutes} min){mat}"
                        ).style("color:#cde; font-size:13px")

                    def on_add_agenda() -> None:
                        n_ev, n_task = 0, 0
                        with get_connection() as conn:
                            for it in items:
                                start = _parse_when(it)
                                if start is not None:
                                    create_event(
                                        conn,
                                        EventCreate(
                                            title=f"Estudo: {it.topic}",
                                            description=f"{it.action}".strip(),
                                            starts_at=start,
                                            ends_at=start + timedelta(minutes=it.minutes),
                                            kind="outro",
                                        ),
                                    )
                                    n_ev += 1
                                else:
                                    create_task(
                                        conn,
                                        TaskCreate(
                                            title=f"Estudar: {it.topic}",
                                            description=f"{it.action} (~{it.minutes} min)",
                                            priority=1,
                                        ),
                                    )
                                    n_task += 1
                        partes = []
                        if n_ev:
                            partes.append(f"{n_ev} sessão(ões) agendada(s)")
                        if n_task:
                            partes.append(f"{n_task} tarefa(s)")
                        ui.notify(
                            "Adicionado à agenda: " + " + ".join(partes), type="positive"
                        )

                    ui.button(
                        "Adicionar à agenda", icon="event", on_click=on_add_agenda
                    ).props("color=primary")
                ui.button("Nova prova", icon="refresh", on_click=render_config).props(
                    "flat color=white"
                )

        render_config()

    dialog.open()
