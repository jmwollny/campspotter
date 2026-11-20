"""
Server settings, read from environment variables (and server/.env) in one place.

Every setting is optional; see .env.example for what each one does. Call
get_settings() to read them; the result is cached, so call
get_settings.cache_clear() after changing the environment (tests do this).
"""

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

# Load server/.env (or the nearest .env above the current directory) once, at import.
# Existing environment variables win over values in the file.
load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
)
DEFAULT_OLLAMA_MODEL = "gemma4:e2b"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

TRUE_VALUES = {"1", "true", "yes", "on"}

# Every environment variable Settings.from_env reads (tests clear these).
ENV_VARS = (
    "LOG_LEVEL",
    "OVERPASS_URLS",
    "OVERPASS_CONNECT_TIMEOUT_S",
    "OVERPASS_READ_TIMEOUT_S",
    "OVERPASS_MAX_ROUNDS",
    "OVERPASS_BACKOFF_S",
    "OVERPASS_RETRY_MIN_DELAY_S",
    "OVERPASS_RETRY_MAX_DELAY_S",
    "OVERPASS_QUERY_DEBUG_FILE",
    "LOCAL_LLM_ENABLED",
    "OLLAMA_BASE_URL",
    "OLLAMA_API_KEY",
    "OLLAMA_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "LLM_TIMEOUT_S",
    "LLM_CANDIDATE_POOL_SIZE",
    "MIN_DISTANCE_TO_HAZARD",
    "HOST",
    "PORT",
)


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        logger.warning(f"Ignoring invalid {name}={raw!r}; using {default}.")
        value = default
    return max(minimum, value) if minimum is not None else value


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        logger.warning(f"Ignoring invalid {name}={raw!r}; using {default}.")
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in TRUE_VALUES


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    items = tuple(
        item.strip() for item in os.getenv(name, "").split(",") if item.strip()
    )
    return items or default


@dataclass(frozen=True)
class Settings:
    # Logging
    log_level: str = "INFO"

    # Overpass (OpenStreetMap)
    overpass_urls: tuple[str, ...] = DEFAULT_OVERPASS_MIRRORS
    overpass_connect_timeout_s: float = 10
    overpass_read_timeout_s: float = 100
    overpass_max_rounds: int = 3
    overpass_backoff_s: float = 3
    overpass_retry_min_delay_s: float = 0.5
    overpass_retry_max_delay_s: float = 1.5
    overpass_query_debug_file: str = "overpass_query_log.txt"

    # LLM
    local_llm_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_api_key: str = field(default="ollama", repr=False)
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    gemini_api_key: str | None = field(default=None, repr=False)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    llm_timeout_s: float = 120
    llm_candidate_pool_size: int = 10

    # Scoring
    min_distance_to_hazard_m: int = 150

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            log_level=_env_str("LOG_LEVEL", defaults.log_level).upper(),
            overpass_urls=_env_list("OVERPASS_URLS", defaults.overpass_urls),
            overpass_connect_timeout_s=_env_float(
                "OVERPASS_CONNECT_TIMEOUT_S", defaults.overpass_connect_timeout_s
            ),
            overpass_read_timeout_s=_env_float(
                "OVERPASS_READ_TIMEOUT_S", defaults.overpass_read_timeout_s
            ),
            overpass_max_rounds=_env_int(
                "OVERPASS_MAX_ROUNDS", defaults.overpass_max_rounds, minimum=1
            ),
            overpass_backoff_s=_env_float(
                "OVERPASS_BACKOFF_S", defaults.overpass_backoff_s
            ),
            overpass_retry_min_delay_s=_env_float(
                "OVERPASS_RETRY_MIN_DELAY_S", defaults.overpass_retry_min_delay_s
            ),
            overpass_retry_max_delay_s=_env_float(
                "OVERPASS_RETRY_MAX_DELAY_S", defaults.overpass_retry_max_delay_s
            ),
            overpass_query_debug_file=_env_str(
                "OVERPASS_QUERY_DEBUG_FILE", defaults.overpass_query_debug_file
            ),
            local_llm_enabled=_env_bool(
                "LOCAL_LLM_ENABLED", defaults.local_llm_enabled
            ),
            ollama_base_url=_env_str("OLLAMA_BASE_URL", defaults.ollama_base_url),
            ollama_api_key=_env_str("OLLAMA_API_KEY", defaults.ollama_api_key),
            ollama_model=_env_str("OLLAMA_MODEL", defaults.ollama_model),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model=_env_str("GEMINI_MODEL", defaults.gemini_model),
            llm_timeout_s=_env_float("LLM_TIMEOUT_S", defaults.llm_timeout_s),
            llm_candidate_pool_size=_env_int(
                "LLM_CANDIDATE_POOL_SIZE", defaults.llm_candidate_pool_size, minimum=1
            ),
            min_distance_to_hazard_m=_env_int(
                "MIN_DISTANCE_TO_HAZARD", defaults.min_distance_to_hazard_m
            ),
            host=_env_str("HOST", defaults.host),
            port=_env_int("PORT", defaults.port),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def configure_logging() -> None:
    """Root logging for the server (LOG_LEVEL), with timestamps."""
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        force=True,
    )
