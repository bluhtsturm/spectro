"""Störungssuche, Tiefton und die Messwerte aus ffmpeg."""

import numpy as np
import pytest

from app import core
from conftest import CLICK_TIMES


class TestStoerungssuche:
    def test_findet_die_eingesetzten_impulse(self, clicks):
        r = core.impulse_scan(str(clicks))
        gefunden = sorted(e["t"] for e in r["events"])
        for soll in CLICK_TIMES:
            assert any(abs(t - soll) < 0.05 for t in gefunden), \
                f"Impuls bei {soll}s nicht gefunden: {gefunden}"

    def test_meldet_keine_geisterimpulse(self, clicks):
        """Höchstens ein Fehltreffer je gesetztem Impuls.

        Auf digitalem Material lag die Rate bei etwa einem Fehltreffer je
        Minute; das ist die Grenze, die hier nicht überschritten werden darf.
        """
        r = core.impulse_scan(str(clicks))
        assert r["count"] <= len(CLICK_TIMES) * 2

    def test_saubere_aufnahme_bleibt_still(self, fullband):
        r = core.impulse_scan(str(fullband))
        assert r["per_minute"] < 10
        assert r["verdict"]["level"] == "ok"

    def test_bass_gegenprobe_verwirft_musiktransienten(self, media):
        """Ein Basseinsatz bringt Tiefton mit und ist damit kein Knackser."""
        import numpy as np
        from conftest import write_pcm, noise, SR
        p = media / "bassdrum.flac"
        n = SR * 6
        x = noise(n, seed=31) * 0.2
        for t in (1.0, 2.0, 3.0, 4.0):
            i = int(t * SR)
            huelle = np.exp(-np.arange(SR // 4) / (SR * 0.02))
            ton = np.sin(2 * np.pi * 60 * np.arange(SR // 4) / SR)
            x[i:i + SR // 4] += (0.8 * huelle * ton).astype(np.float32)
        write_pcm(p, x, SR)
        r = core.impulse_scan(str(p))
        assert r["count"] <= 2, [e["t"] for e in r["events"]]

    def test_zu_kurzes_material_wird_abgewiesen(self, media):
        from conftest import write_pcm, noise, SR
        p = media / "winzig.flac"
        write_pcm(p, noise(200), SR)
        with pytest.raises(core.AudioError):
            core.impulse_scan(str(p))


class TestTiefton:
    def test_netzbrumm_wird_gefunden(self, hum):
        r = core.lowfreq_scan(str(hum))
        assert r["mains_hz"] == 50
        assert r["hum"], "kein Brumm erkannt"
        assert any(abs(h["hz"] - 50) < 2 for h in r["hum"])

    def test_sechzig_hertz_wird_von_fuenfzig_unterschieden(self, hum60):
        """Die Auflösung von 0,24 Hz ist dafür da: mit der Auflösung der
        Bildanalyse (23 Hz bei 48 kHz) lägen 50 und 60 Hz im selben Bin."""
        r = core.lowfreq_scan(str(hum60))
        assert r["mains_hz"] == 60, r["hum"]
        assert any(abs(h["hz"] - 60) < 2 for h in r["hum"])

    def test_ohne_brumm_keine_netzfrequenz(self, fullband):
        """Vorher stand dort immer ein Wert, auch ohne jeden Befund – der war
        dann geraten."""
        r = core.lowfreq_scan(str(fullband))
        assert r["hum"] == []
        assert r["mains_hz"] is None

    def test_rumpeln_wird_gemeldet(self, rumble):
        r = core.lowfreq_scan(str(rumble))
        assert r["verdict"]["level"] == "warn"
        assert r["subsonic_db"] > -55

    def test_stille_meldet_weder_brumm_noch_rumpeln(self, silence):
        """Bei einer stillen Aufnahme liegt der Tiefstton zwangsläufig nahe am
        Gesamtpegel - ohne Absolutschwelle gäbe das eine Rumpelwarnung."""
        r = core.lowfreq_scan(str(silence))
        assert r["verdict"]["level"] == "ok", r["verdict"]["text"]
        assert not r["hum"]

    def test_sauberes_material_ohne_befund(self, fullband):
        r = core.lowfreq_scan(str(fullband))
        assert r["verdict"]["level"] == "ok"


class TestMesswerte:
    def test_aufgeblasene_bittiefe_wird_erkannt(self, fake24):
        rep = core.summary(str(fake24), core.Params())
        l = rep["loudness"]
        assert l["bit_depth_effective"] == 16
        assert l["bit_depth_container"] == 24

    def test_leise_echte_24_bit_gelten_nicht_als_hochgerechnet(self, quiet24):
        """Der erste Ansatz nahm den aussteuerungsabhängigen Wert und hätte
        jede leise 24-bit-Aufnahme als hochgerechnet gemeldet."""
        rep = core.summary(str(quiet24), core.Params())
        l = rep["loudness"]
        assert l["bit_depth_effective"] == l["bit_depth_container"]

    def test_bittiefe_entfaellt_bei_verlustbehafteten_quellen(self, lossy):
        """Dort liefert der Decoder Fließkomma - der Wert beschriebe den
        Decoder, nicht die Datei."""
        rep = core.summary(str(lossy), core.Params())
        assert "bit_depth_effective" not in rep["loudness"]

    def test_lautheit_wird_gelesen(self, fullband):
        l = core.loudness(str(fullband))
        assert l["lufs_integrated"] < 0
        assert "true_peak_dbfs" in l and "peak_dbfs" in l

    def test_stereowerte_bei_mono_leer(self, fullband):
        assert core.stereo_stats(str(fullband), core.Params()) == {}


class TestUebersteuerung:
    """Die Beurteilung stützt sich auf Flat factor und Spitzenzahl.

    Der True Peak allein genügt nicht: er lag auch bei sauberen, aber lauten
    Fassungen über der Grenze (bis +2,0 dBTP), während Flat factor und
    Spitzenrate nur beim tatsächlich übersteuerten Master anschlugen.
    """

    def test_uebersteuertes_master_wird_erkannt(self, uebersteuert):
        rep = core.summary(str(uebersteuert), core.Params())
        c = rep.get("clipping")
        assert c is not None and c["level"] == "warn", rep["loudness"]
        assert c["rate_per_min"] > 30 or c["flat_factor"] > 0

    def test_sauberes_material_bleibt_unauffaellig(self, fullband):
        rep = core.summary(str(fullband), core.Params())
        c = rep.get("clipping")
        assert c is None or c["level"] != "warn" or "dBTP" in c["text"]

    def test_leise_aufnahme_ohne_befund(self, silence):
        rep = core.summary(str(silence), core.Params())
        assert rep.get("clipping") is None

    def test_bewertung_ohne_messwerte(self):
        assert core.clipping_verdict({}, 60.0) is None
        assert core.clipping_verdict({"true_peak_dbfs": -6.0}, 60.0) is None

    def test_stille_zaehlt_nicht_als_uebersteuerung(self):
        """In digitaler Stille zählt astats jedes Sample als Spitze, weil alle
        auf dem Extremwert liegen. Ohne Verankerung am Pegel gäbe das eine
        Warnung für eine leere Datei."""
        still = {"abs_peak_count": 264600, "flat_factor": 0.0, "peak_dbfs": -90.0}
        assert core.clipping_verdict(still, 6.0) is None

    def test_rate_statt_absolutzahl(self):
        """Eine lange Datei sammelt zwangsläufig mehr Spitzen – deshalb zählt
        die Rate je Minute, nicht die Gesamtzahl."""
        werte = {"abs_peak_count": 40, "flat_factor": 0.0, "peak_dbfs": -0.2}
        kurz = core.clipping_verdict(werte, 60.0)
        lang = core.clipping_verdict(werte, 3600.0)
        assert kurz is not None and kurz["level"] == "warn"
        assert lang is None


class TestDauertoene:
    def test_einstreuung_wird_gefunden(self, media):
        from conftest import write_pcm, noise, tone, SR
        p = media / "pfeifton.flac"
        n = SR * 10
        # kraeftiges Programm, dazu ein schwacher Ton bei 15 kHz - so sieht
        # eine Einstreuung aus der Aufnahmekette aus
        x = noise(n, seed=37) * 0.4 + tone(n, 1000, amp=0.35) + tone(n, 15000, amp=0.004)
        write_pcm(p, x, SR)
        a = core.analyse(str(p), core.Params(nfft=8192, overlap=0.5))
        t = core.tonal_peaks(a.mags[0], a.sr, 8192)
        assert any(abs(x["hz"] - 15000) < 60 for x in t), t

    def test_musik_erzeugt_keine_meldung(self, fullband):
        """Ein gehaltener Ton im Programm ist keine Einstreuung: er ist laut
        und breiter als eine schmalbandige Störung."""
        a = core.analyse(str(fullband), core.Params(nfft=8192, overlap=0.5))
        assert core.tonal_peaks(a.mags[0], a.sr, 8192) == []


class TestBrummAbgrenzung:
    """Musikalische Bassanteile sind kein Netzbrumm.

    An echtem Material gemessen: nachgewiesener Brumm ragte 16 bis 40 dB aus
    seinem Umfeld, während der 180-Hz-Anteil eines Popmasters und der Bass
    zweier Quelldateien bei 9,5 bis 10,1 dB lagen. Bei der früheren Schwelle
    von 8 dB meldete das Programm für ein kommerzielles Master „Netzbrumm bei
    60 Hz und Vielfachen".
    """

    def test_musik_mit_kraeftigem_bass_gilt_nicht_als_brumm(self, media):
        """Entscheidend ist das dichte Umfeld: echter Musikbass füllt das
        ganze Band, ein Netzbrumm steht allein in der Stille."""
        from conftest import SR, _saegezahn, tone, write_pcm
        p = media / "bassmusik.flac"
        if not p.exists():
            n = SR * 12
            rng = np.random.default_rng(61)
            roh = np.convolve(rng.normal(0, 1, n), np.ones(60) / 60, mode="same")
            bass = (roh / np.abs(roh).max() * 0.8).astype(np.float32)
            huelle = (0.5 + 0.5 * np.sin(2 * np.pi * 0.4 * np.arange(n) / SR))
            x = bass + (_saegezahn(n, 60.0, amp=0.05) * huelle).astype(np.float32)
            x = x + tone(n, 800, amp=0.1)
            write_pcm(p, x / max(1.0, float(np.abs(x).max())), SR)
        r = core.lowfreq_scan(str(p))
        assert not r["hum"], r["hum"]

    def test_kraeftiger_brumm_wird_weiterhin_gefunden(self, hum60):
        r = core.lowfreq_scan(str(hum60))
        assert r["mains_hz"] == 60
        assert all(h["prominence_db"] >= 14 for h in r["hum"])


class TestDynamik:
    """Ein zusammengedrücktes Master ist kein Mangel, aber eine Feststellung wert.

    Ein zweites Beispiel aus der Lautheitskrieg-Ära zeigte die Lücke: −4,9 LUFS
    bei einem Crest-Faktor von 8,6 dB, aber sauber limitiert statt übersteuert –
    Flat factor 0,0, ein einziges Sample an der Vollaussteuerung. Die
    Übersteuerungsprüfung schwieg dazu zu Recht, das Programm sagte damit aber
    gar nichts über ein offensichtlich gequetschtes Master.
    """

    def test_lautes_master_wird_festgestellt(self):
        note = core.dynamics_note({"crest_db": 8.6, "lufs_integrated": -4.9})
        assert note is not None and note["level"] == "ok"
        assert "8.6" in note["text"]

    def test_analoger_rip_bleibt_unerwaehnt(self):
        assert core.dynamics_note({"crest_db": 21.2, "lufs_integrated": -23.7}) is None

    def test_leise_aber_dichte_aufnahme_bleibt_unerwaehnt(self):
        """Ein leises Signal mit kleinem Crest ist kein lautes Master."""
        assert core.dynamics_note({"crest_db": 9.0, "lufs_integrated": -30.0}) is None

    def test_ohne_messwerte_keine_aussage(self):
        assert core.dynamics_note({}) is None
        assert core.dynamics_note({"crest_db": 8.0}) is None
