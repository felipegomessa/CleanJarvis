"""_pretty_json do diálogo de auditoria — Spec 008 / RF-008.4."""

from __future__ import annotations

from src.ui.dialogs.audit_dialog import _pretty_json


def test_valid_json_is_indented() -> None:
    assert _pretty_json('{"a": 1}') == '{\n  "a": 1\n}'


def test_invalid_json_returns_raw_text() -> None:
    assert _pretty_json("não é json") == "não é json"


def test_none_returns_none() -> None:
    assert _pretty_json(None) is None  # type: ignore[arg-type]
