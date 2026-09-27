"""Text einer GitHub-Release-Seite aus beiden CHANGELOGs.

    python3 .github/scripts/release_notes.py v1.1.0 > notes.md

Oben der englische Abschnitt der Version und der Befehl fuer das Image,
darunter aufklappbar der deutsche. Fehlt die Version in einem der beiden
CHANGELOGs, bricht das Skript ab - eine Release-Seite ohne Inhalt oder nur in
einer Sprache soll gar nicht erst entstehen.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[2]
TAG = re.compile(r"v(\d+\.\d+\.\d+)")
# Relative Links (etwa auf CALIBRATION.md) zeigten auf der Release-Seite ins
# Leere; sie werden auf die Datei im jeweiligen Tag umgeschrieben.
RELATIV = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def abschnitt(datei: Path, version: str) -> str:
    """Inhalt unter "## [version]" bis zur naechsten Versionsueberschrift."""
    text = datei.read_text(encoding="utf-8")
    treffer = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
                        text, re.M | re.S)
    if not treffer or not treffer.group(1).strip():
        raise SystemExit(f"{datei.name}: kein Abschnitt fuer {version}")
    return treffer.group(1).strip()


def entbrechen(text: str) -> str:
    """Fuegt hart umbrochene Absaetze und Listenpunkte zu je einer Zeile.

    Die CHANGELOGs sind nach etwa 80 Zeichen umbrochen. Auf einer
    Release-Seite zeigt GitHub jeden Zeilenumbruch an, die Saetze brachen
    dort also mitten im Satz um.
    """
    zeilen: list[str] = []
    im_code = False
    for zeile in text.split("\n"):
        roh = zeile.strip()
        if roh.startswith("```"):
            im_code = not im_code
            zeilen.append(zeile)
            continue
        neuer_block = (not roh or im_code
                       or roh.startswith(("#", "- ", "* ", "|", ">", "<"))
                       or re.match(r"\d+\. ", roh))
        vorher = zeilen[-1].strip() if zeilen else ""
        if neuer_block or not vorher or vorher.startswith(("#", "```", "|", "<")):
            zeilen.append(zeile)
        else:
            zeilen[-1] = zeilen[-1].rstrip() + " " + roh
    return "\n".join(zeilen)


def notes(tag: str, wurzel: Path = WURZEL,
          repo: str = os.environ.get("GITHUB_REPOSITORY", "bluhtsturm/spectro")) -> str:
    passt = TAG.fullmatch(tag)
    if not passt:
        raise SystemExit(f"kein Versions-Tag: {tag!r} (erwartet z. B. v1.2.3)")
    version = passt.group(1)
    def fest(text: str) -> str:
        return RELATIV.sub(
            lambda m: f"](https://github.com/{repo}/blob/{tag}/{m.group(1)})", text)

    englisch = fest(entbrechen(abschnitt(wurzel / "CHANGELOG.md", version)))
    deutsch = fest(entbrechen(abschnitt(wurzel / "CHANGELOG.de.md", version)))
    return (f"{englisch}\n\n"
            f"```bash\ndocker pull ghcr.io/{repo.lower()}:{version}\n```\n\n"
            f"<details>\n<summary>Deutsch</summary>\n\n{deutsch}\n\n</details>\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.stdout.write(notes(sys.argv[1]))
