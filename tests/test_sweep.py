"""Frequenzgang und Kanaltrennung aus einer Tonfolge.

Die Prüfsignale haben bekannten Frequenzgang und bekannte Kanaltrennung:
jede Stufe wird mit vorgegebenem Pegel erzeugt, das Übersprechen als
gedämpfte Kopie in den anderen Kanal gelegt. Damit lässt sich prüfen, ob die
Messung die Vorgaben zurückliefert.
"""

import subprocess

import numpy as np
import pytest

from app import core
from conftest import SR

STUFEN = [30, 60, 125, 250, 500, 1000, 2000, 4000, 8000, 12000]


def tonfolge(media, name, gang=None, trennung_db=30.0, kanal="L", dauer=2.0):
    """Erzeugt eine Tonleiter mit bekanntem Verlauf und Übersprechen."""
    ziel = media / name
    if ziel.exists():
        return ziel
    gang = gang or {}
    teile = []
    stille = np.zeros((int(SR * 0.4), 2), dtype=np.float32)
    for hz in STUFEN:
        n = int(SR * dauer)
        t = np.arange(n) / SR
        amp = 0.2 * 10 ** (gang.get(hz, 0.0) / 20)
        ton = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
        leise = (ton * 10 ** (-trennung_db / 20)).astype(np.float32)
        blk = np.zeros((n, 2), dtype=np.float32)
        if kanal == "L":
            blk[:, 0], blk[:, 1] = ton, leise
        else:
            blk[:, 1], blk[:, 0] = ton, leise
        teile.extend([blk, stille])
    x = np.concatenate(teile)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR),
                    "-ac", "2", "-i", "-", "-c:a", "flac", str(ziel)],
                   input=x.tobytes(), check=True)
    return ziel


class TestFrequenzgang:
    def test_ebener_gang_wird_als_eben_gemessen(self, media):
        r = core.tone_sweep(str(tonfolge(media, "sweep_flat.flac")))
        kurve = r["response"]["L"]
        assert len(kurve) >= 8
        assert max(abs(k["db"]) for k in kurve) < 0.5, kurve

    def test_vorgegebener_verlauf_wird_wiedergefunden(self, media):
        """Höhenabfall von 6 dB ab 8 kHz, Bassanhebung von 3 dB bei 30 Hz."""
        gang = {30: 3.0, 60: 1.5, 8000: -6.0, 12000: -6.0}
        r = core.tone_sweep(str(tonfolge(media, "sweep_gang.flac", gang=gang)))
        kurve = {k["hz"]: k["db"] for k in r["response"]["L"]}
        def bei(hz):
            passend = min(kurve, key=lambda h: abs(h - hz))
            return kurve[passend]
        assert abs(bei(30) - 3.0) < 0.5, kurve
        assert abs(bei(8000) + 6.0) < 0.5, kurve
        assert abs(bei(1000)) < 0.2

    def test_bezugston_bestimmt_die_null(self, media):
        r = core.tone_sweep(str(tonfolge(media, "sweep_flat.flac")),
                            reference_hz=4000.0)
        kurve = {k["hz"]: k["db"] for k in r["response"]["L"]}
        nahe = min(kurve, key=lambda h: abs(h - 4000))
        assert abs(kurve[nahe]) < 0.2


class TestKanaltrennung:
    @pytest.mark.parametrize("soll", [20.0, 30.0, 40.0])
    def test_vorgegebene_trennung_wird_gemessen(self, media, soll):
        r = core.tone_sweep(str(tonfolge(media, f"sweep_tr{soll:.0f}.flac",
                                         trennung_db=soll)))
        assert abs(r["channel_separation_db"] - soll) < 1.5, r["channel_separation_db"]

    def test_schlechte_trennung_wird_bemaengelt(self, media):
        r = core.tone_sweep(str(tonfolge(media, "sweep_tr10.flac", trennung_db=10.0)))
        assert r["verdict"]["level"] == "warn"

    def test_kanal_wird_richtig_zugeordnet(self, media):
        r = core.tone_sweep(str(tonfolge(media, "sweep_rechts.flac", kanal="R")))
        assert "R" in r["response"] and "L" not in r["response"]


class TestGrenzen:
    def test_ohne_tonfolge_kein_ergebnis(self, analog_rolloff):
        with pytest.raises(core.AudioError, match="Tonfolge|tone sequence"):
            core.tone_sweep(str(analog_rolloff))

    def test_pegelmarken_verfaelschen_den_gang_nicht(self, media):
        """Messplatten stellen der Reihe oft zwei Pegelmarken derselben
        Frequenz voran. Ohne Rücksicht darauf stünde in der Spanne ein
        Sprung von über 10 dB, der nichts mit dem Frequenzgang zu tun hat.
        """
        import shutil
        folge = tonfolge(media, "sweep_flat.flac")
        ziel = media / "sweep_mit_marken.flac"
        if not ziel.exists():
            n = int(SR * 2)
            t = np.arange(n) / SR
            marken = []
            for db in (0.0, -10.0):
                amp = 0.2 * 10 ** (db / 20)
                ton = (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
                blk = np.zeros((n, 2), dtype=np.float32)
                blk[:, 0] = ton
                marken.extend([blk, np.zeros((int(SR * 0.4), 2), dtype=np.float32)])
            roh = media / "_marken.f32"
            with open(roh, "wb") as fh:
                fh.write(np.concatenate(marken).tobytes())
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR),
                            "-ac", "2", "-i", str(roh), "-i", str(folge),
                            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
                            "-c:a", "flac", str(ziel)], check=True)
            shutil.rmtree(roh, ignore_errors=True)
        r = core.tone_sweep(str(ziel))
        kurve = r["response"]["L"]
        assert max(abs(k["db"]) for k in kurve) < 1.0, kurve
