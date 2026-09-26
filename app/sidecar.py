"""Sidecar-Ablage: Analyseergebnisse überdauern den Neustart.

Ein Scan über eine grosse Sammlung kostet Minuten bis Stunden. Ohne Ablage
faengt jeder Aufruf von vorn an, obwohl sich an den Dateien nichts geaendert
hat. Diese Ablage haelt je Datei ein kleines JSON vor und erklaert es fuer
ungueltig, sobald sich Aenderungszeit, Groesse oder die Analyseversion
unterscheiden.

Die Ergebnisse liegen bewusst **nicht** neben den Audiodateien: Medienordner
sind in aller Regel read-only eingehaengt, und selbst wo nicht, gehoert eine
fremde Datei nicht in die Sammlung. Stattdessen spiegelt die Ablage die
Ordnerstruktur unterhalb eines eigenen Verzeichnisses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from . import core

SAFE = re.compile(r"[^A-Za-z0-9._-]+")

# Rueckgabe von quelle() in prune(): dieser Eintrag gehoert einem anderen
# Werkzeug und bleibt unangetastet.
FREMD = object()


def _slug(text: str) -> str:
    """Dateinamenstauglicher Name, der den Ursprung noch erkennen laesst."""
    clean = SAFE.sub("_", text)[-60:].strip("_") or "datei"
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{clean}.{digest}.json"


class SidecarStore:
    """Ergebnisablage unterhalb eines Verzeichnisses, je Wurzel ein Unterordner."""

    def __init__(self, base: str | os.PathLike | None):
        self.base = Path(base).resolve() if base else None
        self.enabled = self.base is not None
        if self.enabled:
            self.base.mkdir(parents=True, exist_ok=True)
            # Vorhandensein genuegt nicht: ein Ordner kann bestehen und
            # trotzdem nicht beschreibbar sein. Ohne diese Probe meldete sich
            # die Ablage als aktiv, verwarf aber jeden Eintrag - der Scan
            # rechnete jedes Mal neu, ohne dass es irgendwo auffiel.
            probe = self.base / ".schreibprobe"
            try:
                probe.write_text("", encoding="utf-8")
            finally:
                try:
                    probe.unlink()
                except OSError:
                    pass

    @staticmethod
    def _root_dir(root: str) -> str:
        """Ordnername einer Wurzel.

        Die Ordnerschluessel der Weboberflaeche bleiben unveraendert lesbar.
        Absolute Pfade (Scans der Kommandozeile) bekommen eine Pruefsumme:
        verschiedene Pfade koennen nach dem Bereinigen gleich aussehen, und
        ein langer Pfad sprengte sonst die zulaessige Laenge eines Namens.
        """
        clean = SAFE.sub("_", root)
        if "/" in root or os.sep in root or len(clean) > 80:
            digest = hashlib.sha1(root.encode("utf-8")).hexdigest()[:10]
            clean = f"{clean.strip('_')[-60:]}.{digest}"
        return clean

    def path_for(self, root: str, rel: str) -> Path | None:
        if not self.enabled:
            return None
        parent = self.base / self._root_dir(root)
        rel_dir = Path(rel).parent
        if str(rel_dir) not in (".", ""):
            parent = parent / SAFE.sub("_", str(rel_dir))[-120:]
        return parent / _slug(rel)

    def load(self, root: str, rel: str, source: Path, kind: str) -> dict | None:
        """Liefert das gespeicherte Ergebnis, sofern es noch gilt."""
        p = self.path_for(root, rel)
        if p is None or not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            st = source.stat()
        except (OSError, ValueError):
            return None
        if data.get("kind") != kind:
            return None
        if data.get("analysis_version") != core.ANALYSIS_VERSION:
            return None
        # Nanosekunden statt ganzer Sekunden: eine Aenderung innerhalb
        # derselben Sekunde bliebe sonst unbemerkt
        if data.get("mtime_ns") != st.st_mtime_ns or data.get("size") != st.st_size:
            return None
        result = data.get("result")
        return result if isinstance(result, dict) else None

    def save(self, root: str, rel: str, source: Path, kind: str,
             result: dict) -> bool:
        p = self.path_for(root, rel)
        if p is None:
            return False
        try:
            st = source.stat()
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "kind": kind,
                "analysis_version": core.ANALYSIS_VERSION,
                "root": root, "path": rel,
                "mtime_ns": st.st_mtime_ns, "size": st.st_size,
                "result": result,
            }
            # atomar schreiben, damit ein Abbruch keine halbe Datei hinterlaesst
            fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, p)
            return True
        except OSError:
            return False

    def stats(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "entries": 0, "bytes": 0}
        entries = bytes_ = 0
        for f in self.base.rglob("*.json"):
            try:
                bytes_ += f.stat().st_size
            except OSError:
                continue
            entries += 1
        return {"enabled": True, "entries": entries, "bytes": bytes_,
                "path": str(self.base)}

    def clear(self) -> int:
        """Loescht alle Eintraege - fuer den Fall, dass neu gemessen werden soll."""
        if not self.enabled:
            return 0
        n = 0
        for f in self.base.rglob("*.json"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        self._leere_ordner_entfernen()
        return n

    def prune(self, quelle) -> dict:
        """Entfernt Eintraege, die nie wieder gelten koennen.

        Das sind Eintraege zu geloeschten oder inzwischen geaenderten
        Dateien, aus einer frueheren Analyseversion oder zu einer Wurzel, die
        es nicht mehr gibt (umbenannter Medienordner). Ohne Aufraeumen wuchs
        die Ablage mit jeder Umbenennung und jedem Update weiter.

        quelle(root, rel) liefert die Datei zu einem Eintrag, None fuer eine
        unbekannte Wurzel oder FREMD fuer Eintraege, die jemand anderem
        gehoeren.
        """
        stand = {"checked": 0, "removed": 0, "kept": 0}
        if not self.enabled:
            return stand
        for f in self.base.rglob("*.json"):
            stand["checked"] += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                datei = quelle(data.get("root"), data.get("path") or "")
                if datei is FREMD:
                    stand["kept"] += 1
                    continue
                gueltig = (data.get("analysis_version") == core.ANALYSIS_VERSION
                           and datei is not None)
                if gueltig:
                    st = datei.stat()
                    gueltig = (data.get("mtime_ns") == st.st_mtime_ns
                               and data.get("size") == st.st_size)
            except (OSError, ValueError, AttributeError):
                gueltig = False                 # unlesbar oder Quelle fehlt
            if gueltig:
                stand["kept"] += 1
                continue
            try:
                f.unlink()
                stand["removed"] += 1
            except OSError:
                stand["kept"] += 1
        self._leere_ordner_entfernen()
        return stand

    def _leere_ordner_entfernen(self) -> None:
        for ordner in sorted((d for d in self.base.rglob("*") if d.is_dir()),
                             key=lambda d: len(d.parts), reverse=True):
            try:
                ordner.rmdir()
            except OSError:
                pass                            # nicht leer
