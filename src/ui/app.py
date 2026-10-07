"""Entry point da UI NiceGUI — ChatGPT-style (Fase 4)."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from nicegui import app as nicegui_app
from nicegui import ui

from src.core.config import get_settings
from src.core.db import apply_migrations, get_connection, smoke_check_vec
from src.core.health import get_health, set_health
from src.core.logging import configure_logging
from src.llm import AgentLoop, GemmaClient
from src.llm.client import set_default_client
from src.ui.components.chat_view import ChatView
from src.ui.components.sidebar import render_sidebar
from src.ui.dialogs.audit_dialog import open_audit_dialog
from src.ui.dialogs.calendar_dialog import open_calendar_dialog
from src.ui.dialogs.exam_dialog import open_exam_dialog
from src.ui.dialogs.materials_dialog import open_materials_dialog
from src.ui.dialogs.tasks_list_dialog import open_tasks_list_dialog
from src.ui.state import set_clients
from src.ui.theme import apply_theme

# O endpoint LIA pode demorar a acordar; acima disso a UI sobe em modo OFFLINE (D-017).
STARTUP_HEALTHCHECK_TIMEOUT_S = 15.0


async def _bootstrap() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_dir)
    logger.info("JARVIS Acadêmico — bootstrap UI iniciado")

    with get_connection() as conn:
        smoke_check_vec(conn)
        schema_version = apply_migrations(conn)
        logger.info(f"DB schema v{schema_version}")

    gemma = GemmaClient(settings)
    set_default_client(gemma)  # disponibiliza o client p/ camadas fora da UI (D-030)
    ok = await gemma.healthcheck(timeout_s=STARTUP_HEALTHCHECK_TIMEOUT_S)
    set_health("ONLINE" if ok else "OFFLINE", error=None if ok else "healthcheck=False")
    if ok:
        logger.info("LLM ONLINE")
    else:
        logger.warning("LLM OFFLINE — chat e RAG desabilitados")

    agent = AgentLoop(gemma=gemma, max_iterations=6)
    set_clients(gemma=gemma, agent=agent, online=ok)


@ui.page("/")
def index_page() -> None:
    apply_theme()

    health = get_health()
    is_online = health.status == "ONLINE"

    chat_view = ChatView()

    # Sidebar (left_drawer fixo, com modo mini = 60px)
    drawer = ui.left_drawer(value=True, fixed=True, bordered=False).props(
        "width=260 mini-width=60 mini-to-overlay=false"
    )
    with drawer:
        render_sidebar(
            drawer=drawer,
            on_new_chat=chat_view.reset,
            on_load_session=chat_view.load_session,
        )

    # Banner OFFLINE (se aplicável) + área central
    with ui.column().classes("w-full h-screen items-stretch"):
        if not is_online:
            with ui.row().classes(
                "w-full items-center justify-center gap-2"
            ).style("background-color:#3a0e0e; padding:8px; border-bottom:1px solid #5a1a1a"):
                ui.icon("warning").classes("text-red-300")
                ui.label(
                    "LLM indisponível — Chat e busca em materiais estão "
                    "desabilitados. Verifique JARVIS_LLM_API_KEY em .env."
                ).style("color:#ffb3b3; font-size:13px")

        # Chat: ocupa toda a largura, mas conteúdo limitado a 800px (mesma idéia ChatGPT)
        chat_view.render(
            dialog_openers={
                "Enviar material": ("upload_file", open_materials_dialog),
                "Estudar / Prova": ("school", open_exam_dialog),
                "Calendário (eventos + tarefas)": ("event", open_calendar_dialog),
                "Lista de tarefas": ("checklist", open_tasks_list_dialog),
                "Pesquisar auditoria": ("history", open_audit_dialog),
            }
        )


nicegui_app.on_startup(_bootstrap)
nicegui_app.add_static_files("/img", str(Path("img").resolve()))


def run() -> None:
    settings = get_settings()
    ui.run(
        title="JARVIS Acadêmico",
        host=settings.ui_host,
        port=settings.ui_port,
        dark=settings.ui_dark,
        reload=False,
        show=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
