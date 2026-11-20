"""
Data shapes shared by the pipeline and the websocket API.

The front end's src/lib/types.ts mirrors these models; keep the two in sync.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MIN_RADIUS_M = 100
MAX_RADIUS_M = 5000

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


def describe_validation_error(exc: ValidationError) -> str:
    """One short line per problem, e.g. "lat: Input should be less than or equal to 90"."""
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        problems.append(f"{location}: {error['msg']}" if location else error["msg"])
    return "; ".join(problems)


class SearchRequest(BaseModel):
    """What the browser sends to /ws/analyze. The radius is clamped to a sane range."""

    model_config = ConfigDict(extra="ignore")

    lat: Annotated[FiniteFloat, Field(ge=-90, le=90)]
    lon: Annotated[FiniteFloat, Field(ge=-180, le=180)]
    radius: FiniteFloat = 500

    @field_validator("radius")
    @classmethod
    def clamp_radius(cls, value: float) -> int:
        return int(min(max(value, MIN_RADIUS_M), MAX_RADIUS_M))

    @property
    def origin(self) -> tuple[float, float]:
        return (self.lat, self.lon)


class LatLon(BaseModel):
    lat: float
    lon: float


class Bounds(BaseModel):
    minlat: float
    minlon: float
    maxlat: float
    maxlon: float


class RedFlag(BaseModel):
    """Something near a site that makes it less suitable (building, barrier, school...)."""

    type: str
    distance_to_red_flag_m: int
    tag: str


class Site(BaseModel):
    """
    A candidate camping site. Stages fill fields in as the search progresses, so
    everything except the identity and position is optional.
    """

    model_config = ConfigDict(extra="forbid")

    # Discover / summarise
    id: int
    type: Literal["node", "way", "relation"]
    lat: float
    lon: float
    terrain_description: str = "unknown"
    area_m2: float | None = None
    area_size_band: Literal["small", "medium", "large", "unknown"] = "unknown"
    distance_to_bbox_m: float | None = None
    nearby_red_flags: list[RedFlag] = []
    bounds: Bounds | None = None
    nearest_bbox_point: LatLon | None = None

    # Enrich
    distance_to_major_road_m: float | None = None
    distance_to_water_m: float | None = None

    # Score
    suitability_score: float | None = None
    suitability_reason: str | None = None

    # Outline
    geometry: list[LatLon] | None = None


# --------------------------------------------------------------------------- #
# Websocket messages (server -> browser)
# --------------------------------------------------------------------------- #


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    msg: str


class BatchMessage(BaseModel):
    """Sites so far (after discovery, then again after enrichment)."""

    type: Literal["batch"] = "batch"
    sites: list[Site]


class FinalMessage(BaseModel):
    """Scored sites plus the ids of the top picks, best first."""

    type: Literal["final"] = "final"
    sites: list[Site]
    refined_ids: list[int]


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    msg: str


ServerMessage = StatusMessage | BatchMessage | FinalMessage | ErrorMessage


# --------------------------------------------------------------------------- #
# LLM replies
# --------------------------------------------------------------------------- #


class Evaluation(BaseModel):
    """The LLM's verdict on one candidate site."""

    id: int  # numeric strings ("123") are accepted
    suitability_score: FiniteFloat
    reason: str = ""

    @field_validator("suitability_score")
    @classmethod
    def clamp_score(cls, value: float) -> float:
        return max(0.0, min(100.0, value))


class SelectionResponse(BaseModel):
    """What the selection prompt asks the LLM to return."""

    selected_ids: list[int] = []
    evaluations: list[Evaluation] = []


# --------------------------------------------------------------------------- #
# Plain-dict shapes used inside the pipeline
# --------------------------------------------------------------------------- #
# Stages pass dicts along and add keys as they go; BatchMessage/FinalMessage validate
# them against Site before anything is sent to the browser.

Coordinate = tuple[float, float]  # (lat, lon)
LatLonDict = dict[str, float]  # {"lat": ..., "lon": ...}
BoundsDict = dict[str, float]  # {"minlat", "minlon", "maxlat", "maxlon"}
OsmTags = dict[str, str]  # OpenStreetMap tags, e.g. {"natural": "wood"}
OsmElement = dict[str, Any]  # one element of an Overpass response
OverpassResponse = dict[str, Any]  # a whole Overpass JSON payload
SiteRecord = dict[str, Any]  # a candidate site; see Site for its fields
