"""Version 2 row, shared by the collector, CSV reader, SQLite writer and API."""

import re
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .source import profile_url

VERSION = 2
HEADERS = {
    "name": "Name",
    "url": "URL",
    "height": "Height",
    "weight": "Weight",
    "weight_class": "Weight Class",
    "reach": "Reach",
    "stance": "Stance",
    "dob": "DOB",
    "slpm": "SLpm",
    "stracc": "StrAcc",
    "sapm": "SApM",
    "strdef": "StrDef",
    "tdavg": "TDAvg",
    "tdacc": "TDAcc",
    "tddef": "TDDef",
    "subavg": "SubAvg",
    "record": "Record",
    "most_recent_fight": "Most Recent Fight",
    "fight_count": "FightCount",
    "fights_in_ufc": "FightsInUFC",
    "bad_sample": "BadSample",
    "fighter_id": "FighterID",
    "source_id": "SourceAthleteID",
    "portrait_url": "PortraitURL",
    "headshot_url": "HeadshotURL",
    "source": "Source",
    "last_fight_date": "LastFightDate",
    "history_status": "HistoryStatus",
    "status": "Status",
    "warnings": "Warnings",
    "favorite_aliases": "FavoriteAliases",
}


class Fighter(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=lambda key: HEADERS.get(key, key),
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )
    name: str = Field(min_length=1)
    url: str
    height: float | None = Field(None, gt=0, description="Height in inches")
    weight: float | None = Field(None, gt=0, description="Weight in pounds")
    weight_class: str | None = None
    reach: float | None = Field(None, gt=0, description="Reach in inches")
    stance: str | None = None
    dob: date | None = None
    slpm: float | None = Field(
        None, ge=0, description="Significant strikes landed per minute"
    )
    stracc: float | None = Field(
        None, ge=0, le=1, description="Significant striking accuracy, fraction"
    )
    sapm: float | None = Field(
        None, ge=0, description="Significant strikes absorbed per minute"
    )
    strdef: float | None = Field(
        None, ge=0, le=1, description="Significant strike defense, fraction"
    )
    tdavg: float | None = Field(None, ge=0, description="Takedowns per 15 minutes")
    tdacc: float | None = Field(
        None, ge=0, le=1, description="Takedown accuracy, fraction"
    )
    tddef: float | None = Field(
        None, ge=0, le=1, description="Takedown defense, fraction"
    )
    subavg: float | None = Field(
        None, ge=0, description="Displayed submission average per 15 minutes"
    )
    record: str | None = None
    most_recent_fight: int | None = Field(
        None,
        ge=0,
        description="Days since the latest completed UFC bout at snapshot date",
    )
    fight_count: int | None = Field(
        None, ge=0, description="Sum of displayed career wins, losses and draws"
    )
    fights_in_ufc: int | None = Field(
        None, ge=0, description="Completed UFC bouts in complete source history"
    )
    bad_sample: bool | None = Field(
        None, description="True below three completed UFC bouts; null for unknown count"
    )
    fighter_id: str = Field(
        pattern=r"^[a-zA-Z0-9_-]+$", description="Stable application and favorites key"
    )
    source_id: str | None = Field(
        None,
        pattern=r"^[1-9][0-9]*$",
        description="Explicit UFC.com Drupal athlete node ID",
    )
    portrait_url: str | None = None
    headshot_url: str | None = None
    source: Literal["UFC.com"]
    last_fight_date: date | None = None
    history_status: Literal["complete", "unknown", "incomplete"]
    status: str | None = None
    warnings: str | None = None
    favorite_aliases: str | None = Field(None, pattern=r"^[a-z0-9-]+( [a-z0-9-]+)*$")

    @field_validator("dob", "last_fight_date", mode="before")
    @classmethod
    def calendar_date(cls, value):
        if value is None or isinstance(value, date):
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Expected an explicit ISO calendar date")
        return date.fromisoformat(value)

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.url != profile_url(self.url)
            or not any(c.isalpha() for c in self.name)
            or self.name.lower() in {"unknown", "none", "null", "n/a"}
        ):
            raise ValueError("Invalid profile identity")
        if (self.history_status == "complete") != (self.fights_in_ufc is not None):
            raise ValueError("Count requires complete history")
        if self.bad_sample != (
            None if self.fights_in_ufc is None else self.fights_in_ufc < 3
        ):
            raise ValueError("Inconsistent sample flag")
        if self.record and not re.fullmatch(r"\d+-\d+-\d+", self.record):
            raise ValueError("Invalid W-L-D record")
        if self.fight_count != (
            sum(map(int, self.record.split("-"))) if self.record else None
        ):
            raise ValueError("Inconsistent fight count")
        has_bouts = bool(self.fights_in_ufc)
        if (self.last_fight_date is not None) != has_bouts or (
            self.most_recent_fight is not None
        ) != has_bouts:
            raise ValueError("Completed UFC history and recency fields disagree")
        for image in (self.portrait_url, self.headshot_url):
            if image and (
                urlsplit(image).scheme != "https" or not urlsplit(image).hostname
            ):
                raise ValueError("Invalid portrait URL")
        return self
