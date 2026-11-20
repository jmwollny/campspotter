import pytest
from pydantic import ValidationError

import select_sites
import summarise
from models import (
    MAX_RADIUS_M,
    MIN_RADIUS_M,
    BatchMessage,
    FinalMessage,
    SearchRequest,
    Site,
)


def test_search_request_parses_and_clamps():
    request = SearchRequest.model_validate_json(
        '{"lat": 51.3, "lon": -1.9, "radius": 800}'
    )
    assert request.origin == (51.3, -1.9)
    assert request.radius == 800
    assert SearchRequest(lat=0, lon=0, radius=1).radius == MIN_RADIUS_M
    assert SearchRequest(lat=0, lon=0, radius=10**9).radius == MAX_RADIUS_M
    assert SearchRequest(lat=0, lon=0).radius == 500


def test_search_request_ignores_unknown_fields():
    assert SearchRequest.model_validate({"lat": 1, "lon": 2, "zoom": 12}).origin == (
        1,
        2,
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[1, 2, 3]",
        '{"lon": -1}',
        '{"lat": 91, "lon": 0}',
        '{"lat": 0, "lon": -181}',
        '{"lat": "abc", "lon": 0}',
        '{"lat": NaN, "lon": 0}',
        '{"lat": 0, "lon": 0, "radius": Infinity}',
    ],
)
def test_search_request_rejects_bad_input(raw):
    with pytest.raises(ValidationError):
        SearchRequest.model_validate_json(raw)


def test_site_requires_identity_and_position_only():
    site = Site(id=1, type="way", lat=51.0, lon=-1.0)
    assert site.nearby_red_flags == []
    assert site.suitability_score is None


def test_site_rejects_unknown_fields():
    """Catches the pipeline and the front end drifting apart."""
    with pytest.raises(ValidationError):
        Site.model_validate(
            {"id": 1, "type": "way", "lat": 0, "lon": 0, "colour": "green"}
        )


def test_real_pipeline_output_matches_the_site_model(real_elements):
    sites = summarise.build_site_summaries(real_elements, (51.3224410, -1.8934199))
    select_sites.llm_select_geom_candidates(
        "criteria", sites
    )  # heuristic scores (no LLM in tests)
    sites[0]["geometry"] = [{"lat": 51.32, "lon": -1.89}, {"lat": 51.33, "lon": -1.88}]

    message = FinalMessage.model_validate(
        {"sites": sites, "refined_ids": [sites[0]["id"]]}
    )

    assert len(message.sites) == len(sites)
    # Round-trips without losing anything the pipeline produced.
    dumped = message.model_dump(mode="json", exclude_none=True)["sites"]
    for original, sent in zip(sites, dumped, strict=True):
        expected = {key: value for key, value in original.items() if value is not None}
        assert sent == expected


def test_batch_message_serialises_with_type():
    message = BatchMessage.model_validate(
        {"sites": [{"id": 1, "type": "node", "lat": 1, "lon": 2}]}
    )
    assert message.model_dump(mode="json", exclude_none=True) == {
        "type": "batch",
        "sites": [
            {
                "id": 1,
                "type": "node",
                "lat": 1.0,
                "lon": 2.0,
                "terrain_description": "unknown",
                "area_size_band": "unknown",
                "nearby_red_flags": [],
            }
        ],
    }
