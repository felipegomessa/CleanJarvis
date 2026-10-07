# Spec 008 — Refatoração Clean Code — Requirements

> Aplica as práticas do capítulo 2 ("Código Limpo") de *Engenharia de Software
> Moderna* (Marco Tulio Valente) ao código de `src/`: funções grandes/pouco coesas,
> tratamento inadequado de exceções, números mágicos, nomes genéricos/abreviados e
> padronização de estilo verificada por ferramenta.

## Contexto

Uma varredura de `src/` (7.9k linhas) encontrou violações em todas as categorias do
capítulo. Entre elas, um **bug real** escondido por `except Exception` largo em
`src/llm/agent.py` e uma **perda de dados** possível na re-ingestão de documentos
(`src/rag/ingest.py`).

Decisões de entrevista SDD (2026-10-06):

| Pergunta | Decisão |
|---|---|
| Escopo | **Médio**: bug + quebrar `Agent.respond` e `ingest_document` + exceções específicas + constantes + nomes locais + ruff no `uv sync`. Sem renomear conceitos/arquivos. |
| Re-ingestão | Mover a remoção do documento antigo para **dentro da transação** de inserção do novo. |
| Dev deps | Migrar o extra `dev` para `[dependency-groups]` (PEP 735) — `uv sync` instala por padrão. |
| Constantes | `UPPER_SNAKE` **no módulo dono do conceito**; defaults já existentes em `Settings` não são duplicados como literais. Sem novas env vars. |
| `date_picker.parse` | **Fora do escopo** desta spec. |

ADRs relevantes: D-007 (agent loop), D-010/D-015 (tool call logs), D-011
(uv/reprodutibilidade), D-014 (retries), D-021 (ingestão idempotente), D-024
(persistência de sessão), D-028 (nome histórico `GemmaClient` — mantido).
ADR novo proposto: **D-031** (dev deps em `[dependency-groups]`).

## Princípio de compatibilidade

Esta spec é uma **refatoração**: nenhuma assinatura pública, contrato de eventos,
schema de banco ou texto de UI muda, **exceto** onde um RF abaixo declara a mudança
de comportamento explicitamente (RF-008.1 e RF-008.3). Toda a suíte existente deve
continuar verde sem alteração de asserts.

## Requisitos funcionais

### RF-008.1 — Bug: `output_json` sem valor no agent loop

Hoje `output_json` só é atribuído dentro do `try` de log em SQLite
([agent.py:172-186](../../src/llm/agent.py#L172-L186)); se `json.dumps` falhar, o
`except Exception` só registra warning e o código segue até usar a variável
(linhas 204 e 219). Na **1ª** tool do turno isso dá `NameError`; nas seguintes é
pior: o `output_json` da tool **anterior** é reaproveitado em silêncio, enviado à
LLM como observação e persistido na sessão.

**Mudança de comportamento declarada**: saída não serializável passa a ser tratada
como **erro da tool** (antes: `status="ok"` com saída inconsistente).

**Critério de aceitação**:
- ✓ A serialização da saída da tool acontece **uma vez, fora** do bloco de log, logo
  após a execução (design.md §1).
- ✓ Se a saída não for serializável (`TypeError`/`ValueError`, ex.: referência
  circular): log `warning`; `status="error"`; `error_msg="saída da tool não
  serializável: ..."`; e **o mesmo dict de erro** `{"status": "error", "error":
  error_msg}` substitui a saída em todos os consumidores — evento `tool_result`
  (o chip da UI, `tool_call_card.py:53-55`, não recebe mais o objeto circular),
  linha de `tool_call_logs` (D-015 coerente), mensagem persistida e observação
  enviada à LLM. O loop continua.
- ✓ Teste A: tool com saída circular como 1ª tool → loop termina com `final`, sem
  `NameError`; `tool_call_logs` tem `status='error'`; o evento `tool_result` tem
  `status == "error"`.
- ✓ Teste B: tool OK seguida de tool com saída circular no mesmo turno → a
  observação da 2ª tool enviada à LLM é o erro de serialização, **não** a saída
  da 1ª.

### RF-008.2 — Decomposição de `AgentLoop.respond`

`respond` (190 linhas, aninhamento 5) concentra parse, correção de JSON, tool
inexistente, execução, log, persistência e observação.

**Critério de aceitação**:
- ✓ `respond` fica com ≤ 50 linhas e delega a métodos privados com uma
  responsabilidade cada (ver design.md §2).
- ✓ A gravação de mensagem na sessão (hoje duplicada nas linhas 105–118 e
  196–215) existe em **um** helper `_persist_session_message`.
- ✓ Os três textos corretivos enviados à LLM viram constantes de módulo nomeadas.
- ✓ **Contrato de eventos inalterado** (tipos, chaves e ordem), salvo RF-008.1.
  Os 7 testes de `tests/integration/test_agent_loop.py` e
  `tests/unit/test_agent_json_parse.py` passam sem alteração.
- ✓ Os aliases privados `_parse_json_response`/`_loads_lenient`
  ([agent.py:39-41](../../src/llm/agent.py#L39-L41)) são **mantidos** —
  `test_agent_json_parse.py:11` os importa de `agent`.
- ✓ Contagem de linhas: "≤ 50 linhas" = do `def` ao fim do corpo, **excluindo
  docstring** (medido via AST `end_lineno - lineno + 1` menos as linhas da docstring).

### RF-008.3 — Decomposição de `ingest_document` + re-ingestão transacional

`ingest_document` (167 linhas) tem seis etapas marcadas por comentários. Além disso,
o documento antigo é apagado **antes** da extração e **fora** da transação
([ingest.py:160](../../src/rag/ingest.py#L160)): se a extração/embedding falhar, o
documento antigo é perdido.

**Critério de aceitação**:
- ✓ `ingest_document` fica com ≤ 50 linhas e orquestra helpers privados (validação
  de entrada, extração + validação de texto, chunk + embed, persistência).
- ✓ Re-ingestão: a remoção do documento antigo ocorre dentro do mesmo
  `BEGIN/COMMIT` que insere o novo. Falha em qualquer etapa (extração, texto
  ilegível, embedding, INSERT) **preserva** o documento antigo e seus chunks.
- ✓ Os valores de `IngestResult` (status/reason/error) são idênticos aos atuais
  para cada cenário.
- ✓ Testes de integração novos (embedding substituído por fake determinístico,
  sem baixar modelo — design.md §8): ingestão nova; hash repetido → `skipped`;
  re-ingestão com sucesso substitui o antigo; re-ingestão com **falha de
  embedding**, com **texto ilegível** e com **falha no INSERT** (prova que o
  `ROLLBACK` desfaz o DELETE) mantêm o antigo; teste parametrizado cobrindo cada
  `reason` de erro (`unsupported_type`, `not_a_file`, `extract_failed`, `no_text`,
  `unreadable_text`, `embed_failed`, `db_insert_failed`). `read_failed` e
  `no_chunks` ficam fora (exigiriam falha de I/O ou chunker vazio artificiais).
- ✓ Nota de revisão adicionada a **D-021** (a ordem da re-ingestão muda; a
  `UNIQUE(source_path)` de `001_initial.sql:10` exige o DELETE antes do INSERT na
  mesma transação).

### RF-008.4 — Exceções específicas, sem engolir erro em silêncio

**Critério de aceitação**:
- ✓ [audit_dialog.py:75,88](../../src/ui/dialogs/audit_dialog.py#L75): os dois
  `except Exception` viram `except (json.JSONDecodeError, TypeError)` num único
  helper `_pretty_json(raw: str) -> str` (remove a duplicação).
- ✓ [json_utils.py:54](../../src/llm/json_utils.py#L54): o `except ...: pass` é
  substituído por fluxo explícito (helper que retorna `None` na falha), mantendo
  o comportamento de `parse_json_response`.
- ✓ Os `except Exception` remanescentes em `agent.py` (persistência/log em
  SQLite — modo degradado, D-015/D-024) continuam logando e ganham comentário do
  **porquê** são largos.
- ✓ Inventário dos demais `except Exception` — **mantidos** (todos logam e são
  fronteiras de falha externa, política §8), sem mudança nesta spec:
  `main.py:15` (topo do processo), `core/db.py:142` e `learning/generator.py:226`
  (ROLLBACK + re-raise), `rag/ingest.py:165,215,248` (extração/embedding/INSERT →
  `IngestResult` de erro; reorganizados por RF-008.3 sem mudar a captura),
  `learning/coach.py:153,169` e `learning/grader.py:72` (falha de RAG/LLM →
  fallback com `warning`), `llm/gemma_client.py:158` (healthcheck → OFFLINE,
  D-017), e os handlers de UI (`ui/**`, fronteira com o usuário → `ui.notify`).
  Só os dois de `audit_dialog.py` mudam, por serem os únicos que capturam um erro
  **previsível e específico** sem log.

### RF-008.5 — Números mágicos viram constantes nomeadas

**Critério de aceitação** (cada literal abaixo é substituído por constante ou por
leitura de `Settings`):

| Local | Literal | Substituto |
|---|---|---|
| `rag/embed.py:41` | `384` | `EMBEDDING_DIM` |
| `llm/json_utils.py:44,46,49` | `[3:]`, `[:-3]`, `[4:]` | `len(CODE_FENCE)`, `len(JSON_LANG_TAG)` |
| `domain/learning/models.py:87`, `learning/coach.py:106,117` | `30` | `DEFAULT_STUDY_MINUTES` |
| `domain/learning/models.py:30-31`, `learning/generator.py:75` | `2`, `6` (condição, mensagem de erro e o "mínimo 2" do prompt) | `MIN_MC_OPTIONS`, `MAX_MC_OPTIONS` (mensagem e prompt interpolam as constantes) |
| `domain/tasks/service.py:35,45` | `23,59,59` | helper `_end_of_day(dt)` |
| `domain/agenda/service.py:73` | `30` | `NEXT_EVENT_WINDOW_DAYS` |
| `llm/agent.py:51` | `6` | `DEFAULT_MAX_ITERATIONS` |
| `llm/gemma_client.py:85-86` | `3`, `1`, `8` | `MAX_LLM_ATTEMPTS` (3 tentativas = 2 retries; o CLAUDE.md §8 diz "3 retries" — comportamento **não** muda, divergência registrada no comentário), `RETRY_WAIT_MIN_S`, `RETRY_WAIT_MAX_S` |
| `rag/chunk.py:39` | `800`, `150` | `DEFAULT_CHUNK_SIZE`, `DEFAULT_CHUNK_OVERLAP` |
| `rag/types.py:41` | `0.6` | `threshold_used: float \| None = None` — **exceção declarada ao princípio de compatibilidade** (muda o default de um modelo público); nenhum código depende do default: `retrieve.py:69-73` sempre preenche e `test_prompt.py:10` não usa o campo |
| `ui/state.py:55` | `50` | `PROMPT_HISTORY_LIMIT` |
| `ui/app.py:40` | `15.0` | `STARTUP_HEALTHCHECK_TIMEOUT_S` |
| `learning/coach.py:47` | texto "7 dias" | derivado de `PLAN_HORIZON_DAYS` |

- ✓ Literais passados como argumento nomeado que já revela o significado
  (`max_length=200`, `timedelta(days=7)`) e códigos HTTP amplamente conhecidos
  (401/403/4xx/5xx) **não** são alterados — exceção prevista no capítulo.

### RF-008.6 — Nomes claros (somente identificadores locais/privados)

**Critério de aceitação**:
- ✓ Variáveis de uma letra/abreviadas fora de compreensões curtas são renomeadas
  (lista em design.md §6), ex.: `s = get_settings()` → `settings`, `v` →
  `schema_version`, `mc/op` → `mc_questions/open_questions`, `cur2` →
  `chunk_cursor`, `spath` → `source_path`, `t = event.get("type")` →
  `event_type`.
- ✓ Em `chat_view.py`, o evento do stream do agent passa a se chamar
  `agent_event` (desambigua de "evento de calendário").
- ✓ [tool_learning.py:49](../../src/tools/tool_learning.py#L49): dedupe por
  efeito colateral (`seen.add` dentro da comprehension) → `list(dict.fromkeys(...))`.
- ✓ Nenhum nome público (função/classe/módulo/chave de JSON de tool) muda.

### RF-008.7 — Guia de estilo verificado automaticamente (P7)

**Critério de aceitação**:
- ✓ `pyproject.toml`: `[project.optional-dependencies] dev` → `[dependency-groups] dev`.
- ✓ `uv.lock` regenerado; numa venv nova, `uv sync` instala ruff/pytest/mypy.
- ✓ `uv run ruff check src tests` sem erros; `uv run pytest` verde.
- ✓ Instruções de uso passam a `uv sync`: `README.md:323` e `STATUS.md:198,235`
  (registros históricos do STATUS, ex. linhas 51/83, não são reescritos).
- ✓ D-031 registrado em `decisions.md`.

## Fora de escopo (explícito)

- Unificar vocabulário `quiz`/`prova`/`exam` e renomear `GemmaClient`/parâmetro
  `gemma` (dívida documentada em D-028; pede spec própria).
- Decompor os diálogos grandes da UI (`exam_dialog`, `materials_dialog`, `sidebar`,
  `audit_dialog`, `theme.apply_theme`).
- Extrair as ~150 cores hexadecimais fixas para o tema.
- `date_picker.parse` retornar `None` para data inválida (decisão da entrevista).
- Mudanças de comportamento além de RF-008.1 e RF-008.3.

## Cenários de erro cobertos

| Cenário | Comportamento esperado | RF |
|---|---|---|
| Saída de tool não serializável | `status="error"`; mesmo dict de erro em evento/log/sessão/observação; log `warning` com nome da tool; loop segue | 008.1 |
| Falha ao gravar `tool_call_logs` / sessão | `warning`, loop segue (modo degradado, inalterado) | 008.2/008.4 |
| Falha de extração/embedding/INSERT na re-ingestão | `ROLLBACK`; documento antigo preservado; `IngestResult` de erro | 008.3 |
| JSON de log ilegível na auditoria | Exibe texto bruto (sem esconder outras exceções) | 008.4 |
