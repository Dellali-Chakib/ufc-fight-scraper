from pydantic import BaseModel, ConfigDict, Field

from scraper.contract import Fighter


class FighterSchema(Fighter):
    """Normalized UFC.com athlete plus the stable numeric API route ID."""

    model_config = ConfigDict(alias_generator=lambda key: key)
    id: int = Field(description="SQLite integer route ID", alias="id")


class LegacyFighter(BaseModel):
    """Read-only compatibility with the previous publication during migration."""

    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    url: str
    weight: str | None
    height: int | None
    reach: int | None
    weight_class: str | None
    stance: str | None
    dob: str | None
    slpm: float | None
    sapm: float | None
    stracc: float | None
    strdef: float | None
    tdavg: float | None
    tddef: float | None
    tdacc: float | None
    subavg: float | None
    record: str | None
    most_recent_fight: int | None
    fights_in_ufc: str | None
    fight_count: int | None
    bad_sample: bool | None


class FighterListResponse(BaseModel):
    count: int
    fighters: list[FighterSchema | LegacyFighter]


class FighterDetailResponse(BaseModel):
    fighter: FighterSchema | LegacyFighter


class MessageResponse(BaseModel):
    message: str
    success: bool
