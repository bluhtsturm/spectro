"""Oberflächentests im echten Browser.

Das Frontend hat über tausend Zeilen JavaScript, und ein Tippfehler darin geht
durch jede Python-Prüfung hindurch. Diese Tests starten die Anwendung, laden
sie in einem Chromium und sammeln dabei sämtliche Konsolen- und Seitenfehler
ein – ein einziger davon lässt den Test scheitern.

Sie überspringen sich selbst, wenn Playwright oder der Browser fehlen, damit
die übrige Suite überall läuft.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError as e:                       # auch ein kaputter Import zählt
    pytest.skip(f"Playwright nicht verfügbar: {e}", allow_module_level=True)

WURZEL = Path(__file__).resolve().parents[1]


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def dienst(tmp_path_factory, request):
    """Startet die Anwendung mit eigenen Ordnern auf einem freien Port."""
    basis = tmp_path_factory.mktemp("browser")
    medien = basis / "medien"
    medien.mkdir(parents=True)
    for name in ("fullband", "lossy", "clicks"):
        quelle = Path(request.getfixturevalue(name))
        shutil.copy(quelle, medien / quelle.name)

    port = freier_port()
    umgebung = {
        **os.environ,
        "MEDIA_DIRS": f"Proben={basis / 'medien'}",
        "UPLOAD_DIR": str(basis / "uploads"),
        "CACHE_DIR": str(basis / "cache"),
        "SIDECAR_DIR": str(basis / "index"),
        "PYTHONPATH": str(WURZEL),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.web:app", "--port", str(port),
         "--log-level", "warning"],
        cwd=str(WURZEL), env=umgebung,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    import urllib.error
    import urllib.request
    for _ in range(60):
        if proc.poll() is not None:
            fehler = proc.stderr.read().decode(errors="replace")[-800:]
            pytest.fail(f"Dienst beendete sich beim Start:\n{fehler}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    else:
        proc.terminate()
        pytest.fail("Dienst wurde nicht rechtzeitig erreichbar")

    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--no-sandbox"])
        except PlaywrightError as e:
            pytest.skip(f"Chromium nicht verfügbar: {str(e)[:120]}")
        yield b
        b.close()


class Seite:
    """Kapselt eine Browserseite samt gesammelter Fehler."""

    def __init__(self, browser, basis, lang="de", breite=1400, hoehe=950):
        self.fehler: list[str] = []
        self.page = browser.new_page(viewport={"width": breite, "height": hoehe})
        self.page.on("pageerror", lambda e: self.fehler.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.fehler.append(f"console: {m.text}")
                     if m.type == "error" else None)
        self.page.goto(f"{basis}/?lang={lang}", wait_until="networkidle")
        self.page.wait_for_timeout(400)

    def datei_waehlen(self, teil, slot=None):
        if slot:
            self.page.click(f".item:has-text('{teil}') .pick button:has-text('{slot}')")
        else:
            self.page.click(f".item:has-text('{teil}') .nm")

    def warte_auf_bild(self, timeout=60000):
        self.page.wait_for_selector("#viewer:not([hidden])", timeout=timeout)
        self.page.wait_for_function(
            "() => { const i = document.getElementById('spec');"
            " return i && i.src && i.naturalWidth > 100; }", timeout=timeout)

    def schliessen(self):
        self.page.close()


@pytest.fixture
def seite(browser, dienst):
    s = Seite(browser, dienst)
    yield s
    assert not s.fehler, s.fehler
    s.schliessen()


class TestGrundfunktion:
    def test_seite_laedt_ohne_fehler(self, seite):
        assert seite.page.locator("#render").inner_text() == "Analysieren"
        assert seite.page.locator("#listing .item").count() >= 1

    def test_statische_texte_werden_eingesetzt(self, seite):
        """Kein Element darf seinen Übersetzungsschlüssel anzeigen."""
        roh = seite.page.evaluate(
            "() => [...document.querySelectorAll('[data-i18n]')]"
            ".map(e => e.textContent).filter(t => /^[a-z]+\\.[a-zA-Z]+$/.test(t))")
        assert roh == [], roh

    def test_einzelanalyse_zeichnet_und_berichtet(self, seite):
        seite.datei_waehlen("fullband")
        seite.warte_auf_bild()
        seite.page.wait_for_selector("#report .card", timeout=60000)
        titel = seite.page.locator("#report .card h3").all_inner_texts()
        assert any("DATEI" in t.upper() for t in titel), titel

    def test_geometrie_kommt_mit_dem_bild(self, seite):
        seite.datei_waehlen("fullband")
        seite.warte_auf_bild()
        boxen = seite.page.evaluate("() => state.boxes")
        assert boxen and 0 < boxen[0]["x0"] < boxen[0]["x1"] < 1


class TestBedienung:
    def test_aufziehen_zoomt_in_zeit_und_frequenz(self, seite):
        seite.datei_waehlen("fullband")
        seite.warte_auf_bild()
        rahmen = seite.page.locator("#imgwrap").bounding_box()
        seite.page.mouse.move(rahmen["x"] + rahmen["width"] * 0.3,
                              rahmen["y"] + rahmen["height"] * 0.75)
        seite.page.mouse.down()
        seite.page.mouse.move(rahmen["x"] + rahmen["width"] * 0.6,
                              rahmen["y"] + rahmen["height"] * 0.35, steps=8)
        seite.page.mouse.up()
        # Der Zoomtext erscheint erst, wenn das neue Bild da ist
        seite.page.wait_for_function(
            "() => document.getElementById('zoominfo').textContent.trim().length > 0",
            timeout=90000)
        text = seite.page.locator("#zoominfo").inner_text()
        assert "–" in text and "kHz" in text, text

        seite.page.keyboard.press("Escape")
        seite.page.wait_for_function(
            "() => document.getElementById('zoominfo').textContent.trim() === ''",
            timeout=90000)

    def test_vergleich_mit_nullprobe(self, seite):
        seite.page.click("#mode-compare")
        seite.page.wait_for_timeout(300)
        seite.datei_waehlen("fullband", "A")
        seite.page.wait_for_timeout(1500)
        seite.datei_waehlen("lossy", "B")
        seite.warte_auf_bild()
        seite.page.wait_for_selector("#report .card", timeout=90000)
        seite.page.click("#nulltest")
        seite.page.wait_for_selector("#nullcard", timeout=90000)
        assert "dB" in seite.page.locator("#nullcard").inner_text()

    def test_scan_zeigt_fortschritt_und_endet(self, seite):
        seite.page.click("#scan")
        seite.page.wait_for_selector("table.scan tbody tr", timeout=90000)
        seite.page.wait_for_function(
            "() => scanData && scanData.laufend === false", timeout=180000)
        zeilen = seite.page.locator("table.scan tbody tr").count()
        assert zeilen >= 2, zeilen

    def test_stoerungssuche_liefert_zeitmarken(self, seite):
        seite.datei_waehlen("clicks")
        seite.warte_auf_bild()
        seite.page.click("#clicks")
        seite.page.wait_for_selector("#clickcard", timeout=90000)
        assert seite.page.locator("#events button").count() >= 1


class TestSprache:
    def test_englische_oberflaeche(self, browser, dienst):
        s = Seite(browser, dienst, lang="en")
        try:
            assert s.page.locator("#render").inner_text() == "Analyse"
            assert s.page.locator("#mode-compare").inner_text() == "Compare A/B"
            assert not s.fehler, s.fehler
        finally:
            s.schliessen()

    def test_umschalten_wechselt_die_sprache(self, browser, dienst):
        s = Seite(browser, dienst, lang="de")
        try:
            s.page.select_option("#lang", "en")
            s.page.wait_for_function(
                "() => document.getElementById('render').textContent === 'Analyse'",
                timeout=30000)
            assert not s.fehler, s.fehler
        finally:
            s.schliessen()


class TestDarstellung:
    def test_schmales_display(self, browser, dienst):
        """Auf dem Telefon muss die Bedienung erreichbar bleiben."""
        s = Seite(browser, dienst, breite=390, hoehe=844)
        try:
            s.datei_waehlen("fullband", "A")
            s.warte_auf_bild()
            breite = s.page.evaluate(
                "() => document.getElementById('spec').getBoundingClientRect().width")
            assert breite <= 390
            assert not s.fehler, s.fehler
        finally:
            s.schliessen()


class TestUploadsLoeschen:
    """Auswahl und Sammellöschung in der Oberfläche."""

    def test_auswahl_und_sammelloeschung(self, browser, dienst, fullband):
        import urllib.request
        s = Seite(browser, dienst)
        try:
            # drei Dateien über die API hochladen, dann in der Oberfläche löschen
            daten = fullband.read_bytes()
            for name in ("u1.flac", "u2.flac", "u3.flac"):
                grenze = "----spectro"
                koerper = (
                    f"--{grenze}\r\nContent-Disposition: form-data; name=\"files\";"
                    f" filename=\"{name}\"\r\nContent-Type: audio/flac\r\n\r\n"
                ).encode() + daten + f"\r\n--{grenze}--\r\n".encode()
                req = urllib.request.Request(
                    f"{dienst}/api/upload", data=koerper, method="POST",
                    headers={"Content-Type": f"multipart/form-data; boundary={grenze}"})
                urllib.request.urlopen(req).read()

            s.page.select_option("#root", "uploads")
            s.page.wait_for_selector("#uploadbar", timeout=30000)
            kaesten = s.page.locator("#listing .upsel")
            assert kaesten.count() >= 3

            kaesten.nth(0).click()
            kaesten.nth(1).click()
            assert "2" in s.page.locator("#uploadbar").inner_text()

            s.page.on("dialog", lambda d: d.accept())
            s.page.click("#up-del")
            s.page.wait_for_function(
                "() => document.querySelectorAll('#listing .upsel').length === 1",
                timeout=30000)

            s.page.click("#up-clear")
            s.page.wait_for_function(
                "() => document.querySelectorAll('#listing .upsel').length === 0",
                timeout=30000)
            assert not s.fehler, s.fehler
        finally:
            s.schliessen()
