"""HTTP-Schicht: Sandbox, Parameterprüfung, Cache, Endpunkte.

Der Sandbox-Teil ist der wichtigste: die Anwendung liest aus Ordnern, die der
Betreiber freigegeben hat, und darf unter keinen Umständen darüber hinaus.
"""

import importlib
import json
import shutil

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def app_env(tmp_path_factory, request):
    """Startet die Anwendung mit eigenen Ordnern und frischem Cache."""
    base = tmp_path_factory.mktemp("web")
    media = base / "medien" / "Alben"
    media.mkdir(parents=True)
    uploads = base / "uploads"
    cache = base / "cache"

    # Fixtures aus der Session in den Medienordner spiegeln
    src = request.getfixturevalue("fullband")
    shutil.copy(src, media / "fullband.flac")
    shutil.copy(request.getfixturevalue("lossy"), media / "lossy.mp3")
    shutil.copy(request.getfixturevalue("clicks"), media / "clicks.flac")
    shutil.copy(request.getfixturevalue("broken"), media / "broken.flac")

    import os
    os.environ.update({
        "MEDIA_DIRS": f"Musik={base / 'medien'}",
        "UPLOAD_DIR": str(uploads),
        "CACHE_DIR": str(cache),
        "SIDECAR_DIR": str(base / "index"),
        "CACHE_MAX_MB": "50",
        "MAX_UPLOAD_MB": "1",
        "AUTH_USER": "",
        "AUTH_PASS": "",
    })
    from app import web
    importlib.reload(web)
    return TestClient(web.app), web, base


@pytest.fixture(scope="module")
def client(app_env):
    return app_env[0]


class TestSandbox:
    @pytest.mark.parametrize("pfad", [
        "../../etc/passwd",
        "Alben/../../../etc/passwd",
        "/etc/passwd",
        "Alben/./../../etc/hosts",
    ])
    def test_ausbruchsversuche_werden_abgewiesen(self, client, pfad):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": pfad})
        assert r.status_code in (403, 404), r.text

    def test_unbekannter_ordner(self, client):
        r = client.get("/api/browse", params={"root": "fremd", "path": ""})
        assert r.status_code == 404

    def test_uploads_loeschen_nur_im_uploadordner(self, client):
        r = client.request("DELETE", "/api/upload",
                           params={"path": "../medien/Alben/fullband.flac"})
        assert r.status_code in (403, 404)

    def test_fehlermeldung_verraet_keinen_serverpfad(self, client, app_env):
        base = str(app_env[2])
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "Alben/broken.flac"})
        assert r.status_code == 422
        assert base not in r.text, r.text


class TestEndpunkte:
    def test_browse_listet_audiodateien(self, client):
        r = client.get("/api/browse", params={"root": "musik", "path": "Alben"})
        assert r.status_code == 200
        namen = {f["name"] for f in r.json()["files"]}
        assert {"fullband.flac", "lossy.mp3"} <= namen

    def test_spektrogramm_liefert_png_und_geometrie(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "Alben/fullband.flac"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        boxes = json.loads(r.headers["x-plot-box"])
        assert boxes and 0 < boxes[0]["x0"] < boxes[0]["x1"] < 1

    def test_zweiter_aufruf_kommt_aus_dem_cache(self, client):
        p = {"root": "musik", "path": "Alben/fullband.flac", "cmap": "viridis"}
        assert client.get("/api/spectrogram.png", params=p).headers["x-cache"] == "miss"
        assert client.get("/api/spectrogram.png", params=p).headers["x-cache"] == "hit"

    def test_cache_schluessel_enthaelt_die_analyseversion(self, app_env):
        """Nach einer Änderung an der Analyse dürfen keine alten Ergebnisse
        mehr ausgeliefert werden."""
        _, web, _ = app_env
        from app import core
        alt = web.cache_key("spec", [], {"a": 1})
        core.ANALYSIS_VERSION += 1
        try:
            assert web.cache_key("spec", [], {"a": 1}) != alt
        finally:
            core.ANALYSIS_VERSION -= 1
        core.RENDER_VERSION += 1
        try:
            assert web.cache_key("spec", [], {"a": 1}) != alt
        finally:
            core.RENDER_VERSION -= 1

    def test_bericht_enthaelt_alle_abschnitte(self, client):
        r = client.get("/api/report",
                       params={"root": "musik", "path": "Alben/fullband.flac"})
        assert r.status_code == 200
        d = r.json()
        for feld in ("file", "band", "bands", "verdict", "loudness", "lowfreq"):
            assert feld in d, feld
        assert d["file"]["path"] == "Alben/fullband.flac"      # kein Serverpfad

    def test_vergleich_und_kennzahlen(self, client):
        p = {"a_root": "musik", "a": "Alben/fullband.flac",
             "b_root": "musik", "b": "Alben/lossy.mp3"}
        assert client.get("/api/compare.png", params=p).status_code == 200
        d = client.get("/api/compare.json", params=p).json()
        assert "diff" in d and "offset_s" in d

    def test_kennzahlen_haengen_nicht_an_der_darstellung(self, client, monkeypatch):
        """Farbskala, Bildgröße, Differenzbereich und abgeschaltetes
        Differenzbild ändern an den Kennzahlen nichts - sie dürfen keinen
        zweiten Vergleich auslösen."""
        from app import core
        p = {"a_root": "musik", "a": "Alben/fullband.flac",
             "b_root": "musik", "b": "Alben/lossy.mp3", "nfft": "1024"}
        bild = client.get("/api/compare.png", params={
            **p, "diff": "0", "diff_range": "12", "cmap": "viridis"})
        assert bild.status_code == 200

        def verboten(*args, **kwargs):
            raise AssertionError("Vergleich wurde ein zweites Mal gerechnet")

        monkeypatch.setattr(core, "compare", verboten)
        r = client.get("/api/compare.json", params={
            **p, "cmap": "gray", "width": "9", "height": "3", "fmax": "8000"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "diff" in d
        assert d["a"]["path"] == "Alben/fullband.flac"       # kein Serverpfad

    def test_kennzahlen_ohne_bild_werden_abgelegt(self, client, monkeypatch):
        from app import core
        p = {"a_root": "musik", "a": "Alben/fullband.flac",
             "b_root": "musik", "b": "Alben/lossy.mp3", "nfft": "512"}
        erst = client.get("/api/compare.json", params=p)
        assert erst.status_code == 200

        def verboten(*args, **kwargs):
            raise AssertionError("Vergleich wurde ein zweites Mal gerechnet")

        monkeypatch.setattr(core, "compare", verboten)
        assert client.get("/api/compare.json", params=p).json() == erst.json()

    def test_cache_schreibt_ueber_eigene_zwischendateien(self, app_env, monkeypatch):
        """Zwei Schreiber mit demselben Ziel teilen sich nie eine Zwischendatei."""
        _, web, _ = app_env
        namen = []
        original = web.tempfile.mkstemp

        def mitschreiben(*args, **kwargs):
            fd, name = original(*args, **kwargs)
            namen.append(name)
            return fd, name

        monkeypatch.setattr(web.tempfile, "mkstemp", mitschreiben)
        ziel = web.CACHE_DIR / "atomar.stats.json"
        web.write_atomic(ziel, b"1")
        web.write_atomic(ziel, b"2")
        assert len(set(namen)) == 2
        assert ziel.read_bytes() == b"2"
        assert not list(web.CACHE_DIR.glob("*.part"))
        ziel.unlink()

    def test_liegengebliebene_zwischendateien_werden_entfernt(self, app_env):
        import os
        import time
        _, web, _ = app_env
        alt = web.CACHE_DIR / "abc.png.x1.part"
        frisch = web.CACHE_DIR / "def.png.x2.part"
        for f in (alt, frisch):
            f.write_bytes(b"x")
        vorher = time.time() - 7200
        os.utime(alt, (vorher, vorher))
        web.prune_cache()
        assert not alt.exists()
        assert frisch.exists()
        frisch.unlink()

    def test_stoerungssuche(self, client):
        r = client.get("/api/clicks",
                       params={"root": "musik", "path": "Alben/clicks.flac"})
        assert r.status_code == 200
        assert r.json()["count"] >= 5

    def test_tiefton(self, client):
        r = client.get("/api/lowfreq",
                       params={"root": "musik", "path": "Alben/fullband.flac"})
        assert r.status_code == 200 and "subsonic_db" in r.json()

    def test_scan(self, client):
        r = client.get("/api/scan", params={"root": "musik", "limit": 10})
        assert r.status_code == 200
        d = r.json()
        assert d["count"] >= 3
        assert all("verdict" in f or "error" in f for f in d["files"])

    def test_healthz_ohne_anmeldung(self, client):
        assert client.get("/healthz").json()["ok"] is True


class TestBrowserCache:
    def test_etag_und_304(self, client):
        p = {"root": "musik", "path": "Alben/fullband.flac", "cmap": "plasma"}
        erst = client.get("/api/spectrogram.png", params=p)
        etag = erst.headers["etag"]
        assert "private" in erst.headers["cache-control"]
        zweit = client.get("/api/spectrogram.png", params=p,
                           headers={"If-None-Match": etag})
        assert zweit.status_code == 304
        assert zweit.headers["x-plot-box"] == erst.headers["x-plot-box"]

    def test_geaenderte_datei_ergibt_neues_etag(self, client, app_env, fullband):
        import os
        _, _, base = app_env
        ziel = base / "medien" / "Alben" / "wechsel.flac"
        ziel.write_bytes(fullband.read_bytes())
        p = {"root": "musik", "path": "Alben/wechsel.flac"}
        etag = client.get("/api/spectrogram.png", params=p).headers["etag"]
        st = ziel.stat()
        os.utime(ziel, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        r = client.get("/api/spectrogram.png", params=p, headers={"If-None-Match": etag})
        assert r.status_code == 200 and r.headers["etag"] != etag
        ziel.unlink()


class TestUnendlicheWerte:
    @pytest.mark.parametrize("pfad,q", [
        ("/api/spectrogram.png", {"fmax": "nan"}),
        ("/api/spectrogram.png", {"width": "inf"}),
        ("/api/audio", {"start": "nan"}),
        ("/api/clicks", {"threshold_db": "nan"}),
        ("/api/wowflutter", {"nominal_hz": "0"}),
        ("/api/sweep", {"reference_hz": "-inf"}),
    ])
    def test_werden_abgewiesen(self, client, pfad, q):
        r = client.get(pfad, params={"root": "musik", "path": "Alben/fullband.flac", **q})
        assert r.status_code == 400, r.text


class TestWiedergabe:
    def test_ausschnitt_als_mp3(self, client, tmp_path):
        from app import core
        r = client.get("/api/audio", params={"root": "musik", "path": "Alben/fullband.flac",
                                             "start": "1", "duration": "2"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/mpeg"
        ziel = tmp_path / "ausschnitt.mp3"
        ziel.write_bytes(r.content)
        info = core.probe(str(ziel))
        assert info["codec"] == "mp3"
        assert abs(info["duration"] - 2.0) < 0.2

    def test_ausserhalb_der_freigabe(self, client):
        r = client.get("/api/audio", params={"root": "musik", "path": "../../etc/passwd"})
        assert r.status_code in (403, 404)


class TestResidualEndpunkte:
    P = {"a_root": "musik", "a": "Alben/clicks.flac",
         "b_root": "musik", "b": "Alben/clicks.flac"}

    def test_kennzahlen_dann_datei(self, client, tmp_path):
        from app import core
        info = client.get("/api/residual.json", params=self.P)
        assert info.status_code == 200, info.text
        assert info.json()["residual_db"] < -100          # identische Dateien
        r = client.get("/api/residual", params=self.P)
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/flac"
        assert "residual_clicks_minus_clicks.flac" in r.headers["content-disposition"]
        ziel = tmp_path / "r.flac"
        ziel.write_bytes(r.content)
        assert core.probe(str(ziel))["codec"] == "flac"

    def test_darstellung_aendert_den_schluessel_nicht(self, app_env):
        from app import core
        _, web, base = app_env
        f = base / "medien" / "Alben" / "clicks.flac"
        eins = web.residual_key(f, f, core.Params(cmap="gray", width=6).validate(), 0.0)
        zwei = web.residual_key(f, f, core.Params(db_range=60).validate(), 0.0)
        assert eins == zwei
        assert web.residual_key(f, f, core.Params().validate(), 6.0) != eins


class TestMessungenAusDerAblage:
    @pytest.mark.parametrize("pfad,funktion", [
        ("/api/report", "summary"), ("/api/clicks", "impulse_scan"),
        ("/api/lowfreq", "lowfreq_scan"),
    ])
    def test_zweiter_aufruf_rechnet_nicht(self, client, monkeypatch, pfad, funktion):
        """Die Oberfläche lädt den Bericht nach jedem Bild neu; eine andere
        Farbskala oder Dynamik darf ihn nicht neu rechnen lassen."""
        from app import core
        p = {"root": "musik", "path": "Alben/fullband.flac", "nfft": "1024"}
        assert client.get(pfad, params={**p, "cmap": "viridis"}).status_code == 200

        def verboten(*args, **kwargs):
            raise AssertionError("zweimal gerechnet")

        monkeypatch.setattr(core, funktion, verboten)
        r = client.get(pfad, params={**p, "cmap": "gray", "db_range": "60", "height": "3"})
        assert r.status_code == 200, r.text

    def test_andere_sprache_wird_neu_gerechnet(self, client):
        p = {"root": "musik", "path": "Alben/fullband.flac", "nfft": "512"}
        de = client.get("/api/report", params={**p, "lang": "de"}).json()
        en = client.get("/api/report", params={**p, "lang": "en"}).json()
        assert de["verdict"]["text"] != en["verdict"]["text"]


class TestSymlinks:
    """Browser und Scan zeigen nur, was sich auch öffnen lässt."""

    @pytest.fixture
    def links(self, app_env, fullband):
        import shutil
        _, _, base = app_env
        ordner = base / "medien" / "Links"
        ordner.mkdir()
        extern = base / "extern.flac"
        extern.write_bytes(fullband.read_bytes())
        (ordner / "draussen.flac").symlink_to(extern)
        (ordner / "drinnen.flac").symlink_to(base / "medien" / "Alben" / "fullband.flac")
        yield
        shutil.rmtree(ordner)
        extern.unlink()

    def test_browser(self, client, links):
        namen = {f["name"] for f in client.get(
            "/api/browse", params={"root": "musik", "path": "Links"}).json()["files"]}
        assert namen == {"drinnen.flac"}

    def test_scan(self, client, links):
        d = client.get("/api/scan", params={"root": "musik", "path": "Links",
                                            "seconds": 5}).json()
        assert [f["name"] for f in d["files"]] == ["drinnen.flac"]
        assert d["truncated"] is False


class TestAblageAufraeumen:
    def test_prune_ueber_die_api(self, client, app_env, fullband):
        _, web, _ = app_env
        web.SIDECARS.save("gibtsnicht", "x.flac", fullband, "q", {"n": 1})
        vorher = web.SIDECARS.stats()["entries"]
        d = client.post("/api/index/prune").json()
        assert d["checked"] == vorher and d["removed"] >= 1
        assert web.SIDECARS.stats()["entries"] == vorher - d["removed"]


class TestScanGrenze:
    def test_gekuerzt_nur_wenn_mehr_da_ist(self, client):
        alle = client.get("/api/scan", params={"root": "musik", "seconds": 5}).json()
        n = alle["count"]
        genau = client.get("/api/scan", params={"root": "musik", "seconds": 5,
                                                "limit": n}).json()
        assert genau["truncated"] is False and genau["count"] == n
        weniger = client.get("/api/scan", params={"root": "musik", "seconds": 5,
                                                  "limit": n - 1}).json()
        assert weniger["truncated"] is True and weniger["count"] == n - 1

    def test_grenze_gehoert_zur_laufenden_schleife(self, app_env):
        import asyncio
        _, web, _ = app_env
        grenze = web.Grenze(2)

        async def zweimal():
            return grenze(), grenze()

        a1, a2 = asyncio.run(zweimal())
        b1, _ = asyncio.run(zweimal())
        assert a1 is a2 and a1 is not b1


class TestSprache:
    def test_query_bestimmt_die_sprache(self, client):
        d = client.get("/api/report", params={"root": "musik",
                                              "path": "Alben/fullband.flac",
                                              "lang": "en"}).json()
        assert "band edge" in d["verdict"]["text"].lower()

    def test_accept_language_wird_beachtet(self, client):
        d = client.get("/api/report", params={"root": "musik",
                                              "path": "Alben/fullband.flac"},
                       headers={"Accept-Language": "en-GB,en;q=0.9"}).json()
        assert "band edge" in d["verdict"]["text"].lower()

    def test_voreinstellung_ist_deutsch(self, client):
        d = client.get("/api/report", params={"root": "musik",
                                              "path": "Alben/fullband.flac"}).json()
        assert "Bandkante" in d["verdict"]["text"]

    def test_konfiguration_nennt_die_sprachen(self, client):
        cfg = client.get("/api/config").json()
        assert set(cfg["languages"]) == {"de", "en"}

    def test_ablage_trennt_die_sprachen(self, client):
        """Sonst käme ein deutscher Text aus der Ablage in einer englischen
        Anfrage zurück."""
        de = client.get("/api/scan", params={"root": "musik", "limit": 5,
                                             "lang": "de"}).json()
        en = client.get("/api/scan", params={"root": "musik", "limit": 5,
                                             "lang": "en"}).json()
        t_de = next(f["verdict"]["text"] for f in de["files"] if f.get("verdict"))
        t_en = next(f["verdict"]["text"] for f in en["files"] if f.get("verdict"))
        assert t_de != t_en


class TestParameterpruefung:
    @pytest.mark.parametrize("q", [
        {"nfft": "1000"}, {"theme": "../etc"}, {"cmap": "; rm -rf /"},
        {"sr": "1"}, {"overlap": "3"}, {"window": "unbekannt"},
    ])
    def test_ungueltige_parameter_ergeben_400(self, client, q):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "Alben/fullband.flac", **q})
        assert r.status_code == 400, r.text

    def test_vertauschte_grenzen_werden_akzeptiert(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "Alben/fullband.flac",
                               "fmin": "18000", "fmax": "500"})
        assert r.status_code == 200


class TestUpload:
    def test_zu_grosse_datei_wird_abgelehnt(self, client, app_env):
        gross = b"0" * (2 * 1024 * 1024)
        r = client.post("/api/upload", files={"files": ("gross.flac", gross)})
        assert r.status_code == 200
        assert r.json()["errors"], r.json()

    def test_nicht_audio_wird_abgelehnt(self, client):
        r = client.post("/api/upload", files={"files": ("notiz.mp3", b"kein audio")})
        assert r.json()["saved"] == []

    def test_pfadangaben_im_namen_werden_entschaerft(self, client, app_env, fullband):
        daten = fullband.read_bytes()
        r = client.post("/api/upload",
                        files={"files": ("../../boese.flac", daten)})
        gespeichert = r.json()["saved"]
        assert gespeichert and "/" not in gespeichert[0]["path"]
        assert not (app_env[2] / "boese.flac").exists()

    def test_windows_pfad_im_namen(self, client, fullband):
        r = client.post("/api/upload",
                        files={"files": ("C:\\Musik\\windows.flac", fullband.read_bytes())})
        assert r.json()["saved"][0]["name"] == "windows.flac"

    def test_fuehrender_punkt_wird_entfernt(self, client, fullband):
        """Eine versteckte Datei tauchte nirgends auf und liess sich über die
        Oberfläche weder finden noch löschen."""
        r = client.post("/api/upload",
                        files={"files": (".versteckt.flac", fullband.read_bytes())})
        name = r.json()["saved"][0]["name"]
        assert name == "versteckt.flac"
        namen = {f["name"] for f in
                 client.get("/api/browse", params={"root": "uploads"}).json()["files"]}
        assert name in namen

    def test_zu_grosse_datei_hinterlaesst_nichts(self, client, app_env):
        _, web, _ = app_env
        vorher = set(web.UPLOAD_DIR.iterdir())
        r = client.post("/api/upload",
                        files={"files": ("riesig.flac", b"0" * (3 * 1024 * 1024))})
        assert r.json()["errors"] and not r.json()["saved"]
        assert set(web.UPLOAD_DIR.iterdir()) == vorher

    def test_mehrere_dateien_in_einer_anfrage(self, client, fullband):
        daten = fullband.read_bytes()
        r = client.post("/api/upload", files=[
            ("files", ("paar1.flac", daten)),
            ("files", ("kaputt.flac", b"kein audio")),
            ("files", ("paar2.flac", daten)),
        ])
        d = r.json()
        assert sorted(x["name"] for x in d["saved"]) == ["paar1.flac", "paar2.flac"]
        assert [e["name"] for e in d["errors"]] == ["kaputt.flac"]

    def test_gleiche_namen_werden_unterschieden(self, client, fullband):
        daten = fullband.read_bytes()
        namen = [client.post("/api/upload", files={"files": ("doppelt.flac", daten)})
                 .json()["saved"][0]["name"] for _ in range(2)]
        assert namen[0] == "doppelt.flac" and namen[1] == "doppelt_1.flac"

    def test_ohne_multipart_400(self, client):
        r = client.post("/api/upload", json={"files": "x"})
        assert r.status_code == 400


class TestScanStrom:
    """Der Ereignisstrom liefert Ergebnisse einzeln, statt am Ende alles auf einmal."""

    def _ereignisse(self, roh: str):
        art = None
        for zeile in roh.splitlines():
            if zeile.startswith("event: "):
                art = zeile[7:]
            elif zeile.startswith("data: ") and art:
                yield art, json.loads(zeile[6:])

    def test_strom_meldet_start_dateien_und_ende(self, client):
        with client.stream("GET", "/api/scan/stream",
                           params={"root": "musik", "limit": 5, "seconds": 10}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            roh = "".join(r.iter_text())
        arten = [a for a, _ in self._ereignisse(roh)]
        assert arten[0] == "start"
        assert arten[-1] == "done"
        assert arten.count("file") >= 3

    def test_jede_datei_kommt_mit_fortschritt(self, client):
        with client.stream("GET", "/api/scan/stream",
                           params={"root": "musik", "limit": 5, "seconds": 10}) as r:
            roh = "".join(r.iter_text())
        dateien = [d for a, d in self._ereignisse(roh) if a == "file"]
        for i, d in enumerate(dateien, start=1):
            assert d["done"] == i
            assert d["total"] >= len(dateien)
            assert "path" in d["file"]

    def test_abschluss_zaehlt_richtig(self, client):
        with client.stream("GET", "/api/scan/stream",
                           params={"root": "musik", "limit": 5, "seconds": 10}) as r:
            roh = "".join(r.iter_text())
        dateien = [d for a, d in self._ereignisse(roh) if a == "file"]
        ende = next(d for a, d in self._ereignisse(roh) if a == "done")
        assert ende["count"] == len(dateien)
        assert ende["computed"] + ende["from_index"] == ende["count"]

    def test_zweiter_lauf_kommt_aus_der_ablage(self, client):
        """Prüft zugleich, dass die Ablage überhaupt aktiv ist.

        Ohne diese Zusicherung schlug der Test nur auf Läufern fehl, die den
        Vorgabepfad nicht anlegen dürfen – und die Ursache stand nirgends.
        """
        p = {"root": "musik", "limit": 5, "seconds": 10}
        for _ in range(2):
            with client.stream("GET", "/api/scan/stream", params=p) as r:
                roh = "".join(r.iter_text())
        start = next(d for a, d in self._ereignisse(roh) if a == "start")
        assert start["index"], "Ergebnisablage ist abgeschaltet"
        ende = next(d for a, d in self._ereignisse(roh) if a == "done")
        dateien = [d["file"] for a, d in self._ereignisse(roh) if a == "file"]
        fehler = sum(1 for f in dateien if f.get("error"))
        # Fehlerhafte Dateien landen bewusst nicht in der Ablage und werden
        # jedes Mal neu versucht - vielleicht ist die Datei ja repariert.
        assert ende["from_index"] == ende["count"] - fehler, (ende, fehler)

    def test_unbekannter_ordner_wird_abgewiesen(self, client):
        r = client.get("/api/scan/stream", params={"root": "fremd"})
        assert r.status_code == 404


class TestFehlermeldungenSprache:
    """Auch Fehlertexte folgen der Sprache – sonst bekommt ein englischer
    Nutzer mitten im Ablauf einen deutschen Satz."""

    def test_datei_nicht_gefunden(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "gibtsnicht.flac",
                               "lang": "en"})
        assert r.status_code == 404
        assert r.json()["detail"] == "file not found"

    def test_unbekannter_ordner(self, client):
        r = client.get("/api/browse", params={"root": "fremd", "lang": "en"})
        assert "unknown folder" in r.json()["detail"]

    def test_ungueltiger_parameter(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "Alben/fullband.flac",
                               "nfft": "abc", "lang": "en"})
        assert r.status_code == 400
        assert "invalid value" in r.json()["detail"]

    def test_ausbruchsversuch(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "../../etc/passwd",
                               "lang": "en"})
        assert r.status_code == 403
        assert "outside" in r.json()["detail"]

    def test_deutsch_bleibt_voreinstellung(self, client):
        r = client.get("/api/spectrogram.png",
                       params={"root": "musik", "path": "gibtsnicht.flac"})
        assert r.json()["detail"] == "Datei nicht gefunden"


class TestUploadVerwaltung:
    """Mehrere Uploads auf einmal löschen, und den Ordner leeren."""

    def _hochladen(self, client, fullband, namen):
        daten = fullband.read_bytes()
        gespeichert = []
        for name in namen:
            r = client.post("/api/upload", files={"files": (name, daten)})
            gespeichert.extend(x["path"] for x in r.json()["saved"])
        return gespeichert

    def test_mehrere_auf_einmal(self, client, fullband):
        pfade = self._hochladen(client, fullband, ["m1.flac", "m2.flac", "m3.flac"])
        assert len(pfade) == 3
        r = client.request("DELETE", "/api/upload",
                           params=[("path", pfade[0]), ("path", pfade[1])])
        d = r.json()
        assert sorted(d["deleted"]) == sorted(pfade[:2]), d
        assert not d["errors"]
        uebrig = {f["name"] for f in
                  client.get("/api/browse", params={"root": "uploads"}).json()["files"]}
        assert "m3.flac" in uebrig and "m1.flac" not in uebrig

    def test_unbekannter_pfad_wird_gemeldet_ohne_abbruch(self, client, fullband):
        pfade = self._hochladen(client, fullband, ["echt.flac"])
        r = client.request("DELETE", "/api/upload",
                           params=[("path", "gibtsnicht.flac"), ("path", pfade[0])])
        d = r.json()
        assert d["deleted"] == pfade
        assert len(d["errors"]) == 1

    def test_ausbruch_beim_mehrfachloeschen(self, client, app_env, fullband):
        """Ein unzulässiger Pfad wird abgewiesen, auch im Verbund mit gültigen."""
        r = client.request("DELETE", "/api/upload",
                           params=[("path", "../medien/Alben/fullband.flac")])
        assert r.status_code in (403, 404), r.text
        assert (app_env[2] / "medien" / "Alben" / "fullband.flac").exists()

        pfade = self._hochladen(client, fullband, ["mitlauf.flac"])
        r = client.request("DELETE", "/api/upload",
                           params=[("path", "../medien/Alben/fullband.flac"),
                                   ("path", pfade[0])])
        d = r.json()
        assert d["deleted"] == pfade and len(d["errors"]) == 1
        assert (app_env[2] / "medien" / "Alben" / "fullband.flac").exists()

    def test_alle_leeren(self, client, fullband):
        self._hochladen(client, fullband, ["a1.flac", "a2.flac"])
        d = client.request("DELETE", "/api/uploads").json()
        assert d["count"] >= 2 and d["bytes"] > 0
        rest = client.get("/api/browse", params={"root": "uploads"}).json()["files"]
        assert rest == []

    def test_leeren_bei_leerem_ordner(self, client):
        client.request("DELETE", "/api/uploads")
        d = client.request("DELETE", "/api/uploads").json()
        assert d["count"] == 0 and d["deleted"] == []


class TestAblageOrt:
    """Die Ablage weicht aus, statt sich abzuschalten."""

    def test_ausweichen_wenn_der_vorgabepfad_fehlschlaegt(self, tmp_path, monkeypatch):
        import importlib

        from app import web
        monkeypatch.setenv("SIDECAR_DIR", "/proc/gibtsnicht/index")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("MEDIA_DIRS", f"Musik={tmp_path}")
        importlib.reload(web)
        try:
            assert web.SIDECARS.enabled
            assert str(tmp_path / "cache") in web.SIDECARS.stats()["path"]
        finally:
            importlib.reload(web)

    def test_abschaltbar(self, tmp_path, monkeypatch):
        import importlib

        from app import web
        monkeypatch.setenv("SIDECAR", "0")
        monkeypatch.setenv("MEDIA_DIRS", f"Musik={tmp_path}")
        importlib.reload(web)
        try:
            assert web.SIDECARS.enabled is False
        finally:
            importlib.reload(web)


class TestAnmeldung:
    """Ein gesetztes Passwort schützt auch ohne Benutzernamen."""

    def test_nur_passwort_schaltet_die_anmeldung_ein(self, tmp_path, monkeypatch):
        import base64
        import importlib

        from app import web
        monkeypatch.setenv("AUTH_USER", "")
        monkeypatch.setenv("AUTH_PASS", "geheim")
        monkeypatch.setenv("MEDIA_DIRS", f"Musik={tmp_path}")
        monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "up"))
        monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
        importlib.reload(web)
        try:
            c = TestClient(web.app)
            assert c.get("/api/config").status_code == 401
            falsch = base64.b64encode(b":falsch").decode()
            assert c.get("/api/config", headers={
                "Authorization": f"Basic {falsch}"}).status_code == 401
            richtig = base64.b64encode(b":geheim").decode()
            assert c.get("/api/config", headers={
                "Authorization": f"Basic {richtig}"}).status_code == 200
            assert c.get("/healthz").status_code == 200
        finally:
            monkeypatch.setenv("AUTH_PASS", "")
            importlib.reload(web)
