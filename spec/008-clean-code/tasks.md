# Spec 008 — Refatoração Clean Code — Tasks

> Ordenadas por dependência. `[P]` = paralelizável com as irmãs do mesmo bloco.
> Implementação só começa após auditoria + aprovação humana (`aprovo a spec 008`).
> Regra de ouro: rodar `uv run pytest` ao fim de cada task; nada de mudar asserts
> de testes existentes.

## T-008.1 — Ferramental (pré-requisito dos gates)

- `pyproject.toml`: `[project.optional-dependencies] dev` → `[dependency-groups] dev`.
- `uv lock` + `uv sync`; confirmar `uv run ruff --version` e `uv run pytest` (baseline).
- `README.md:323`, `STATUS.md:198,235`: `uv sync --extra dev` → `uv sync`.
- `decisions.md`: registrar **D-031** (dev deps em `[dependency-groups]`).

## T-008.2 — Bug do `output_json` (RF-008.1)

- Teste primeiro (em `tests/integration/test_agent_loop.py`, registry com tool
  fake que devolve dict circular): teste A (1ª tool → hoje `NameError`) e teste B
  (tool OK + tool circular → hoje reaproveita a saída anterior). Ambos devem falhar
  antes da correção.
- `src/llm/agent.py`: `_serialize_tool_output` → `(output_json, erro)`; em erro,
  `status="error"` e saída trocada pelo dict de erro em evento/log/sessão/observação.

## T-008.3 — Decomposição do agent loop (RF-008.2) — depende de T-008.2

- Constantes `DEFAULT_MAX_ITERATIONS`, `INVALID_JSON_CORRECTION`,
  `MISSING_KEYS_CORRECTION`, `MAX_ITERATIONS_REPLY`.
- Dataclass `ToolRun`; métodos `_build_initial_messages`, `_handle_reply`,
  `_handle_unknown_tool`, `_run_tool`, `_log_tool_call`,
  `_persist_session_message`, `_append_correction`.
- Comentários do porquê nos `except Exception` remanescentes.
- Manter os aliases `_parse_json_response`/`_loads_lenient`.
- Gate: `respond` ≤ 50 linhas (sem docstring); `test_agent_loop.py` verde sem alterações.

## T-008.4 — Ingestão (RF-008.3) [P com T-008.2/T-008.3]

- Teste primeiro: `tests/integration/test_ingest_document.py` (fixture em
  design.md §8): nova; `skipped`; re-ingestão OK; re-ingestão com falha de
  embedding / texto ilegível / falha no INSERT preserva o antigo (os três devem
  falhar antes da refatoração); `reason` parametrizado.
- `decisions.md`: nota de revisão em D-021 (nova ordem da re-ingestão).
- `src/rag/ingest.py`: `_error`, `_validate_input_file`, `_find_document_by_hash`,
  `_find_document_by_path`, `PreparedContent` + `_prepare_content`, `_persist`
  (DELETE do antigo dentro da transação).
- Gate: `ingest_document` ≤ 50 linhas (sem docstring); `test_ingest_quality.py` verde.

## T-008.5 — Exceções específicas (RF-008.4) [P]

- `src/ui/dialogs/audit_dialog.py`: `_pretty_json` + uso nos dois pontos.
- `src/llm/json_utils.py`: `CODE_FENCE`, `JSON_LANG_TAG`, `_try_loads`.
- `tests/unit/test_audit_pretty_json.py`.

## T-008.6 — Constantes (RF-008.5) [P]

- Aplicar a tabela de design.md §5 (embed, learning/models + coach, tasks/service,
  agenda/service, gemma_client, chunk, rag/types, ui/state, ui/app, coach "7 dias").
- `_end_of_day` + teste unitário.

## T-008.7 — Nomes locais (RF-008.6) — depois de T-008.3/T-008.4 (evita conflito)

- Aplicar a tabela de design.md §6.
- `tool_learning.py`: dedupe com `list(dict.fromkeys(resolved_ids))`.

## T-008.8 — Fechamento

- `uv run ruff check src tests` limpo; `uv run pytest` verde (registrar contagem).
- Atualizar `STATUS.md` com a Spec 008 concluída.
- Commit(s) referenciando `spec/008-clean-code`.

## Matriz critério → task/teste

| Critério | Task | Verificação |
|---|---|---|
| RF-008.1 | T-008.2 | testes A e B de saída não serializável |
| RF-008.2 | T-008.3 | `test_agent_loop.py` existente + contagem de linhas |
| RF-008.3 | T-008.4 | `test_ingest_document.py` (cenários + `reason` parametrizado) |
| RF-008.4 | T-008.5 | `test_audit_pretty_json.py`, `test_agent_json_parse.py` |
| RF-008.5 | T-008.6 | `_end_of_day` test + suíte |
| RF-008.6 | T-008.7 | ruff + suíte |
| RF-008.7 | T-008.1 | `uv sync` em venv nova instala ruff; ruff limpo |
