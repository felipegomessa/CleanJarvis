"""Agent loop com tool calling prompt-based JSON — Spec 005 / D-007.

Fluxo:
1. system prompt (gerado pelo registry) + history + user message
2. LLM responde com JSON: {"tool": ..., "args": ...} OU {"reply": "..."}
3. Se tool: executa, loga em tool_call_logs (D-015), injeta observação, repete
4. Se reply: stream o texto ao chamador e termina
5. Limite de iterações para evitar loops infinitos

Eventos emitidos pelo gerador:
- {"type": "thinking", "iteration": N}
- {"type": "tool_call", "tool": "...", "args": {...}}
- {"type": "tool_result", "tool": "...", "output": {...}, "duration_ms": int, "status": "ok"|"error"}
- {"type": "reply_token", "token": "..."}    # apenas se stream_reply=True
- {"type": "final", "reply": "..."}
- {"type": "error", "message": "..."}       # não-terminal: o loop pede correção e segue
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.core.db import get_connection, log_tool_call
from src.domain.chat.models import MessageRole
from src.domain.chat.repo import (
    add_message,
    next_position,
    update_session_timestamp,
)
from src.llm.gemma_client import GemmaClient
from src.llm.json_utils import loads_lenient, parse_json_response
from src.llm.types import Message
from src.tools.registry import ToolDefinition, ToolRegistry, build_system_prompt, get_registry

# Mantidos como nomes privados históricos (testes e código interno os importam daqui).
_parse_json_response = parse_json_response
_loads_lenient = loads_lenient

# Rodadas LLM→tool permitidas por mensagem do usuário antes de desistir.
DEFAULT_MAX_ITERATIONS = 6

INVALID_JSON_CORRECTION = (
    "Sua última resposta não era um JSON válido. "
    "Responda APENAS com um JSON único no formato "
    '{"tool": ..., "args": ...} ou {"reply": "..."}. '
    "Não inclua texto antes ou depois do JSON."
)
MISSING_KEYS_CORRECTION = (
    "Sua resposta tinha JSON mas sem 'tool' nem 'reply'. "
    "Responda novamente no formato correto."
)
MAX_ITERATIONS_REPLY = (
    "Desculpe, não consegui produzir uma resposta final após várias "
    "tentativas. Tente reformular sua pergunta de forma mais direta."
)


@dataclass
class ToolRun:
    """Resultado de uma execução de tool, já serializado para log/observação."""

    output: Any
    output_json: str
    status: str
    error_msg: str | None
    duration_ms: int


def _serialize_tool_output(output: Any) -> tuple[str, str | None]:
    """Serializa a saída da tool. Devolve (output_json, erro); nunca levanta."""
    try:
        return json.dumps(output, ensure_ascii=False, default=str), None
    except (TypeError, ValueError) as e:  # ValueError = referência circular
        return "", f"saída da tool não serializável: {e}"


def _append_correction(msgs: list[Message], raw: str, text: str) -> None:
    """Devolve à LLM a própria resposta seguida de uma instrução do 'usuário'."""
    msgs.append({"role": "assistant", "content": raw})
    msgs.append({"role": "user", "content": text})


class AgentLoop:
    """Orquestra interação entre LLM e tools — Spec 005."""

    def __init__(
        self,
        gemma: GemmaClient,
        registry: ToolRegistry | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
    ) -> None:
        self._gemma = gemma
        self._registry = registry or get_registry()
        self._max_iterations = max_iterations

    async def respond(
        self,
        user_message: str,
        history: list[Message] | None = None,
        session_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Async generator que emite eventos do agent loop. Ver docstring do módulo.

        Se `session_id` for fornecido, grava cada mensagem (user, assistant final,
        tool events) em `chat_messages` para restauração posterior via sidebar.
        Se None, modo "efêmero" (não persiste — usado em testes e em fluxos rápidos).
        """
        msgs = self._build_initial_messages(user_message, history)

        for iteration in range(1, self._max_iterations + 1):
            yield {"type": "thinking", "iteration": iteration}

            raw = await self._gemma.complete_chat(msgs)
            logger.debug(f"[agent iter={iteration}] LLM raw: {raw[:200]}...")

            try:
                parsed = _parse_json_response(raw)
            except ValueError as e:
                logger.warning(f"JSON inválido (iter {iteration}): {e}")
                _append_correction(msgs, raw, INVALID_JSON_CORRECTION)
                continue

            if "reply" in parsed:
                yield self._handle_reply(parsed, session_id)
                return

            if "tool" in parsed:
                tool_name = str(parsed["tool"])
                args = parsed.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                yield {"type": "tool_call", "tool": tool_name, "args": args}
                yield await self._handle_tool_call(tool_name, args, raw, msgs, session_id)
                continue

            yield {"type": "error", "message": f"JSON inesperado da LLM: {parsed}"}
            _append_correction(msgs, raw, MISSING_KEYS_CORRECTION)

        yield {"type": "final", "reply": MAX_ITERATIONS_REPLY}

    def _build_initial_messages(
        self, user_message: str, history: list[Message] | None
    ) -> list[Message]:
        msgs: list[Message] = [
            {"role": "system", "content": build_system_prompt(self._registry)}
        ]
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": user_message})
        return msgs

    def _handle_reply(self, parsed: dict[str, Any], session_id: int | None) -> dict[str, Any]:
        final = str(parsed["reply"])
        self._persist_session_message(session_id, role="assistant", content=final, touch=True)
        return {"type": "final", "reply": final}

    async def _handle_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        raw: str,
        msgs: list[Message],
        session_id: int | None,
    ) -> dict[str, Any]:
        """Executa a tool pedida e injeta a observação em `msgs`. Retorna o tool_result."""
        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            return self._handle_unknown_tool(tool_name, raw, msgs)

        run = await self._run_tool(tool_def, args)
        self._log_tool_call(tool_name, args, run)
        self._persist_session_message(
            session_id,
            role="tool",
            content=run.output_json,
            metadata={
                "tool": tool_name,
                "args": args,
                "status": run.status,
                "duration_ms": run.duration_ms,
                "error_msg": run.error_msg,
            },
        )
        _append_correction(msgs, raw, f"Observação da tool '{tool_name}': {run.output_json}")
        return {
            "type": "tool_result",
            "tool": tool_name,
            "status": run.status,
            "output": run.output,
            "duration_ms": run.duration_ms,
        }

    def _handle_unknown_tool(
        self, tool_name: str, raw: str, msgs: list[Message]
    ) -> dict[str, Any]:
        observation = {
            "status": "error",
            "error": f"tool '{tool_name}' não existe",
            "tools_disponiveis": self._registry.names(),
        }
        _append_correction(
            msgs,
            raw,
            f"Observação: ERRO - {observation['error']}. "
            f"Tools disponíveis: {observation['tools_disponiveis']}. "
            "Tente novamente com uma tool válida ou responda com {\"reply\": \"...\"}.",
        )
        return {
            "type": "tool_result",
            "tool": tool_name,
            "status": "error",
            "output": observation,
            "duration_ms": 0,
        }

    async def _run_tool(self, tool_def: ToolDefinition, args: dict[str, Any]) -> ToolRun:
        started = time.perf_counter()
        output: Any
        status = "ok"
        error_msg: str | None = None
        try:
            output = await tool_def.handler(args)
        except Exception as e:
            # Política §8: erro de tool volta para a LLM como observação, não derruba o loop.
            status = "error"
            error_msg = f"{type(e).__name__}: {e}"
            output = {"status": "error", "error": error_msg}
            logger.exception(f"tool {tool_def.name} levantou exceção")
        duration_ms = int((time.perf_counter() - started) * 1000)

        output_json, serialize_error = _serialize_tool_output(output)
        if serialize_error is not None:
            logger.warning(f"tool {tool_def.name}: {serialize_error}")
            status = "error"
            error_msg = serialize_error
            output = {"status": "error", "error": serialize_error}
            output_json, _ = _serialize_tool_output(output)
        return ToolRun(output, output_json, status, error_msg, duration_ms)

    def _log_tool_call(self, tool_name: str, args: dict[str, Any], run: ToolRun) -> None:
        """Grava a chamada em tool_call_logs (D-015)."""
        input_json, _ = _serialize_tool_output(args)
        try:
            with get_connection() as conn:
                log_tool_call(
                    conn=conn,
                    tool_name=tool_name,
                    input_json=input_json,
                    output_json=run.output_json,
                    status=run.status,
                    error_msg=run.error_msg,
                    duration_ms=run.duration_ms,
                )
        except Exception as e:
            # Largo de propósito: falha de auditoria não pode derrubar a conversa
            # (modo degradado); o erro fica no log de aplicação.
            logger.warning(f"falha ao logar tool call em SQLite: {e}")

    def _persist_session_message(
        self,
        session_id: int | None,
        role: MessageRole,
        content: str,
        metadata: dict[str, Any] | None = None,
        touch: bool = False,
    ) -> None:
        """Grava em chat_messages (D-024); `touch` atualiza o timestamp da sessão."""
        if session_id is None:
            return
        try:
            with get_connection() as conn:
                add_message(
                    conn,
                    session_id,
                    role=role,
                    content=content,
                    metadata=metadata,
                    position=next_position(conn, session_id),
                )
                if touch:
                    update_session_timestamp(conn, session_id)
        except Exception as e:
            # Largo de propósito: sem persistência a sessão não é restaurável depois,
            # mas a resposta ao usuário ainda deve sair (modo degradado).
            logger.warning(f"falha ao persistir mensagem ({role}) na sessão {session_id}: {e}")
