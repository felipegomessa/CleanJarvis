# STATUS — JARVIS Acadêmico (Onde Paramos)

> **Atualizado em**: 2026-10-06
> **Versão da UI**: 2.0 — ChatGPT-style dark + Calendário unificado estilo Google Calendar.

## 🧹 ONDE PARAMOS (2026-10-06) — Spec 008 (Refatoração Clean Code)

**Spec 008 implementada** (cap. 2 "Código Limpo", *Engenharia de Software Moderna*):
- **Bug corrigido** no agent loop: saída de tool não serializável causava
  `NameError` (1ª tool) ou reenviava à LLM a saída da tool anterior. Agora vira
  `status="error"` coerente em evento/log/sessão/observação.
- **Re-ingestão transacional** (nota em D-021): falha de extração/embedding/INSERT
  não apaga mais o documento antigo.
- `AgentLoop.respond` 190 → 38 linhas; `ingest_document` 167 → 27 linhas.
- Exceções específicas (`audit_dialog`, `json_utils`), constantes nomeadas no lugar
  de números mágicos, nomes locais claros.
- **D-031**: dev deps em `[dependency-groups]` — `uv sync` já instala ruff/pytest/mypy.
- `pytest` **185 passed / 3 skipped** (+18 testes), `ruff` limpo.

## 🆕 ONDE PARAMOS (2026-06-13) — Spec 007 (Aprendizado / Trabalho 2)

**Erro 1 (PDF ilegível) corrigido** (ADR D-029): guarda de qualidade na ingestão
rejeita lixo `(cid:N)`; dataset re-indexado (4 docs / 119 chunks, sem lixo).

**Spec 007 — Melhorias de Aprendizado: implementada e testada offline.** Entrega o
requisito obrigatório do T2 (≥2 funcionalidades, ≥1 interativa):
1. **Prova eletrônica** (interativa): gera questões MC + dissertativas de vários
   documentos, usuário responde, sistema corrige (MC determinística + dissertativa
   por LLM-juiz, nota sugerida) e dá **nota 0–10**.
2. **Dificuldades + plano de estudos**: agrega desempenho por tópico, recomenda
   revisão (RAG) e monta plano com botão "Adicionar à agenda" (adianta a Func. 3.4).

- **Camadas novas** (D-030): `src/domain/learning/` (models+repo), `src/learning/`
  (generator/grader/coach/service), `src/llm/{client,json_utils}.py`,
  `rag.get_document_chunks` (corrige **Falha 4**), `src/tools/tool_learning.py`
  (5 tools → **15 no total**), `src/ui/dialogs/exam_dialog.py` (menu "+").
- **Migration 005** (v5): quizzes/quiz_documents/quiz_questions/quiz_attempts/quiz_answers.
- **Dep nova**: `python-docx` (relatório Word). `pytest` **162 passed / 3 skipped**,
  `ruff` limpo.

**Feito (2026-06-13/14)**: Spec 007 implementada + commit/push (`672cfa1`); dataset
ampliado para **11 docs (10 indexados)** e reorganizado (`data/Livros/` versionado,
`data/uploads/` gitignored); relatório Word gerado (`scripts/gen_relatorio_aprendizado.py`,
saída em `docs/` que é gitignored); upload e ingestão corrigidos.

**Índice `.db` pré-construído — CONCLUÍDO** (commit `3c23c2e`, pushado):
`data/jarvis.db` (25 MB) versionado com **10 docs / 9.502 chunks** (The_Origins
rejeitado) + demo de **4 eventos e 4 tarefas**. `.gitignore` com exceção
`!data/jarvis.db`. Permite rodar o sistema **sem reindexar** (turnkey p/ correção).
Regenerável: apagar `data/jarvis.db*` → `apply_migrations` +
`ingest_directory(Path('data'), recursive=True)` + `seed_demo --no-ingest`.

**Pendências humanas**:
- **Gravar vídeo ≤3min do T2** (prova + plano; o do T1 só cobria 3.1/3.2/3.3).
- Inserir prints no relatório Word (seção 7).
- (Por último) relatórios Word de auditoria do enunciado + análise de erros.

## 🧭 ONDE PARAMOS (2026-06-12, ~21h) — ler isto primeiro

**Resumo de 1 linha**: Trabalho 1 funcionalmente completo (3.1/3.2/3.3 + 10 tools),
dataset importado e indexado, todas as melhorias do `PLANO_MELHORIAS_T1.md`
implementadas; **falta validar o chat com a LLM real (endpoint estava em 502)** e
gravar o vídeo.

- **Ambiente**: `uv sync --extra dev` ok. `pytest` → **115 passed, 3 skipped**.
  `ruff check .` limpo. Python 3.12.13 no `.venv`.
- **Dataset (C1)**: ✅ 10 PDFs em `data/` (importados do Drive do professor).
  **5 indexados** no RAG (Artigos + Material de Aula) = **502 chunks**; os 5
  livros em `data/Livros/` são acervo (gitignored, ~88 MB, recuperáveis pelo
  link no `data/README.md`). Recuperação validada (TF-IDF/KNN/chunking/regressão).
- **Melhorias**: A1+A2 (RAG grounding), A3 (Fontes na UI), M1 (D-027), M2
  (concluir por título), M3 (`scripts/seed_demo.py`), B1 (chunking fiel), B2
  (editar/remover evento) — **todas implementadas e verdes**.
- **Demo data**: `seed_demo --no-ingest` rodado → 4 eventos + 4 tarefas.
- **App**: sobe ok em http://127.0.0.1:8080 (DB v4, sqlite-vec ok). **PORÉM** o
  endpoint Gemma da LIA (`https://llm.liaufms.org/...`) estava retornando **502
  Bad Gateway em todos os caminhos** (queda do servidor da LIA, não é a key nem
  config). Logo, o app entrou em **modo degradado** (chat/RAG-geração off). A key
  ESTÁ no `.env`.

**Próximos passos (quando a LIA voltar)**:
1. Subir o app (`python -m src.main`) e confirmar **LLM ONLINE** no log de boot.
2. Validar 3.1 ponta a ponta: perguntar "explique regressão logística", "o que é
   TF-IDF", "como funciona o KNN" → conferir resposta + citações `[Doc N]` +
   bloco "Fontes". (Já adianta a avaliação ≥10 perguntas do Trab. 2.)
3. Gravar o **vídeo ≤3 min** (arquitetura + sistema funcionando).
4. `git push` para o GitHub (repo já inicializado e commitado localmente).

> Obs.: o healthcheck roda só no boot — se a LIA voltar com o app aberto,
> **reinicie o app** para reabilitar o chat.

## Rodada de melhorias 2026-06-12 (qualidade de RAG + robustez)

Ver o plano vivo em [`PLANO_MELHORIAS_T1.md`](PLANO_MELHORIAS_T1.md). Implementado
e validado (`ruff` limpo, `pytest` **115 passed, 3 skipped**):

- **Ambiente reconstruído** (`uv sync --extra dev`) — baseline verde restaurado.
- **RAG grounding (A1+A2)**: `buscar_material_rag` agora envia o **texto completo**
  do chunk (antes truncava em 400 chars), numera `[Doc N]` e inclui instrução de
  grounding; `top_k` 5→4; regra 7 de citação no system prompt (`registry.py`).
- **Fontes na UI (A3)**: bloco "Fontes" sob a resposta (`chat_view.py`).
- **Caminho RAG único (M1 / [D-027](decisions.md#d-027))**: removido o
  `src/rag/pipeline.py` órfão + tipos `Citation`/`RagResponse`.
- **Chunking fiel (B1)**: `chunk_text` reescrito — cada chunk é fatia contígua
  exata da fonte, com offsets corretos e overlap real (+2 testes).
- **Concluir tarefa por título (M2)**: `concluir_tarefa` aceita `task_id` OU
  `titulo` (+5 testes).
- **CRUD de evento por chat (B2)**: novas tools `editar_evento` e `remover_evento`
  (por `event_id` ou `titulo`) — **total de 10 tools** (+4 testes).
- **Seed de demonstração (M3)**: `scripts/seed_demo.py` idempotente (agenda +
  tarefas + ingestão de `data/`), pronto para rodar.

## Status geral

| Componente | Status |
|---|---|
| Spec 000 — Foundation | ✅ Aprovada |
| Spec 001 — Core Infrastructure | ✅ Implementada + 32 testes |
| Spec 002 — RAG | ✅ Implementada |
| Spec 003 — Agenda | ✅ Implementada |
| Spec 004 — Tarefas | ✅ Implementada |
| Spec 005 — Tool Calling | ✅ 10 tools + agent loop com logs SQLite |
| **Spec 006 — GUI (v1)** | ✅ tabs básicos (substituídos) |
| **UI v2 (Fases 1-10 do plano)** | ✅ ChatGPT-style + Calendário unificado |
| **Spec D-024 — Chat sessions persistidas** | ✅ Migration 003 + restauração via sidebar |
| **Spec D-025 — Calendar VIEW unificada** | ✅ Migration 004 + tool_calendar |

**Validação automatizada**: `pytest -q` → **115 passed, 3 skipped** (smoke LLM
opt-in). `ruff check .` → **All checks passed!**

**Validação manual**: app sobe em `http://127.0.0.1:8080`, todas as 4 migrations
aplicam (v=4), LLM healthcheck OK, UI ChatGPT-style com sidebar Recentes +
Calendário unificado funcional.

## Mudanças aplicadas em 2026-05-24 (UI v2)

### Visual (Fases 1, 4, 5)

- **Tema dark ChatGPT-style** (`src/ui/theme.py`): fundo `#000000` absoluto,
  fonte Inter via Google Fonts, locale Quasar PT-BR (calendários, meses,
  dias da semana em português), paleta refinada.
- **Layout 2 colunas**: sidebar fixa de 260px à esquerda + área central
  centralizada com input pill. **Removidos os tabs antigos.**
- **Sidebar com "Recentes"** populando dinamicamente — clique em conversa
  restaura todas as mensagens + tool calls preservados.
- **Pill input** com botão "+" à esquerda (menu) e botão azul circular de
  envio à direita.
- **Histórico de prompts** acessível via setas ↑/↓ no input (terminal-style,
  até 50 prompts em memória da sessão).
- **Tool calls discretas**: card colapsado por padrão (`ui.expansion`), com
  ícone de ferramenta + nome + duração; clique expande para ver input/output
  formatados em JSON.

### Menu "+" do chat (Fase 6 + Fase 10)

Substituiu os tabs antigos. 4 opções:

1. **Enviar material** → dialog modal com upload + lista de documentos.
2. **Calendário (eventos + tarefas)** → dialog fullscreen com grid mensal
   unificado, mini-calendário lateral, filtros, wizard de criação.
3. **Lista de tarefas** → modo to-do puro com checkboxes.
4. **Pesquisar auditoria** → tabela de `tool_call_logs` (D-015).

### Persistência de conversas (Fase 3 / D-024)

- Migration 003: `chat_sessions` + `chat_messages` (com posições ordenadas).
- `src/domain/chat/` (models, repo, service).
- `AgentLoop.respond(session_id=...)` grava user/assistant/tool events.
- Sidebar lê via `list_recent_sessions(limit=30)`.
- Click restaura mensagens via `list_messages_of_session`.

### Calendário unificado (Fases 8-10 / D-025)

**Desafio resolvido**: Eventos (agenda) e Tarefas (com prazo) convivem no mesmo
calendário, distinguidos visualmente por **cor + ícone**:
- Eventos = barra colorida (`HH:MM Título`).
- Tarefas = bolinha + título (riscado se concluída).

**Estratégia de dados**: VIEW SQL `calendar_items_view` que faz UNION ALL
de `events` + `tasks` (apenas com `due_at NOT NULL`). Sem duplicação de dados;
tools existentes (`consultar_agenda`, `listar_tarefas`) continuam funcionando.

**Wizard de criação** (`src/ui/components/calendar_wizard.py`): pergunta primeiro
"É um Evento ou uma Tarefa?" com cards didáticos explicando cada um, antes de
abrir o form específico. A LLM também recebe dica no system prompt para
distinguir as duas categorias.

**Nova tool**: `consultar_calendario(data_inicio, data_fim, ...)` para queries
unificadas via chat.

### Acentuação PT-BR corrigida (Fase 2)

- System prompts: `tools/registry.py`, `rag/prompt.py`, `llm/agent.py`.
- Tools: `tool_agenda.py`, `tool_tasks.py`, `tool_rag.py`, `tool_materials.py`.
- Tool enum `"amanha"` agora aceita tanto `"amanha"` quanto `"amanhã"` (LLM
  pode mandar qualquer um — normalize via `unicodedata`).
- Mensagens de erro, docstrings e logs em `src/rag/ingest.py`,
  `domain/agenda/*`, `domain/tasks/*`.

### Acessibilidade / Date pickers (Fase 7)

- `src/ui/components/date_picker.py` — input com formato `dd/mm/aaaa[ HH:mm]`,
  máscara, e calendário Quasar em PT-BR (Janeiro, Domingo, etc.).
- Usado em: wizard de criação, formulários de edição no calendar_dialog,
  lista de tarefas.

## Como rodar agora

```powershell
# Setup (uma vez):
python -m pip install --user uv
python -m uv sync
copy .env.example .env
# preencher JARVIS_LLM_API_KEY no .env

# Rodar:
.venv\Scripts\python.exe -m src.main
# Abrir http://127.0.0.1:8080
```

## Métricas

- **Migrations SQLite**: 4 (versões 001 a 004) + 1 VIEW unificada.
- **Tabelas**: 7 (`documents`, `chunks`, `events`, `tasks`, `tool_call_logs`,
  `chat_sessions`, `chat_messages`) + 1 virtual (`chunk_vecs`) + 1 view
  (`calendar_items_view`).
- **Tools registradas**: 10 (`consultar_agenda`, `adicionar_evento`,
  `editar_evento`, `remover_evento`, `listar_tarefas`, `adicionar_tarefa`,
  `concluir_tarefa`, `buscar_material_rag`, `listar_materiais`,
  `consultar_calendario`).
- **ADRs**: D-001 a D-027 (inclui D-024 chat sessions, D-025 calendar VIEW,
  D-026 UI v2, D-027 caminho RAG único).
- **Specs SDD**: 7 (000-006).
- **Testes pytest**: 115 passed, 3 skipped (smoke LLM opt-in).
- **Linhas de código (src/)**: ~5.500+ (UI v2 adicionou ~2.500 linhas).

## O que ainda falta (entregas humanas)

1. ~~Dataset em `/data` com ≥10 documentos~~ ✅ **FEITO** (10 PDFs, 5 indexados).
2. **Validar o chat/RAG com a LLM real** assim que o endpoint da LIA sair do 502.
3. **Vídeo demo ≤ 3 min** (arquitetura + sistema funcionando: chat, calendário,
   tool calls).
4. **`git push`** para o GitHub (repo já inicializado e commitado localmente).

## Retomar em outra sessão

1. Ler [`CLAUDE.md`](CLAUDE.md) (constituição) + [`decisions.md`](decisions.md) (ADRs).
2. Ler este `STATUS.md`.
3. `uv sync` para garantir ambiente (inclui o grupo dev — D-031).
4. `pytest -q` para baseline verde.
5. `.venv\Scripts\python.exe -m src.main` → http://127.0.0.1:8080.

Próximos caminhos:
- **Trabalho 1 final**: dataset + vídeo + GitHub.
- **Trabalho 2**: funcionalidade 3.4 (planejamento integrado) + funcionalidades
  de aprendizado interativas (active recall, geração de exercícios) +
  avaliação ≥10 perguntas + análise de erros.
