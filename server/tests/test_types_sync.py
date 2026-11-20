"""
src/lib/types.ts mirrors models.py by hand; this catches the two drifting apart.
Checks field names and which fields are optional (TypeScript `?`, i.e. Pydantic
fields with a None default that the server leaves out).
"""

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

import models

TYPES_TS = Path(__file__).resolve().parents[2] / "src" / "lib" / "types.ts"


def ts_interfaces() -> dict[str, dict[str, bool]]:
    """{interface name: {field name: optional?}} parsed from types.ts."""
    source = TYPES_TS.read_text()
    interfaces = {}
    for match in re.finditer(r"export interface (\w+) \{(.*?)\n\}", source, re.S):
        fields = re.findall(r"^\s+(\w+)(\??):", match.group(2), re.M)
        interfaces[match.group(1)] = {name: bool(q) for name, q in fields}
    return interfaces


@pytest.mark.parametrize(
    "model",
    [
        models.LatLon,
        models.Bounds,
        models.RedFlag,
        models.Site,
        models.SearchRequest,
        models.StatusMessage,
        models.BatchMessage,
        models.FinalMessage,
        models.ErrorMessage,
    ],
)
def test_typescript_interface_matches_pydantic_model(model: type[BaseModel]) -> None:
    ts_fields = ts_interfaces()[model.__name__]
    for name, field in model.model_fields.items():
        assert name in ts_fields, f"{model.__name__}.{name} is missing from types.ts"
        # None defaults are left out of messages, so TypeScript must mark them optional.
        sent_as_optional = not field.is_required() and field.default is None
        assert ts_fields[name] == sent_as_optional, (
            f"{model.__name__}.{name}: optional in types.ts should be {sent_as_optional}"
        )
    extra = set(ts_fields) - set(model.model_fields)
    assert not extra, f"types.ts has fields the server never sends: {extra}"
