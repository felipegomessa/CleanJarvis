"""Servicos de consulta temporal da agenda — RF-003.3."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.agenda.models import Event
from src.domain.agenda.repo import list_events

DEFAULT_TZ = ZoneInfo("America/Campo_Grande")

# Quão à frente `next_event` procura o próximo compromisso.
NEXT_EVENT_WINDOW_DAYS = 30


def _today_window(tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Janela [hoje 00:00, amanhã 00:00) no fuso `tz`, retornado em UTC-naive."""
    now = datetime.now(tz)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local, end_local


def events_today(
    conn: sqlite3.Connection,
    tz: ZoneInfo = DEFAULT_TZ,
    kind: str | None = None,
) -> list[Event]:
    start, end = _today_window(tz)
    return list_events(conn, start, end, kind=kind)


def events_tomorrow(
    conn: sqlite3.Connection,
    tz: ZoneInfo = DEFAULT_TZ,
    kind: str | None = None,
) -> list[Event]:
    _today_start, today_end = _today_window(tz)
    tomorrow_start = today_end
    tomorrow_end = tomorrow_start + timedelta(days=1)
    return list_events(conn, tomorrow_start, tomorrow_end, kind=kind)


def events_this_week(
    conn: sqlite3.Connection,
    tz: ZoneInfo = DEFAULT_TZ,
    kind: str | None = None,
) -> list[Event]:
    """Eventos entre segunda 00:00 e proxima segunda 00:00 (no tz local)."""
    now = datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Monday = 0 ... Sunday = 6
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    return list_events(conn, week_start, week_end, kind=kind)


def has_event_kind_tomorrow(
    conn: sqlite3.Connection,
    kind: str,
    tz: ZoneInfo = DEFAULT_TZ,
) -> bool:
    """Útil para 'tenho prova amanhã?'."""
    return len(events_tomorrow(conn, tz=tz, kind=kind)) > 0


def next_event(
    conn: sqlite3.Connection,
    tz: ZoneInfo = DEFAULT_TZ,
) -> Event | None:
    """Próximo evento a partir de agora (qualquer kind)."""
    now = datetime.now(tz)
    end = now + timedelta(days=NEXT_EVENT_WINDOW_DAYS)
    evs = list_events(conn, now, end)
    return evs[0] if evs else None
