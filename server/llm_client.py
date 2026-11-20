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
from pydantic import BaseModel, ValidationError

import config
from models import describe_validation_error
from prompts import STRICT_JSON_RETRY_TEMPLATE

logger = logging.getLogger(__name__)

# Chat message format ({"role": ..., "content": ...}); callers use this, not openai types.
ChatMessage = ChatCompletionMessageParam

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class LLMUnavailable(Exception):
    """No LLM is configured (local LLM disabled and no Gemini API key)."""


class LLMReplyInvalid(Exception):
    """The LLM's reply wasn't a JSON object matching the expected schema (after one retry)."""


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
    response_format: dict[str, Any] | None = None,
) -> str:
    """
    Send a chat request and return the reply text ("" if the model sent none).
    Raises LLMUnavailable if no LLM is configured; provider errors propagate.
    `purpose` is only used in log messages. `response_format` is passed through
    (complete_json uses it to request schema-shaped JSON).
    """
    chat = get_chat_client()
    if chat is None:
        raise LLMUnavailable()

    logger.debug(f"LLM {purpose} prompt: {messages}")
    started = time.perf_counter()
    extra: dict[str, Any] = {}
    if response_format is not None:
        extra["response_format"] = response_format
    response = chat.client.chat.completions.create(
        model=chat.model, messages=messages, temperature=temperature, **extra
    )
    logger.info(f"LLM {purpose} completed in {time.perf_counter() - started:.2f}s.")
    content = response.choices[0].message.content or ""
    logger.debug(f"LLM {purpose} reply: {content}")
    return content


def complete_json[ReplyModel: BaseModel](
    messages: list[ChatMessage], schema: type[ReplyModel], *, purpose: str
) -> ReplyModel:
    """
    Ask for a JSON reply shaped like `schema` and return it validated.

    The schema is sent as the response format (Ollama and Gemini can constrain their
    output to it). If the reply still isn't valid, the model gets one retry with a
    stricter prompt that lists what was wrong; a second failure raises LLMReplyInvalid.
    LLMUnavailable and provider errors propagate without a retry.
    """
    schema_json = schema.model_json_schema()
    response_format = {
        "type": "json_schema",
        "json_schema": {"name": schema.__name__, "schema": schema_json},
    }
    reply = complete(messages, purpose=purpose, response_format=response_format)
    try:
        return _validate_reply(reply, schema)
    except LLMReplyInvalid as problem:
        logger.warning(
            f"LLM {purpose} reply didn't match {schema.__name__} ({problem}); "
            "retrying once with a stricter prompt."
        )
        retry_prompt = STRICT_JSON_RETRY_TEMPLATE.format(
            problems=problem, schema_json=json.dumps(schema_json)
        )

    retry_messages: list[ChatMessage] = [
        *messages,
        {"role": "assistant", "content": reply},
        {"role": "user", "content": retry_prompt},
    ]
    reply = complete(
        retry_messages, purpose=f"{purpose} retry", response_format=response_format
    )
    return _validate_reply(reply, schema)


def _validate_reply[ReplyModel: BaseModel](
    reply: str, schema: type[ReplyModel]
) -> ReplyModel:
    parsed = parse_json_object_from_text(reply)
    if parsed is None:
        raise LLMReplyInvalid("the reply was not a JSON object")
    try:
        return schema.model_validate(parsed)
    except ValidationError as exc:
        raise LLMReplyInvalid(describe_validation_error(exc)) from exc


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
