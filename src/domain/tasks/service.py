"""Servicos de consulta de tarefas — RF-004.3."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.domain.agenda.service import DEFAULT_TZ
from src.domain.tasks.models import Task
from src.domain.tasks.repo import list_tasks


def _end_of_day(moment: datetime) -> datetime:
    """Último segundo do dia de `moment` (23:59:59), mantendo o fuso."""
    return moment.replace(hour=23, minute=59, second=59, microsecond=0)


def pending_tasks(conn: sqlite3.Connection) -> list[Task]:
    return list_tasks(conn, status="pending")


def done_tasks(conn: sqlite3.Connection, limit: int = 50) -> list[Task]:
    return list_tasks(conn, status="done", limit=limit)


def overdue_tasks(
    conn: sqlite3.Connection, tz: ZoneInfo = DEFAULT_TZ
) -> list[Task]:
    """Tarefas pendentes com due_at no passado (em relacao ao agora no tz local)."""
    now = datetime.now(tz)
    candidates = list_tasks(conn, status="pending", only_due_until=now)
    return candidates


def tasks_due_today(
    conn: sqlite3.Connection, tz: ZoneInfo = DEFAULT_TZ
) -> list[Task]:
    now = datetime.now(tz)
    return list_tasks(conn, status="pending", only_due_until=_end_of_day(now))


def tasks_due_this_week(
    conn: sqlite3.Connection, tz: ZoneInfo = DEFAULT_TZ
) -> list[Task]:
    now = datetime.now(tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = _end_of_day(today + timedelta(days=(6 - today.weekday())))
    return list_tasks(conn, status="pending", only_due_until=week_end)
