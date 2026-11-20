"""
The one place that talks to an LLM.

Local Ollama is used when LOCAL_LLM_ENABLED (the default), otherwise Gemini when
GEMINI_API_KEY is set. Both are reached through their OpenAI-compatible APIs, so
swapping provider is a settings change. Callers use complete(); if no LLM is
configured it raises LLMUnavailable, and any provider error propagates so the
caller can fall back.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

import config

logger = logging.getLogger(__name__)

# Chat message format ({"role": ..., "content": ...}); callers use this, not openai types.
ChatMessage = ChatCompletionMessageParam

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMUnavailable(Exception):
    """No LLM is configured (local LLM disabled and no Gemini API key)."""


@dataclass(frozen=True)
class ChatClient:
    client: OpenAI
    model: str
    provider: Literal["ollama", "gemini"]


def get_chat_client() -> ChatClient | None:
    """The configured LLM client, or None if no LLM is configured."""
    settings = config.get_settings()
    if settings.local_llm_enabled:
        logger.info(f"Using local Ollama model '{settings.ollama_model}'.")
        client = OpenAI(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )
        return ChatClient(client, settings.ollama_model, "ollama")

    if settings.gemini_api_key:
        logger.info(f"Using Gemini model '{settings.gemini_model}'.")
        client = OpenAI(
            base_url=GEMINI_OPENAI_BASE_URL,
            api_key=settings.gemini_api_key,
            timeout=settings.llm_timeout_s,
            max_retries=1,
        )
        return ChatClient(client, settings.gemini_model, "gemini")

    logger.info(
        "No LLM configured (LOCAL_LLM_ENABLED is off and GEMINI_API_KEY is missing)."
    )
    return None


def complete(
    messages: list[ChatMessage],
    *,
    purpose: str,
    temperature: float = 0.1,
) -> str:
    """
    Send a chat request and return the reply text ("" if the model sent none).
    Raises LLMUnavailable if no LLM is configured; provider errors propagate.
    `purpose` is only used in log messages.
    """
    chat = get_chat_client()
    if chat is None:
        raise LLMUnavailable()

    logger.debug(f"LLM {purpose} prompt: {messages}")
    started = time.perf_counter()
    response = chat.client.chat.completions.create(
        model=chat.model, messages=messages, temperature=temperature
    )
    logger.info(f"LLM {purpose} completed in {time.perf_counter() - started:.2f}s.")
    content = response.choices[0].message.content or ""
    logger.debug(f"LLM {purpose} reply: {content}")
    return content


def parse_json_object_from_text(text: str | None) -> dict[str, Any] | None:
    """Extract the outermost {...} JSON object from LLM output (which may include prose/fences)."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
