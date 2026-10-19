"""Preset library operations (create, rename, duplicate, search, import/export)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from ..domain.presets import (
    BUNDLE_FORMAT,
    UNCATEGORIZED,
    Genre,
    Preset,
    PresetBundle,
)
from ..protocol.thr_v2 import filter_applicable
from ..storage.repository import PresetRepository

SEED_MARKER = ".starters_seeded"


@dataclass
class ImportResult:
    added: list[Preset] = field(default_factory=list)
    skipped: int = 0  # identical preset already in the library
    errors: list[str] = field(default_factory=list)


class PresetError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(p: Preset) -> tuple[str, str | None, tuple[tuple[str, int], ...]]:
    return (
        p.name.casefold(),
        p.genre.value if p.genre else None,
        tuple(sorted(p.settings.items())),
    )


class PresetManager:
    def __init__(self, repo: PresetRepository) -> None:
        self.repo = repo

    # -- queries -----------------------------------------------------------
    def all(self) -> list[Preset]:
        return sorted(self.repo.load_all(), key=lambda p: p.name.casefold())

    def get(self, preset_id: str) -> Preset | None:
        return self.repo.get(preset_id)

    def search(
        self,
        query: str = "",
        genre: Genre | str | None = None,
        favorites_only: bool = False,
    ) -> list[Preset]:
        """Case-insensitive; every word of *query* must match the name, genre or notes.

        *genre* may be a :class:`Genre` or the string ``"Uncategorized"``.
        """
        words = query.casefold().split()
        result = []
        for p in self.all():
            if favorites_only and not p.favorite:
                continue
            if genre is not None and p.genre_label != (
                genre.value if isinstance(genre, Genre) else genre
            ):
                continue
            haystack = f"{p.name} {p.genre_label} {p.notes}".casefold()
            if all(w in haystack for w in words):
                result.append(p)
        return result

    # -- mutations ---------------------------------------------------------
    def _require(self, preset_id: str) -> Preset:
        preset = self.repo.get(preset_id)
        if preset is None:
            raise PresetError(f"preset {preset_id!r} not found")
        return preset

    def _save(self, preset: Preset) -> Preset:
        preset.modified = _now()
        self.repo.save(preset)
        return preset

    def create(
        self,
        name: str,
        settings: dict[str, int],
        genre: Genre | None = None,
        notes: str = "",
    ) -> Preset:
        try:
            preset = Preset(
                name=name, settings=filter_applicable(settings), genre=genre, notes=notes
            )
        except ValidationError as exc:
            raise PresetError(str(exc)) from exc
        return self._save(preset)

    def update_settings(self, preset_id: str, settings: dict[str, int]) -> Preset:
        preset = self._require(preset_id)
        try:
            updated = Preset.model_validate(
                {**preset.model_dump(), "settings": filter_applicable(settings)}
            )
        except ValidationError as exc:
            raise PresetError(str(exc)) from exc
        return self._save(updated)

    def rename(self, preset_id: str, name: str) -> Preset:
        preset = self._require(preset_id)
        try:
            updated = Preset.model_validate({**preset.model_dump(), "name": name})
        except ValidationError as exc:
            raise PresetError(str(exc)) from exc
        return self._save(updated)

    def set_genre(self, preset_id: str, genre: Genre | None) -> Preset:
        preset = self._require(preset_id)
        preset.genre = genre
        return self._save(preset)

    def set_favorite(self, preset_id: str, favorite: bool) -> Preset:
        preset = self._require(preset_id)
        preset.favorite = favorite
        return self._save(preset)

    def duplicate(self, preset_id: str) -> Preset:
        src = self._require(preset_id)
        names = {p.name.casefold() for p in self.repo.load_all()}
        base = f"{src.name} (copy)"
        name, n = base, 2
        while name.casefold() in names:
            name, n = f"{base} {n}", n + 1
        copy = src.model_copy(
            update={"id": uuid4().hex, "name": name[:64], "favorite": False, "created": _now()}
        )
        return self._save(copy)

    def delete(self, preset_id: str) -> None:
        if not self.repo.delete(preset_id):
            raise PresetError(f"preset {preset_id!r} not found")

    # -- import / export ---------------------------------------------------
    def export_presets(self, preset_ids: list[str], path: str | Path) -> int:
        presets = [self._require(i) for i in preset_ids]
        bundle = PresetBundle(presets=presets)
        Path(path).write_text(
            json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return len(presets)

    def import_presets(self, path: str | Path) -> ImportResult:
        """Import a bundle or a single preset file. Imported presets get fresh ids."""
        result = ImportResult()
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result.errors.append(f"cannot read {path}: {exc}")
            return result
        if isinstance(raw, dict) and "presets" in raw:
            if raw.get("format", BUNDLE_FORMAT) != BUNDLE_FORMAT:
                result.errors.append(
                    f"not a THR Control preset file (format {raw.get('format')!r})"
                )
                return result
            items = raw["presets"]
        elif isinstance(raw, dict) and "settings" in raw:
            items = [raw]
        else:
            result.errors.append("not a THR Control preset file")
            return result
        if not isinstance(items, list):
            result.errors.append("'presets' must be a list")
            return result

        known = {_fingerprint(p) for p in self.repo.load_all()}
        for i, item in enumerate(items):
            try:
                preset = Preset.model_validate(item)
            except ValidationError as exc:
                first = exc.errors()[0]
                result.errors.append(f"preset #{i + 1}: {first['loc']}: {first['msg']}")
                continue
            if _fingerprint(preset) in known:
                result.skipped += 1
                continue
            preset = preset.model_copy(update={"id": uuid4().hex, "favorite": preset.favorite})
            self._save(preset)
            known.add(_fingerprint(preset))
            result.added.append(preset)
        return result

    # -- starter presets ---------------------------------------------------
    def seed_starters(self) -> list[Preset]:
        """Add the bundled starter presets once per library (deleting them keeps them gone)."""
        marker = self.repo.directory / SEED_MARKER
        if marker.exists():
            return []
        text = (
            resources.files("thr_control.data").joinpath("starter_presets.json").read_text("utf-8")
        )
        tmp = self.repo.directory.parent / ".starter_import.json"
        self.repo.directory.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        try:
            added = self.import_presets(tmp).added
        finally:
            tmp.unlink(missing_ok=True)
        marker.write_text("starter presets were added once\n", encoding="utf-8")
        return added


GENRE_FILTERS: list[str] = [g.value for g in Genre] + [UNCATEGORIZED]
