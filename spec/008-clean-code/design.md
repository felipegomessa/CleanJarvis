# Spec 008 — Refatoração Clean Code — Design

> Camadas tocadas: `llm/`, `rag/`, `domain/`, `learning/`, `tools/`, `ui/`.
> Nenhuma importação nova entre camadas — toda constante nova mora no módulo dono
> do conceito (§4.1 da constituição preservado).

## 1. RF-008.1 — Serialização da saída da tool

```python
# src/llm/agent.py
def _serialize_tool_output(output: Any) -> tuple[str, str | None]:
    """Serializa a saída da tool. Devolve (output_json, erro); nunca levanta."""
    try:
        return json.dumps(output, ensure_ascii=False, default=str), None
    except (TypeError, ValueError) as e:  # ValueError = referência circular
        return "", f"saída da tool não serializável: {e}"
```

`_run_tool` chama o helper logo após executar a tool. Se `erro` não é `None`:
`logger.warning` (com o nome da tool — P5), `status="error"`, `error_msg=erro`,
`output={"status": "error", "error": erro}` e `output_json` = esse dict
serializado. É **esse** `ToolRun` (output e output_json coerentes) que alimenta o
evento `tool_result`, `log_tool_call`, `_persist_session_message` e a observação.
O bloco de log passa a conter só `log_tool_call`. Como `output_json` é campo do
`ToolRun` da iteração corrente, a saída de uma tool anterior nunca é reaproveitada.

## 2. RF-008.2 — Estrutura de `AgentLoop.respond`

```python
DEFAULT_MAX_ITERATIONS = 6  # limite de rodadas LLM→tool antes de desistir

INVALID_JSON_CORRECTION = "Sua última resposta não era um JSON válido. ..."
MISSING_KEYS_CORRECTION = "Sua resposta tinha JSON mas sem 'tool' nem 'reply'. ..."
MAX_ITERATIONS_REPLY = "Desculpe, não consegui produzir uma resposta final ..."
```

`respond` vira o laço de orquestração; cada ramo delega:

| Método privado | Responsabilidade | Retorno |
|---|---|---|
| `_build_initial_messages(user_message, history)` | system + history + user | `list[Message]` |
| `_handle_reply(parsed, session_id)` | persiste a resposta final | `dict` evento `final` |
| `_handle_unknown_tool(tool_name, raw, msgs)` | observação de erro + correção | `dict` evento `tool_result` |
| `_run_tool(tool_def, tool_name, args)` | executa, mede duração, captura exceção | `ToolRun` (dataclass: `output`, `output_json`, `status`, `error_msg`, `duration_ms`) |
| `_log_tool_call(tool_name, args, run)` | grava `tool_call_logs` (D-015) | `None` |
| `_persist_session_message(session_id, role, content, metadata=None, touch=False)` | **único** ponto de gravação em `chat_messages` (D-024); `touch=True` atualiza o timestamp da sessão | `None` |
| `_append_correction(msgs, raw, text)` | anexa `assistant: raw` + `user: text` | `None` |

Como `respond` é um *async generator*, os helpers **retornam** eventos em vez de
dar `yield`; `respond` faz o `yield` deles. A ordem dos eventos é preservada: por
iteração, `thinking` seguido de **um** entre `tool_call`+`tool_result`, `error` ou
`final`. **`error` não é terminal**: o loop anexa `MISSING_KEYS_CORRECTION` e
continua (`agent.py:224-237`); só `final` encerra. Os aliases
`_parse_json_response`/`_loads_lenient` (linhas 39-41) permanecem.

Os `except Exception` em `_log_tool_call` e `_persist_session_message` permanecem
largos **de propósito**: falha de auditoria/persistência não pode derrubar a
conversa (modo degradado). Cada um ganha comentário com esse porquê e mantém o
`logger.warning`. `_run_tool` mantém `except Exception` + `logger.exception`
(política §8: "Tool execution erro → capturar, registrar, devolver ao loop").

## 3. RF-008.3 — Estrutura de `ingest_document`

```python
def ingest_document(path: Path) -> IngestResult:
    source_path = str(path)
    if (error := _validate_input_file(path)) is not None:
        return error
    try:
        content_hash = _compute_sha256(path)
    except OSError as e:
        return _error(source_path, "read_failed", str(e))

    with get_connection() as conn:
        if (doc_id := _find_document_by_hash(conn, content_hash)) is not None:
            return IngestResult(status="skipped", ..., reason="hash_match", document_id=doc_id)
        previous_id = _find_document_by_path(conn, source_path)   # NÃO apaga aqui
        prepared = _prepare_content(path)                          # extrai + valida + chunk + embed
        if isinstance(prepared, IngestResult):
            return prepared                                        # antigo intacto
        return _persist(conn, path, content_hash, prepared, previous_id)
```

- `_error(source_path, reason, error) -> IngestResult` elimina as 9 construções
  repetidas de `IngestResult(status="error", ...)`.
- `_prepare_content` devolve `PreparedContent` (dataclass: `text`, `chunks`,
  `embeddings`) ou um `IngestResult` de erro; reasons inalterados
  (`extract_failed`, `no_text`, `unreadable_text`, `no_chunks`, `embed_failed`).
- `_persist` abre `BEGIN`; **se `previous_id` não é `None`, chama
  `_delete_document(conn, previous_id)` dentro da transação**; insere documento,
  chunks e vetores; `COMMIT`. Qualquer exceção → `ROLLBACK` + `logger.exception` +
  `_error(..., "db_insert_failed", ...)`. Log `info` de re-ingestão movido para cá.
- Ordem alterada (mudança de comportamento declarada): extração/embedding agora
  rodam **antes** de qualquer remoção. `documents.source_path` é `UNIQUE`
  (`001_initial.sql:10`), por isso o DELETE do antigo **precisa** vir antes do
  INSERT do novo, na mesma transação. Nota de revisão em D-021.

## 4. RF-008.4 — Exceções específicas

```python
# src/ui/dialogs/audit_dialog.py
def _pretty_json(raw: str) -> str:
    """Indenta JSON para exibição; devolve o texto bruto se não for JSON válido."""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return raw
```

```python
# src/llm/json_utils.py
CODE_FENCE = "```"
JSON_LANG_TAG = "json"

def _try_loads(text: str) -> dict[str, Any] | None:
    """loads_lenient que devolve None em vez de levantar — usado na 1ª tentativa."""
```

`parse_json_response` passa a usar `if (parsed := _try_loads(text)) is not None:
return parsed`, e `len(CODE_FENCE)`/`len(JSON_LANG_TAG)` nos fatiamentos.

## 5. RF-008.5 — Constantes

| Módulo | Constante | Comentário (porquê) |
|---|---|---|
| `rag/embed.py` | `EMBEDDING_DIM = 384` | dimensão do e5-small; casa com `FLOAT[384]` da migration 002 |
| `domain/learning/models.py` | `DEFAULT_STUDY_MINUTES = 30`, `MIN_MC_OPTIONS = 2`, `MAX_MC_OPTIONS = 6` | `coach.py` e `generator.py` importam **direto de `src.domain.learning.models`** (learning→domain é permitido; `__init__` não muda) |
| `domain/tasks/service.py` | `_end_of_day(dt) -> datetime` | substitui o `replace(23, 59, 59)` duplicado |
| `domain/agenda/service.py` | `NEXT_EVENT_WINDOW_DAYS = 30` | |
| `llm/agent.py` | `DEFAULT_MAX_ITERATIONS = 6` | |
| `llm/gemma_client.py` | `MAX_LLM_ATTEMPTS = 3`, `RETRY_WAIT_MIN_S = 1`, `RETRY_WAIT_MAX_S = 8` | política §8 / D-014; comentário registra que são 3 **tentativas** (2 retries) |
| `rag/chunk.py` | `DEFAULT_CHUNK_SIZE = 800`, `DEFAULT_CHUNK_OVERLAP = 150` | defaults da função pura (D-006); a ingestão continua passando `settings.chunk_*` |
| `rag/types.py` | `threshold_used: float \| None = None` | `retrieve.search` sempre preenche; `None` = "não aplicável" em vez de repetir o 0.6 de `Settings` |
| `ui/state.py` | `PROMPT_HISTORY_LIMIT = 50` | |
| `ui/app.py` | `STARTUP_HEALTHCHECK_TIMEOUT_S = 15.0` | |
| `learning/coach.py` | — | mensagem usa `f"... próximos {PLAN_HORIZON_DAYS} dias"` |

`chunk.py` não importa `core.config` para manter `chunk_text` como função pura
testável; o comentário da constante aponta para `Settings.chunk_size` (D-006).

## 6. RF-008.6 — Renomeações locais

| Arquivo | Antes | Depois |
|---|---|---|
| `core/db.py:91` | `v`, `f` | `version`, `migration_file` |
| `ui/app.py:35` | `v` | `schema_version` |
| `ui/state.py:49` | `p` | `normalized_prompt` |
| `tools/tool_learning.py:53` | `s` | `settings` |
| `tools/tool_learning.py:150-165` | `aid` (150, 160), `d` (154, 164) | `attempt_id`, `report_dict` |
| `tools/tool_learning.py:31-45` | `d`, `did`, `alvo`, `out` | `reference`, `document_id`, `target_title`, `resolved_ids` |
| `learning/generator.py:26` | `n` | `ref_counter` |
| `learning/generator.py:94` | `s` | `normalized` |
| `learning/generator.py:145,184,209` | `mc`, `op` | `mc_questions`, `open_questions` |
| `learning/coach.py:60,147,149` | `s`, `res` | `topic_score`, `retrieval` |
| `rag/ingest.py` | `spath`, `cur2`, `emb`, `c` | `source_path`, `chunk_cursor`, `embedding`, `chunk` |
| `ui/components/chat_view.py:197-205` | `event`, `t` | `agent_event`, `event_type` |
| `ui/dialogs/exam_dialog.py:159-169,209` | `el`, `val`, `q` | `answer_input`, `answer_value`, `question` |

Compreensões de uma linha com variável curta e escopo óbvio (`[_row_to_event(r)
for r in rows]`) **não** mudam. Tuplas `y, m` de ano/mês em calendários também
ficam (idioma consolidado e escopo de 2–3 linhas).

## 7. RF-008.7 — Dev deps (D-031)

```toml
[dependency-groups]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", "pytest-cov>=5.0.0",
       "ruff>=0.5.0", "mypy>=1.10.0"]
```

Remove `[project.optional-dependencies]`. `uv lock` regenera o lockfile.
`README.md:323` e `STATUS.md:198,235` (instruções de uso) passam a `uv sync`.
Registros históricos em `STATUS.md` (linhas 51, 83) não são reescritos.

## 8. Estratégia de testes

| Teste | Tipo | Cobre |
|---|---|---|
| `tests/integration/test_agent_loop.py` (existente, sem mudança) | integration | contrato de eventos (RF-008.2) |
| `test_loop_unserializable_output_first_tool` e `test_loop_unserializable_output_does_not_reuse_previous` (novos, mesmo arquivo) | integration | RF-008.1 (testes A e B) |
| `tests/integration/test_ingest_document.py` (novo) | integration | RF-008.3 (cenários + `reason` parametrizado) |
| `tests/unit/test_agent_json_parse.py` (existente) | unit | RF-008.4 (`json_utils`) |
| `tests/unit/test_audit_pretty_json.py` (novo) | unit | RF-008.4 (`_pretty_json` válido/ inválido/`None`) |
| `tests/unit/test_tasks_end_of_day.py` (novo) ou extensão existente | unit | RF-008.5 (`_end_of_day`) |
| `uv run ruff check src tests` + suíte completa | gate | RF-008.6/008.7 |

Fixture de `test_ingest_document.py`:
- `JARVIS_DB_PATH` temporário + `JARVIS_LLM_API_KEY="fake"` (campo obrigatório,
  `config.py:28`) + `get_settings.cache_clear()` antes e depois, como em
  `test_get_document_chunks.py`.
- Fake de embedding em **`src.rag.ingest.embed_passages`** (o módulo importa o nome
  direto, `ingest.py:16`), devolvendo
  `np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)`. `float32` é
  obrigatório: `chunk_vecs` é `vec0 FLOAT[384]` (1536 bytes por vetor).
- Falha de embedding: fake que levanta `RuntimeError`.
- Falha no INSERT (exercita o ROLLBACK real, depois do DELETE): fake devolvendo
  `dtype=np.float64` (3072 bytes), que o `vec0` rejeita dentro da transação.
- Texto ilegível: `.txt` com lixo `(cid:N)` (mesmo padrão de `test_ingest_quality.py`).
- `extract_failed`: arquivo `.pdf` com bytes inválidos (o `pdfplumber` levanta na abertura).

A suíte live (`live_llm`) não é necessária para esta spec.
