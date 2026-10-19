import json

import pytest
from pydantic import ValidationError

from tests.fake_amp import FakeAmp, real_payload
from thr_control import cli
from thr_control.domain.presets import Genre, Preset, apply_order
from thr_control.protocol import thr_v2
from thr_control.services.controller import ThrController, apply_preset
from thr_control.services.preset_manager import PresetError, PresetManager
from thr_control.storage.repository import PresetRepository

SETTINGS = {"amp": 1, "gain": 40, "master": 50, "reverb": 1}


@pytest.fixture
def manager(tmp_path):
    return PresetManager(PresetRepository(tmp_path / "lib"))


# -- model ---------------------------------------------------------------
def test_preset_validation():
    p = Preset(name="  Warm   Jazz ", settings=SETTINGS)
    assert p.name == "Warm Jazz" and p.genre_label == "Uncategorized"
    for bad in (
        {"nope": 1},
        {"master": 101},
        {"amp": 5},
        {"delay": 2},
        {"master": -1},
    ):
        with pytest.raises(ValidationError):
            Preset(name="x", settings=bad)
    with pytest.raises(ValidationError):
        Preset(name="   ", settings={})
    with pytest.raises(ValidationError):
        Preset(name="x" * 65, settings={})
    with pytest.raises(ValidationError):
        Preset(id="../evil", name="x", settings={})


def test_apply_order_puts_amp_first():
    order = apply_order({"gain": 1, "reverb": 1, "amp": 2, "master": 3})
    assert order[0] == ("amp", 2) and len(order) == 4


# -- repository ----------------------------------------------------------
def test_repository_roundtrip_and_delete(tmp_path):
    repo = PresetRepository(tmp_path / "lib")
    p = Preset(name="A", genre=Genre.BLUES, favorite=True, settings=SETTINGS)
    repo.save(p)
    assert repo.get(p.id) == p
    assert repo.load_all() == [p]
    assert not list((tmp_path / "lib").glob(".tmp-*"))
    assert repo.delete(p.id) and not repo.delete(p.id)
    assert repo.get(p.id) is None


def test_repository_skips_corrupt_files(tmp_path):
    repo = PresetRepository(tmp_path)
    good = Preset(name="Good", settings=SETTINGS)
    repo.save(good)
    (tmp_path / "broken.json").write_text("{not json")
    (tmp_path / "bad_value.json").write_text(
        json.dumps({"id": "bad_value", "name": "Bad", "settings": {"master": 999}})
    )
    (tmp_path / "wrong_id.json").write_text(
        json.dumps({"id": "other", "name": "Mismatch", "settings": {}})
    )
    assert repo.load_all() == [good]
    assert len(repo.errors) == 3


def test_repository_rejects_path_traversal(tmp_path):
    repo = PresetRepository(tmp_path)
    for bad in ("../x", "a/b", "", "a.b"):
        with pytest.raises(ValueError):
            repo.get(bad)


# -- manager -------------------------------------------------------------
def test_create_rename_duplicate_delete(manager):
    p = manager.create("Lead", SETTINGS, Genre.ROCK)
    manager.rename(p.id, "Big Lead")
    assert manager.get(p.id).name == "Big Lead"
    d1, d2 = manager.duplicate(p.id), manager.duplicate(p.id)
    assert d1.name == "Big Lead (copy)" and d2.name == "Big Lead (copy) 2"
    assert d1.id != p.id and d1.settings == p.settings and d1.genre == Genre.ROCK
    manager.delete(d1.id)
    assert {x.name for x in manager.all()} == {"Big Lead", "Big Lead (copy) 2"}
    with pytest.raises(PresetError):
        manager.delete("missing")
    with pytest.raises(PresetError):
        manager.rename(p.id, "   ")
    with pytest.raises(PresetError):
        manager.create("bad", {"master": 500})


def test_update_settings_and_modified(manager):
    p = manager.create("A", SETTINGS)
    q = manager.update_settings(p.id, {"master": 10})
    assert q.settings == {"master": 10} and q.modified >= p.modified
    with pytest.raises(PresetError):
        manager.update_settings(p.id, {"master": 101})
    assert manager.get(p.id).settings == {"master": 10}  # failed update left it intact


def test_search_filters_genre_favorites(manager):
    a = manager.create("Warm Jazz", SETTINGS, Genre.JAZZ, notes="dark clean")
    b = manager.create("Texas Blues", SETTINGS, Genre.BLUES)
    c = manager.create("Mystery", SETTINGS)
    manager.set_favorite(b.id, True)
    names = lambda ps: [p.name for p in ps]  # noqa: E731
    assert names(manager.search()) == ["Mystery", "Texas Blues", "Warm Jazz"]
    assert names(manager.search("jazz")) == ["Warm Jazz"]
    assert names(manager.search("DARK clean")) == ["Warm Jazz"]
    assert names(manager.search("blues warm")) == []
    assert names(manager.search(genre=Genre.BLUES)) == ["Texas Blues"]
    assert names(manager.search(genre="Uncategorized")) == ["Mystery"]
    assert names(manager.search(favorites_only=True)) == ["Texas Blues"]
    manager.set_genre(c.id, Genre.AMBIENT)
    assert names(manager.search("ambient")) == ["Mystery"]
    assert a.id


def test_export_import_roundtrip(manager, tmp_path):
    a = manager.create("A", SETTINGS, Genre.CLEAN)
    b = manager.create("B", {"gain": 5})
    out = tmp_path / "export.json"
    assert manager.export_presets([a.id, b.id], out) == 2
    data = json.loads(out.read_text())
    assert data["format"] == "thr-control-preset" and len(data["presets"]) == 2

    other = PresetManager(PresetRepository(tmp_path / "other"))
    result = other.import_presets(out)
    assert len(result.added) == 2 and not result.errors
    assert {p.name for p in other.all()} == {"A", "B"}
    assert {p.id for p in other.all()}.isdisjoint({a.id, b.id})  # fresh ids
    again = other.import_presets(out)
    assert again.skipped == 2 and not again.added  # no duplicates on re-import


def test_import_single_preset_and_errors(manager, tmp_path):
    single = tmp_path / "one.json"
    single.write_text(json.dumps({"name": "Solo", "settings": {"gain": 3}}))
    assert len(manager.import_presets(single).added) == 1

    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps(
            {
                "presets": [
                    {"name": "Fine", "settings": {"gain": 9}},
                    {"name": "Bad", "settings": {"gain": 900}},
                    {"name": "Unknown", "settings": {"compressor_type": 1}},
                ]
            }
        )
    )
    res = manager.import_presets(mixed)
    assert [p.name for p in res.added] == ["Fine"] and len(res.errors) == 2

    for content in ("not json", "[1,2]", '{"hello": 1}', '{"format": "x", "presets": []}'):
        f = tmp_path / "bad.json"
        f.write_text(content)
        r = manager.import_presets(f)
        assert r.errors and not r.added
    assert manager.import_presets(tmp_path / "missing.json").errors


def _starter_entries():
    from importlib import resources

    raw = resources.files("thr_control.data").joinpath("starter_presets.json").read_text("utf-8")
    return json.loads(raw)["presets"]


def test_starter_presets_are_valid_and_cover_every_genre(manager):
    entries = _starter_entries()
    assert len(entries) >= 20
    assert len({e["starter_id"] for e in entries}) == len(entries)
    assert len({e["name"].casefold() for e in entries}) == len(entries)
    added = manager.seed_starters()
    assert len(added) == len(entries)
    assert {p.genre for p in added} == set(Genre)  # all seven genres have presets
    for p in added:
        assert p.notes  # every starter explains itself
        assert p.settings["master"] <= 60  # never ask for an unsafe loudness
        assert p.settings == thr_v2.filter_applicable(p.settings)


def test_starter_presets_seed_once_and_deleted_ones_stay_deleted(manager):
    added = manager.seed_starters()
    manager.delete(added[0].id)
    assert manager.seed_starters() == []
    assert len(manager.all()) == len(added) - 1


def test_upgrade_from_first_release_adds_only_new_starters(tmp_path):
    from thr_control.services.preset_manager import LEGACY_STARTER_IDS, SEED_MARKER

    repo = PresetRepository(tmp_path / "lib")
    repo.directory.mkdir(parents=True)
    (repo.directory / SEED_MARKER).write_text("starter presets were added once\n")  # old marker
    # the user already has (and may have deleted) the original five
    manager = PresetManager(repo)
    added = manager.seed_starters()
    names = {p.name for p in added}
    assert not names & {"Warm Jazz", "Texas Blues", "Indie Clean", "Golden Brown", "Indie Rock"}
    assert len(added) == len(_starter_entries()) - len(LEGACY_STARTER_IDS)
    assert manager.seed_starters() == []  # and nothing more on the next start


def test_set_notes(manager):
    p = manager.create("N", SETTINGS)
    q = manager.set_notes(p.id, "slow and dark")
    assert manager.get(p.id).notes == "slow and dark" and q.modified >= p.modified
    assert [x.name for x in manager.search("dark")] == ["N"]  # notes are searchable
    with pytest.raises(PresetError):
        manager.set_notes(p.id, "x" * 1001)
    assert manager.get(p.id).notes == "slow and dark"


# -- applying to an amp --------------------------------------------------
def test_apply_preset_to_fake_amp_amp_first(manager):
    amp = FakeAmp(real_payload())
    preset = manager.create("P", {"gain": 11, "reverb": 1, "amp": 3, "master": 44})
    assert apply_preset(ThrController(amp, settle=0), preset, amp_settle=0) == []
    assert amp.sets[0] == ("amp", 3)
    final = dict(amp.sets)
    assert final == {"amp": 3, "gain": 11, "reverb": 1, "master": 44}


def test_apply_preset_reports_mismatch(manager):
    amp = FakeAmp(real_payload())
    amp.ignore_sets = True
    preset = manager.create("P", {"gain": 11})
    bad = apply_preset(ThrController(amp, settle=0), preset, amp_settle=0)
    assert [r.name for r in bad] == ["gain"]


# -- CLI -----------------------------------------------------------------
def test_cli_presets_list_export_import_apply_dry_run(tmp_path, capsys):
    lib = str(tmp_path / "lib")
    assert cli.main(["presets", "list", "--library", lib]) == 0
    out = capsys.readouterr().out
    assert "Warm Jazz" in out and "Indie Rock" in out
    assert cli.main(["presets", "list", "--library", lib, "--query", "blues"]) == 0
    assert capsys.readouterr().out.count("\n") == 3  # Delta Blues, Slow Blues Crunch, Texas Blues
    export = str(tmp_path / "all.json")
    assert cli.main(["presets", "export", export, "--library", lib]) == 0
    assert cli.main(["presets", "import", export, "--library", str(tmp_path / "lib2")]) == 0
    assert cli.main(["presets", "apply", "warm jazz", "--library", lib]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert cli.main(["presets", "apply", "nothing", "--library", lib]) == 1
    assert cli.main(["presets", "apply", "--library", lib]) == 1


def test_apply_order_types_and_cab_before_their_parameters():
    order = [
        n
        for n, _ in apply_order(
            {
                "modulation_p1": 5,
                "gain": 1,
                "cab": 2,
                "modulation_type": 3,
                "reverb_type": 1,
                "amp": 4,
                "modulation": 1,
            }
        )
    ]
    assert order[0] == "amp"
    assert set(order[1:4]) == {"cab", "modulation_type", "reverb_type"}
    assert order.index("modulation_type") < order.index("modulation_p1")


def test_presets_never_store_or_apply_values_for_another_reverb_type(manager):
    p = manager.create("Mixed", {"reverb_type": 0, "reverb_time": 50, "reverb_spring_reverb": 40})
    assert p.settings == {"reverb_type": 0, "reverb_time": 50}  # spring value dropped on save
    q = manager.update_settings(
        p.id, {"reverb_type": 3, "reverb_time": 50, "reverb_spring_filter": 9}
    )
    assert q.settings == {"reverb_type": 3, "reverb_spring_filter": 9}
    # a hand-edited / imported file that includes both is filtered again at apply time
    sneaky = Preset(name="s", settings={"reverb_type": 0, "reverb_spring_reverb": 40, "gain": 5})
    assert dict(apply_order(sneaky.settings)) == {"reverb_type": 0, "gain": 5}
    assert dict(apply_order({"reverb_time": 30, "gain": 5})) == {"gain": 5}  # no type: skip
