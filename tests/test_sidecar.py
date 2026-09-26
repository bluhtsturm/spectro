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


class TestSchreibbarkeit:
    """Ein Ordner kann bestehen und trotzdem nicht beschreibbar sein.

    Vorher meldete sich die Ablage in diesem Fall als aktiv, verwarf aber
    jeden Eintrag – der Scan rechnete jedes Mal alles neu, ohne dass es
    irgendwo auffiel. Aufgefallen ist es erst auf einem CI-Läufer, der den
    Vorgabepfad nicht anlegen durfte.
    """

    def test_nicht_beschreibbarer_ordner_wird_abgelehnt(self, tmp_path):
        import os
        gesperrt = tmp_path / "gesperrt"
        gesperrt.mkdir()
        gesperrt.chmod(0o555)
        try:
            if os.getuid() == 0:
                pytest.skip("als root sind auch schreibgeschützte Ordner offen")
            with pytest.raises(OSError):
                SidecarStore(gesperrt)
        finally:
            gesperrt.chmod(0o755)

    def test_probe_hinterlaesst_nichts(self, tmp_path):
        ort = tmp_path / "neu"
        SidecarStore(ort)
        assert list(ort.iterdir()) == []

    def test_neuer_ordner_wird_angelegt(self, tmp_path):
        ablage = SidecarStore(tmp_path / "a" / "b" / "c")
        assert ablage.enabled and (tmp_path / "a" / "b" / "c").is_dir()


class TestAufraeumen:
    """Einträge, die nie wieder gelten können, verschwinden auf Wunsch."""

    def test_geloeschte_und_geaenderte_quellen(self, store, media, fullband):
        import shutil

        from app.sidecar import FREMD
        ordner = media / "aufraeumen"
        ordner.mkdir(exist_ok=True)
        bleibt, weg, anders = (ordner / n for n in ("bleibt.flac", "weg.flac", "anders.flac"))
        for f in (bleibt, weg, anders):
            shutil.copy(fullband, f)
            store.save("m", f.name, f, "q", {"n": 1})
        store.save("fremd", "x.flac", fullband, "q", {"n": 1})
        store.save("umbenannt", "y.flac", fullband, "q", {"n": 1})
        weg.unlink()
        anders.write_bytes(b"neuer Inhalt")

        def quelle(root, rel):
            if root == "m":
                return ordner / rel
            return FREMD if root == "fremd" else None

        stand = store.prune(quelle)
        assert stand == {"checked": 5, "removed": 3, "kept": 2}
        assert store.load("m", "bleibt.flac", bleibt, "q") == {"n": 1}
        assert store.load("fremd", "x.flac", fullband, "q") == {"n": 1}
        shutil.rmtree(ordner)

    def test_alte_analyseversion(self, store, fullband):
        store.save("m", "v.flac", fullband, "q", {"n": 1})
        core.ANALYSIS_VERSION += 1
        try:
            assert store.prune(lambda root, rel: fullband)["removed"] == 1
        finally:
            core.ANALYSIS_VERSION -= 1

    def test_leere_ordner_verschwinden(self, store, fullband):
        store.save("m", "tief/unten/z.flac", fullband, "q", {"n": 1})
        store.clear()
        assert list(store.base.iterdir()) == []


class TestWurzelnamen:
    def test_ordnerschluessel_der_oberflaeche_bleiben_lesbar(self, store):
        """Sonst wäre nach dem Update jede vorhandene Ablage verwaist."""
        assert store.path_for("vinyl-rips", "a.flac").parent.name == "vinyl-rips"

    def test_absolute_pfade_kollidieren_nicht(self, store):
        a = store.path_for("/srv/a b", "x.flac").parent.name
        b = store.path_for("/srv/a_b", "x.flac").parent.name
        assert a != b

    def test_lange_pfade_bleiben_benennbar(self, store, fullband):
        lang = "/" + "/".join(["verzeichnis"] * 40)
        assert len(store.path_for(lang, "x.flac").parent.name) < 100
        assert store.save(lang, "x.flac", fullband, "q", {"n": 1})
