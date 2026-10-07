"""Dialog modal: auditoria de tool_call_logs — Fase 6."""

from __future__ import annotations

import json

from nicegui import ui

from src.core.db import get_connection


def _pretty_json(raw: str) -> str:
    """Indenta JSON para exibição; devolve o texto bruto se não for JSON válido."""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return raw


def open_audit_dialog() -> None:
    with ui.dialog().props("persistent maximized=false") as dialog, ui.card().classes(
        "w-full max-w-5xl"
    ).style("background:#0a0a0a; color:#f5f5f5"):
        with ui.row().classes("items-center justify-between w-full px-2"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("history").classes("text-cyan-400")
                ui.label("Auditoria de Tool Calls").style(
                    "font-size:20px; font-weight:600"
                )
            with ui.row().classes("items-center gap-2"):
                ui.button("Atualizar", icon="refresh", on_click=lambda: refresh()).props(
                    "flat dense color=primary"
                )
                ui.button(icon="close", on_click=dialog.close).props(
                    "flat round size=sm color=white"
                )

        ui.label(
            "Cada chamada de tool feita pelo agente é registrada aqui "
            "(D-015 / tabela tool_call_logs)."
        ).style("color:#aaa; font-size:13px; padding:0 8px")

        list_container = ui.column().classes("w-full gap-1 px-2").style(
            "max-height:60vh; overflow-y:auto"
        )

        def refresh() -> None:
            list_container.clear()
            with get_connection() as conn:
                rows = conn.execute(
                    """SELECT id, ts, tool_name, status, duration_ms,
                              input_json, output_json, error_msg
                         FROM tool_call_logs
                        ORDER BY id DESC
                        LIMIT 300"""
                ).fetchall()
            with list_container:
                ui.label(f"Últimas {len(rows)} chamadas").style(
                    "font-weight:600; padding-top:8px"
                )
                if not rows:
                    ui.label("(nenhuma chamada registrada ainda)").style(
                        "color:#666; font-style:italic; font-size:13px"
                    )
                    return
                for r in rows:
                    border = "#1b5e20" if r["status"] == "ok" else "#b71c1c"
                    with ui.expansion(
                        f"#{r['id']} · {r['ts']} · {r['tool_name']} · "
                        f"{r['status']} · {r['duration_ms']} ms",
                        icon="history",
                    ).classes("w-full").style(
                        f"border-left:3px solid {border}; padding-left:8px; "
                        f"background:#0d0d0d; border-radius:4px; margin:2px 0"
                    ):
                        with ui.column().classes("gap-1 text-xs px-2"):
                            ui.label("Entrada:").style("color:#aaa; font-weight:600")
                            ui.code(_pretty_json(r["input_json"]), language="json").classes(
                                "max-w-full"
                            )

                            ui.label("Saída:").style(
                                "color:#aaa; font-weight:600; margin-top:4px"
                            )
                            if r["output_json"]:
                                ui.code(
                                    _pretty_json(r["output_json"]), language="json"
                                ).classes("max-w-full")
                            else:
                                ui.label("(null)").style(
                                    "color:#666; font-style:italic"
                                )

                            if r["error_msg"]:
                                ui.label("error_msg:").style(
                                    "color:#ff8a80; font-weight:600; margin-top:4px"
                                )
                                ui.label(r["error_msg"]).style("color:#ff8a80")

        refresh()

    dialog.open()
