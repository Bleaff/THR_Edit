"""Preset data model (Pydantic). Pure data: no I/O, no Qt, no MIDI."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..protocol import thr_v2

BUNDLE_FORMAT = "thr-control-preset"
BUNDLE_VERSION = 1
UNCATEGORIZED = "Uncategorized"


class Genre(StrEnum):
    BLUES = "Blues"
    JAZZ = "Jazz"
    BOSSA_NOVA = "Bossa Nova"
    INDIE = "Indie"
    ROCK = "Rock"
    AMBIENT = "Ambient"
    CLEAN = "Clean"


def _now() -> datetime:
    return datetime.now(UTC)


class Preset(BaseModel):
    """A named set of amplifier parameters.

    ``settings`` maps parameter names from ``thr_v2.PARAMETERS`` to user-unit values
    (switches are 0/1). A preset may contain only a subset of parameters; anything
    missing is left untouched when the preset is applied.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=64)
    device: str = "THR5"
    genre: Genre | None = None
    favorite: bool = False
    notes: str = Field(default="", max_length=1000)
    settings: dict[str, int]
    created: datetime = Field(default_factory=_now)
    modified: datetime = Field(default_factory=_now)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("settings")
    @classmethod
    def _valid_settings(cls, value: dict[str, int]) -> dict[str, int]:
        for name, v in value.items():
            param = thr_v2.PARAMETERS.get(name)
            if param is None:
                raise ValueError(f"unknown parameter {name!r}")
            param.to_wire(v)  # raises ValueError when out of range
        return value

    @property
    def genre_label(self) -> str:
        return self.genre.value if self.genre else UNCATEGORIZED


class PresetBundle(BaseModel):
    """Export/import container."""

    format: Literal["thr-control-preset"] = "thr-control-preset"
    version: int = BUNDLE_VERSION
    presets: list[Preset]


def apply_order(settings: dict[str, int]) -> list[tuple[str, int]]:
    """Order in which to write a preset: amp model first.

    Changing the amp model makes the amp re-apply its own cab/tone defaults, so it
    must go out before the individual parameters.
    """
    items = list(settings.items())
    return sorted(items, key=lambda kv: kv[0] != "amp")
