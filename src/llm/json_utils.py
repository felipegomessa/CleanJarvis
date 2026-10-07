"""Parsing tolerante de JSON vindo do LLM — extraído do agent loop (Spec 007/T-007.5).

Centraliza a leitura de respostas JSON do LLM (envelopes ```json```, texto ao redor,
barras invertidas cruas de LaTeX) para reúso pelo agent loop e pelo módulo `learning`.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Barras invertidas que tratamos como literais de LaTeX e dobramos no reparo.
# Honramos só os escapes que o LLM usa de propósito em prosa: \" \\ \/ \n \r \t
# \uXXXX. Deixamos \b e \f FORA de propósito: form-feed/backspace nunca são
# intencionais num chat, mas colidem com LaTeX comum (\beta, \frac) — então
# preferimos preservá-los como '\beta'/'\frac' a virar caracteres de controle.
_INVALID_JSON_ESCAPE = re.compile(r'\\(?!["\\/nrtu])')

# Envelope markdown que o LLM às vezes coloca em volta do JSON: ```json ... ```
CODE_FENCE = "```"
JSON_LANG_TAG = "json"


def loads_lenient(s: str) -> dict[str, Any]:
    """json.loads tolerante a barras invertidas cruas de LaTeX (\\sigma, \\frac).

    Estrito primeiro; só na falha dobra as '\\' que não iniciam um escape honrado
    e re-tenta. Best-effort: cobre o caso real (comandos LaTeX crus do Qwen em
    respostas matemáticas) sem mexer em '\\n'/'\\t' legítimos de quebra de linha.
    """
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        repaired = _INVALID_JSON_ESCAPE.sub(r"\\\\", s)
        return json.loads(repaired)


def _try_loads(text: str) -> dict[str, Any] | None:
    """loads_lenient que devolve None em vez de levantar — 1ª tentativa, antes do recorte."""
    try:
        return loads_lenient(text)
    except json.JSONDecodeError:
        return None


def parse_json_response(text: str) -> dict[str, Any]:
    """Extrai JSON da resposta do LLM. Tolera envelopes ```json ... ``` ou texto pré/pós."""
    text = text.strip()
    if not text:
        raise ValueError("resposta vazia")

    if text.startswith(CODE_FENCE):
        # remove primeira linha de fence
        text = text.split("\n", 1)[1] if "\n" in text else text[len(CODE_FENCE) :]
        if text.rstrip().endswith(CODE_FENCE):
            text = text.rstrip()[: -len(CODE_FENCE)]
        text = text.strip()
        if text.startswith(JSON_LANG_TAG):
            text = text[len(JSON_LANG_TAG) :].lstrip()

    parsed = _try_loads(text)
    if parsed is not None:
        return parsed

    # Procura primeiro { até último }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        json_candidate = text[start : end + 1]
        try:
            return loads_lenient(json_candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido após extração: {e}") from e

    raise ValueError("não foi possível extrair JSON da resposta")
