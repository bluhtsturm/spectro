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

    @staticmethod
    def _suche_stelle_fuer_stelle(med_db, sr, nfft, min_hz=7000.0):
        """Die urspruengliche Suche als Schleife - Massstab fuer die
        vektorisierte Fassung, die exakt dasselbe liefern muss."""
        df = sr / nfft
        sm = core._smooth(med_db, max(1, int(150 / df)))
        nyq = sr / 2
        best = None
        for i in range(max(int(min_hz / df), 4), int(0.995 * nyq / df)):
            f = i * df
            b0, b1 = max(4, int((f - 1500) / df)), i
            a0, a1 = int((f + 300) / df), int(min(f + 4000, nyq) / df)
            if b1 - b0 < 3 or a1 - a0 < 3:
                continue
            drop = float(np.median(sm[b0:b1]) - np.median(sm[a0:a1]))
            if best is None or drop > best[0]:
                best = (drop, f, float(np.median(sm[a0:a1])))
        return best

    @pytest.mark.parametrize("sr,nfft", [(44100, 1024), (44100, 4096), (48000, 8192),
                                         (96000, 4096), (192000, 16384)])
    def test_suche_entspricht_der_schleife(self, sr, nfft, monkeypatch):
        """Die Kante ist kalibriert - schneller rechnen darf sie nicht verschieben.

        Geprüft wird die Fundstelle vor der Feinjustierung: dazu wird die
        Mindestdifferenz so gesetzt, dass jede Fundstelle durchkommt, und die
        erste Stufe über ein Spionfenster abgegriffen.
        """
        from app import band
        rng = np.random.default_rng(sr + nfft)
        f = np.arange(nfft // 2 + 1) * sr / nfft
        gefunden = []
        original = band._window_medians

        def mitschreiben(x, starts, ends):
            werte = original(x, starts, ends)
            gefunden.append(werte)
            return werte

        monkeypatch.setattr(band, "_window_medians", mitschreiben)
        for versuch in range(20):
            kante = rng.uniform(8000, sr / 2)
            med = (rng.normal(-40, rng.uniform(0.1, 8), f.size)
                   - np.where(f > kante, rng.uniform(0, 90), 0))
            if versuch % 4 == 0:
                med = np.round(med)                  # viele gleiche Werte
            gefunden.clear()
            band.spectral_edge(med, sr, nfft, min_drop=-1e9, min_steepness=-1e9)
            erwartet = self._suche_stelle_fuer_stelle(med, sr, nfft)
            unten, oben = gefunden
            k = int(np.argmax(unten - oben))
            assert (float((unten - oben)[k]), float(oben[k])) == (erwartet[0], erwartet[2])


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

    def test_meldungen_folgen_der_sprache(self):
        with pytest.raises(ValueError, match="power of two"):
            core.Params(nfft=3, lang="en").validate()
        with pytest.raises(ValueError, match="unknown window"):
            core.Params(window="x", lang="en").validate()

    @pytest.mark.parametrize("feld", ["fmax", "width", "db_range", "start", "overlap"])
    def test_nicht_endliche_werte_werden_abgelehnt(self, feld):
        for wert in (float("nan"), float("inf")):
            with pytest.raises(ValueError, match=feld):
                core.Params(**{feld: wert}).validate()

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

    @pytest.mark.parametrize("abweichung", [{"channels": "left"}, {"overlap": 0.75}])
    def test_anders_entstandenes_spektrum_wird_nicht_uebernommen(self, brickwall_20k,
                                                                  abweichung):
        """Nur ein Spektrum, das wie das eigene entstanden ist, darf das Urteil
        tragen - sonst urteilte die Ansicht "links" allein über einen Kanal.

        Als Köder dient ein flaches Spektrum ohne jede Kante: wird es
        übernommen, verschwindet die Bandbegrenzung aus dem Urteil.
        """
        koeder = np.ones((core.REFERENCE_NFFT // 2 + 1, 200), dtype=np.float32)
        passend = core.Params(nfft=core.REFERENCE_NFFT, overlap=0.5)
        assert core.band_report(str(brickwall_20k), passend, koeder, 44100,
                                "flac")["pattern"] == "voll"
        p = core.Params(**{"nfft": core.REFERENCE_NFFT, "overlap": 0.5, **abweichung})
        b = core.band_report(str(brickwall_20k), p, koeder, 44100, "flac")
        assert b["pattern"] == "konstant", b["verdict"]["text"]


class TestBandenergie:
    @pytest.mark.parametrize("sr", [44100, 22050])
    def test_anteile_ergeben_zusammen_eins(self, sr):
        """Kein Frequenzbin darf in zwei Bändern zählen.

        Bei 22,05 kHz liegt Nyquist unter der 16-kHz-Grenze; dort muss das
        oberste Band trotzdem bis Nyquist reichen.
        """
        mag = np.random.default_rng(5).random((2049, 50)).astype(np.float32)
        baender = core.band_energy(mag, sr, 4096)
        assert abs(sum(b["share"] for b in baender) - 1.0) < 1e-9
        assert baender[-1]["hi"] == sr / 2


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
