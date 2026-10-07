"""Testes do AgentLoop com FakeLLM scripted (sem bater no endpoint real).

Nota: as tools internas (listar_tarefas, etc.) usam get_connection() que aponta
para Settings.db_path. Nestes testes, monkeypatchamos JARVIS_DB_PATH para que
agente + tools + assercoes usem o mesmo DB temporario.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from src.core.config import get_settings
from src.core.db import apply_migrations, get_connection
from src.llm.agent import AgentLoop
from src.llm.types import Message
from src.tools import build_system_prompt, get_registry
from src.tools.registry import ToolDefinition, ToolRegistry


class ScriptedLLM:
    """Versao scriptada do GemmaClient para testes deterministicos."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    async def complete_chat(
        self, messages: list[Message], max_tokens: int | None = None
    ) -> str:
        self.calls.append(list(messages))
        if not self.responses:
            return '{"reply": "sem mais respostas no roteiro"}'
        return self.responses.pop(0)

    async def stream_chat(  # pragma: no cover
        self, messages: list[Message], max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        if False:
            yield ""


@pytest.fixture
def shared_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Patcha JARVIS_DB_PATH para um arquivo unico que agent+tools+test compartilham."""
    db_path = tmp_path / "agent-test.db"
    monkeypatch.setenv("JARVIS_DB_PATH", str(db_path))
    monkeypatch.setenv("JARVIS_LLM_API_KEY", "fake-token-for-agent-tests")
    get_settings.cache_clear()
    # Inicializa schema
    with get_connection() as conn:
        apply_migrations(conn)
    yield db_path
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_loop_direct_reply_no_tool(shared_db: Path) -> None:
    """LLM responde direto com reply, sem chamar tool."""
    _ = get_registry()
    llm = ScriptedLLM(['{"reply": "Ola! Como posso ajudar?"}'])
    loop = AgentLoop(gemma=llm, max_iterations=3)  # type: ignore[arg-type]

    events: list[dict[str, Any]] = []
    async for ev in loop.respond("ola"):
        events.append(ev)

    finals = [e for e in events if e["type"] == "final"]
    assert len(finals) == 1
    assert "Ola" in finals[0]["reply"]
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    assert tool_calls == []


@pytest.mark.asyncio
async def test_loop_executes_tool_and_logs(shared_db: Path) -> None:
    """LLM chama listar_tarefas, depois responde com reply. Verifica log no SQLite."""
    _ = get_registry()

    # Adiciona uma tarefa via tool (testa o pipeline completo de criacao)
    from src.domain.tasks.models import TaskCreate
    from src.domain.tasks.repo import create_task

    with get_connection() as conn:
        create_task(conn, TaskCreate(title="Estudar Python", priority=1))

    responses = [
        '{"tool": "listar_tarefas", "args": {"status": "pending"}}',
        '{"reply": "Voce tem 1 tarefa pendente: Estudar Python."}',
    ]
    llm = ScriptedLLM(responses)
    loop = AgentLoop(gemma=llm, max_iterations=4)  # type: ignore[arg-type]

    events: list[dict[str, Any]] = []
    async for ev in loop.respond("quais minhas tarefas?"):
        events.append(ev)

    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    finals = [e for e in events if e["type"] == "final"]

    assert len(tool_calls) == 1
    assert tool_calls[0]["tool"] == "listar_tarefas"
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == "ok"
    assert tool_results[0]["output"]["count"] == 1
    assert len(finals) == 1
    assert "Estudar Python" in finals[0]["reply"]

    # Tool foi loggada em tool_call_logs (D-015)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT tool_name, status FROM tool_call_logs"
        ).fetchall()
    assert any(r["tool_name"] == "listar_tarefas" and r["status"] == "ok" for r in rows)


@pytest.mark.asyncio
async def test_loop_handles_unknown_tool(shared_db: Path) -> None:
    _ = get_registry()
    responses = [
        '{"tool": "tool_inexistente", "args": {}}',
        '{"reply": "OK, sem essa tool consigo ajudar diretamente."}',
    ]
    llm = ScriptedLLM(responses)
    loop = AgentLoop(gemma=llm, max_iterations=4)  # type: ignore[arg-type]

    events: list[dict[str, Any]] = []
    async for ev in loop.respond("algo"):
        events.append(ev)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["status"] == "error"
    assert "não existe" in tool_results[0]["output"]["error"]


@pytest.mark.asyncio
async def test_loop_recovers_from_invalid_json(shared_db: Path) -> None:
    _ = get_registry()
    responses = [
        "isto nao e JSON nem em sonho",
        '{"reply": "Recuperei e respondi."}',
    ]
    llm = ScriptedLLM(responses)
    loop = AgentLoop(gemma=llm, max_iterations=4)  # type: ignore[arg-type]

    events: list[dict[str, Any]] = []
    async for ev in loop.respond("teste"):
        events.append(ev)

    finals = [e for e in events if e["type"] == "final"]
    assert len(finals) == 1
    assert "Recuperei" in finals[0]["reply"]


def test_system_prompt_contains_all_5_tools() -> None:
    reg = get_registry()
    prompt = build_system_prompt(reg)
    for name in [
        "consultar_agenda",
        "listar_tarefas",
        "adicionar_tarefa",
        "concluir_tarefa",
        "buscar_material_rag",
    ]:
        assert name in prompt, f"tool {name} faltando no system prompt"


@pytest.mark.asyncio
async def test_loop_persists_messages_when_session_id_given(shared_db: Path) -> None:
    """Com session_id, AgentLoop grava user/tool/assistant em chat_messages."""
    from src.core.db import get_connection
    from src.domain.chat.repo import (
        add_message,
        create_session,
        list_messages_of_session,
        next_position,
    )

    _ = get_registry()

    # Cria sessão e grava a 1ª user message (simulando o fluxo do chat_view)
    with get_connection() as conn:
        sid = create_session(conn, "Teste persistência")
        add_message(conn, sid, role="user", content="quais minhas tarefas?",
                    position=next_position(conn, sid))

    responses = [
        '{"tool": "listar_tarefas", "args": {"status": "pending"}}',
        '{"reply": "Você não tem tarefas pendentes."}',
    ]
    llm = ScriptedLLM(responses)
    loop = AgentLoop(gemma=llm, max_iterations=4)  # type: ignore[arg-type]

    events: list[dict[str, Any]] = []
    async for ev in loop.respond("quais minhas tarefas?", session_id=sid):
        events.append(ev)

    # Lê o que ficou persistido
    with get_connection() as conn:
        msgs = list_messages_of_session(conn, sid)

    roles = [m.role for m in msgs]
    # Esperado: user (pré-gravada), tool, assistant
    assert roles == ["user", "tool", "assistant"]
    assert msgs[0].content == "quais minhas tarefas?"
    assert "listar_tarefas" in (msgs[1].metadata or {}).get("tool", "")
    assert "Você não tem" in msgs[2].content


@pytest.mark.asyncio
async def test_loop_does_not_persist_without_session_id(shared_db: Path) -> None:
    """Sem session_id, AgentLoop não grava nada (backward-compat)."""
    from src.core.db import get_connection
    from src.domain.chat.repo import list_recent_sessions

    _ = get_registry()
    llm = ScriptedLLM(['{"reply": "ok"}'])
    loop = AgentLoop(gemma=llm, max_iterations=2)  # type: ignore[arg-type]

    async for _ in loop.respond("oi"):
        pass

    with get_connection() as conn:
        sessions = list_recent_sessions(conn, limit=10)
    assert sessions == []


# ============================================================
# Spec 008 / RF-008.1 — saída de tool não serializável
# ============================================================


def _registry_with_fake_tools() -> ToolRegistry:
    """Registry com uma tool OK e uma cuja saída tem referência circular."""
    async def _ok_tool(args: dict[str, Any]) -> dict[str, Any]:
        return {"valor": "saida-da-tool-ok"}

    async def _circular_tool(args: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {"status": "ok"}
        output["self"] = output  # json.dumps levanta ValueError (circular)
        return output

    registry = ToolRegistry()
    for name, handler in (("tool_ok", _ok_tool), ("tool_circular", _circular_tool)):
        registry.register(
            ToolDefinition(
                name=name, description=name, parameters_schema={}, handler=handler
            )
        )
    return registry


@pytest.mark.asyncio
async def test_loop_unserializable_output_first_tool(shared_db: Path) -> None:
    llm = ScriptedLLM(['{"tool": "tool_circular", "args": {}}', '{"reply": "fim"}'])
    loop = AgentLoop(gemma=llm, registry=_registry_with_fake_tools(), max_iterations=4)  # type: ignore[arg-type]

    events = [ev async for ev in loop.respond("teste")]

    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["status"] == "error"
    assert "não serializável" in results[0]["output"]["error"]
    assert events[-1] == {"type": "final", "reply": "fim"}
    with get_connection() as conn:
        rows = conn.execute("SELECT tool_name, status FROM tool_call_logs").fetchall()
    assert [(r["tool_name"], r["status"]) for r in rows] == [("tool_circular", "error")]


@pytest.mark.asyncio
async def test_loop_unserializable_output_does_not_reuse_previous(shared_db: Path) -> None:
    llm = ScriptedLLM([
        '{"tool": "tool_ok", "args": {}}',
        '{"tool": "tool_circular", "args": {}}',
        '{"reply": "fim"}',
    ])
    loop = AgentLoop(gemma=llm, registry=_registry_with_fake_tools(), max_iterations=5)  # type: ignore[arg-type]

    _ = [ev async for ev in loop.respond("teste")]

    # A 3ª chamada à LLM recebe como última mensagem a observação da tool_circular.
    last_observation = llm.calls[2][-1]["content"]
    assert "tool_circular" in last_observation
    assert "não serializável" in last_observation
    assert "saida-da-tool-ok" not in last_observation
