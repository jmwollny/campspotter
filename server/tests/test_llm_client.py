import pytest

import config
import llm_client
from tests.conftest import FakeLLM, use_llm


def test_get_chat_client_picks_ollama_then_gemini_then_none(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("OLLAMA_MODEL", "my-model")
    monkeypatch.setenv("LLM_TIMEOUT_S", "45")
    chat = llm_client.get_chat_client()
    assert chat is not None
    assert (chat.model, chat.provider) == ("my-model", "ollama")
    assert "11434" in str(chat.client.base_url)
    assert chat.client.timeout == 45

    monkeypatch.setenv("LOCAL_LLM_ENABLED", "false")
    assert llm_client.get_chat_client() is None

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    chat = llm_client.get_chat_client()
    assert chat is not None
    assert (chat.model, chat.provider) == (config.DEFAULT_GEMINI_MODEL, "gemini")
    assert "googleapis" in str(chat.client.base_url)


def test_complete_raises_when_no_llm_is_configured():
    with pytest.raises(llm_client.LLMUnavailable):
        llm_client.complete([{"role": "user", "content": "hi"}], purpose="test")


def test_complete_sends_messages_and_returns_text(monkeypatch):
    fake = FakeLLM("hello")
    use_llm(monkeypatch, fake)
    messages: list[llm_client.ChatMessage] = [{"role": "user", "content": "hi"}]
    assert llm_client.complete(messages, purpose="test", temperature=0.3) == "hello"
    assert fake.calls == [
        {"model": "fake-model", "messages": messages, "temperature": 0.3}
    ]


def test_complete_returns_empty_string_for_no_content(monkeypatch):
    use_llm(monkeypatch, FakeLLM(None))
    assert llm_client.complete([], purpose="test") == ""


def test_complete_lets_provider_errors_propagate(monkeypatch):
    use_llm(monkeypatch, FakeLLM(error=ConnectionError("ollama down")))
    with pytest.raises(ConnectionError):
        llm_client.complete([], purpose="test")


@pytest.mark.parametrize(
    "text, expected",
    [
        ('```json\n{"selected_ids": [1]}\n```', {"selected_ids": [1]}),
        ('Sure! {"a": {"b": 2}} hope that helps', {"a": {"b": 2}}),
        ("no json here", None),
        ("{not valid}", None),
        ('["a", "list"]', None),
        ("", None),
        (None, None),
    ],
)
def test_parse_json_object_from_text(text, expected):
    assert llm_client.parse_json_object_from_text(text) == expected
