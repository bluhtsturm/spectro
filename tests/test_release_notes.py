"""Release-Seite: der Text entsteht aus beiden CHANGELOGs."""

import importlib.util
import re
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_notes", WURZEL / ".github" / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_notes)


def versionen(datei: str) -> list[str]:
    text = (WURZEL / datei).read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)


class TestReleaseText:
    def test_beide_changelogs_fuehren_dieselben_versionen(self):
        assert versionen("CHANGELOG.md") == versionen("CHANGELOG.de.md")

    @pytest.mark.parametrize("version", versionen("CHANGELOG.md"))
    def test_jede_version_ergibt_eine_seite(self, version):
        text = release_notes.notes(f"v{version}", repo="Beispiel/Spectro")
        englisch, deutsch = text.split("<details>")
        assert "###" in englisch and "###" in deutsch
        assert f"ghcr.io/beispiel/spectro:{version}" in englisch
        # nur der eigene Abschnitt, nicht die Versionen darunter
        assert "## [" not in text

    def test_abschnitt_endet_vor_der_naechsten_version(self):
        text = release_notes.notes("v1.0.1")
        assert "Analysis version unchanged (12)." in text
        assert "First release" not in text

    def test_relative_links_zeigen_auf_den_tag(self):
        text = release_notes.notes("v1.0.0", repo="bluhtsturm/spectro")
        assert "](CALIBRATION.md)" not in text
        assert "(https://github.com/bluhtsturm/spectro/blob/v1.0.0/CALIBRATION.md)" in text
        assert "(https://github.com/bluhtsturm/spectro/blob/v1.0.0/CALIBRATION.de.md)" in text
        assert "(https://keepachangelog.com" not in text     # Kopf gehört nicht dazu

    @pytest.mark.parametrize("tag", ["v9.9.9", "1.1.0", "v1.1", "main"])
    def test_unbekannte_oder_falsche_tags_brechen_ab(self, tag):
        with pytest.raises(SystemExit):
            release_notes.notes(tag)
