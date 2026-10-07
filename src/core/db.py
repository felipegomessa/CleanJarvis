"""Acesso ao SQLite — conexão, migrations e helpers — RF-001.2/1.6 / D-012/D-013/D-015.

Conexão per-operação via context manager. PRAGMAs aplicados em toda conexão:
- journal_mode=WAL
- foreign_keys=ON
- busy_timeout=3000
- synchronous=NORMAL
Carrega a extensão sqlite-vec automaticamente.

Migrations forward-only via PRAGMA user_version + arquivos .sql numerados.
"""

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from loguru import logger

from src.core.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Regex para remover comentários SQL de linha (-- ...) antes do split por ';'
_COMMENT_RE = re.compile(r"--[^\n]*")


# ============================================================
# Conexão
# ============================================================

@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre conexão SQLite com PRAGMAs e sqlite-vec carregado.

    Args:
        db_path: Caminho do arquivo. Default: `Settings.db_path`.

    Yields:
        Conexão configurada (autocommit; usar BEGIN/COMMIT explícito para
        transações).
    """
    path = db_path or get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    # isolation_level=None → autocommit; BEGIN explícito ativa transações manuais
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 3000")
        conn.execute("PRAGMA synchronous = NORMAL")

        yield conn
    finally:
        conn.close()


# ============================================================
# Migrations
# ============================================================

def _split_statements(sql: str) -> list[str]:
    """Quebra um arquivo .sql em statements individuais.

    Estratégia: remove comentários `-- ...` e split por `;`. Suficiente para
    nosso schema (sem strings com `;` ou triggers complexos).
    """
    no_comments = _COMMENT_RE.sub("", sql)
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def _current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _list_migrations() -> list[tuple[int, Path]]:
    items: list[tuple[int, Path]] = []
    if not MIGRATIONS_DIR.exists():
        return items
    for migration_file in MIGRATIONS_DIR.glob("*.sql"):
        try:
            version = int(migration_file.name.split("_", 1)[0])
        except ValueError:
            logger.warning(
                f"migration file {migration_file.name} sem prefixo numérico — ignorada"
            )
            continue
        items.append((version, migration_file))
    items.sort(key=lambda x: x[0])
    return items


def apply_migrations(conn: sqlite3.Connection) -> int:
    """Aplica migrations pendentes (forward-only). Retorna a versão final.

    NÃO usa `executescript` porque ele emite COMMIT implícito antes do script,
    o que invalidaria nosso BEGIN/ROLLBACK manual. Usa loop de `execute()`
    statement-por-statement.

    Raises:
        RuntimeError: se DB user_version > maior migration disponível.
    """
    current = _current_version(conn)
    all_migrations = _list_migrations()
    max_available = max((v for v, _ in all_migrations), default=0)

    if current > max_available:
        raise RuntimeError(
            f"DB user_version={current} > maior migration disponível "
            f"({max_available}). Atualize o código antes de prosseguir."
        )

    pending = [(v, f) for v, f in all_migrations if v > current]
    if not pending:
        logger.debug(f"migrations: nada a aplicar (current=v{current})")
        return current

    for v, f in pending:
        sql = f.read_text(encoding="utf-8")
        statements = _split_statements(sql)
        logger.info(
            f"applying migration {f.name} (v{current} → v{v}, {len(statements)} stmts)"
        )
        try:
            conn.execute("BEGIN")
            for stmt in statements:
                upper = stmt.upper().strip()
                # PRAGMA user_version dentro do .sql é gerenciado pelo runner
                if upper.startswith("PRAGMA USER_VERSION"):
                    continue
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {v}")
            conn.execute("COMMIT")
            current = v
        except Exception:
            conn.execute("ROLLBACK")
            logger.exception(f"migration {f.name} failed; rolled back")
            raise

    return current


# ============================================================
# Helpers de tool call logging
# ============================================================

def log_tool_call(
    conn: sqlite3.Connection,
    tool_name: str,
    input_json: str,
    output_json: str | None,
    status: str,  # 'ok' | 'error'
    error_msg: str | None,
    duration_ms: int,
    llm_call_id: str | None = None,
) -> int:
    """Insere uma linha em `tool_call_logs`. Retorna o `lastrowid`."""
    if status not in ("ok", "error"):
        raise ValueError(f"status inválido: {status!r}")

    ts = (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    cur = conn.execute(
        """
        INSERT INTO tool_call_logs
            (ts, tool_name, input_json, output_json, status, error_msg,
             duration_ms, llm_call_id)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ts,
            tool_name,
            input_json,
            output_json,
            status,
            error_msg,
            duration_ms,
            llm_call_id,
        ),
    )
    return int(cur.lastrowid or 0)


# ============================================================
# Smoke da extensão sqlite-vec (chamado no startup)
# ============================================================

def smoke_check_vec(conn: sqlite3.Connection) -> str:
    """Verifica que sqlite-vec está carregado. Retorna a versão.

    Raises:
        RuntimeError: se a extensão não estiver disponível.
    """
    try:
        row = conn.execute("SELECT vec_version()").fetchone()
        version = str(row[0])
        logger.info(f"sqlite-vec carregado, versão {version}")
        return version
    except sqlite3.OperationalError as e:
        raise RuntimeError(
            "extensão sqlite-vec não carregou. Verifique a instalação: "
            "execute `uv sync` e reinstale `sqlite-vec`."
        ) from e
