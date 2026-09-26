"""Kommandozeile: sie muss dasselbe sagen wie Oberfläche und API."""

import json
import sys

import pytest

import spectro
from app import band, core
from app.sidecar import SidecarStore


def starten(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["spectro.py", *map(str, argv)])
    return spectro.main()


class TestBandurteil:
    def test_cutoff_urteilt_bei_der_bezugsaufloesung(self, lossy, capsys, monkeypatch):
        """--cutoff bewertet wie der Bericht bei REFERENCE_NFFT, nicht bei der
        FFT-Größe des Bildes (Standard 2048). Die Lage einer Steilkante hängt
        vom Analysefenster ab - sonst könnten CLI und Oberfläche für dieselbe
        Datei verschiedene Urteile fällen."""
        aufloesungen = []
        original = band.band_analysis

        def mitschreiben(mag, sr, nfft, *args, **kwargs):
            aufloesungen.append(nfft)
            return original(mag, sr, nfft, *args, **kwargs)

        monkeypatch.setattr(band, "band_analysis", mitschreiben)
        monkeypatch.setattr(sys, "argv", ["spectro.py", "--cutoff", "--no-image",
                                          "--lang", "de", str(lossy)])
        assert spectro.main() == 0
        assert aufloesungen == [core.REFERENCE_NFFT]

        erwartet = core.band_report(str(lossy), core.Params(lang="de"))
        assert erwartet["verdict"]["text"] in capsys.readouterr().out

    @pytest.mark.parametrize("fft", ["2048", "8192"])
    def test_urteil_wie_im_bericht(self, lossy, capsys, monkeypatch, fft):
        monkeypatch.setattr(sys, "argv", ["spectro.py", "--cutoff", "--no-image",
                                          "--fft", fft, "--lang", "en", str(lossy)])
        assert spectro.main() == 0
        bericht = core.summary(str(lossy), core.Params(nfft=int(fft), lang="en"),
                               with_loudness=False)
        assert bericht["verdict"]["text"] in capsys.readouterr().out


@pytest.fixture
def sammlung(tmp_path, fullband, lossy, broken):
    import shutil
    ordner = tmp_path / "sammlung"
    (ordner / "b").mkdir(parents=True)
    shutil.copy(fullband, ordner / "a.flac")
    shutil.copy(lossy, ordner / "b" / "c.mp3")
    shutil.copy(broken, ordner / "b" / "d.flac")
    shutil.copy(fullband, ordner / "e.flac")
    return ordner


class TestScan:
    def test_parallel_wie_nacheinander(self, sammlung, capsys, monkeypatch):
        """Mehrere Arbeits-Threads ändern weder Ergebnis noch Reihenfolge."""
        ergebnisse = []
        for jobs in (1, 3):
            assert starten(monkeypatch, "--scan", sammlung, "--json", "--seconds", 5,
                           "-j", jobs) == 1                  # d.flac ist kaputt
            ergebnisse.append(json.loads(capsys.readouterr().out))
        einzeln, parallel = ergebnisse
        assert [f["path"] for f in parallel["files"]] == \
            ["a.flac", "b/c.mp3", "b/d.flac", "e.flac"]
        assert parallel == einzeln

    def test_unerwarteter_fehler_beendet_den_scan_nicht(self, sammlung, capsys,
                                                         monkeypatch):
        original = core.quickcheck

        def mal_so_mal_so(pfad, *args, **kwargs):
            if pfad.endswith("a.flac"):
                raise RuntimeError("ganz unerwartet")
            return original(pfad, *args, **kwargs)

        monkeypatch.setattr(core, "quickcheck", mal_so_mal_so)
        assert starten(monkeypatch, "--scan", sammlung, "--json", "--seconds", 5) == 1
        d = json.loads(capsys.readouterr().out)
        fehler = {f["path"]: f.get("error") for f in d["files"]}
        assert "ganz unerwartet" in fehler["a.flac"]
        assert fehler["e.flac"] is None

    def test_ablage_trennt_die_scan_ordner(self, tmp_path, sammlung, fullband, capsys,
                                           monkeypatch):
        """Früher landeten alle Ordner unter demselben Schlüssel "cli"."""
        import shutil
        zweiter = tmp_path / "zweiter"
        zweiter.mkdir()
        shutil.copy(fullband, zweiter / "a.flac")
        index = tmp_path / "index"
        for ordner in (sammlung, zweiter):
            starten(monkeypatch, "--scan", ordner, "--index", index, "--seconds", 5, "-q")
        wurzeln = {json.loads(f.read_text())["root"] for f in index.rglob("*.json")}
        assert wurzeln == {str(sammlung), str(zweiter)}
        capsys.readouterr()


class TestAufraeumen:
    def test_prune_entfernt_geloeschte_und_alte_eintraege(self, tmp_path, sammlung,
                                                           fullband, capsys, monkeypatch):
        index = tmp_path / "index"
        starten(monkeypatch, "--scan", sammlung, "--index", index, "--seconds", 5, "-q")
        ablage = SidecarStore(index)
        ablage.save("cli", "alt.flac", fullband, "q", {"n": 1})      # frühere Fassung
        ablage.save("musik", "web.flac", fullband, "q", {"n": 1})    # Weboberfläche
        (sammlung / "e.flac").unlink()
        assert starten(monkeypatch, "--prune", "--index", index, "--lang", "en") == 0
        ausgabe = capsys.readouterr().out
        # a.flac und b/c.mp3 bleiben, e.flac und "cli" fallen weg, "musik" gehört
        # der Oberfläche und bleibt; b/d.flac ist kaputt und nie abgelegt worden
        assert "2 removed, 3 kept" in ausgabe
        assert ablage.load("musik", "web.flac", fullband, "q") == {"n": 1}

    def test_prune_ohne_index(self, monkeypatch):
        with pytest.raises(SystemExit):
            starten(monkeypatch, "--prune")


class TestSprache:
    def test_hilfe_auf_englisch(self, capsys, monkeypatch):
        with pytest.raises(SystemExit):
            starten(monkeypatch, "--lang", "en", "--help")
        hilfe = capsys.readouterr().out
        assert "frequency axis" in hilfe and "Frequenzachse" not in hilfe

    def test_voreinstellung_aus_der_umgebung(self, capsys, monkeypatch):
        monkeypatch.setenv("LANG_DEFAULT", "en")
        with pytest.raises(SystemExit):
            starten(monkeypatch, "--help")
        assert "frequency axis" in capsys.readouterr().out

    def test_vergleich_ohne_deutsche_reste(self, tmp_path, fullband, lossy, capsys,
                                           monkeypatch):
        assert starten(monkeypatch, "--compare", fullband, lossy, "--lang", "en",
                       "-d", tmp_path, "--null") == 0
        ausgabe = capsys.readouterr().out
        for deutsch in ("Differenz", "Nullprobe", "Versatz", "Bandkante"):
            assert deutsch not in ausgabe, ausgabe
        assert "difference: median" in ausgabe
        assert (tmp_path / "comparison.png").exists()

    def test_fehlermeldung_folgt_der_sprache(self, capsys, monkeypatch):
        with pytest.raises(SystemExit) as ende:
            starten(monkeypatch, "--fft", 1000, "--lang", "en", "x.flac")
        assert "power of two" in str(ende.value)
