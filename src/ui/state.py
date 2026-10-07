"""Estado global da UI (singleton por processo)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.llm import AgentLoop, GemmaClient

# Quantos prompts recentes o histórico em memória guarda.
PROMPT_HISTORY_LIMIT = 50


@dataclass
class AppState:
    gemma: GemmaClient | None = None
    agent: AgentLoop | None = None
    online: bool = False
    user_name: str = "Felipe Sá"

    # Sessão de chat atual (None = ainda não criada)
    current_session_id: int | None = None

    # Histórico de prompts em memória (até PROMPT_HISTORY_LIMIT, FIFO)
    prompt_history: list[str] = field(default_factory=list)

    # Sidebar colapsada (mini-mode 60px) ou expandida (260px)
    sidebar_collapsed: bool = False

    # Callbacks notificados quando a lista de sessões muda (sidebar refresh)
    _on_sessions_changed: list[Callable[[], None]] = field(default_factory=list)

    # Callbacks notificados quando a sidebar é colapsada/expandida (passa novo valor)
    _on_sidebar_toggled: list[Callable[[bool], None]] = field(default_factory=list)


_state = AppState()


def get_state() -> AppState:
    return _state


def set_clients(gemma: GemmaClient, agent: AgentLoop, online: bool) -> None:
    _state.gemma = gemma
    _state.agent = agent
    _state.online = online


def add_to_prompt_history(prompt: str) -> None:
    """Insere no topo (mais recente primeiro), sem duplicatas, até PROMPT_HISTORY_LIMIT."""
    normalized_prompt = prompt.strip()
    if not normalized_prompt:
        return
    if normalized_prompt in _state.prompt_history:
        _state.prompt_history.remove(normalized_prompt)
    _state.prompt_history.insert(0, normalized_prompt)
    _state.prompt_history = _state.prompt_history[:PROMPT_HISTORY_LIMIT]


def register_sessions_changed(cb: Callable[[], None]) -> None:
    _state._on_sessions_changed.append(cb)


def notify_sessions_changed() -> None:
    import contextlib

    for cb in list(_state._on_sessions_changed):
        with contextlib.suppress(Exception):
            cb()


def reset_session() -> None:
    """Inicia uma nova conversa (limpa a sessão atual)."""
    _state.current_session_id = None


def register_sidebar_toggled(cb: Callable[[bool], None]) -> None:
    _state._on_sidebar_toggled.append(cb)


def toggle_sidebar() -> bool:
    """Alterna entre expandida (260px) e mini (60px). Retorna novo estado."""
    import contextlib

    _state.sidebar_collapsed = not _state.sidebar_collapsed
    for cb in list(_state._on_sidebar_toggled):
        with contextlib.suppress(Exception):
            cb(_state.sidebar_collapsed)
    return _state.sidebar_collapsed
