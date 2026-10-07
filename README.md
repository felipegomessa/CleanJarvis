# JARVIS Acadêmico

> Assistente pessoal inteligente para estudantes universitários.
> **Trabalho 1 — Disciplina de Inteligência Artificial**
> Universidade Federal de Mato Grosso do Sul (UFMS) · Faculdade de Computação (FACOM) · 2026

**Autor**: Felipe Sá

---

## Visão geral

JARVIS Acadêmico integra **Retrieval-Augmented Generation (RAG)**, **Tool Calling**
e um **LLM Gemma 12B** (servido via endpoint da LIA UFMS) para auxiliar o estudante
em três frentes:

1. **Consulta a materiais de estudo** — perguntas sobre PDFs, textos e anotações indexados.
2. **Agenda acadêmica** — aulas, provas, trabalhos e outros eventos com data/hora.
3. **Lista de tarefas** — itens com prazo, prioridade e status de conclusão.

A LLM **decide autonomamente** quais ferramentas chamar a partir da pergunta do usuário,
e **cada chamada é auditada** em SQLite (entrada, saída, status, duração).

A interface é uma UI web estilo ChatGPT (dark mode), com calendário unificado de
eventos+tarefas inspirado no Google Calendar, persistência de conversas, e
gerenciamento de materiais via upload.

---

## Funcionalidades implementadas

| Funcionalidade | Descrição | Status |
|---|---|---|
| **3.1 RAG** | Indexação de PDF/TXT/MD em chunks, busca vetorial via embeddings, geração com contexto e citações `[Doc N]` | ✅ |
| **3.2 Agenda** | CRUD completo de eventos (criar/consultar/editar/remover) com tipo (aula/prova/trabalho/outro), local, intervalo de datas | ✅ |
| **3.3 Tarefas** | CRUD de tarefas com prazo, prioridade (normal/alta/urgente) e status pendente/concluída | ✅ |
| **Tool Calling** | 10 ferramentas registradas; LLM escolhe via prompt-based JSON; agent loop com retry | ✅ |
| **Auditoria** | Toda chamada de tool persistida em `tool_call_logs` (consultável via UI) | ✅ |
| **GUI moderna** | ChatGPT-style: sidebar colapsável, chat central, dialogs modais, calendário unificado | ✅ |
| **Persistência de conversas** | Sessões e mensagens em SQLite; restauração via sidebar "Recentes" | ✅ |

### Ferramentas (tools) disponíveis à LLM

| Tool | Função |
|---|---|
| `buscar_material_rag` | Busca semântica em chunks indexados; retorna o texto completo dos trechos relevantes + instrução de grounding para citar `[Doc N]` |
| `consultar_agenda` | Consulta eventos por intervalo de datas ou palavras-chave (hoje/amanhã/semana) |
| `adicionar_evento` | Cria novo evento (título, data/hora, tipo, local, descrição) |
| `editar_evento` | Edita um evento existente (localizado por `event_id` ou `titulo`): horário, local, tipo, título |
| `remover_evento` | Remove/cancela um evento (localizado por `event_id` ou `titulo`) |
| `listar_tarefas` | Lista tarefas filtradas por status/prioridade |
| `adicionar_tarefa` | Cria nova tarefa (título, prazo, prioridade) |
| `concluir_tarefa` | Marca tarefa como concluída (por `task_id` ou `titulo`) |
| `listar_materiais` | Lista documentos indexados (título, tipo, contagem de chunks) |
| `consultar_calendario` | Consulta unificada de eventos + tarefas (com prazo) num intervalo de datas |

---

## Tecnologias e ferramentas

### Linguagem e runtime
- **Python 3.12**
- **uv** (Astral) — gerenciamento de dependências e venv

### LLM e Tool Calling
- **Gemma 12B** servido em endpoint OpenAI-compatible (LIA UFMS)
- **openai** (cliente AsyncOpenAI) — comunicação com o endpoint
- **tenacity** — retry com backoff exponencial para falhas transitórias (timeout, 5xx, 429)
- Tool calling implementado via **prompt-based JSON** (modelo retorna `{"tool":"...", "args":{...}}` ou `{"reply":"..."}`)
- **Agent loop próprio** — coordena múltiplas chamadas de tool em sequência até a resposta final, com reparo de JSON malformado

### RAG (Retrieval-Augmented Generation)
- **sentence-transformers** com modelo `intfloat/multilingual-e5-small` — embeddings densos locais (384 dim)
- **sqlite-vec** — extensão SQLite para busca vetorial (vetores armazenados na própria base)
- **pdfplumber** — extração de texto de PDFs
- **Recursive Character Splitter próprio** — chunking ~800 chars com overlap 150; cada chunk é uma fatia contígua exata do texto original (overlap real a partir da fonte)

### Persistência e dados
- **SQLite** (via `sqlite3` nativo do Python) — base única do projeto
- **Migrations forward-only** versionadas via `PRAGMA user_version` + arquivos `.sql` numerados
- Modo **WAL** + `foreign_keys ON`
- **Pydantic v2** + **pydantic-settings** — validação de modelos e carregamento de `.env`

### Interface (GUI)
- **NiceGUI 3.x** (servidor Python + Quasar/Vue no browser)
- CSS customizado (sem Bootstrap — Quasar já está embutido no NiceGUI)
- Fonte **Inter** (Google Fonts)
- Locale Quasar PT-BR injetado para calendários e datepickers

### Observabilidade
- **loguru** — logging estruturado (console colorizado + arquivo rotativo diário em `logs/`)
- Tabela SQLite **`tool_call_logs`** — cada tool call grava input/output JSON completo, duração, status, exceção

### Qualidade
- **pytest** + **pytest-asyncio** — testes unitários e de integração
- **ruff** — lint + format (regras E, F, W, I, B, UP, SIM, RUF)
- **mypy** (não-estrito) — checagem de tipos opcional

### Ferramentas de IA no desenvolvimento
- **Claude Code** — assistente de desenvolvimento utilizado para gerar código a partir das especificações no padrão **SDD (Spec-Driven Development)**: para cada funcionalidade, escreveu-se primeiro `requirements.md`, `design.md` e `tasks.md` com critérios de aceitação verificáveis; só então o Claude Code gerou o código correspondente, revisado pelo autor antes da integração.

---

## Arquitetura

### Visão em camadas

```
┌─────────────────────────────────────────────────────────────┐
│  src/ui/                       (NiceGUI: páginas + dialogs) │
│  ├── app.py                    (entry point HTTP)           │
│  ├── theme.py                  (CSS global + locale PT-BR)  │
│  ├── components/               (sidebar, chat, calendário)  │
│  └── dialogs/                  (materiais, tarefas, etc.)   │
└──────────────────┬──────────────────────────────────────────┘
                   │ usa
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  src/llm/                      (cliente LLM + agent loop)   │
│  ├── gemma_client.py           (AsyncOpenAI + retry)        │
│  └── agent.py                  (loop tool-call → response)  │
└──────────────────┬──────────────────────────────────────────┘
                   │ chama
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  src/tools/                    (ferramentas registradas)    │
│  ├── registry.py               (catálogo + system prompt)   │
│  └── tool_*.py                 (1 arquivo por tool)         │
└─────────┬─────────────────────────────────┬─────────────────┘
          │ delega para                     │ delega para
          ▼                                 ▼
┌─────────────────────────┐    ┌──────────────────────────────┐
│  src/domain/            │    │  src/rag/                    │
│  ├── agenda/            │    │  ├── ingest.py               │
│  ├── tasks/             │    │  ├── chunk.py                │
│  ├── chat/              │    │  ├── embed.py                │
│  └── calendar_view/     │    │  ├── retrieve.py             │
│  (regras de negócio)    │    │  └── prompt.py               │
└──────────┬──────────────┘    └──────────────┬───────────────┘
           │                                  │
           └────────────────┬─────────────────┘
                            │ persiste em
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  src/core/                     (infraestrutura comum)       │
│  ├── db.py                     (SQLite + sqlite-vec + WAL)  │
│  ├── config.py                 (settings via .env)          │
│  ├── logging.py                (loguru)                     │
│  ├── health.py                 (estado LLM ONLINE/OFFLINE)  │
│  └── migrations/*.sql          (001 → 004 + VIEW)           │
└─────────────────────────────────────────────────────────────┘
```

**Regras de importação** (sem ciclos):
- `ui/` → pode importar de `domain/`, `tools/`, `llm/`, `rag/`, `core/`
- `tools/` → pode importar de `domain/`, `rag/`, `core/`
- `llm/` → pode importar de `tools/`, `core/`
- `rag/` → pode importar de `core/`
- `domain/` → pode importar de `core/`
- `core/` → não importa nada interno (apenas stdlib + libs externas)

### Fluxo de uma pergunta no chat

```
1. Usuário digita: "quais minhas tarefas pendentes?"
       │
       ▼
2. UI (chat_view.py) cria/recupera sessão, persiste a mensagem em chat_messages
       │
       ▼
3. AgentLoop.respond() envia ao LLM:
   [system prompt + catálogo de tools] + histórico + mensagem
       │
       ▼
4. LLM retorna JSON: {"tool": "listar_tarefas", "args": {"status": "pending"}}
       │
       ▼
5. AgentLoop executa a tool → consulta src/domain/tasks/repo.py → SQLite
       │
       ▼
6. Resultado da tool é logado em tool_call_logs e devolvido à LLM como "tool_result"
       │
       ▼
7. LLM gera resposta final em linguagem natural: {"reply": "Você tem 3 tarefas..."}
       │
       ▼
8. UI renderiza a resposta + chips clicáveis com Entrada/Saída de cada tool call
```

### Modelo de dados (SQLite)

**4 migrations forward-only** (versão atual: `user_version = 4`):

| # | Arquivo | Contém |
|---|---|---|
| 001 | `001_initial.sql` | `documents`, `chunks`, `events`, `tasks`, `tool_call_logs` + 6 índices |
| 002 | `002_rag.sql` | `content_hash` em documents, tabela virtual `chunk_vecs` (sqlite-vec) |
| 003 | `003_chat.sql` | `chat_sessions`, `chat_messages` (com posições ordenadas) |
| 004 | `004_calendar_view.sql` | VIEW `calendar_items_view` (UNION ALL de events + tasks) |

**7 tabelas + 1 tabela virtual + 1 VIEW**:
- `documents` — metadados dos arquivos indexados
- `chunks` — pedaços textuais dos documentos
- `chunk_vecs` (virtual, sqlite-vec) — vetores dos chunks para busca semântica
- `events` — eventos da agenda
- `tasks` — tarefas
- `chat_sessions`, `chat_messages` — histórico de conversas
- `tool_call_logs` — auditoria de cada chamada de tool
- `calendar_items_view` — visão unificada de eventos + tarefas (com `due_at`) para o calendário

---

## Estrutura de pastas

```
.
├── README.md                       Este arquivo
├── pyproject.toml                  Configuração do projeto (uv, ruff, pytest, mypy)
├── uv.lock                         Lockfile reproduzível
├── .env.example                    Template de variáveis (commitado)
├── .env                            Variáveis reais (NÃO commitado — contém token LLM)
│
├── src/                            Código-fonte
│   ├── main.py                     Entry point CLI (sobe a UI)
│   ├── core/                       Infraestrutura comum
│   │   ├── config.py               Settings via pydantic-settings (.env)
│   │   ├── db.py                   SQLite + sqlite-vec + WAL + log_tool_call
│   │   ├── health.py               Estado LLM ONLINE/OFFLINE
│   │   ├── logging.py              loguru (console + arquivo rotativo)
│   │   └── migrations/             001_initial, 002_rag, 003_chat, 004_calendar_view
│   ├── llm/                        Comunicação com o LLM
│   │   ├── gemma_client.py         AsyncOpenAI + tenacity (retry exponencial)
│   │   ├── agent.py                Loop tool-call → resposta com persistência opcional
│   │   ├── exceptions.py           LLMAuthError, LLMTimeoutError, LLMServerError, etc.
│   │   └── types.py                Modelos Pydantic de chat messages
│   ├── rag/                        Retrieval-Augmented Generation
│   │   ├── ingest.py               Pipeline de ingestão (PDF/TXT/MD)
│   │   ├── chunk.py                Recursive Character Splitter
│   │   ├── embed.py                sentence-transformers (lazy load)
│   │   ├── retrieve.py             Busca por similaridade no sqlite-vec
│   │   ├── prompt.py               Construção do prompt RAG com contexto
│   │   └── populate.py             CLI de ingestão em lote da pasta data/
│   ├── domain/                     Regras de negócio (camada de domínio)
│   │   ├── agenda/                 models, repo, service
│   │   ├── tasks/                  models, repo, service
│   │   ├── chat/                   sessões e mensagens persistidas
│   │   └── calendar_view/          Leitura unificada eventos+tarefas (via VIEW SQL)
│   ├── tools/                      10 tools + registry
│   │   ├── registry.py             Catálogo + construção do system prompt
│   │   ├── tool_rag.py             buscar_material_rag
│   │   ├── tool_agenda.py          consultar_agenda, adicionar_evento, editar_evento, remover_evento
│   │   ├── tool_tasks.py           listar_tarefas, adicionar_tarefa, concluir_tarefa
│   │   ├── tool_materials.py       listar_materiais
│   │   └── tool_calendar.py        consultar_calendario (unificado)
│   └── ui/                         Interface NiceGUI
│       ├── app.py                  @ui.page("/") + left_drawer + chat central
│       ├── theme.py                CSS global, fonte Inter, locale Quasar PT-BR
│       ├── state.py                Singleton de estado (gemma, agent, sessão, sidebar)
│       ├── components/
│       │   ├── sidebar.py          Sidebar 260px ↔ 60px (mini-mode)
│       │   ├── chat_view.py        Área central: mensagens + input pill
│       │   ├── prompt_input.py     Input com histórico via setas ↑/↓
│       │   ├── tool_call_card.py   Chip discreto + dialog modal com I/O
│       │   ├── greeting.py         Saudação dinâmica por horário
│       │   ├── date_picker.py      Helper dd/mm/aaaa em PT-BR
│       │   ├── calendar_colors.py  Paleta (primária por tipo + secundária por kind)
│       │   ├── calendar_month_view.py  Grid 7×6 do mês
│       │   ├── calendar_mini.py    Mini-calendário lateral
│       │   └── calendar_wizard.py  Wizard "Evento vs Tarefa" de criação
│       └── dialogs/
│           ├── materials_dialog.py     Upload + lista de documentos indexados
│           ├── calendar_dialog.py      Calendário unificado fullscreen
│           ├── tasks_list_dialog.py    Lista de tarefas modo to-do
│           └── audit_dialog.py         Pesquisa em tool_call_logs
│
├── tests/                          Testes pytest
│   ├── unit/                       Testes unitários (chunking, prompt, greeting, cores, etc.)
│   └── integration/                Testes contra SQLite real + smoke do agent loop
│
├── data/                           Dataset RAG (PDFs, .txt, .md indexáveis)
│   ├── README.md                   Inventário do dataset
│   └── uploads/                    Arquivos enviados via UI (criado em runtime)
│
├── scripts/                        Utilitários de linha de comando
│   └── seed_demo.py                Popula agenda + tarefas + ingere data/ (idempotente)
│
├── spec/                           Documentação de design por feature
│   ├── 000-foundation/             Decisões transversais
│   ├── 001-core-infra/             DB, LLM client, logging, config
│   ├── 002-rag/                    Indexação + retrieval
│   ├── 003-agenda/                 CRUD de eventos
│   ├── 004-tasks/                  CRUD de tarefas
│   ├── 005-tool-calling/           Tools + agent loop
│   └── 006-gui/                    Frontend NiceGUI
│
├── img/                            Logos do projeto
│   ├── jarvis-logo-completo.png    (140px — sidebar expandida)
│   └── jarvis-logo-menor.png       (32px — sidebar mini)
│
└── logs/                           Saída do loguru (rotação diária)
    └── jarvis-AAAA-MM-DD.log
```

---

## Pré-requisitos

- **Python 3.12** (uma versão entre 3.12.0 e 3.12.x; 3.13 não é suportado por dependências do `sqlite-vec`)
- **uv** instalado globalmente (`pip install uv` ou via instalador oficial em https://docs.astral.sh/uv/)
- **Token de acesso ao endpoint da LLM Gemma** fornecido pela LIA UFMS
- Sistema operacional: Windows, macOS ou Linux

---

## Instalação

```powershell
# 1. Clonar o repositório
git clone <url-do-repo>
cd Trabalho1

# 2. Sincronizar o ambiente virtual e instalar dependências (inclui dev)
python -m uv sync

# 3. Configurar variáveis de ambiente
copy .env.example .env       # Windows
# ou
cp .env.example .env         # Linux/macOS

# 4. Editar .env e preencher o token:
#    JARVIS_LLM_API_KEY=<seu_token>
```

A primeira execução fará download automático do modelo de embeddings (~470 MB),
que ficará em cache local (`~/.cache/huggingface/`) e não será baixado novamente.

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `JARVIS_LLM_API_KEY` | *(obrigatório)* | Token de acesso ao endpoint Gemma LIA UFMS |
| `JARVIS_LLM_BASE_URL` | `https://chat.lia.ufms.br/v1` | Endpoint OpenAI-compatible |
| `JARVIS_LLM_MODEL` | `gemma-3-12b` | Identificador do modelo |
| `JARVIS_DB_PATH` | `./data/jarvis.db` | Caminho do banco SQLite |
| `JARVIS_LOG_LEVEL` | `INFO` | Nível de log (DEBUG, INFO, WARNING, ERROR) |
| `JARVIS_LOG_DIR` | `./logs` | Diretório de arquivos de log |
| `JARVIS_UI_HOST` | `127.0.0.1` | Host da UI |
| `JARVIS_UI_PORT` | `8080` | Porta da UI |
| `JARVIS_UI_DARK` | `true` | Modo escuro (sempre true nesta versão) |

Ver `.env.example` para a lista completa.

### Popular dados de demonstração (opcional)

Para deixar a agenda e a lista de tarefas com conteúdo realista (útil para a
demo e os testes) e indexar o dataset da pasta `data/`:

```powershell
# Agenda + tarefas (datas relativas a hoje) + ingestão de ./data
.venv\Scripts\python.exe -m scripts.seed_demo

# Apenas agenda + tarefas (sem ingerir documentos)
.venv\Scripts\python.exe -m scripts.seed_demo --no-ingest
```

O script é **idempotente** (marca o que cria com `[seed-demo]` e nunca apaga
dados criados pelo usuário) — pode rodar quantas vezes quiser.

---

## Como executar

```powershell
# Windows
.venv\Scripts\python.exe -m src.main

# Linux / macOS
.venv/bin/python -m src.main

# Ou via script entry-point definido no pyproject.toml:
python -m uv run jarvis
```

A UI abre em **http://127.0.0.1:8080**.

### Fluxo típico de uso

1. **Abrir o navegador** em http://127.0.0.1:8080
2. **Sidebar à esquerda**: botão "Novo chat", lista de conversas recentes (clique restaura uma sessão), toggle de colapso (260px ↔ 60px)
3. **Chat central**: digite a pergunta no input pill. Histórico de prompts acessível via setas ↑/↓
4. **Botão "+" no input** abre 4 ações:
   - **Enviar material** — upload de PDF/TXT/MD ou indexação em lote da pasta `data/`
   - **Calendário** — visão mensal unificada de eventos + tarefas, com wizard de criação
   - **Lista de tarefas** — modo to-do com checkboxes
   - **Pesquisar auditoria** — tabela com todas as chamadas de tool
5. **Pergunte**: a LLM decide se responde direto ou chama uma ou mais tools
6. **Chips de tool call** aparecem abaixo da resposta — clique para ver Entrada/Saída em JSON formatado

### Exemplos de perguntas que disparam tools

| Pergunta | Tool esperada |
|---|---|
| "Quais minhas tarefas pendentes?" | `listar_tarefas` |
| "O que tenho no calendário esta semana?" | `consultar_calendario` |
| "Adiciona prova de IA dia 30/05 às 14h, sala 5" | `adicionar_evento` |
| "Anota pra eu estudar Naive Bayes até quinta, urgente" | `adicionar_tarefa` |
| "Resume o material sobre redes neurais" | `buscar_material_rag` |
| "Lista os materiais que tenho indexados" | `listar_materiais` |

---

## Como testar

### Suite completa de testes

```powershell
# Windows
.venv\Scripts\python.exe -m pytest -q

# Linux/macOS
.venv/bin/python -m pytest -q
```

Saída esperada: **~115 passed, 3 skipped** (os 3 skipped são smoke tests do LLM real, executados opt-in).

### Apenas testes unitários (rápidos)

```powershell
.venv\Scripts\python.exe -m pytest tests/unit -q
```

### Testes de integração (com SQLite temporário real)

```powershell
.venv\Scripts\python.exe -m pytest tests/integration -q
```

### Smoke test do LLM (chama o endpoint real — exige token válido)

```powershell
$env:JARVIS_RUN_LIVE_LLM=1; .venv\Scripts\python.exe -m pytest tests/integration/test_gemma_smoke.py -q
```

### Linting + checagem de estilo

```powershell
.venv\Scripts\python.exe -m ruff check .
```

### Checagem de tipos (opcional)

```powershell
.venv\Scripts\python.exe -m mypy src --ignore-missing-imports
```

### Cobertura

```powershell
.venv\Scripts\python.exe -m pytest --cov=src --cov-report=term-missing
```

### Smoke test manual da UI

1. `python -m src.main`
2. Abrir http://127.0.0.1:8080 (Ctrl+Shift+R para hard reload se necessário)
3. Verificar:
   - Saudação central varia entre "Bom dia/tarde/noite" e variações neutras
   - Sidebar alterna entre expandida (260px) e mini (60px) via botão
   - "+" abre menu com 4 opções
   - Calendário mostra eventos (cyan) e tarefas (pink) distinguíveis visualmente
   - Materiais aparecem em cards uniformes após upload
   - Chips de tool call aparecem abaixo da resposta quando a LLM usa alguma ferramenta

---

## Autoria

Trabalho desenvolvido pelo acadêmico **Felipe Sá**
para a disciplina de Inteligência Artificial
da Universidade Federal de Mato Grosso do Sul (UFMS),
Faculdade de Computação (FACOM), 2026.

## Licença

MIT (uso acadêmico).
