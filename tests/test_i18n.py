"""Zweisprachigkeit: Vollständigkeit und Wirkung."""

import re
from pathlib import Path

import pytest

from app import core
from app.i18n import LANGUAGES, MESSAGES, khz, normalise, t

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


class TestSprachtabelle:
    def test_alle_sprachen_haben_dieselben_schluessel(self):
        basis = set(MESSAGES["de"])
        for lang in LANGUAGES:
            fehlt = basis - set(MESSAGES[lang])
            zuviel = set(MESSAGES[lang]) - basis
            assert not fehlt, (lang, sorted(fehlt))
            assert not zuviel, (lang, sorted(zuviel))

    def test_platzhalter_stimmen_ueberein(self):
        """Ein vergessener Platzhalter fiele sonst erst im Betrieb auf."""
        muster = re.compile(r"\{(\w+)")
        for key, vorlage in MESSAGES["de"].items():
            for lang in LANGUAGES:
                assert set(muster.findall(vorlage)) == set(muster.findall(MESSAGES[lang][key])), \
                    (key, lang)

    @pytest.mark.parametrize("roh,erwartet", [
        ("de", "de"), ("en", "en"), ("de-DE", "de"), ("en_GB", "en"),
        ("fr", "de"), ("", "de"), (None, "de"),
    ])
    def test_sprachcodes_werden_normalisiert(self, roh, erwartet):
        assert normalise(roh) == erwartet

    def test_dezimaltrennzeichen(self):
        assert khz(16500, "de") == "16,5 kHz"
        assert khz(16500, "en") == "16.5 kHz"

    def test_unbekannter_schluessel_faellt_nicht_um(self):
        assert t("gibt.es.nicht", "en") == "gibt.es.nicht"


class TestOberflaeche:
    def test_frontend_hat_beide_sprachen(self):
        quelle = (STATIC / "i18n.js").read_text(encoding="utf-8")
        for lang in LANGUAGES:
            assert f"  {lang}: {{" in quelle, lang

    def test_keine_deutschen_texte_mehr_im_javascript(self):
        """Sichtbare Texte gehören in i18n.js, nicht in die Logik.

        Kommentare dürfen deutsch bleiben - sie erscheinen nie auf dem
        Bildschirm -, deshalb werden sie vorher entfernt. Ebenso wichtig:
        der Ausdruck darf nicht über Zeilenumbrüche hinweg greifen, sonst
        verbindet er zwei unabhängige Anführungszeichen zu einem Treffer.
        """
        quelle = (STATIC / "app.js").read_text(encoding="utf-8")
        ohne_kommentare = "\n".join(
            re.sub(r"//.*$", "", zeile) for zeile in quelle.splitlines())
        verdaechtig = re.findall(
            r'"[^"\n]*\b(?:Datei|Dateien|Fehler|Kanäle|läuft|gefunden|Bewertung)\b[^"\n]*"',
            ohne_kommentare)
        assert not verdaechtig, verdaechtig


class TestAnalyseSprache:
    def test_bewertung_folgt_der_sprache(self, lossy):
        p_de = core.Params(nfft=4096, overlap=0.5, lang="de")
        a = core.analyse(str(lossy), p_de)
        de = core.band_analysis(a.mags[0], a.sr, 4096, "mp3", lang="de")
        en = core.band_analysis(a.mags[0], a.sr, 4096, "mp3", lang="en")
        assert de["verdict"]["text"] != en["verdict"]["text"]
        assert "Bandbegrenzung" in de["verdict"]["text"]
        assert "Band limit" in en["verdict"]["text"]

    def test_kanalnamen_folgen_der_sprache(self, fullband):
        assert core.analyse(str(fullband), core.Params(lang="de")).labels == ["Mono"]
        assert core.analyse(str(fullband), core.Params(lang="en")).labels == ["Mono"]

    def test_unbekannte_sprache_faellt_auf_deutsch_zurueck(self):
        assert core.Params(lang="klingon").validate().lang == "de"

    def test_fehlermeldung_folgt_der_sprache(self, fullband, silence):
        with pytest.raises(core.AudioError, match="silent"):
            core.null_test(str(fullband), str(silence), core.Params(lang="en"))


class TestSprachkontext:
    """Die Sprache gilt je Aufruf, nicht prozessweit.

    Mit einer globalen Variablen hätte eine gleichzeitige Anfrage in einer
    anderen Sprache die Meldungen dieser hier umgestellt.
    """

    def test_kontext_wirkt_auf_die_voreinstellung(self):
        from app.i18n import current, set_current
        try:
            set_current("en")
            assert current() == "en"
            assert t("http.not_found") == "file not found"
        finally:
            set_current("de")
        assert t("http.not_found") == "Datei nicht gefunden"

    def test_ausdrueckliche_sprache_schlaegt_den_kontext(self):
        from app.i18n import set_current
        try:
            set_current("en")
            assert t("http.not_found", "de") == "Datei nicht gefunden"
        finally:
            set_current("de")

    def test_nebenlaeufige_aufrufe_stoeren_sich_nicht(self):
        import concurrent.futures as cf

        from app import core

        def arbeite(lang):
            core.set_language(lang)
            ergebnisse = []
            for _ in range(20):
                ergebnisse.append(t("http.not_found"))
            return set(ergebnisse)

        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            aufgaben = [ex.submit(arbeite, lang)
                        for lang in ("de", "en") * 8]
            treffer = [f.result() for f in aufgaben]
        for menge in treffer:
            assert len(menge) == 1, menge          # je Thread nur eine Sprache

    def test_zahlen_folgen_dem_kontext(self):
        from app.i18n import khz, set_current
        try:
            set_current("en")
            assert khz(16500) == "16.5 kHz"
            set_current("de")
            assert khz(16500) == "16,5 kHz"
        finally:
            set_current("de")
