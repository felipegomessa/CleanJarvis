"""Cliente assíncrono do Gemma 12B (LIA UFMS, OpenAI-compatible) — RF-001.3.

ADRs:
- D-014: AsyncOpenAI + tenacity para retries (5xx/timeout/429).
- D-018: Dual mode — stream_chat() (yield de tokens) e complete_chat() (string).
- D-017: healthcheck() para o degraded mode.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from loguru import logger
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.config import Settings
from src.llm.exceptions import (
    LLMAuthError,
    LLMError,
    LLMRequestError,
    LLMServerError,
    LLMTimeoutError,
)
from src.llm.types import Message

# Exceções re-tentadas pelo tenacity (5xx vira LLMServerError; retry abaixo cobre).
_NETWORK_RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError)

# Política §8 / D-014. São 3 TENTATIVAS (= 2 retries); o CLAUDE.md fala em
# "3 retries" — divergência conhecida, comportamento mantido (Spec 008).
MAX_LLM_ATTEMPTS = 3
RETRY_WAIT_MIN_S = 1
RETRY_WAIT_MAX_S = 8


class GemmaClient:
    """Cliente assíncrono para o endpoint LIA UFMS (gemma-3-12b-it)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=str(settings.llm_base_url),
            api_key=settings.llm_api_key,
            timeout=settings.llm_timeout_s,
        )

    # ----- Núcleo: faz UMA chamada à API (não-retentável; o retry é aplicado pelos métodos públicos) -----
    async def _call(self, messages: list[Message], stream: bool, max_tokens: int | None):
        try:
            return await self._client.chat.completions.create(
                model=self._settings.llm_model,
                messages=list(messages),  # type: ignore[arg-type]
                max_tokens=max_tokens or self._settings.llm_max_tokens,
                temperature=self._settings.llm_temperature,
                stream=stream,
            )
        # IMPORTANTE: capturar RateLimitError ANTES de APIStatusError
        # (RateLimitError IS-A APIStatusError no SDK openai). Re-raise como-é
        # para que o tenacity em _call_with_retry detecte e retente.
        except RateLimitError:
            raise
        except APITimeoutError as e:
            # APITimeoutError IS-A APIConnectionError; trate aqui ANTES.
            raise LLMTimeoutError(f"timeout: {e}") from e
        except APIConnectionError as e:
            raise LLMTimeoutError(f"connection error: {e}") from e
        except APIStatusError as e:
            if e.status_code in (401, 403):
                raise LLMAuthError(f"auth falhou ({e.status_code}): {e}") from e
            if 400 <= e.status_code < 500:
                # 429 já saiu acima por RateLimitError; aqui são outros 4xx
                raise LLMRequestError(f"4xx ({e.status_code}): {e}") from e
            raise LLMServerError(f"5xx ({e.status_code}): {e}") from e

    # ----- Helper: aplica tenacity sobre _call -----
    async def _call_with_retry(self, messages: list[Message], stream: bool, max_tokens: int | None):
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(MAX_LLM_ATTEMPTS),
            wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN_S, max=RETRY_WAIT_MAX_S),
            retry=retry_if_exception_type(
                (LLMTimeoutError, LLMServerError, RateLimitError)
            ),
            reraise=True,
        ):
            with attempt:
                return await self._call(messages, stream=stream, max_tokens=max_tokens)
        # inalcançável: reraise=True levanta a última exceção
        raise LLMError("retry exhausted (deveria ter sido propagado)")

    # ----- API pública -----

    async def stream_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield de tokens conforme são gerados (para resposta direta ao usuário)."""
        resp = await self._call_with_retry(messages, stream=True, max_tokens=max_tokens)
        async for chunk in resp:  # type: ignore[union-attr]
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = getattr(choice, "delta", None)
            content = getattr(delta, "content", None) if delta else None
            if not content:
                # O endpoint Qwen da LIA ignora stream=True e devolve a resposta
                # inteira num único chunk com delta=None e o texto em
                # choice.message.content. Sem este fallback, stream_chat renderia
                # 0 tokens. Endpoints OpenAI-compliant (delta) continuam intactos.
                msg = getattr(choice, "message", None)
                if isinstance(msg, dict):
                    content = msg.get("content")
                elif msg is not None:
                    content = getattr(msg, "content", None)
            if content:
                yield content

    async def complete_chat(
        self,
        messages: list[Message],
        max_tokens: int | None = None,
    ) -> str:
        """Retorna a resposta completa como string (usado pelo agent loop)."""
        resp = await self._call_with_retry(messages, stream=False, max_tokens=max_tokens)
        if not resp.choices:  # type: ignore[union-attr]
            return ""
        content = resp.choices[0].message.content  # type: ignore[union-attr]
        return content or ""

    async def healthcheck(self, timeout_s: float = 5.0) -> bool:
        """Faz 1 chamada rápida. Retorna True se a LLM respondeu, False caso contrário.

        NÃO usa retry (apenas 1 tentativa). Timeout próprio (default 5s).
        """
        try:
            await asyncio.wait_for(
                self._call(
                    [{"role": "user", "content": "ping"}],
                    stream=False,
                    max_tokens=1,
                ),
                timeout=timeout_s,
            )
            return True
        except TimeoutError:
            logger.warning("LLM healthcheck timeout")
            return False
        except LLMError as e:
            logger.warning(f"LLM healthcheck falhou: {type(e).__name__}: {e}")
            return False
        except Exception as e:  # defensivo: qualquer erro inesperado
            logger.warning(f"LLM healthcheck erro inesperado: {type(e).__name__}: {e}")
            return False
