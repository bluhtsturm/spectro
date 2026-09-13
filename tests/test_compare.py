"""Vergleich zweier Dateien, Nullprobe und Residual."""

import numpy as np
import pytest

from app import core


class TestVergleich:
    def test_gleiche_zeitaufloesung_bei_ungleicher_laenge(self, fullband, longer):
        """Das Spalten-Pooling arbeitet in Zweierpotenzen.

        Unterschiedlich lange Dateien bekommen dadurch verschiedene Zeitraster;
        ohne Angleichung verglich das Differenzbild verschiedene Zeitpunkte
        miteinander.
        """
        panels, _ = core.compare(str(fullband), str(longer), core.Params())
        a, b = panels[0], panels[1]
        da = (a.t1 - a.t0) / a.db.shape[1]
        db = (b.t1 - b.t0) / b.db.shape[1]
        # Rundung auf ganze Spalten laesst einen Rest von unter einem Prozent;
        # ein falsches Raster waere um den Faktor zwei daneben
        assert abs(da - db) / max(da, db) < 5e-3

    def test_versatz_wird_ausgeglichen(self, fullband, delayed):
        _, stats = core.compare(str(fullband), str(delayed), core.Params())
        assert abs(stats["offset_s"] + 0.25) < 0.05, stats["offset_s"]

    def test_identische_dateien_ergeben_null_differenz(self, fullband):
        _, stats = core.compare(str(fullband), str(fullband), core.Params())
        assert stats["diff"]["p90_abs_db"] == 0.0

    def test_kanalmodus_alle_wird_zur_summe(self, fullband, longer):
        """Ein Differenzbild über mehrere Kanäle ist nicht definiert."""
        panels, _ = core.compare(str(fullband), str(longer),
                                 core.Params(channels="all"))
        assert len(panels) == 3
        assert "Mono" in panels[0].label or "Summe" in panels[0].label

    def test_ausrichtung_greift_nicht_bei_fremdem_material(self, fullband, unrelated):
        """Lieber kein Versatz als ein zufälliger: bei unverwandtem Material
        darf die Suche nicht irgendeine Verschiebung erfinden."""
        _, stats = core.compare(str(fullband), str(unrelated), core.Params())
        assert stats["offset_s"] == 0.0


class TestNullprobe:
    def test_identisch(self, fullband):
        r = core.null_test(str(fullband), str(fullband))
        assert r["residual_db"] < -100
        assert r["correlation"] > 0.999
        assert r["verdict"]["level"] == "ok"

    def test_fremdes_material_wird_erkannt(self, fullband, unrelated):
        r = core.null_test(str(fullband), str(unrelated))
        assert r["correlation"] < 0.5
        assert "Ursprung" in r["verdict"]["text"]

    def test_versatz_wird_gefunden(self, fullband, delayed):
        r = core.null_test(str(fullband), str(delayed))
        assert abs(r["offset_ms"] + 250) < 5
        assert r["residual_db"] < -40

    def test_stille_wird_abgewiesen(self, fullband, silence):
        with pytest.raises(core.AudioError, match="still"):
            core.null_test(str(fullband), str(silence))


class TestResidual:
    def test_entknacksen_hinterlaesst_impulse(self, tmp_path, clicks, declicked):
        out = tmp_path / "residual.flac"
        r = core.null_residual(str(clicks), str(declicked), str(out))
        assert out.exists()
        # Das Entfernte ist impulsartig: deutlich höherer Crest als die Quelle
        assert r["crest_db"] - r["source_crest_db"] > 10
        assert r["verdict"]["level"] == "ok"
        # Und die Energie sitzt an den Stellen, an denen die Knackser waren.
        # Nicht mit impulse_scan pruefen: der Entknackser ersetzt ein Fenster
        # von etwa 55 ms, das Residual besteht also aus breiten Bursts.
        from conftest import CLICK_TIMES
        x = core._decode_mono(str(out), 44100)
        blocke = 4410                                   # 100 ms
        e = (x[:len(x) // blocke * blocke].reshape(-1, blocke) ** 2).mean(axis=1)
        ruhe = float(np.median(e))
        # An den Knackser-Stellen liegt die Energie rund 13 dB über dem
        # ruhigen Rest; der Faktor 10 lässt dafür etwas Luft.
        laut = [t for t in CLICK_TIMES if e[int(t * 44100 / blocke)] > ruhe * 10]
        assert len(laut) == len(CLICK_TIMES), (laut, ruhe)

    def test_kennzahlen_der_zerlegung_vorhanden(self, tmp_path, clicks, declicked):
        out = tmp_path / "r2.flac"
        r = core.null_residual(str(clicks), str(declicked), str(out))
        for feld in ("quiet_rel_db", "loud_rel_db", "shape_correlation"):
            assert feld in r, feld

    def test_reine_pegelaenderung_bleibt_uebrig_klein(self, tmp_path, media, fullband):
        """Ein konstanter Pegelunterschied wird abgeglichen, nicht gemeldet."""
        from conftest import ff
        leiser = media / "leiser.flac"
        if not leiser.exists():
            ff(["-i", str(fullband), "-af", "volume=-6dB", str(leiser)])
        out = tmp_path / "r3.flac"
        r = core.null_residual(str(fullband), str(leiser), str(out))
        assert r["residual_db"] < -60
        assert abs(r["gain_db"] - 6.0) < 0.5

    def test_verstuemmeltes_material_wird_abgewiesen(self, tmp_path, fullband, broken):
        with pytest.raises(core.AudioError):
            core.null_residual(str(fullband), str(broken), str(tmp_path / "x.flac"))


class TestRobustheit:
    def test_defekte_datei_endet_als_audioerror(self, broken):
        with pytest.raises(core.AudioError):
            core.analyse(str(broken), core.Params())

    def test_datei_kuerzer_als_das_fenster(self, media):
        from conftest import write_pcm, tone, SR
        p = media / "sehr_kurz.wav"
        write_pcm(p.with_suffix(".flac"), tone(2000, 1000), SR)
        a = core.analyse(str(p.with_suffix(".flac")), core.Params(nfft=8192))
        assert a.mags[0].shape[1] >= 1

    def test_render_liefert_geometrie(self, tmp_path, fullband):
        p = core.Params()
        a = core.analyse(str(fullband), p)
        boxes = core.render(core.build_panels(a, p), p, str(tmp_path / "x.png"),
                            title="t", subtitle="s")
        assert len(boxes) == 1
        b = boxes[0]
        assert 0 < b["x0"] < b["x1"] < 1
        assert 0 < b["y0"] < b["y1"] < 1
        assert b["t0"] == 0 and b["t1"] > 7

    def test_render_ohne_achsen(self, tmp_path, fullband):
        p = core.Params(raw=True)
        a = core.analyse(str(fullband), p)
        out = tmp_path / "raw.png"
        core.render(core.build_panels(a, p), p, str(out))
        assert out.stat().st_size > 1000

    def test_zeitfenster_ausserhalb_der_datei(self, fullband):
        with pytest.raises(core.AudioError):
            core.analyse(str(fullband), core.Params(start=600, duration=5))

    def test_langlauf_bleibt_im_spaltenlimit(self, longer):
        p = core.Params(max_cols=500)
        a = core.analyse(str(longer), p)
        assert a.mags[0].shape[1] <= 1000        # Pooling verdoppelt maximal
        assert abs(a.duration - 200) < 1
