import logging
import re
from pathlib import Path

import pytest

import config
from config import Settings


def test_defaults_when_nothing_is_set(monkeypatch):
    # conftest sets these two for isolation; remove them to see the real defaults.
    monkeypatch.delenv("LOCAL_LLM_ENABLED")
    monkeypatch.delenv("OVERPASS_QUERY_DEBUG_FILE")
    settings = Settings.from_env()
    assert settings == Settings()
    assert settings.local_llm_enabled is True
    assert settings.overpass_urls[0] == "https://overpass-api.de/api/interpreter"
    assert settings.llm_candidate_pool_size == 10
    assert settings.min_distance_to_hazard_m == 150
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)


def test_values_are_read_and_converted(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("OVERPASS_URLS", " https://a.example , ,https://b.example")
    monkeypatch.setenv("OVERPASS_READ_TIMEOUT_S", "42.5")
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "No")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("LLM_CANDIDATE_POOL_SIZE", "30")
    monkeypatch.setenv("PORT", "9000")
    settings = Settings.from_env()
    assert settings.log_level == "DEBUG"
    assert settings.overpass_urls == ("https://a.example", "https://b.example")
    assert settings.overpass_read_timeout_s == 42.5
    assert settings.local_llm_enabled is False
    assert settings.gemini_api_key == "secret-key"
    assert settings.llm_candidate_pool_size == 30
    assert settings.port == 9000


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("YES", True), ("on", True), ("0", False), ("nope", False)],
)
def test_boolean_values(monkeypatch, raw, expected):
    monkeypatch.setenv("LOCAL_LLM_ENABLED", raw)
    assert Settings.from_env().local_llm_enabled is expected


def test_invalid_numbers_fall_back_to_defaults_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("LLM_TIMEOUT_S", "two minutes")
    monkeypatch.setenv("PORT", "eighty")
    with caplog.at_level(logging.WARNING, logger="config"):
        settings = Settings.from_env()
    assert settings.llm_timeout_s == 120
    assert settings.port == 8000
    assert "LLM_TIMEOUT_S" in caplog.text and "PORT" in caplog.text


@pytest.mark.parametrize(
    "name, field",
    [
        ("LLM_CANDIDATE_POOL_SIZE", "llm_candidate_pool_size"),
        ("OVERPASS_MAX_ROUNDS", "overpass_max_rounds"),
    ],
)
def test_counts_are_at_least_one(monkeypatch, name, field):
    monkeypatch.setenv(name, "0")
    assert getattr(Settings.from_env(), field) == 1


def test_empty_gemini_key_means_no_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert Settings.from_env().gemini_api_key is None


def test_secrets_are_not_in_repr(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-gemini")
    monkeypatch.setenv("OLLAMA_API_KEY", "super-secret-ollama")
    text = repr(Settings.from_env())
    assert "super-secret" not in text


def test_get_settings_is_cached_until_cleared(monkeypatch):
    monkeypatch.setenv("PORT", "1111")
    config.get_settings.cache_clear()
    assert config.get_settings().port == 1111
    monkeypatch.setenv("PORT", "2222")
    assert config.get_settings().port == 1111
    config.get_settings.cache_clear()
    assert config.get_settings().port == 2222
    config.get_settings.cache_clear()


def test_env_vars_lists_everything_from_env_reads():
    source = Path(config.__file__).read_text()
    from_env = source[source.index("def from_env") :]
    read = set(re.findall(r'"([A-Z][A-Z_]+)"', from_env)) - {"INFO"}
    assert read == set(config.ENV_VARS)
