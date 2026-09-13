"""Bandkante, Bandbreite und die daraus abgeleitete Bewertung.

Hier liegen die Fälle, an denen die Heuristik in der Entwicklung mehrfach
falsch lag. Wer eine Schwelle ändert, sieht hier zuerst, was dabei kaputtgeht.
"""

import numpy as np
import pytest

from app import core


def band_of(path, nfft=2048):
    p = core.Params(nfft=nfft, overlap=0.5, max_cols=6000)
    a = core.analyse(str(path), p)
    return core.band_analysis(a.mags[0], a.sr, nfft, a.info["codec"]), a


class TestBandkante:
    def test_vollband_ohne_kante(self, fullband):
        b, _ = band_of(fullband)
        assert b["pattern"] == "voll"
        assert b["edge_hz"] is None
        assert b["verdict"]["level"] == "ok"

    def test_verlustbehaftet_hat_konstante_kante(self, lossy):
        b, a = band_of(lossy)
        assert b["pattern"] == "konstant"
        assert 14000 < b["edge_hz"] < 20000
        # bei verlustbehaftetem Container ist das erwartbar, keine Warnung
        assert b["verdict"]["level"] == "ok"

    def test_analoger_hoehenabfall_ist_kein_transcode(self, analog_rolloff):
        """Der Fehlalarm, der die Steilheitsprüfung nötig gemacht hat.

        Ein weicher Abfall von 3 bis 6 dB/kHz darf niemals als Bandbegrenzung
        durchgehen - sonst wird jede Auslaufrille als Transcode gemeldet.
        """
        b, _ = band_of(analog_rolloff)
        assert b["pattern"] == "voll", b["verdict"]["text"]
        assert b["verdict"]["level"] == "ok"
        assert b["signal_bandwidth_hz"] is not None

    def test_hochgesampelt_erkannt_mit_richtiger_quellrate(self, upsampled):
        """Die Quellrate folgt aus dem Stoppbandbeginn, nicht aus der Kante.

        Die Kante liegt im Übergangsbereich davor; früher wurde deshalb eine
        48-kHz-Quelle als 44,1 kHz ausgewiesen.
        """
        b, _ = band_of(upsampled, nfft=4096)
        assert b["pattern"] == "hochgesampelt", b["verdict"]["text"]
        assert b["source_rate_hint"] == 48000
        assert b["verdict"]["level"] == "warn"
        assert 22000 < b["stopband_hz"] < 26000

    def test_kante_bei_91_prozent_gilt_als_bandbegrenzung(self, brickwall_20k):
        """Die Schwelle stammt aus einer Encoder-Leiter.

        Encoder-Tiefpässe lagen zwischen 72 und 91 % der Nyquist-Frequenz.
        Bei der früheren Schwelle von 90 % fielen MP3 320, AAC 128 und Vorbis
        durch das Raster.
        """
        b, a = band_of(brickwall_20k, nfft=4096)
        assert b["pattern"] == "konstant", b["verdict"]["text"]
        assert 18500 < b["edge_hz"] < 21000
        assert 0.85 < b["edge_hz"] / (a.sr / 2) < 0.94

    def test_antialiasing_filter_gilt_nicht_als_bandbegrenzung(self, antialias):
        """Bei 97 % der Nyquist-Frequenz ist es der Wandler, nicht ein Encoder."""
        b, _ = band_of(antialias, nfft=4096)
        assert b["pattern"] == "voll", b["verdict"]["text"]
        assert b["verdict"]["level"] == "ok"

    def test_ganzdatei_entscheidet_ueber_die_bandbegrenzung(self, brickwall_20k):
        """Bei hohen Bitraten sitzt die Kante im Gesamtspektrum unübersehbar,
        fällt in einzelnen Abschnitten aber selten auf. Würde nur
        abschnittsweise gezählt, blieben MP3 320 und AAC 128 unerkannt."""
        b, _ = band_of(brickwall_20k, nfft=4096)
        assert b["pattern"] == "konstant"
        assert b["edge_hz"] is not None

    def test_hinweis_nennt_keine_bitrate(self, lossy):
        """Die Frequenz benennt weder Format noch Bitrate: gemessen lagen
        MP3 128 und 192 nur 50 Hz auseinander, und um 20 kHz treffen sich
        MP3 320, AAC 128, Vorbis und Opus."""
        b, _ = band_of(lossy)
        text = b["verdict"]["text"]
        assert "kbit/s" not in text or "bis" in text or "128 to 192" in text

    def test_kante_am_encoder_tiefpass_ist_steil(self, lossy):
        p = core.Params(nfft=4096, overlap=0.5, max_cols=4000)
        a = core.analyse(str(lossy), p)
        P = a.mags[0].astype(np.float64) ** 2
        med = 10 * np.log10(np.median(P, axis=1) + 1e-30)
        e = core.spectral_edge(med - med.max(), a.sr, 4096, min_steepness=0.0)
        assert e is not None and e["steepness_db_per_khz"] > 20


class TestSteilheit:
    """Die Steilheitsprüfung als Baustein - mit konstruierten Spektren.

    Gemessen an echten Aufnahmen: Encoder- und Wandlerfilter fallen mit 45 bis
    80 dB/kHz, der Höhenabfall von Platte und Band mit 3 bis 6. Die Schwelle
    liegt bei 10 dB/kHz.
    """

    SR, NFFT = 48000, 8192

    def _spektrum(self, verlauf):
        df = self.SR / self.NFFT
        f = np.arange(self.NFFT // 2 + 1) * df
        return verlauf(f), df

    def test_steilabfall_wird_erkannt(self):
        """Eine ideale Steilkante muss auch genau lokalisiert werden.

        Die reine Suche nach dem größten Pegelunterschied trifft hier bis zu
        2 kHz zu tief, weil das obere Vergleichsfenster schon davor ganz im
        Sperrbereich liegt - die Steilheit würde dann an einer Stelle gemessen,
        an der es noch flach ist, und die Kante fiele durch die Prüfung.
        """
        med, _ = self._spektrum(lambda f: np.where(f < 16000, 0.0, -90.0))
        e = core.spectral_edge(med, self.SR, self.NFFT)
        assert e is not None
        assert abs(e["hz"] - 16000) < 700
        assert e["steepness_db_per_khz"] > 40

    def test_sanfter_hoehenabfall_wird_verworfen(self):
        """4 dB/kHz oberhalb 8 kHz: insgesamt über 60 dB Abfall, aber weich."""
        med, _ = self._spektrum(
            lambda f: np.minimum(0.0, -(np.maximum(f - 8000, 0) / 1000) * 8))
        assert core.spectral_edge(med, self.SR, self.NFFT) is None
        # ohne die Steilheitsprüfung würde derselbe Verlauf eine Kante melden
        e = core.spectral_edge(med, self.SR, self.NFFT, min_steepness=0.0)
        assert e is not None and e["steepness_db_per_khz"] < 10

    def test_grenzfall_knapp_ueber_der_schwelle(self):
        med, _ = self._spektrum(
            lambda f: np.minimum(0.0, -(np.maximum(f - 15000, 0) / 1000) * 15))
        e = core.spectral_edge(med, self.SR, self.NFFT)
        assert e is not None and e["steepness_db_per_khz"] > 10

    def test_bandbreite_liegt_unter_der_kante(self, lossy):
        b, _ = band_of(lossy)
        assert b["signal_bandwidth_hz"] <= b["edge_hz"] + 1000


class TestParameter:
    @pytest.mark.parametrize("kw,erwartet", [
        ({"nfft": 3}, "Zweierpotenz"),
        ({"overlap": 1.5}, "overlap"),
        ({"window": "gibtsnicht"}, "Fenster"),
        ({"scale": "polar"}, "Skala"),
        ({"channels": "surround"}, "Kanalmodus"),
        ({"cmap": "rm -rf"}, "Colormap"),
        ({"theme": "hack"}, "Theme"),
        ({"sr": 10}, "sr"),
        ({"fmin": 5000, "fmax": 5000}, "dicht"),
    ])
    def test_unsinnige_werte_werden_abgelehnt(self, kw, erwartet):
        with pytest.raises(ValueError, match=erwartet):
            core.Params(**kw).validate()

    def test_vertauschte_grenzen_werden_getauscht(self):
        p = core.Params(fmin=18000, fmax=200).validate()
        assert (p.fmin, p.fmax) == (200.0, 18000.0)

    def test_negative_werte_werden_geklemmt(self):
        p = core.Params(fmin=-800, duration=-5).validate()
        assert p.fmin == 0.0 and p.duration is None


class TestBezugsaufloesung:
    """Das Urteil darf nicht von der FFT-Größe abhängen.

    Die Lage einer Steilkante verschiebt sich mit dem Analysefenster: bei
    langem Fenster liegt der Rauschboden tiefer, der Übergang zieht sich, und
    die steilste Stelle wandert nach oben. An einer Encoder-Leiter gemessen
    wanderte dieselbe Kante zwischen nfft 4096 und 16384 um 1,3 kHz – genug,
    um „konstante Bandkante" in „kein Steilabfall" kippen zu lassen.
    """

    @pytest.mark.parametrize("nfft", [1024, 2048, 4096, 8192, 16384])
    def test_bandbegrenzung_wird_bei_jeder_fft_groesse_erkannt(self, brickwall_20k, nfft):
        b = core.band_report(str(brickwall_20k), core.Params(nfft=nfft, overlap=0.5))
        assert b["pattern"] == "konstant", (nfft, b["verdict"]["text"])

    @pytest.mark.parametrize("nfft", [1024, 4096, 16384])
    def test_antialiasing_bleibt_bei_jeder_fft_groesse_unauffaellig(self, antialias, nfft):
        b = core.band_report(str(antialias), core.Params(nfft=nfft, overlap=0.5))
        assert b["pattern"] == "voll", (nfft, b["verdict"]["text"])

    def test_kantenlage_bleibt_stabil(self, brickwall_20k):
        werte = [core.band_report(str(brickwall_20k),
                                  core.Params(nfft=n, overlap=0.5))["edge_hz"]
                 for n in (1024, 4096, 16384)]
        assert max(werte) - min(werte) < 300, werte

    def test_passende_einstellung_spart_die_zusatzanalyse(self, brickwall_20k):
        """Bei nfft = Bezugsauflösung wird das vorhandene Spektrum genutzt."""
        p = core.Params(nfft=core.REFERENCE_NFFT, overlap=0.5)
        a = core.analyse(str(brickwall_20k), p)
        b = core.band_report(str(brickwall_20k), p, a.mags[0], a.sr, "flac")
        assert b["pattern"] == "konstant"


class TestVerlustfreieFormate:
    """ALAC, WavPack und Monkey's Audio müssen wie PCM behandelt werden.

    Alle drei gelten als verlustfrei; eine Bandbegrenzung darin wäre also ein
    Transcode-Hinweis. Wird der Codec nicht als verlustfrei erkannt, bliebe
    die Warnung aus.
    """

    @pytest.mark.parametrize("codec", ["alac", "wavpack", "ape", "tta",
                                       "pcm_s16le", "pcm_s24le", "flac"])
    def test_als_verlustfrei_gefuehrt(self, codec):
        assert codec in core.LOSSLESS_CODECS

    @pytest.mark.parametrize("codec", ["mp3", "aac", "opus", "vorbis", "wmav2"])
    def test_nicht_als_verlustfrei_gefuehrt(self, codec):
        assert codec not in core.LOSSLESS_CODECS

    def test_gleicher_inhalt_gleiche_bewertung(self, media, fullband):
        """Dasselbe Material in verschiedenen verlustfreien Containern muss
        identisch bewertet werden."""
        from conftest import ff
        ergebnisse = {}
        for endung, args in (("m4a", ["-c:a", "alac"]),
                             ("wv", ["-c:a", "wavpack"]),
                             ("wav", ["-c:a", "pcm_s16le"])):
            ziel = media / f"gleich.{endung}"
            if not ziel.exists():
                ff(["-i", str(fullband), *args, str(ziel)])
            b = core.band_report(str(ziel), core.Params(nfft=4096, overlap=0.5))
            ergebnisse[endung] = (b["pattern"], b["verdict"]["text"])
        assert len(set(ergebnisse.values())) == 1, ergebnisse


class TestMusterVokabular:
    """Nur drei Einstufungen, und jede sagt etwas aus.

    Das frühere Muster „vereinzelte Kante" entfiel: an 41 Dateien gemessen
    zeigte es nie etwas Echtes an, seit die Ganzdatei entscheidet – einzelne
    Abschnitte einer sauberen verlustfreien Aufnahme erfüllen die
    Kantenbedingung rein zufällig.
    """

    @pytest.mark.parametrize("fixture_name,erwartet", [
        ("fullband", "voll"), ("analog_rolloff", "voll"),
        ("lossy", "konstant"), ("upsampled", "hochgesampelt"),
    ])
    def test_einstufungen(self, request, fixture_name, erwartet):
        pfad = request.getfixturevalue(fixture_name)
        b = core.band_report(str(pfad), core.Params(nfft=4096, overlap=0.5))
        assert b["pattern"] == erwartet, b["verdict"]["text"]

    def test_abschnittszahlen_bleiben_als_kennzahl(self, fullband):
        b = core.band_report(str(fullband), core.Params(nfft=4096, overlap=0.5))
        assert "blocks" in b and "blocks_with_edge" in b
