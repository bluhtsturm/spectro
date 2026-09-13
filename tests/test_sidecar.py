"""Sidecar-Ablage: Wiederverwendung und Ungültigkeit."""

import json

import pytest

from app import core
from app.sidecar import SidecarStore


@pytest.fixture
def store(tmp_path):
    return SidecarStore(tmp_path / "index")


class TestAblage:
    def test_speichern_und_laden(self, store, fullband):
        assert store.save("musik", "a/b.flac", fullband, "quickcheck:60", {"x": 1})
        assert store.load("musik", "a/b.flac", fullband, "quickcheck:60") == {"x": 1}

    def test_andere_art_wird_nicht_verwechselt(self, store, fullband):
        store.save("musik", "b.flac", fullband, "quickcheck:60", {"x": 1})
        assert store.load("musik", "b.flac", fullband, "quickcheck:30") is None

    def test_geaenderte_datei_macht_den_eintrag_ungueltig(self, store, media, fullband):
        import shutil
        kopie = media / "kopie.flac"
        shutil.copy(fullband, kopie)
        store.save("musik", "kopie.flac", kopie, "q", {"x": 1})
        assert store.load("musik", "kopie.flac", kopie, "q") == {"x": 1}
        kopie.touch()                              # nur die Änderungszeit
        assert store.load("musik", "kopie.flac", kopie, "q") is None

    def test_neue_analyseversion_macht_den_eintrag_ungueltig(self, store, fullband):
        """Sonst zeigt das Programm nach einem Update alte Bewertungen."""
        store.save("musik", "c.flac", fullband, "q", {"x": 1})
        core.ANALYSIS_VERSION += 1
        try:
            assert store.load("musik", "c.flac", fullband, "q") is None
        finally:
            core.ANALYSIS_VERSION -= 1

    def test_pfade_verschiedener_ordner_kollidieren_nicht(self, store, fullband):
        store.save("musik", "gleich.flac", fullband, "q", {"quelle": "musik"})
        store.save("rips", "gleich.flac", fullband, "q", {"quelle": "rips"})
        assert store.load("musik", "gleich.flac", fullband, "q")["quelle"] == "musik"
        assert store.load("rips", "gleich.flac", fullband, "q")["quelle"] == "rips"

    def test_gleicher_name_in_verschiedenen_unterordnern(self, store, fullband):
        store.save("m", "a/track.flac", fullband, "q", {"n": 1})
        store.save("m", "b/track.flac", fullband, "q", {"n": 2})
        assert store.load("m", "a/track.flac", fullband, "q")["n"] == 1
        assert store.load("m", "b/track.flac", fullband, "q")["n"] == 2

    def test_ausbruch_ueber_den_pfad_ist_nicht_moeglich(self, store, fullband):
        store.save("m", "../../boese.flac", fullband, "q", {"n": 1})
        eintraege = list(store.base.rglob("*.json"))
        assert eintraege
        for e in eintraege:
            assert store.base in e.parents

    def test_defekter_eintrag_wird_ignoriert(self, store, fullband):
        store.save("m", "d.flac", fullband, "q", {"n": 1})
        ziel = store.path_for("m", "d.flac")
        ziel.write_text("{kein json")
        assert store.load("m", "d.flac", fullband, "q") is None

    def test_abgeschaltet_liefert_nichts(self, fullband):
        aus = SidecarStore(None)
        assert aus.enabled is False
        assert aus.save("m", "x.flac", fullband, "q", {"n": 1}) is False
        assert aus.load("m", "x.flac", fullband, "q") is None
        assert aus.stats()["enabled"] is False

    def test_statistik_und_leeren(self, store, fullband):
        for i in range(3):
            store.save("m", f"t{i}.flac", fullband, "q", {"n": i})
        st = store.stats()
        assert st["entries"] == 3 and st["bytes"] > 0
        assert store.clear() == 3
        assert store.stats()["entries"] == 0

    def test_eintrag_ist_lesbares_json(self, store, fullband):
        store.save("m", "l.flac", fullband, "quickcheck:60", {"n": 1})
        daten = json.loads(store.path_for("m", "l.flac").read_text(encoding="utf-8"))
        assert daten["kind"] == "quickcheck:60"
        assert daten["analysis_version"] == core.ANALYSIS_VERSION
        assert daten["result"] == {"n": 1}
