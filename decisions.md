# Registro de Decisões — JARVIS Acadêmico

Este arquivo é o **registro não-volátil** de decisões técnicas e de negócio do projeto.
Toda decisão aprovada vai aqui, com data, contexto, alternativas e justificativa.

Formato: [Architecture Decision Record (ADR)](https://adr.github.io/) simplificado.

---

## Convenções

- **ID**: D-NNN incremental.
- **Status**: `proposed` / `accepted` / `superseded by D-XXX` / `rejected`.
- **Data**: ISO 8601 (YYYY-MM-DD).
- Cada decisão aprovada deve constar também no `CLAUDE.md` (constituição) quando for transversal.

---

## D-001 — Abordagem geral: Híbrida leve

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: O trabalho exige implementar "explicitamente" RAG, integração com LLM e tool calling. É acadêmico, será avaliado e o grupo precisa explicar o código.
- **Decisão**: Usar bibliotecas pequenas e focadas (`openai` client, `sentence-transformers`, `sqlite-vec`, `pdfplumber`) e implementar o pipeline de RAG e o loop de tool calling com código próprio. Não usar frameworks pesados (LangChain, LlamaIndex).
- **Alternativas consideradas**:
  - LangChain completo (rejeitada: esconde demais, contraria "implementar explicitamente").
  - LlamaIndex + tools custom (rejeitada: framework ainda pesado).
  - 100% from scratch (rejeitada: custo de tempo alto, risco de bugs).
- **Consequências**: Mais código de pipeline próprio (chunking, retrieval, agent loop), mas total visibilidade e didática para o professor.

---

## D-002 — GUI: NiceGUI

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Requisito do projeto: interface gráfica moderna e bonita; precisa de chat + dashboards (agenda/tarefas) + upload de documentos.
- **Decisão**: Usar **NiceGUI** (web-based, componentes Quasar/Vue, real-time).
- **Alternativas consideradas**:
  - Streamlit (rejeitada: visual genérico, modelo de re-execução do script atrapalha tool calling longo).
  - Flet (rejeitada: menos componentes prontos para chat, curva maior).
  - Gradio (rejeitada: limitado a demos, não cobre dashboards complexos).
- **Consequências**: Interface bonita e moderna out-of-the-box; modelo de programação assíncrono — exige cuidado com chamadas bloqueantes (embeddings, LLM).

---

## D-003 — Vector store: sqlite-vec

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: O usuário definiu SQLite como storage para simplificar deploy. Precisamos de busca KNN para o RAG.
- **Decisão**: Usar a extensão **sqlite-vec** (carregada via `enable_load_extension`).
- **Alternativas consideradas**:
  - NumPy brute-force (rejeitada: solução secundária; sqlite-vec é mais profissional).
  - ChromaDB local (rejeitada: foge da escolha de "tudo num único SQLite").
  - sqlite-vss (rejeitada: o próprio autor recomenda migrar para sqlite-vec).
- **Consequências**: Um único arquivo `.db`. Necessário usar `sqlite3` nativo (não SQLAlchemy/ORM) para facilitar carregamento da extensão.

---

## D-004 — Embeddings: intfloat/multilingual-e5-small (local)

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Material de estudo será majoritariamente em português. Precisamos de embeddings de boa qualidade, baratos e idealmente locais (sem depender da API LIA UFMS para embeddings, que não está documentada).
- **Decisão**: Usar **`intfloat/multilingual-e5-small`** via `sentence-transformers` (384 dim, ~120 MB, multilingual incluindo PT).
- **Alternativas consideradas**:
  - paraphrase-multilingual-MiniLM-L12-v2 (rejeitada: mais pesado, sem esquema query/passage do e5).
  - BAAI/bge-m3 (rejeitada: ~2 GB, lento em CPU, overkill para 10–20 docs).
  - Embeddings via API Gemma (rejeitada: endpoint LIA UFMS pode não suportar embeddings).
- **Consequências**: Usar prefixos `query:` (consultas) e `passage:` (chunks indexados) conforme padrão do modelo. Primeira execução baixa o modelo (~120 MB).

---

## D-005 — Parser de documentos: pdfplumber

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Material acadêmico vem em PDFs (frequentemente com tabelas, layout estruturado) e textos simples (.txt/.md).
- **Decisão**: Usar **pdfplumber** para PDFs e leitura nativa de arquivo para .txt/.md.
- **Alternativas consideradas**:
  - PyMuPDF (rejeitada: licença AGPL exige citação cuidadosa).
  - pypdf (rejeitada: qualidade inferior em PDFs com layout complexo).
  - Docling (rejeitada: dependências enormes, overkill para 10–20 docs).
- **Consequências**: Boa extração de texto e tabelas. Mais lento que PyMuPDF, mas tolerável para o dataset do trabalho.

---

## D-006 — Chunking: Recursive Character Splitter com overlap

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: O trabalho exige documentar a "estratégia de chunking e impacto no RAG".
- **Decisão**: Implementar **Recursive Character Splitter** com tamanho-alvo **800 chars** e overlap **150 chars**. Separadores hierárquicos: `["\n\n", "\n", ". ", "? ", "! ", " ", ""]`.
- **Alternativas consideradas**:
  - Token-based fixo (rejeitada: ganho marginal, requer tokenizer extra).
  - Por parágrafo simples (rejeitada: parágrafos longos/curtos viram chunks ruins).
  - Semantic chunking (rejeitada: caro e difícil de justificar).
- **Consequências**: Parâmetros (`chunk_size`, `chunk_overlap`) ficam configuráveis via `.env` para ajuste fino durante avaliação.

---

## D-007 — Tool Calling: prompt-based JSON + agent loop próprio

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Requisito do trabalho: "a decisão de chamada deve ser feita pela LLM (não apenas lógica fixa)" e logs com ferramenta/entrada/saída são obrigatórios. Endpoint LIA UFMS é OpenAI-compatível mas suporte ao parâmetro `tools=` não está confirmado.
- **Decisão**: Construir system prompt detalhado descrevendo as tools (nome, schema, exemplos). LLM retorna JSON estruturado tipo `{"tool": "...", "args": {...}}` ou resposta direta. Loop agentivo próprio executa a tool e re-injeta o resultado.
- **Alternativas consideradas**:
  - OpenAI `tools=` nativo (rejeitada: depende de suporte do endpoint LIA UFMS, sem garantia).
  - Híbrido com fallback (rejeitada: complexidade dupla para um trabalho acadêmico).
  - JSON mode/structured output (rejeitada: similar problema de suporte).
- **Consequências**: Total visibilidade do prompt e do fluxo agentivo — excelente para explicar ao professor. Robustez de parsing JSON é responsabilidade nossa (tratar respostas malformadas).

---

## D-008 — Arquitetura: Layered + feature modules

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Rubrica avalia engenharia de software (organização, separação de responsabilidades) em 10%.
- **Decisão**: Estrutura em camadas com módulos por feature:
  ```
  src/
    core/      (config, db, logging)
    llm/       (cliente Gemma + agent loop)
    rag/       (ingest, chunk, embed, retrieve)
    domain/
      agenda/  (models + repo + service)
      tasks/   (models + repo + service)
    tools/     (registry + tool_*.py)
    ui/        (NiceGUI views)
    main.py
  ```
- **Alternativas consideradas**:
  - Feature-based plano (rejeitada: duplica infraestrutura).
  - Hexagonal/Ports & Adapters (rejeitada: overkill).
  - Flat (rejeitada: não demonstra engenharia).
- **Consequências**: Convenções claras de import (`from src.core.db import ...`). UI nunca importa direto de `core` — passa por `domain`/`tools`.

---

## D-009 — DB access: sqlite3 nativo + Pydantic v2

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Necessário usar `sqlite3` puro para carregar a extensão `sqlite-vec` via `enable_load_extension`. Precisamos validar argumentos vindos da LLM (tool calling).
- **Decisão**: Conexão direta com módulo `sqlite3` em repositórios finos. **Pydantic v2** para modelos de domínio (validação, serialização, schemas para tools).
- **Alternativas consideradas**:
  - SQLModel (rejeitada: integração com extensão SQLite mais complexa).
  - SQLAlchemy ORM (rejeitada: pesado, overkill).
  - sqlite3 + dataclasses (rejeitada: perde validação para argumentos vindos da LLM).
- **Consequências**: SQL explícito em `repo.py` de cada feature. Modelos Pydantic v2 servem também como base para `json schema` das tools.

---

## D-010 — Logging: loguru + tabela SQLite (audit)

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Trabalho exige logs com ferramenta/entrada/saída para auditoria de tool calls.
- **Decisão**: **Dois layers**:
  1. **loguru** para logging geral da aplicação (console com cores + arquivo rotativo em `./logs/`).
  2. **Tabela `tool_call_logs` no SQLite** para auditoria estruturada e consultável de toda chamada de tool (timestamp, tool_name, input_json, output_json, duration_ms, status, error).
- **Alternativas consideradas**:
  - stdlib logging + JSON formatter (rejeitada: boilerplate pesado).
  - structlog (rejeitada: curva maior, tool calls vão pra SQLite mesmo).
  - print() + SQLite (rejeitada: sem níveis, erros silenciam).
- **Consequências**: Demo do vídeo pode mostrar a tabela `tool_call_logs` como evidência de Tool Calling funcionando.

---

## D-011 — Gestão de deps: uv + pyproject.toml + uv.lock

- **Status**: accepted
- **Data**: 2026-05-23
- **Contexto**: Instrução do usuário (#7): decisões devem ser não-voláteis para que o projeto continue em outras máquinas. Reprodutibilidade é crítica.
- **Decisão**: Usar **uv** (Astral) com `pyproject.toml` e `uv.lock`. Python **3.12**.
- **Alternativas consideradas**:
  - pip + requirements.txt (rejeitada: sem lockfile real).
  - Poetry (rejeitada: mais lento, histórico de breaking changes).
  - conda (rejeitada: pesado, não necessário).
- **Consequências**: Setup em qualquer máquina: `uv sync` instala tudo. Adicionar dep: `uv add <pkg>`.

---

## D-012 — Schema migrations: PRAGMA user_version + arquivos .sql numerados

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: Spec 000 excluiu framework de migration (alembic). Mas o grupo precisa
  evoluir o schema entre Specs (002 acrescenta colunas, 003 acrescenta `events`, etc.).
- **Decisão**: Sistema próprio em `src/core/migrations/`:
  - Arquivos `NNN_<descricao>.sql` numerados sequencialmente (001 = inicial com 5 tabelas).
  - Runner em `src/core/db.py` lê `PRAGMA user_version`, aplica em ordem todos os scripts
    com versão maior, e bumpa `user_version` ao final de cada um.
  - Forward-only (sem rollback automático).
- **Alternativas consideradas**:
  - `yoyo-migrations` (rejeitada: dependência extra, mistura .py com .sql).
  - alembic (rejeitada: foge da decisão D-009 sem ORM; vinculado a SQLAlchemy).
  - Programmatic schema em Python (rejeitada: sem rastreamento de evolução de colunas).
- **Conseqüências**: Schema visível/auditavel em `.sql` puro. Cada Spec subsequente que
  precise evoluir o schema acrescenta um migration. Inicia banco vazio: aplica todos os
  migrations. Inicia banco antigo: aplica diferença.

---

## D-013 — Conexão SQLite: per-operação + WAL + foreign_keys + busy_timeout

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: Operações concorrentes (UI + agent loop + tool calls) precisam acessar o
  SQLite sem deadlocks; sqlite-vec exige `enable_load_extension`.
- **Decisão**: Em `src/core/db.py`, função `get_connection()` como context manager:
  ```python
  with get_connection() as conn:
      ...
  ```
  Aplica em TODA conexão:
  - `PRAGMA journal_mode = WAL` (leitor não trava escritor).
  - `PRAGMA foreign_keys = ON` (integridade referencial).
  - `PRAGMA busy_timeout = 3000` (3s de retry automático em lock).
  - `PRAGMA synchronous = NORMAL` (balanço segurança/perf, padrão em WAL).
  - `conn.enable_load_extension(True)` + load do `sqlite-vec`.
  Código síncrono envolvido em `asyncio.to_thread(...)` quando chamado de async.
- **Alternativas consideradas**:
  - Conexão global com Lock (rejeitada: serializa tudo, ruim para UX).
  - `aiosqlite` (rejeitada: complica carregamento da extensão).
  - Sem PRAGMAs (rejeitada: perde integridade e fica vulnerável a lock).
- **Conseqüências**: Custo de abrir conexão por operação é pequeno; WAL acrescenta
  arquivos `-wal` e `-shm` (gitignored).

---

## D-014 — Cliente LLM: AsyncOpenAI + tenacity (retry async)

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: NiceGUI é assíncrono; CLAUDE.md §8 exige retry com backoff em 5xx/timeout.
- **Decisão**: `src/llm/gemma_client.py` expõe classe `GemmaClient` usando
  `openai.AsyncOpenAI`. Retries via `tenacity` (`@retry(stop=stop_after_attempt(3),
  wait=wait_exponential(multiplier=1, min=1, max=8))`) cobrindo `APITimeoutError`,
  `APIConnectionError`, `RateLimitError`, 5xx. Erros de auth (401) e 4xx de validação
  NÃO re-tentam (fail-fast).
- **Alternativas consideradas**:
  - Sync + asyncio.to_thread (rejeitada: ergonomia inferior).
  - Retry manual (rejeitada: reinventa a roda).
  - Sync + async lado a lado (rejeitada: overkill).
- **Conseqüências**: Adiciona dependência `tenacity` ao pyproject. Métodos do
  `GemmaClient` são async (ver D-018 sobre streaming).

---

## D-015 — tool_call_logs: full JSON I/O + metadados, retenção indefinida

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: Trabalho exige logs com ferramenta/entrada/saída; análise de erros (Trabalho 2)
  precisa de rastreabilidade.
- **Decisão**: Schema da tabela `tool_call_logs`:
  ```sql
  CREATE TABLE tool_call_logs (
      id          INTEGER PRIMARY KEY AUTOINCREMENT,
      ts          TEXT    NOT NULL DEFAULT (datetime('now')),
      tool_name   TEXT    NOT NULL,
      input_json  TEXT    NOT NULL,
      output_json TEXT,                              -- NULL se erro antes da execução
      status      TEXT    NOT NULL CHECK (status IN ('ok','error')),
      error_msg   TEXT,
      duration_ms INTEGER NOT NULL,
      llm_call_id TEXT                               -- opcional, vincula à conversa
  );
  CREATE INDEX idx_tool_call_logs_ts ON tool_call_logs(ts);
  CREATE INDEX idx_tool_call_logs_tool ON tool_call_logs(tool_name);
  ```
  Sem truncação de payload; sem purge automático.
- **Alternativas consideradas**:
  - Auto-purge >30d (rejeitada: é acadêmico, dataset pequeno).
  - Truncação 4KB (rejeitada: perde detalhes).
  - Só metadados (rejeitada: descumpre requisito).
- **Conseqüências**: A UI poderá expor uma view "auditoria de tool calls" como
  diferencial. Crescimento da tabela é aceitável para o escopo.

---

## D-016 — Carregamento do modelo de embeddings: lazy + indicador de progresso

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: `multilingual-e5-small` é ~120 MB; carrega em ~2–5s em CPU; primeiro
  uso baixa do HuggingFace.
- **Decisão**: `src/rag/embed.py` expõe `get_embedder()` que retorna um singleton
  carregado **na primeira chamada**. UI mostra spinner com "Carregando modelo de
  embeddings..." durante o carregamento (`ui.notification` ou `ui.spinner`). Modelo
  permanece em memória pela sessão.
- **Alternativas consideradas**:
  - Eager (rejeitada: boot lento desnecessário).
  - Background preload (rejeitada: complexidade extra).
  - Configurável via env (rejeitada: over-engineering).
- **Conseqüências**: Boot da app é rápido. Primeira operação RAG da sessão tem ~2–5s
  extra (visível ao usuário via indicador).

---

## D-017 — Comportamento offline: degraded mode + healthcheck + banner

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: Endpoint LIA UFMS pode estar indisponível; token pode expirar; rede
  pode cair durante uso.
- **Decisão**:
  - Ao startup, `GemmaClient.healthcheck()` faz 1 chamada rápida (timeout 5s,
    `messages=[{'role':'user','content':'ping'}]`, `max_tokens=1`).
  - Se sucesso: estado da app = ONLINE.
  - Se falha: estado = OFFLINE; UI mostra banner persistente '⚠️ LLM indisponível —
    funcionalidades de chat e RAG estão desabilitadas. Verifique o token em .env'
    com botão "Tentar reconectar" que re-roda o healthcheck.
  - Agenda e Tarefas operam normalmente em ambos os estados.
  - Durante uso, falhas pós-retries (3 tentativas via tenacity) viram toast amigável
    sem crashar o app.
- **Alternativas consideradas**:
  - Recusar iniciar (rejeitada: impede features offline).
  - Lazy fail (rejeitada: usuário descobre tarde).
  - Mock mode automático (rejeitada: confunde avaliador).
- **Conseqüências**: Healthcheck adiciona ~5s ao startup em rede ruim. Mas é
  amigável ao usuário e ao demo do vídeo.

---

## D-018 — LLM streaming: dual mode (stream para texto, complete para tool calls)

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: Streaming token-a-token traz UX moderna; tool calls prompt-based exigem
  JSON completo antes de parsear.
- **Decisão**: `GemmaClient` expõe dois métodos:
  ```python
  async def stream_chat(messages: list[Message]) -> AsyncIterator[str]:
      """Yield de tokens conforme são gerados (para resposta direta ao usuário)."""

  async def complete_chat(messages: list[Message]) -> str:
      """Retorna resposta completa (usado pelo agent_loop para parsear tool calls)."""
  ```
  O `agent_loop` (Spec 005) usa `complete_chat()` na fase de decisão e
  `stream_chat()` quando entrega a resposta final ao usuário.
- **Alternativas consideradas**:
  - Sempre bloqueante (rejeitada: UX inferior).
  - Sempre streaming com parser incremental (rejeitada: parser frágil).
  - Decidir mais tarde (rejeitada: design tem que prever ambos).
- **Conseqüências**: NiceGUI usa `ui.chat_message` com update em tempo real
  (diferencial visual no vídeo). Código do client tem dois caminhos.

---

## D-019 — Estratégia de testes: pirâmide unit + integration + smoke LLM opt-in

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 001.
- **Contexto**: CLAUDE.md §7 define a política em alto nível; infraestrutura concreta
  precisa ser fixada para que Specs 002–6 a herdam.
- **Decisão**:
  - **`tests/unit/`**: lógica pura (chunking, parsing JSON da LLM, validação Pydantic,
    serializers). pytest síncrono.
  - **`tests/integration/`**: repositórios contra SQLite em arquivo temporário
    (`tmp_path` fixture), com extensão `sqlite-vec` carregada. `pytest-asyncio` em
    `asyncio_mode = "auto"`.
  - **Smoke LLM opt-in**: testes marcados `@pytest.mark.live_llm` rodam só quando
    `JARVIS_RUN_LIVE_LLM=1`. Default: skipped (não queima token em CI/local).
  - **Fixtures globais** em `tests/conftest.py`: `tmp_db`, `sample_documents`,
    `fake_llm` (stub que retorna respostas pre-definidas).
- **Alternativas consideradas**:
  - Só integration (rejeitada: lento).
  - Mock-heavy (rejeitada: frágil).
  - Sem testes formais agora (rejeitada: adia infra).
- **Conseqüências**: Cobertura efetiva; rapidez razoável; sem dor de queimar token
  toda vez que rodar `pytest`.

---

## D-020 — Vector store: chunk_vecs USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[384])

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 002.
- **Contexto**: Spec 002 precisa mapear chunks de texto a embeddings de 384 dim
  (multilingual-e5-small). A tabela `chunks` já existe (D-015 / migration 001).
- **Decisão**: Criar virtual table `chunk_vecs` via sqlite-vec com `chunk_id`
  como PK pareando 1:1 com `chunks.id`:
  ```sql
  CREATE VIRTUAL TABLE chunk_vecs USING vec0(
      chunk_id INTEGER PRIMARY KEY,
      embedding FLOAT[384]
  );
  ```
  Sem FK explícita (vec0 não garante FK), mas semanticamente 1:1. Cleanup
  manual em delete cascading: o repository deleta da `chunk_vecs` ANTES de
  deletar de `chunks` (ou usa trigger).
- **Alternativas consideradas**:
  - FK em virtual table (rejeitada: SQLite não garante).
  - BLOB direto em `chunks.embedding` + brute-force NumPy (rejeitada:
    contraria D-003, usa sqlite-vec para nada).
  - vec0 com metadados embutidos (rejeitada: duplica texto e document_id).
- **Conseqüências**: Retrieval usa `vec_search` em `chunk_vecs` retornando
  `chunk_id`, depois JOIN com `chunks` e `documents`.

---

## D-021 — Re-ingestão: hash-based SHA-256 com cascade delete em mudança

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 002.
- **Contexto**: Usuário pode re-fazer upload de um PDF (mesmo arquivo) ou de
  uma versão editada (mesmo path mas conteúdo diferente). Comportamento não
  estava definido.
- **Decisão**: Adicionar coluna `content_hash TEXT NOT NULL` em `documents`
  via migration 002. Ao ingerir:
  1. Calcular SHA-256 do arquivo (streaming em chunks de 64KB).
  2. Se já existe documento com mesmo `content_hash` → retornar (no-op).
  3. Se existe `source_path` igual mas `content_hash` diferente → deletar
     o documento antigo (CASCADE remove chunks; e nossas chamadas explícitas
     limpam chunk_vecs) e re-ingerir.
  4. Caso contrário → novo INSERT.
- **Alternativas consideradas**:
  - Path-based + flag manual (rejeitada: UX inferior).
  - Sempre re-ingerir (rejeitada: desperdiça embeddings).
  - Versionado (rejeitada: overkill).
- **Conseqüências**: Idempotência total. Re-uploads não custam embeddings se
  o conteúdo não mudou.
- **Revisão (2026-10-06, Spec 008 / RF-008.3)**: a remoção do documento antigo
  passou a ocorrer **dentro da mesma transação** que insere o novo, e só depois de
  extração, validação de texto e embedding terem dado certo. Antes, o DELETE
  rodava em autocommit antes da extração: uma falha posterior perdia o documento
  antigo. Como `documents.source_path` é `UNIQUE`, o DELETE precede o INSERT.

---

## D-022 — RAG retrieval vazio: threshold + prompt anti-hallucination + UI hint

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 002.
- **Contexto**: Trabalho 2 vai avaliar "correção" das respostas. Alucinar em
  retrieval vazio seria classificado como "incorreta".
- **Decisão**:
  - Cálculo da relevância: `vec_distance_cosine` retorna distância (0=idêntico,
    2=oposto). Definir `JARVIS_RAG_DISTANCE_THRESHOLD` (default 0.6).
  - Se 0 chunks recuperados OU min(distances) > threshold → marcar
    `no_relevant_context = True`.
  - System prompt SEMPRE inclui: *"Se o contexto fornecido não contém
    informação suficiente para responder, diga claramente que não encontrou
    material relevante e sugira que o usuário carregue mais documentos. Não
    invente informações."*.
  - UI mostra badge cinza "sem material relevante" no topo da resposta quando
    `no_relevant_context = True`.
- **Alternativas consideradas**:
  - Só prompt (rejeitada: modelo pode tentar 'remendar' contexto fraco).
  - Só threshold (rejeitada: perde fluidez).
  - Sem proteção (rejeitada: alto risco de hallucination).
- **Conseqüências**: Variável `JARVIS_RAG_DISTANCE_THRESHOLD` entra em config.
  Adiciona pequena mudança no `.env.example`.

---

## D-023 — RAG prompt template: PT-BR + chunks numerados + citação obrigatória

- **Status**: accepted
- **Data**: 2026-05-23
- **Origem**: Entrevista Spec 002.
- **Contexto**: Trabalho 2 exige rastreabilidade dos documentos recuperados
  por pergunta. A LLM Gemma 12B suporta PT-BR bem (multilingual).
- **Decisão**: Template fixo:
  ```
  System:
    Você é um assistente acadêmico que ajuda estudantes a entender materiais
    de estudo. Responda APENAS com base no contexto fornecido abaixo. Cite a
    fonte como [Doc N] sempre que afirmar algo. Se o contexto for insuficiente,
    diga claramente que não encontrou material relevante e sugira que o usuário
    carregue mais documentos. Não invente informações.

    Contexto:
    [Doc 1: <título do documento>]
    <texto do chunk>

    [Doc 2: <título do documento>]
    <texto do chunk>
    ...

  User:
    <pergunta original>
  ```
  Numeração dos chunks segue ordem de relevância (menor distância primeiro).
- **Alternativas consideradas**:
  - Sem citações (rejeitada: perde rastreabilidade).
  - Sistema em EN (rejeitada: mistura confunde Gemma).
  - Few-shot examples (rejeitada: estoura tokens, exemplos difíceis de
    generalizar).
- **Conseqüências**: Função `build_rag_prompt(question, chunks_with_docs)` em
  `src/rag/prompt.py`. Testes verificam estrutura do prompt e ordenação por
  distância.

---

## D-024 — Persistência de conversas (chat sessions + messages)

- **Status**: accepted
- **Data**: 2026-05-24
- **Origem**: Pedido do usuário (UI v2) — sidebar "Recentes" estilo ChatGPT
  deve restaurar conversa INTEIRA (não só re-injetar o prompt).
- **Contexto**: Chat efêmero não permite revisitar conversas, prejudica demo do
  vídeo do trabalho e a experiência de uso real.
- **Decisão**: Migration 003 cria `chat_sessions(id, title, created_at, updated_at)`
  + `chat_messages(id, session_id, role, content, metadata_json, position, created_at)`
  com `UNIQUE(session_id, position)` e FK CASCADE. Módulo `src/domain/chat/`
  com models Pydantic, repo CRUD e service (`title_from_prompt`,
  `start_session_with_first_message`). `AgentLoop.respond()` recebe
  `session_id` opcional — se fornecido, grava cada mensagem
  (user/assistant final/tool events com metadata estruturada).
- **Alternativas consideradas**:
  - Apenas prompts em `app.storage.user` (rejeitada: perde contexto da
    conversa anterior, não é "ChatGPT real").
  - Híbrido em memória só (rejeitada: perde no reload do app).
- **Consequências**:
  - `tool` role: persistido com `metadata_json` contendo `{tool, args, status,
    duration_ms, error_msg}` → permite restauração fiel dos cards de tool call.
  - Título da sessão: primeiros 60 chars do primeiro prompt (com ellipsis).
  - Sidebar lê via `list_recent_sessions(limit=30)` ordenado por `updated_at DESC`.
  - `AgentLoop` sem `session_id` (default None) continua funcionando em testes
    e fluxos efêmeros — backward-compatible.

---

## D-025 — VIEW SQL unificada para o Calendário (eventos + tarefas)

- **Status**: accepted
- **Data**: 2026-05-24
- **Origem**: Pedido do usuário (UI v2) — calendário visual estilo Google
  Calendar onde eventos e tarefas convivem.
- **Contexto**: Eventos (`events`) e Tarefas (`tasks`) são entidades distintas
  do domínio com schemas diferentes. Mas no calendário do usuário precisam
  aparecer juntos, ordenados por data, distinguidos visualmente.
- **Decisão**: Migration 004 cria `CREATE VIEW calendar_items_view AS SELECT ...
  FROM events UNION ALL SELECT ... FROM tasks WHERE due_at IS NOT NULL` —
  normalizando colunas (`item_uid`, `item_type`, `source_id`, `title`,
  `starts_at`, `ends_at`, `category`, `status`, `priority`, `location`,
  ...). Tarefas SEM `due_at` não aparecem no calendário (só na "Lista de
  tarefas" pura). Service `list_calendar_items(conn, start, end,
  include_events, include_tasks, only_pending_tasks, kinds)` retorna
  `list[CalendarItem]` (Pydantic).
- **Alternativas consideradas**:
  - Tabela única polimórfica (rejeitada: breaking change quebra tools, perde D-009).
  - Queries separadas + merge em Python (rejeitada: mais código, menos performante).
- **Consequências**:
  - Tools existentes (`consultar_agenda`, `listar_tarefas`) continuam
    funcionando sem mudança.
  - Nova tool `consultar_calendario(data_inicio, data_fim, ...)` permite à
    LLM responder perguntas unificadas tipo "o que tenho na semana?".
  - View NÃO é editável — CRUD continua via repos específicos
    (`agenda/repo.py`, `tasks/repo.py`).

---

## D-026 — UI v2: ChatGPT-style com Calendário unificado

- **Status**: accepted
- **Data**: 2026-05-24
- **Origem**: Pedido do usuário com especificação JSON detalhada + print do
  Google Calendar.
- **Contexto**: UI v1 tinha 5 tabs (Chat, Agenda, Tarefas, Materiais,
  Auditoria) e visual genérico — atrapalha o "diferencial" da rubrica.
- **Decisão**: Reescrita completa de `src/ui/` em 10 fases (plano em
  `~/.claude/plans/melhorias-necess-rias-fancy-lollipop.md`). Componentes
  reutilizáveis em `src/ui/components/`; dialogs modais em `src/ui/dialogs/`;
  estado global em `src/ui/state.py` com callbacks de sessão. Tabs antigos
  100% removidos (`src/ui/views/` deletado). Menu "+" do chat substitui
  navegação tabular: Enviar material, Calendário, Lista de tarefas,
  Pesquisar auditoria.
- **Decisões locais consolidadas**:
  - **Tema**: fundo `#000000` absoluto (override `#121212` Quasar via
    `app.colors(dark='#000000', dark_page='#000000')` + CSS `!important`).
    Fonte **Inter** via Google Fonts.
  - **Locale PT-BR Quasar**: injetado via `ui.add_head_html` com script JS
    que aguarda `window.Quasar.lang` e chama `Quasar.lang.set({...})` com
    arrays de meses/dias em português. Resolve calendários, datepickers e
    labels Quasar automaticamente.
  - **Histórico de prompts**: lista em memória (até 50, FIFO sem
    duplicatas) acessível por ↑/↓ no input. NÃO persiste entre sessões do
    browser (intencional — comportamento de terminal/shell).
  - **Tool calls discretas**: `ui.expansion(value=False)` colapsado por
    padrão, ícone 🔧 + nome + duração no header; clique expande input/output
    formatados em JSON.
  - **Wizard Evento vs Tarefa**: 2 cards grandes com texto didático
    explicando cada um (evento = "VAI ACONTECER em horário fixo"; tarefa =
    "PRECISA FAZER até um prazo"). Reduz erro do usuário e da LLM.
  - **Cores do calendário**: eventos por `kind` (aula=azul, prova=vermelho,
    trabalho=âmbar, outro=cinza); tarefas por `priority` (0=cinza,
    1=laranja, 2=rosa) com bolinha + texto riscado se concluída.
  - **Avatar do usuário**: HTML `<div>` puro com `border-radius:50%`
    (Quasar `q-avatar` não tem prop nativa pra texto/iniciais).
  - **Date pickers PT-BR**: helper `date_picker_ptbr(label, with_time)`
    em `src/ui/components/date_picker.py` — input com máscara
    `##/##/####[ ##:##]` + slot append com ícone que abre menu Quasar.
- **Alternativas consideradas**:
  - Manter tabs como navegação alternativa (rejeitada: redundância UX).
  - FullCalendar.js para o calendário (rejeitada: 200KB+ de JS, contraria
    decisão D-002 de stack leve).
  - SVG/Canvas custom (rejeitada: overkill, NiceGUI grid manual basta).
- **Consequências**:
  - 14 arquivos novos em `src/ui/` + 1 domínio (`calendar_view`) + 1 tool +
    2 migrations.
  - `src/ui/views/` removido completamente.
  - 75 testes passando, ruff limpo, UI sobe em http://127.0.0.1:8080.
  - Acentuação PT-BR global (~76 strings) corrigida nos system prompts,
    tools, agent loop, ingest e services.

---

## D-027 — RAG: caminho único via agent loop (remoção do `pipeline.ask` órfão)

- **Data**: 2026-06-12.
- **Contexto**: existiam dois caminhos de geração RAG — (1) o agent loop, que
  recupera trechos via a tool `buscar_material_rag` e gera a resposta final, e
  (2) `src/rag/pipeline.py` (`ask`/`ask_complete`), um pipeline RAG dedicado com
  streaming e citações. A UI (`chat_view`) sempre usou **apenas** o caminho (1);
  o `pipeline.ask` nunca foi chamado em produção (código órfão).
- **Decisão**: consolidar em **um único caminho** (agent loop). Reforçar a tool
  `buscar_material_rag` para enviar o **texto completo** do chunk, numerar os
  trechos como `[Doc N]` e incluir uma `instrucao` de grounding no retorno
  (antes truncava em 400 chars e não instruía a LLM). Adicionada a regra 7 de
  citação no system prompt do agente (`registry.py`), `top_k` default 5→4 e
  bloco "Fontes" na UI (`chat_view`). Remover `src/rag/pipeline.py` e os tipos
  exclusivos dele (`Citation`, `RagResponse`).
- **Razão**: P1 (simplicidade explícita) e "o aluno deve conseguir explicar o
  código" — manter dois caminhos, um deles morto, confunde e contraria a
  arquitetura. A política de grounding rígida (antes só em `rag/prompt.py`)
  passou a valer no caminho que de fato roda.
- **Alternativas consideradas**: rotear perguntas conceituais para
  `pipeline.ask` (rejeitada pelo mantenedor — preferiu caminho único no agent).
- **Consequências**:
  - `src/rag/pipeline.py` removido; `Citation`/`RagResponse` removidos de
    `types.py`; `__init__.py` atualizado.
  - `src/rag/prompt.py` (`build_rag_messages`, `SYSTEM_PROMPT`) **mantido** —
    coberto por teste (`test_prompt.py`) e documenta a política de citação.
  - `ruff` limpo, `pytest` 104 passed / 3 skipped.
- **Relacionada a**: [D-007](#d-007), [D-022](#d-022), [D-023](#d-023).

---

## D-028 — Migração do LLM: Gemma 12B → Qwen2.5-14B-Instruct-AWQ (LIA UFMS)

- **Data**: 2026-06-13.
- **Contexto**: o projeto foi construído sobre o **Gemma 12B** servido pela LIA
  UFMS (`https://llm.liaufms.org/v1/gemma-3-12b-it`). Em 2026-06-13 o endpoint
  Gemma passou a retornar **404 — `Instance 'gemma-3-12b-it' not found`** (a LIA
  aposentou a instância) e o token antigo passou a dar **401 Invalid API token**.
  Um notebook de referência do professor (`testetoken.ipynb`) revelou o endpoint
  ativo: **Qwen2.5-14B-Instruct-AWQ** em
  `https://llm.liaufms.org/v1/qwen2-5-14b-instruct-awq`, com novo token.
- **Decisão**: migrar a configuração do LLM para o Qwen (novas `JARVIS_LLM_*`
  em `.env`/`.env.example`). **Manter** a classe `GemmaClient` e o módulo
  `src/llm/gemma_client.py` com o nome histórico — o cliente é OpenAI-compatível
  e funciona com o Qwen sem alteração estrutural; renomear tudo (classe, arquivo,
  ~27 referências) traria risco/ruído sem ganho funcional para a entrega.
- **Razão**: P7 (reprodutibilidade) — o setup precisa apontar para o endpoint que
  de fato existe. A troca é só de configuração; a arquitetura OpenAI-compatible
  (D-014/D-018) já abstrai o provedor. Documentar aqui evita que o nome "Gemma"
  espalhado pelo código confunda a banca ("o aluno deve explicar o código").
- **Quirk de streaming (importante)**: ao contrário do Gemma, o endpoint Qwen da
  LIA **ignora `stream=True`** e devolve a resposta inteira num **único chunk**
  com `delta=None` e o texto em `choice.message.content` (não em `delta.content`).
  O `stream_chat` original (que só lê `delta.content`) renderizava 0 tokens.
  Adicionado fallback em `gemma_client.py::stream_chat` para extrair de
  `message.content` quando o delta vier vazio (endpoints OpenAI-compliant seguem
  usando `delta`). Como a UI consome a resposta final via evento `final` do agent
  loop (não via `stream_chat`), o chat nunca ficou em branco; o efeito de
  digitação na UI (`chat_view`) é simulado revelando o texto em blocos.
- **Alternativas consideradas**: renomear todo o código Gemma→Qwen (rejeitada —
  alto esforço, alto risco, zero ganho funcional para o Trabalho 1).
- **Consequências**:
  - `.env`/`.env.example`: `JARVIS_LLM_BASE_URL`, `JARVIS_LLM_MODEL`,
    `JARVIS_LLM_API_KEY` apontam para o Qwen.
  - `gemma_client.py::stream_chat` ganhou o fallback `delta → message.content`.
  - `chat_view.py`: efeito de digitação para o evento `final`.
  - `ruff` limpo, `pytest` 115 passed / 3 skipped, smoke live (Qwen) 3/3.
  - **Dívida de naming**: nome "Gemma" permanece em CLAUDE.md (§3), `GemmaClient`,
    `gemma_client.py` e ADRs anteriores — intencional e documentado aqui.
- **Relacionada a**: [D-014](#d-014), [D-017](#d-017), [D-018](#d-018).

---

## D-029 — Ingestão: guarda de qualidade de texto (rejeita PDF ilegível)

- **Data**: 2026-06-13.
- **Contexto**: durante a preparação da análise de erros (Trabalho 2), a inspeção
  do índice revelou que **`The_Origins_of_Logistic_Regression.pdf`** havia sido
  ingerido como **383 chunks de lixo `(cid:N)`** — 0% de palavras reais. O PDF usa
  fontes **sem mapa de caracteres (sem ToUnicode CMap)**; `pdfplumber`, `pdfminer`
  e `PyMuPDF` (testados) **todos** devolvem `(cid:N)`/caracteres de controle. A
  única guarda existente em `ingest_document` era `if not text.strip()`, que não
  pega lixo **não-vazio**. Resultado: embeddings de ruído poluíam o índice e
  desviavam o retrieval (perguntas sobre esse doc retornavam trechos de outros).
  Isso **violava a própria política do CLAUDE.md §8** ("PDF sem texto extraível →
  skipar, logar warning, continuar").
- **Decisão**: adicionar um **guarda de qualidade** após a extração em
  `src/rag/ingest.py`. Métrica `real_word_ratio(text)` = fração de tokens que são
  palavras reais (`^[A-Za-zÀ-ÿ]{2,}$`). Se `< MIN_REAL_WORD_RATIO` (0.25), recusa
  com `status="error"`, `reason="unreadable_text"` e `logger.warning`, cumprindo a
  §8. Calibrado contra o dataset: docs bons 0.53-0.69; lixo 0.00 → corte em 0.25
  com folga, **sem** rejeitar docs parcialmente sujos (figuras/fórmulas).
- **Razão**: P5/§8 (erros tratados, nunca silenciosos) + qualidade de RAG (índice
  não envenenado). Métrica simples e explicável ("o aluno deve explicar o código").
- **PyMuPDF rejeitado como dependência**: testado, **não** recupera este arquivo
  (fonte sem mapa de caracteres → recuperável só por OCR). Não foi adicionado ao
  `pyproject`/`uv.lock` para preservar reprodutibilidade (P7).
- **Consequências**:
  - `ingest.py`: funções públicas `real_word_ratio` e `is_readable_text` + checagem
    no passo 3b de `ingest_document`; constante `MIN_REAL_WORD_RATIO`.
  - Dataset re-indexado: doc 4 (383 chunks-lixo) removido; índice agora
    **4 documentos / 119 chunks / 119 vetores**, consistente e sem lixo 100%.
  - Novos testes `tests/unit/test_ingest_quality.py` (5). Suíte: **127 passed,
    3 skipped**, `ruff` limpo.
  - **Pendência de dataset**: `The_Origins` precisa de **OCR** ou de uma **cópia
    com texto selecionável** para voltar ao índice (requisito de ≥10 docs do
    enunciado). Decisão de dados a tratar antes da entrega.
- **Registro de análise de erros (Trabalho 2)**: esta é a **Falha 1** (recuperação/
  ingestão), agora **corrigida**. Falhas deixadas **em aberto** para o relatório:
  (2) threshold filtra só o melhor chunk, não cada um (`retrieve.py:62`);
  (3) sem aterramento obrigatório — LLM pode responder do próprio conhecimento sem
  chamar `buscar_material_rag` (geração); (4) sem leitura por documento / pedidos
  estruturais ("índice", "resuma o doc X") inviáveis. Reserva: duplicação por
  overlap; healthcheck só no boot.
- **Relacionada a**: [D-005](#d-005), [D-021](#d-021), [D-022](#d-022).

---

## D-030 — Camada `learning/`, client LLM default e relatório `.docx` (Spec 007)

- **Data**: 2026-06-13.
- **Contexto**: a Spec 007 (Melhorias de Aprendizado — prova eletrônica + dificuldades/
  plano) precisa de orquestração que combina **LLM + RAG + domínio**. Isso não cabe
  em `domain/` (só importa `core/`) nem em `tools/` (não pode importar `llm/`, para
  não fechar o ciclo `llm/agent ↔ tools/registry`). Além disso, uma tool acionada
  pela LLM precisa do `GemmaClient`, mas o contrato de handler é `handler(args)`
  (`agent.py:216`) e o `AppState.gemma` vive em `src/ui/` (camada proibida para
  `tools/`). Auditoria da spec (spec-auditor) levantou ambos como bloqueadores.
- **Decisão 1 — nova camada `src/learning/`**: orquestra geração/correção/coach.
  Pode importar `core`, `domain`, `rag`, `llm`; é importada por `ui/` e `tools/`.
  `src/domain/learning/` (models + repo) permanece puro (só `core/`). CLAUDE.md
  §4/§4.1 atualizados.
- **Decisão 2 — client LLM default** (`src/llm/client.py`): `set_default_client`/
  `get_default_client` (singleton de processo, no estilo `get_settings`/`get_embedder`),
  setado no boot em **`src/ui/app.py`** (onde o `GemmaClient` é criado, ~linha 36).
  `learning/*` recebe `gemma` opcional e cai no default. Assim `tools/tool_learning`
  importa **apenas `learning/`** (não `llm/` nem `ui/`) — §4.1 preservado
  literalmente; sem ciclo (`gemma_client` importa só `core`+`llm.{exceptions,types}`,
  verificado). A UI e os testes continuam injetando o client explicitamente.
- **Decisão 3 — leitura por documento** (`rag.get_document_chunks`): lê os chunks de
  UM documento em ordem (sem embeddings). Habilita a geração de provas e a tool
  `ler_documento`, e **corrige a Falha 4** da análise de erros (recuperação sem
  escopo por documento — "leia/resuma o documento X / me dê o índice").
- **Decisão 4 — dependência `python-docx`**: adicionada ao `pyproject` para gerar o
  relatório acadêmico Word das 2 funcionalidades (RF-007.10). Uso pontual de
  entrega, não afeta o runtime do app. Lockfile re-gerado (`uv lock`). Alternativa
  rejeitada: gerar `.docx` à mão (frágil) ou só `.md` (não cumpre "formato Word").
- **Modelo de dados** (migration 005): `quizzes`, `quiz_documents` (N:N de fontes),
  `quiz_questions` (mc|open, `source_chunk_id` p/ aterramento), `quiz_attempts`
  (nota 0–10), `quiz_answers` (pontos + feedback). `PRAGMA user_version = 5`.
- **Correção**: MC determinística; dissertativa via **LLM-juiz** com rubrica →
  nota **sugerida** (0–1) + feedback. Nota final = Σpontos/Σmax × 10.
- **Consequências**: +camada `learning/`, +`domain/learning/`, +`llm/client.py`,
  +`llm/json_utils.py` (parsing extraído do agent, retrocompat preservada),
  +`rag.get_document_chunks`, +`tools/tool_learning.py` (5 tools → **15 no total**),
  +`ui/dialogs/exam_dialog.py` (menu "+"), +migration 005, +`python-docx`.
  `pytest` **162 passed / 3 skipped**, `ruff` limpo.
- **Relacionada a**: [D-007](#d-007), [D-013](#d-013), [D-019](#d-019),
  [D-022](#d-022), [D-029](#d-029).

---

## D-031 — Dependências de desenvolvimento em `[dependency-groups]` (PEP 735)

- **Data**: 2026-10-06.
- **Contexto**: ruff/pytest/mypy estavam em `[project.optional-dependencies] dev`.
  O `uv sync` (comando de setup do CLAUDE.md, P7) não instala extras opcionais, então
  uma venv nova ficava sem ruff e sem pytest — o guia de estilo não era verificável
  sem lembrar de `--extra dev` (achado da revisão clean code, Spec 008).
- **Decisão**: mover o grupo para `[dependency-groups] dev`. O uv instala o grupo
  `dev` por padrão no `uv sync`. `uv.lock` regenerado.
- **Razão**: P7 (reprodutibilidade) e padronização de estilo verificada por
  ferramenta (cap. 2, *Engenharia de Software Moderna*).
- **Alternativas consideradas**: documentar `uv sync --extra dev` (rejeitada:
  depende de quem lê lembrar a flag).
- **Consequências**: README e STATUS passam a instruir só `uv sync`. Para uma
  instalação só de runtime: `uv sync --no-dev`.
- **Relacionada a**: [D-011](#d-011), [D-019](#d-019).

---

## Próximas decisões pendentes (futuras Specs ou Trabalho 2)

- Idioma do dataset (PT-BR vs misto) — para teste de retrieval multilingual.
- Multi-usuário (Spec 000 excluiu, mas relevante para Trabalho 2).
- Funcionalidade 3.4 (planejamento de estudos) — Trabalho 2.
- Funcionalidades de aprendizado interativas (active recall, geração de
  exercícios) — Trabalho 2.
- Avaliação ≥10 perguntas + análise de erros ≥3 falhas — Trabalho 2.
- Streaming na restauração de sessão (atualmente carrega tudo de uma vez).
- Drag-and-drop no calendário para reagendar (não-bloqueante).
