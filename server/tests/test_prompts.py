import json
import os
import string

import pytest

import prompts
import select_sites
import summarise
from tests.conftest import FIXTURES, FakeLLM, use_llm

SNAPSHOT = FIXTURES / "prompts_snapshot.json"


def render_prompts(monkeypatch, real_elements) -> list:
    """Every message the app sends to the LLM during one search, in order."""
    sites = summarise.summarise_sites(real_elements, (51.3224410, -1.8934199))
    fake = FakeLLM('{"selected_ids": [], "evaluations": []}')
    use_llm(monkeypatch, fake)
    select_sites.get_camping_criteria()
    select_sites.score_and_select_sites("CRITERIA TEXT", sites)
    return [call["messages"] for call in fake.calls]


def test_prompts_match_the_snapshot(monkeypatch, real_elements):
    """
    Fails whenever prompt wording or the data sent to the LLM changes, so prompt changes
    are always deliberate (CLAUDE.md). If the change is intended, regenerate with:

        UPDATE_PROMPT_SNAPSHOT=1 uv run pytest tests/test_prompts.py

    and say what changed and why in the commit message.
    """
    rendered = render_prompts(monkeypatch, real_elements)
    if os.getenv("UPDATE_PROMPT_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(rendered, indent=1))
    assert rendered == json.loads(SNAPSHOT.read_text())


@pytest.mark.parametrize(
    "template, placeholders",
    [
        (prompts.SELECTION_SYSTEM_TEMPLATE, {"criteria"}),
        (prompts.SELECTION_USER_TEMPLATE, {"max_candidates", "candidates_json"}),
        (prompts.CRITERIA_PROMPT, set()),
        (prompts.DEFAULT_CRITERIA, set()),
    ],
)
def test_templates_use_only_their_placeholders(template, placeholders):
    fields = {field for _, field, _, _ in string.Formatter().parse(template) if field}
    assert fields == placeholders


def test_braces_in_substituted_text_are_kept_literally():
    criteria = "- avoid {roads} and {} JSON-ish text"
    rendered = prompts.SELECTION_SYSTEM_TEMPLATE.format(criteria=criteria)
    assert criteria in rendered
