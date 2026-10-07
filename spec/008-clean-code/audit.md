# Auditoria — Spec 008: Refatoração Clean Code

**Auditor**: spec-auditor · **Data**: 2026-10-06 · **Spec**: spec/008-clean-code/

## Resumo / veredito

🟡 **APROVADA COM RESSALVAS: 2 bloqueadores pequenos** (de design/teste, corrigíveis
na própria spec sem nova entrevista). Depois de corrigidos, a spec pode ir para
aprovação humana.

A spec está bem fundamentada. Conferi as duas alegações centrais contra o código:
- o bug do `output_json` existe;
- a perda de dados na re-ingestão também existe, porque a conexão é autocommit
  (`db.py:49-50`) e o `DELETE` em `ingest.py:160` é efetivado na hora.

O escopo é enxuto, o "fora de escopo" é explícito e não há violação de camadas. Os
problemas estão (1) no fixture de teste da ingestão, que falharia como está descrito,
e (2) no contrato do RF-008.1, que fica indefinido para o status/evento quando a
saída não é serializável.

---

## Bloqueadores

### B1. O fake de embedding descrito em design.md §8 quebra a própria ingestão
- design.md §8 manda o fake retornar `np.zeros((n, EMBEDDING_DIM))`. O dtype padrão
  desse array é **float64**.
- A coluna `chunk_vecs.embedding` é `vec0 FLOAT[384]` (`002_rag.sql:11-13`), e
  `ingest.py:245` grava `emb.tobytes()`. Em float64 isso dá 3072 bytes em vez de
  1536, e o sqlite-vec rejeita.
- Resultado: o `INSERT` falha → `ROLLBACK` → `reason="db_insert_failed"`. Os cenários
  "ingestão nova" e "re-ingestão com sucesso" falhariam por causa do teste, não do
  código. O embedder real faz `astype(np.float32)` (`embed.py:45`).
- **Correção**: usar `np.zeros((n, EMBEDDING_DIM), dtype=np.float32)` e especificar o
  alvo do monkeypatch: **`src.rag.ingest.embed_passages`**. `ingest.py:16` faz
  `from src.rag.embed import embed_passages`, então trocar `src.rag.embed.embed_passages`
  não tem efeito e baixaria o modelo real.
- O fixture também precisa de `JARVIS_LLM_API_KEY`, porque `llm_api_key` é obrigatório
  (`config.py:28`) e `ingest_document` chama `get_settings()`. O modelo a seguir é o
  `shared_db` de `test_agent_loop.py:45-56` (env + `cache_clear` + `apply_migrations`).

### B2. RF-008.1 não define status nem payload do evento quando a saída não é serializável
- O design (§1) só troca `output_json` por um JSON de erro. Ficam em aberto:
  - **Status no log**: `status` continua `"ok"` (`agent.py:160`). A linha em
    `tool_call_logs` fica com `status='ok'` e `output_json` de erro, o que deixa a
    auditoria D-015 incoerente. A spec precisa dizer se o status vira `'error'`, e
    com qual `error_msg`.
  - **Evento `tool_result`**: continua com `"output": output`, o objeto circular
    (`agent.py:188-194`). A UI serializa esse objeto de novo em
    `tool_call_card.py:53-55` com `json.dumps(..., default=str)`, que **também levanta
    `ValueError` (Circular reference)**. Assim o bug só sai do agent e reaparece no
    chip do chat. O evento também diverge do que é persistido na sessão
    (`content=output_json`, de erro).
- **Correção**: decidir e escrever na spec. Recomendação: quando a serialização falha,
  `status="error"`, `error_msg` = mensagem do helper, e evento/observação/persistência
  usam o mesmo dict de erro. Isso deve ser declarado como parte da mudança de
  comportamento do RF-008.1, já que mexe no conteúdo de um evento. Por consequência,
  `_serialize_tool_output` ou `ToolRun` precisa devolver o *output efetivo*, não só a
  string.

---

## Ressalvas (não-bloqueantes)

1. **O bug é pior do que o descrito (RF-008.1).** O `NameError` só ocorre se a falha
   acontecer na **1ª** tool do turno. Nas iterações seguintes, `output_json` já está
   ligado à tool anterior e é **reaproveitado em silêncio**: observação errada para a
   LLM em `agent.py:219` e conteúdo errado persistido em `agent.py:204`.
   - Vale corrigir o texto do RF.
   - Vale um 2º caso de teste: tool OK seguida de tool circular, com assert de que a
     observação da 2ª não repete a saída da 1ª.
   - Lembrete: em `agent.py:204` o `NameError` é engolido pelo `except` em
     `agent.py:214`. Só a linha 219 propaga.

2. **Aliases privados precisam ser preservados explicitamente.**
   `tests/unit/test_agent_json_parse.py:11` importa `_parse_json_response` de
   `src.llm.agent`, e os aliases ficam em `agent.py:39-41`. A promessa "testes sem
   alteração" depende de manter `_parse_json_response`/`_loads_lenient` na
   decomposição. Isso deve constar no design §2. O ruff não acusa esses aliases (são
   atribuições de módulo), mas uma "limpeza" manual pode removê-los.

3. **`RetrievalResult.threshold_used: float | None = None` muda um modelo público**
   (`types.py:41`), e isso não está declarado como exceção ao "Princípio de
   compatibilidade".
   - Impacto real verificado: nenhum teste quebra. `test_prompt.py:10` não passa o
     campo e não o lê, `test_prompt.py:35` passa `0.6`, o único construtor em produção
     sempre preenche (`retrieve.py:69-73`) e `tool_rag.py:61` só repassa o valor.
   - Ainda assim, o tipo exposto passa a aceitar `None`. Declarar isso no RF-008.5, ou
     retirar o item.

4. **D-021 é alterado e precisa de registro (P2).**
   - D-021 (passo 3) diz "deletar o documento antigo … e re-ingerir". A spec muda a
     ordem: prepara antes, apaga dentro da transação. Adicionar uma nota de revisão em
     D-021 (ou registrar junto ao D-031).
   - design §3 diz "a `UNIQUE(source_path)` (se existir)". Ela **existe**
     (`001_initial.sql:10`). Por isso o `DELETE` antes do `INSERT` na mesma transação é
     **obrigatório**, não opcional. Ajustar o texto.

5. **Cobertura parcial do RF-008.3.** O motivo da mudança é "falha em qualquer etapa
   preserva o antigo", mas só a falha de embedding é testada. Faltam:
   - **Falha no INSERT**: é o caso que exercita o `ROLLBACK` desfazendo o `DELETE`.
     Dá para provocar de forma barata com o próprio fake devolvendo float64 ou dimensão
     errada (ver B1).
   - Texto ilegível/vazio na re-ingestão.
   - Um teste parametrizado dos `reason` (`unsupported_type`, `not_a_file`, `no_text`,
     `unreadable_text`) para sustentar o critério "IngestResult idênticos".

6. **Inventário de `except Exception` incompleto (RF-008.4).** O RF cita só agent,
   `main.py`, `db.py:142` e `generator.py:226`. Existem ainda:
   - `coach.py:153,169`
   - `grader.py:72`
   - `gemma_client.py:158`
   - `ingest.py:165,215,248`
   - UI: `calendar_wizard.py`, `calendar_dialog.py`, `exam_dialog.py`,
     `materials_dialog.py`, `chat_view.py:227`

   Declarar que ficam (fronteiras de UI/LLM) ou incluí-los. Para a ingestão, dizer se
   o `except Exception` da extração permanece. Ele se justifica pela política §8 (PDF
   corrompido → pular), porque o pdfplumber levanta tipos variados, e deve ganhar o
   comentário do porquê como os demais.

7. **STATUS.md tem instruções operacionais, não só histórico.** `STATUS.md:198` e
   `STATUS.md:235` mandam rodar `uv sync --extra dev`. Depois da migração para
   `[dependency-groups]`, o uv falha com extra inexistente. Atualizar essas duas linhas
   (o README:323 já está previsto) ou dizer explicitamente que ficam.

8. **Descrição do contrato de eventos (design §2) imprecisa.** O texto diz
   "… → `final` | `error`", mas `error` **não é terminal**: em `agent.py:224-237` o loop
   continua após emiti-lo. Também falta dizer como se mede o "≤ 50 linhas" (com ou sem
   docstring). Pelo meu esboço, o limite é viável, mas fica justo se a normalização de
   `args` (`agent.py:124-127`) continuar inline.

9. **Deriva de números de linha e itens faltando na tabela de constantes.**
   - `domain/learning/models.py:31` → o literal `2 <= … <= 6` está na linha **30**. A
     mensagem "entre 2 e 6 alternativas" (linha 31) também deve derivar das constantes.
   - `ui/app.py:38` → `timeout_s=15.0` está na linha **40**.
   - `ui/state.py:56` → `[:50]` está na linha **55**.
   - `tool_learning.py:154,164` → `aid` está em **150/160** (`d` em 154/164).
   - `json_utils.py:54` → é o `except`; o `pass` está na 55.
   - `json_utils.py:46` (`[:-3]`) também é fatiamento de fence e deveria usar
     `-len(CODE_FENCE)`.
   - `generator.py:75` ("mínimo 2") repete o literal de `MIN_MC_OPTIONS` no prompt.

10. **`MAX_LLM_ATTEMPTS = 3` evidencia uma divergência.** `stop_after_attempt(3)`
    (`gemma_client.py:85`) são 3 *tentativas* (2 retries), enquanto CLAUDE.md §8 diz
    "3 retries". O nome da constante está correto em relação ao código e a spec não
    deve mudar comportamento. Registrar a divergência (nota em D-014 ou no STATUS) para
    não confundir na apresentação.

11. **Import de `DEFAULT_STUDY_MINUTES`.** `coach.py:13-19` importa do pacote
    `src.domain.learning`, que reexporta via `__init__.py`. Ou a constante é adicionada
    ao `__init__`/`__all__`, ou o coach importa de `src.domain.learning.models`. Isso
    não afeta §4.1, porque learning→domain é permitido.

---

## Verificações OK

- ✓ **Coerência com CLAUDE.md**:
  - P1 (código explicável, sem framework);
  - P3 (três arquivos + decisões de entrevista registradas);
  - P7/D-011 (o `[dependency-groups]` reforça "`uv sync` instala tudo");
  - §6 (constantes UPPER_SNAKE, comentários do porquê, erros nunca silenciosos);
  - §8 (tool error → captura/registro/devolução ao loop, mantido em `_run_tool`).
- ✓ **Camadas (§4.1)**:
  - toda constante nova mora no módulo dono;
  - `coach`→`domain.learning` é permitido;
  - `chunk.py` não passa a importar `core.config` (design §5);
  - nenhuma importação nova entre camadas.
- ✓ **ADRs**:
  - D-006 (defaults 800/150 como constantes, a ingestão continua usando `settings.chunk_*`);
  - D-010/D-015 (log de tool mantido, `except` largo justificado como modo degradado);
  - D-014 (valores 3/1/8 inalterados);
  - D-024 (`_persist_session_message` com `touch=True` reproduz o
    `update_session_timestamp` só na resposta final, `agent.py:116`);
  - D-028 (`GemmaClient` fora de escopo).
- ✓ **Bug do `output_json` real**: atribuído só dentro do `try` (`agent.py:172-186`) e
  usado em `agent.py:204,219`. `json.dumps(..., default=str)` ainda levanta
  `ValueError` para referência circular e `TypeError` para chaves não-str (ex.: tupla),
  então o par de exceções do helper está correto.
- ✓ **Perda de dados na re-ingestão real**: a conexão é autocommit
  (`db.py:49-50`, `isolation_level=None`). O `_delete_document` em `ingest.py:160` é
  efetivado antes da extração (`:163`) e do embedding (`:213`). O `BEGIN` só começa em
  `ingest.py:227`. O design §3 corrige isso preparando o conteúdo fora da transação,
  sem lock de escrita longo.
- ✓ **`_pretty_json`**: `audit_dialog.py:75,88` conferidos. `json.loads(None)` levanta
  `TypeError`, então `(json.JSONDecodeError, TypeError)` cobre os casos reais.
- ✓ **`_end_of_day`**: `tasks/service.py:35,45` conferidos. A linha 45 não zera
  `microsecond`, mas parte de `today`, que já tem `microsecond=0`, então o resultado é
  idêntico.
- ✓ **Outros literais conferidos**: `embed.py:41` (384), `chunk.py:39` (800/150),
  `types.py:41` (0.6), `agenda/service.py:73` (30), `gemma_client.py:85-86` (3/1/8),
  `coach.py:47,106,117`, `models.py:87`, `agent.py:51`.
- ✓ **Renomeações**: os nomes listados existem (`db.py:91` `v`/`f`, `app.py:35` `v`,
  `state.py:49` `p`, `tool_learning.py:31-53`, `generator.py:26,94,145-147,180-217`,
  `coach.py:60,147,149`, `ingest.py` `spath`/`cur2`/`emb`/`c`,
  `chat_view.py:197-205`, `exam_dialog.py:159-169,209`). O dedupe por
  `dict.fromkeys` (`tool_learning.py:48-49`) tem a mesma semântica, preservando ordem.
- ✓ **"7 testes" de `test_agent_loop.py`** conferidos (linhas 60, 78, 121, 141, 159,
  173, 215). Nenhum importa nome privado de `agent`, e o contrato que eles verificam
  (tipos/chaves/ordem, persistência `user→tool→assistant`) é preservado pelo design.
- ✓ **Viabilidade do design**:
  - helpers síncronos ou `async` que *retornam* eventos para o `yield` em `respond` é
    um padrão válido em async generator;
  - `ToolRun`/`PreparedContent` como dataclass é trivial;
  - `_run_tool` precisa ser `async` (await do handler), e o design trata isso.
- ✓ **`[dependency-groups]` (PEP 735)**: suportado pelo uv instalado (`uv 0.11.18`).
  O grupo `dev` é sincronizado por padrão em `uv sync`.
- ✓ **O problema do RF-008.7 é real hoje**: na venv atual,
  `uv run --no-sync ruff` → "program not found" e `import pytest` →
  `ModuleNotFoundError`.
- ✓ **Gate de lint viável**: baseline `ruff check src tests` (ruff 0.16.10 via `uvx`,
  sem tocar no repo) → "All checks passed!".
- ✓ **Testabilidade**:
  - cada RF tem verificação na matriz de tasks.md;
  - "teste primeiro" em T-008.2/T-008.4 está correto (os testes devem falhar antes da
    correção);
  - a suíte `live_llm` é dispensada de forma coerente.
- ✓ **Ordenação de tasks**: T-008.1 (ferramental) antes dos gates. T-008.7 (renomeações)
  depois de T-008.3/T-008.4 evita conflito nos mesmos arquivos. Os `[P]` estão coerentes.

---

## Re-auditoria (rodada 2)

**Data**: 2026-10-06 · **Escopo**: requirements.md, design.md e tasks.md revisados
para tratar B1, B2 e R1–R11.

### Veredito atualizado

✅ **APROVADA**: sem bloqueadores. Pronta para a aprovação humana
(`aprovo a spec 008`). Restam 3 observações cosméticas (abaixo), que podem ser
resolvidas na implementação.

### Situação de cada item

| Item | Situação | Evidência na spec revisada |
|---|---|---|
| **B1** fake de embedding | ✅ Resolvido | design §8: fake em `src.rag.ingest.embed_passages`, `np.zeros(..., dtype=np.float32)`, `JARVIS_LLM_API_KEY="fake"`, `cache_clear` antes/depois. O padrão citado existe em `test_get_document_chunks.py:18-22,36`. |
| **B2** contrato da saída não serializável | ✅ Resolvido | RF-008.1: "Mudança de comportamento declarada"; `status="error"`, `error_msg` e **o mesmo dict de erro** no evento, no log, na sessão e na observação. design §1: `_serialize_tool_output -> (output_json, erro)`, e `ToolRun` coerente alimenta todos os consumidores. Teste A verifica `status='error'` no log e no evento. |
| **R1** reaproveitamento silencioso | ✅ Resolvido | RF-008.1 descreve o caso; Teste B (tool OK + tool circular). design §1: `output_json` é campo do `ToolRun` da iteração. |
| **R2** aliases privados | ✅ Resolvido | RF-008.2 + design §2 + T-008.3 mantêm `_parse_json_response`/`_loads_lenient`. |
| **R3** `threshold_used` | ✅ Resolvido | RF-008.5: "exceção declarada ao princípio de compatibilidade", com justificativa conferida (`retrieve.py:69-73`, `test_prompt.py:10`). |
| **R4** D-021 + UNIQUE | ✅ Resolvido | RF-008.3 e T-008.4 incluem a nota em D-021. design §3 cita `001_initial.sql:10` e diz "**precisa**". |
| **R5** cobertura RF-008.3 | ✅ Resolvido | Re-ingestão com falha de embedding, texto ilegível e falha no INSERT, além de `reason` parametrizado (7 reasons). |
| **R6** inventário `except Exception` | ✅ Resolvido | RF-008.4 lista e justifica todos os que encontrei na rodada 1 (`main.py:15`, `db.py:142`, `generator.py:226`, `ingest.py:165,215,248`, `coach.py:153,169`, `grader.py:72`, `gemma_client.py:158`, `ui/**`). |
| **R7** STATUS.md | ✅ Resolvido | RF-008.7, design §7 e T-008.1 cobrem `README.md:323` e `STATUS.md:198,235`. As linhas foram conferidas como instruções de uso; as históricas 51/83 ficam. |
| **R8** `error` não terminal + regra de contagem | ✅ Resolvido | design §2: "`error` não é terminal … só `final` encerra". RF-008.2: contagem via AST, excluindo docstring. |
| **R9** linhas | ✅ Resolvido | `models.py:30-31`, `ui/state.py:55`, `ui/app.py:40`, `tool_learning.py` `aid` 150/160 e `d` 154/164, `json_utils.py:46` (`[:-3]`), `generator.py:75` incluídos. |
| **R10** tentativas vs. retries | ✅ Resolvido | RF-008.5 e design §5: comentário em `MAX_LLM_ATTEMPTS` registra 3 tentativas = 2 retries, sem mudar comportamento. |
| **R11** import da constante | ✅ Resolvido | design §5: `coach.py`/`generator.py` importam direto de `src.domain.learning.models`; `__init__` não muda. |

### Verificação empírica do truque float64 (falha no INSERT)

Rodei um script descartável no scratchpad, fora do repo
(`uv run --frozen --no-sync`, com `get_connection` + `apply_migrations` reais e DB
temporário). Ele reproduz a sequência de `_persist`:

1. documento antigo com vetor float32 → `COMMIT` ok;
2. `BEGIN` → DELETE de `chunk_vecs` e `documents` do antigo → INSERT do novo
   documento e chunk → INSERT em `chunk_vecs` com `np.zeros(384, dtype=np.float64)`.

Resultado:

```
float64 insert FAILED as expected: OperationalError Dimension mismatch for inserted
vector for the "embedding" column. Expected 384 dimensions but received 768.
docs: [(1, 'h1')]   chunks: 1   vecs: 1
```

A falha ocorre **dentro da transação, depois do DELETE**. O `ROLLBACK` restaura o
documento antigo, o chunk e também o vetor: a tabela virtual `vec0` participa do
rollback. O teste de "falha no INSERT" exercita exatamente o caminho que motiva o
RF-008.3. Como a exceção é `sqlite3.OperationalError`, ela cai no `except` de
`_persist`, e o resultado esperado é `reason="db_insert_failed"`.

Também conferi que `ToolRegistry` tem `__init__()` + `register(ToolDefinition)`
(`registry.py:27-33`). Montar o registry fake com tool circular dos Testes A/B é
viável sem tocar no registry global.

### Observações cosméticas (não-bloqueantes)

1. **Gatilho de `extract_failed` no teste parametrizado não especificado.** Sugestão:
   um `.pdf` com bytes inválidos (o pdfplumber levanta) ou monkeypatch de
   `src.rag.ingest._extract_text`. `read_failed` e `no_chunks` ficaram fora da lista.
   É aceitável: o primeiro exige simular erro de I/O e o segundo é praticamente
   inalcançável com texto legível não vazio. Basta deixar isso explícito no teste.
2. **Tabela "Cenários de erro cobertos" (requirements.md).** A linha "Saída de tool
   não serializável" ainda não menciona `status="error"`, que agora é o comportamento
   declarado. Ajuste de redação.
3. **Mensagem de warning no log.** design §1 move o `logger.warning` para `_run_tool`.
   Garantir que a mensagem inclua o nome da tool, como no rascunho da rodada 1, para
   rastreabilidade (P5).
