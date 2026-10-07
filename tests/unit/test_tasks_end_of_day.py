"""_end_of_day do serviço de tarefas — Spec 008 / RF-008.5."""

from __future__ import annotations

from datetime import datetime

from src.domain.agenda.service import DEFAULT_TZ
from src.domain.tasks.service import _end_of_day


def test_end_of_day_keeps_date_and_timezone() -> None:
    moment = datetime(2026, 10, 6, 9, 15, 30, 123456, tzinfo=DEFAULT_TZ)

    assert _end_of_day(moment) == datetime(2026, 10, 6, 23, 59, 59, tzinfo=DEFAULT_TZ)
