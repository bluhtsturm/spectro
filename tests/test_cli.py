"""Kommandozeile: sie muss dasselbe sagen wie Oberfläche und API."""

import sys

import pytest

import spectro
from app import band, core


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
