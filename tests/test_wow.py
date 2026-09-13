"""Gleichlauf: Drehzahl, Wow und Flutter.

Die Prüfsignale haben bekannte Schwankung – ein Ton wird mit genau
vorgegebenem Effektivwert frequenzmoduliert. Damit lässt sich nicht nur
prüfen, dass etwas gemessen wird, sondern auch *wie genau*.
"""

import subprocess

import numpy as np
import pytest

from app import core
from conftest import SR

NPERSEG_SEKUNDEN = 12


def moduliert(media, soll_pct: float, mod_hz: float, traeger: float = 315.0,
              name: str | None = None):
    """Ton mit genau bekanntem Schwankungs-Effektivwert."""
    ziel = media / (name or f"wow_{soll_pct:.2f}_{mod_hz:.2f}.flac")
    if not ziel.exists():
        t = np.arange(SR * NPERSEG_SEKUNDEN) / SR
        if mod_hz > 0:
            amp = soll_pct * np.sqrt(2) / 100
            phase = 2 * np.pi * traeger * (t + amp / (2 * np.pi * mod_hz)
                                           * np.sin(2 * np.pi * mod_hz * t))
        else:
            phase = 2 * np.pi * traeger * t
        x = (np.sin(phase) * 0.5).astype(np.float32)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR),
                        "-ac", "1", "-i", "-", "-c:a", "flac", str(ziel)],
                       input=x.tobytes(), check=True)
    return ziel


class TestGenauigkeit:
    @pytest.mark.parametrize("soll,mod", [(0.10, 0.55), (0.30, 0.55), (0.50, 3.0)])
    def test_bekannte_schwankung_wird_getroffen(self, media, soll, mod):
        r = core.wow_flutter(str(moduliert(media, soll, mod)))
        gemessen = r["wow_pct"] if mod < 6 else r["flutter_pct"]
        assert abs(gemessen - soll) < 0.02, (soll, r)

    def test_unmodulierter_ton_ergibt_null(self, media):
        r = core.wow_flutter(str(moduliert(media, 0.0, 0.0)))
        assert r["wow_pct"] < 0.01 and r["flutter_pct"] < 0.01
        assert r["verdict"]["level"] == "ok"

    def test_modulationsfrequenz_wird_gefunden(self, media):
        r = core.wow_flutter(str(moduliert(media, 0.30, 0.55)))
        assert abs(r["dominant_mod_hz"] - 0.55) < 0.2, r["dominant_mod_hz"]

    def test_flutter_wird_von_wow_getrennt(self, media):
        schnell = core.wow_flutter(str(moduliert(media, 0.40, 20.0)))
        assert schnell["flutter_pct"] > 0.3
        assert schnell["wow_pct"] < 0.05


class TestDrehzahl:
    def test_sollfrequenz_wird_erkannt(self, media):
        r = core.wow_flutter(str(moduliert(media, 0.0, 0.0, traeger=315.0)))
        assert r["nominal_hz"] == 315.0
        assert abs(r["speed_deviation_pct"]) < 0.05

    def test_abweichung_wird_beziffert(self, media):
        """Ein Ton bei 312 Hz gegen 315 Hz Soll: −0,95 %."""
        r = core.wow_flutter(str(moduliert(media, 0.0, 0.0, traeger=312.0,
                                           name="wow_312.flac")))
        assert r["nominal_hz"] == 315.0
        assert abs(r["speed_deviation_pct"] + 0.952) < 0.05, r

    def test_vorgegebene_sollfrequenz_schlaegt_die_automatik(self, media):
        r = core.wow_flutter(str(moduliert(media, 0.0, 0.0, traeger=312.0,
                                           name="wow_312.flac")),
                             nominal_hz=312.0)
        assert abs(r["speed_deviation_pct"]) < 0.05

    def test_exzentrizitaet_wird_benannt(self, media):
        """Eine Schwankung im Takt einer Umdrehung deutet auf eine
        außermittige Pressung – das soll der Text auch sagen."""
        r = core.wow_flutter(str(moduliert(media, 0.30, 0.55)))
        assert "Umdrehung" in r["verdict"]["text"]
        en = core.wow_flutter(str(moduliert(media, 0.30, 0.55)),
                              core.Params(lang="en"))
        assert "revolution" in en["verdict"]["text"]


class TestGrenzen:
    def test_ohne_dauerton_kein_ergebnis(self, analog_rolloff):
        """Gemessener Tonanteil: reines Rauschen 0,003, Musik 0,05, ein
        Messton 0,48 bis 1,0. Die Schwelle liegt bei 0,2."""
        with pytest.raises(core.AudioError, match="Dauerton|steady"):
            core.wow_flutter(str(analog_rolloff))

    def test_zu_kurzes_material(self, media):
        from conftest import tone, write_pcm
        p = media / "kurzton.flac"
        if not p.exists():
            write_pcm(p, tone(SR // 2, 315.0), SR)
        with pytest.raises(core.AudioError):
            core.wow_flutter(str(p))

    def test_starke_schwankung_wird_bemaengelt(self, media):
        r = core.wow_flutter(str(moduliert(media, 0.60, 1.5)))
        assert r["verdict"]["level"] == "warn", r["verdict"]["text"]
