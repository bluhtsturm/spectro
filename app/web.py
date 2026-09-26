"""
spectro-web - Web-Oberflaeche fuer die Spektralanalyse.

Konfiguration ueber Umgebungsvariablen (siehe .env.example / docker-compose.yml):
    MEDIA_DIRS      Doppelpunkt-getrennte Liste von Medienordnern, optional mit
                    Label:  "Musik=/media/musik:Rips=/media/rips"
    UPLOAD_DIR      Ablage fuer Uploads (beschreibbar)
    CACHE_DIR       PNG-Cache
    MAX_UPLOAD_MB   Groessenlimit je Upload
    CACHE_MAX_MB    Cache-Obergrenze, danach wird LRU-artig aufgeraeumt
    MAX_RENDERS     gleichzeitige Renderjobs
    SCAN_JOBS       gleichzeitige Dateien aller laufenden Scans zusammen
    MAX_STREAMS     gleichzeitige Wiedergaben (MP3-Ausschnitte)
    AUTH_USER/AUTH_PASS  optionale HTTP-Basic-Absicherung
    SHOW_ALL_FILES  1 = auch Dateien ohne bekannte Audio-Endung anzeigen
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (FileResponse, HTMLResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import core
from .core import AudioError, Params
from .i18n import LANGUAGES, khz as core_khz, normalise, set_current, t
from .sidecar import SidecarStore

try:                                     # python-multipart ab 0.0.13
    from python_multipart.exceptions import FormParserError
    from python_multipart.multipart import MultipartParser, parse_options_header
except ImportError:                      # pragma: no cover - aeltere Fassungen
    from multipart.exceptions import FormParserError
    from multipart.multipart import MultipartParser, parse_options_header

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("spectro")

BASE = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/data/uploads"))
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/cache"))
MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "1024"))
CACHE_MAX_MB = float(os.environ.get("CACHE_MAX_MB", "2048"))
MAX_RENDERS = int(os.environ.get("MAX_RENDERS", str(max(1, (os.cpu_count() or 2) // 2))))
SHOW_ALL_FILES = os.environ.get("SHOW_ALL_FILES", "0") not in ("0", "", "false")
SIDECAR_DIR = os.environ.get("SIDECAR_DIR", "/data/index")
SIDECAR_ENABLED = os.environ.get("SIDECAR", "1") not in ("0", "", "false")
DEFAULT_LANG = normalise(os.environ.get("LANG_DEFAULT", "de"))
AUTH_USER = os.environ.get("AUTH_USER", "")
AUTH_PASS = os.environ.get("AUTH_PASS", "")
SCAN_JOBS = max(1, int(os.environ.get("SCAN_JOBS", str(MAX_RENDERS))))
MAX_STREAMS = max(1, int(os.environ.get("MAX_STREAMS", str(max(4, 2 * MAX_RENDERS)))))
MAX_UPLOAD_FILES = 50

# Die Anmeldung gilt, sobald einer der beiden Werte gesetzt ist. Vorher
# schaltete ein vergessener AUTH_USER den Schutz still ab, obwohl ein
# Passwort gesetzt war.
AUTH_ENABLED = bool(AUTH_USER or AUTH_PASS)
if AUTH_PASS and not AUTH_USER:
    log.warning("AUTH_PASS ist gesetzt, AUTH_USER nicht - die Anmeldung erwartet "
                "einen leeren Benutzernamen. AUTH_USER setzen.")
elif AUTH_USER and not AUTH_PASS:
    log.warning("AUTH_USER ist gesetzt, AUTH_PASS nicht - die Anmeldung erwartet "
                "ein leeres Passwort. AUTH_PASS setzen.")

# Interaktive Analysen, Scans und Wiedergaben haben je eine eigene Grenze.
# Die Scan-Grenze gilt fuer alle Scans zusammen: vorher brachte jeder
# weitere Scan (zweiter Tab, zweiter Nutzer) seine eigene mit und
# vervielfachte die Zahl gleichzeitiger ffmpeg-Laeufe.
class Grenze:
    """Parallelitaetsgrenze, die zur laufenden Ereignisschleife gehoert.

    Eine asyncio.Semaphore bindet sich an die erste Schleife, in der jemand
    auf sie warten muss. Im Betrieb gibt es nur eine; Testclients starten
    dagegen je Anfrage eine neue, und die gebundene Semaphore wuerfe dann.
    Aufruf liefert die Semaphore selbst: ``async with _sem():``.
    """

    def __init__(self, n: int):
        self.n = n
        self._loop = None
        self._sem: asyncio.Semaphore | None = None

    def __call__(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._loop is not loop or self._sem is None:
            self._loop, self._sem = loop, asyncio.Semaphore(self.n)
        return self._sem


_sem = Grenze(MAX_RENDERS)
_scan_sem = Grenze(SCAN_JOBS)
_audio_sem = Grenze(MAX_STREAMS)


# --------------------------------------------------------------------------
# Wurzelverzeichnisse
# --------------------------------------------------------------------------

def _load_roots() -> dict:
    """Liest MEDIA_DIRS und meldet beim Start, was tatsaechlich eingebunden ist.

    Ein Tippfehler im Pfad oder ein vergessener volume-Eintrag faellt sonst
    erst auf, wenn der Ordner in der Oberflaeche fehlt.
    """
    roots: dict = {}
    labels: dict = {}
    raw = os.environ.get("MEDIA_DIRS") or os.environ.get("MEDIA_DIR") or ""
    for i, entry in enumerate([e for e in raw.split(":") if e.strip()]):
        if "=" in entry and not entry.startswith("/"):
            label, _, path = entry.partition("=")
        else:
            label, path = os.path.basename(entry.rstrip("/")) or "Medien", entry
        label = label.strip()
        p = Path(path.strip()).expanduser().resolve()
        if not p.is_dir():
            log.warning("Medienordner uebersprungen (nicht vorhanden oder kein "
                        "Verzeichnis): %s -> %s", label, path)
            continue
        if not os.access(p, os.R_OK | os.X_OK):
            log.warning("Medienordner nicht lesbar (Rechte pruefen): %s", p)
            continue
        labels[label] = labels.get(label, 0) + 1
        if labels[label] > 1:                 # gleiche Beschriftung unterscheidbar machen
            label = f"{label} ({labels[label]})"
        key = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"root{i}"
        while key in roots:
            key += "x"
        roots[key] = {"key": key, "label": label, "path": p, "writable": False}
        log.info("Medienordner: %s -> %s", label, p)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    roots["uploads"] = {"key": "uploads", "label": "Uploads",
                        "path": UPLOAD_DIR.resolve(), "writable": True}
    if len(roots) == 1:
        log.warning("Kein Medienordner eingebunden - es steht nur 'Uploads' zur "
                    "Verfuegung. MEDIA_DIRS und die volume-Eintraege pruefen.")
    return roots


ROOTS = _load_roots()
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _ergebnisablage() -> SidecarStore:
    """Waehlt den Ort der Ergebnisablage.

    Die Vorgabe /data/index passt im Container. Laeuft der Dienst ohne Docker,
    gehoert dieser Pfad meist root und ist nicht anlegbar; dann weicht die
    Ablage auf das Benutzerverzeichnis aus, statt sich stillschweigend
    abzuschalten - sonst rechnet jeder Scan alles neu, ohne dass jemand merkt
    warum.
    """
    if not SIDECAR_ENABLED:
        return SidecarStore(None)
    kandidaten = [Path(SIDECAR_DIR)]
    heim = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    ausweich = Path(heim) / "spectro" / "index"
    if ausweich != kandidaten[0]:
        kandidaten.append(ausweich)
    for ort in kandidaten:
        try:
            ablage = SidecarStore(ort)
        except OSError as exc:
            log.warning("Ergebnisablage %s nicht nutzbar (%s)", ort, exc)
            continue
        if ort != kandidaten[0]:
            log.warning("Ergebnisablage weicht auf %s aus", ort)
        return ablage
    log.warning("Keine Ergebnisablage nutzbar - der Scan rechnet jedes Mal neu")
    return SidecarStore(None)


SIDECARS = _ergebnisablage()


def resolve(root: str, rel: str, must_be_file: bool = True) -> Path:
    """Sandbox: loest root+relativen Pfad auf und verhindert Ausbrueche."""
    r = ROOTS.get(root)
    if not r:
        raise HTTPException(404, t("http.unknown_root", root=root))
    rel = (rel or "").lstrip("/")
    target = (r["path"] / rel).resolve()
    try:
        target.relative_to(r["path"])
    except ValueError:
        raise HTTPException(403, t("http.outside")) from None
    if not target.exists():
        raise HTTPException(404, t("http.not_found"))
    if must_be_file and not target.is_file():
        raise HTTPException(400, t("http.not_a_file"))
    return target


def is_audio(p: Path) -> bool:
    return SHOW_ALL_FILES or p.suffix.lower().lstrip(".") in core.AUDIO_EXT


def inside(root_path: Path, p: Path) -> bool:
    """Liegt ein Eintrag - auch ueber einen Symlink - im freigegebenen Ordner?

    Dieselbe Regel wie in resolve(): Browser und Scan zeigen nur, was sich
    danach auch oeffnen laesst. Vorher listete der Browser Symlinks nach
    draussen, die dann mit 403 scheiterten, und der Scan analysierte sie.
    Geprueft wird nur die letzte Pfadkomponente; der Ordner darueber ist
    bereits aufgeloest.
    """
    if not p.is_symlink():
        return True
    try:
        p.resolve().relative_to(root_path)
    except (ValueError, OSError, RuntimeError):
        return False
    return True


def finite(name: str, value: float | None) -> float | None:
    """Weist NaN und Unendlich ab - FastAPI nimmt beides als Zahl an."""
    if value is not None and not math.isfinite(value):
        raise HTTPException(400, t("http.bad_value", name=name))
    return value


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def cache_key(kind: str, files: list, params: dict) -> str:
    ident = []
    for f in files:
        st = f.stat()
        ident.append([str(f), int(st.st_mtime), st.st_size])
    blob = json.dumps([core.ANALYSIS_VERSION, core.RENDER_VERSION, kind, ident, params],
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


# Nur fuer die Darstellung - an den Messwerten aendern sie nichts. Stuenden
# sie im Schluessel der Kennzahlen, rechnete jede Aenderung an Farbskala,
# Bildgroesse oder Differenzbereich den ganzen Vergleich ein zweites Mal.
DISPLAY_ONLY = frozenset({"cmap", "width", "height", "dpi", "theme", "raw",
                          "diff_range", "fmin", "fmax"})


# Fuer Messungen an einer einzelnen Datei zaehlt auch der Dynamikbereich
# nicht - er bestimmt nur die Farbskala des Bildes.
MESS_IGNORIERT = ("db_range", "db_top", "normalize")


def analysis_params(p: Params, *ignoriert: str) -> dict:
    return {k: v for k, v in p.as_dict().items()
            if k not in DISPLAY_ONLY and k not in ignoriert}


def write_atomic(path: Path, data: bytes) -> None:
    """Schreibt ueber eine eigene Zwischendatei und benennt dann um.

    Jeder Schreiber bekommt einen eigenen Namen: teilten sich zwei
    gleichzeitige Anfragen mit demselben Schluessel eine Zwischendatei,
    landete ein Gemisch aus beiden im Cache.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                               suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cache_get(key: str):
    p = CACHE_DIR / f"{key}.png"
    if not p.exists():
        return None, "[]"
    os.utime(p, None)
    meta = CACHE_DIR / f"{key}.json"
    return p, (meta.read_text() if meta.exists() else "[]")


def stats_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.stats.json"


def compare_stats_path(fa: Path, fb: Path, p: Params, align: bool) -> Path:
    """Ablage der Vergleichskennzahlen - unabhaengig von der Darstellung."""
    return stats_path(cache_key("cmpstats", [fa, fb],
                                {**analysis_params(p), "align": align}))


def cache_put(key: str, data: bytes, boxes: list | None = None) -> Path:
    p = CACHE_DIR / f"{key}.png"
    # Geometrie zuerst: wer das Bild schon sieht, soll auch die Plotflaechen
    # finden, sonst funktioniert der Zoom auf diesem Treffer nicht
    if boxes is not None:
        write_atomic(CACHE_DIR / f"{key}.json", json.dumps(boxes).encode())
    write_atomic(p, data)
    maybe_prune()
    return p


_letztes_aufraeumen = 0.0


def maybe_prune(force: bool = False) -> None:
    """Raeumt hoechstens alle 30 s auf - jeder Durchlauf liest den ganzen
    Cache-Ordner. Die Grenze ist damit weich: sie kann fuer einige Sekunden
    um die zuletzt gerechneten Bilder ueberschritten sein."""
    global _letztes_aufraeumen
    jetzt = time.monotonic()
    if force or jetzt - _letztes_aufraeumen >= 30:
        _letztes_aufraeumen = jetzt
        prune_cache()


def _cache_entry(f: Path) -> bool:
    """Eintraege, die nach Groesse und Alter aufgeraeumt werden."""
    return (f.suffix in (".png", ".flac")
            or f.name.endswith((".stats.json", ".result.json")))


# private: hinter der Anmeldung darf kein geteilter Proxy mitspeichern.
# no-cache: der Browser fragt jedes Mal nach, ob sich etwas geaendert hat -
# die Antwort 304 kostet nur ein stat(). Vorher hielt er ein Bild einen Tag
# lang, auch wenn sich die Datei inzwischen geaendert hatte.
BILD_CACHE = "private, no-cache"


def png_headers(key: str, state: str, boxes_json: str) -> dict:
    return {"X-Cache": state, "ETag": f'"{key}"', "Cache-Control": BILD_CACHE,
            "X-Plot-Box": boxes_json}


def not_modified(request: Request, key: str) -> Response | None:
    """304, wenn der Browser genau dieses Bild schon hat.

    Der Schluessel enthaelt Aenderungszeit und Groesse der Dateien, alle
    Parameter und die Analyseversion - gleicher Schluessel heisst gleiches Bild.
    """
    angefragt = [e.strip() for e in request.headers.get("if-none-match", "").split(",")]
    if f'"{key}"' not in angefragt:
        return None
    headers = {"ETag": f'"{key}"', "Cache-Control": BILD_CACHE}
    meta = CACHE_DIR / f"{key}.json"
    try:
        headers["X-Plot-Box"] = meta.read_text()
    except OSError:
        pass                        # der Browser behaelt die gespeicherte Geometrie
    return Response(status_code=304, headers=headers)


def prune_cache() -> None:
    """Raeumt den Cache nach Gesamtgroesse auf - inklusive der Residual-Dateien.

    Zaehlte man nur die PNGs, wuechse der Ordner durch die deutlich groesseren
    FLAC-Residuen unbegrenzt weiter. Zwischendateien, die ein Abbruch liegen
    gelassen hat, verschwinden nach einer Stunde.
    """
    limit = CACHE_MAX_MB * 1024 * 1024
    stale = time.time() - 3600
    entries = []
    total = 0
    for f in CACHE_DIR.iterdir():
        try:
            if not f.is_file():
                continue
            st = f.stat()
        except OSError:
            continue
        if f.suffix == ".part":
            if st.st_mtime < stale:
                f.unlink(missing_ok=True)
            continue
        if not _cache_entry(f):
            continue
        entries.append((st.st_atime, f, st.st_size))
        total += st.st_size
    entries.sort()
    for _, f, size in entries:
        if total <= limit:
            break
        total -= size
        f.unlink(missing_ok=True)
        key = f.name.split(".", 1)[0]
        for extra in (".json", ".stats.json", ".res.json"):
            (CACHE_DIR / f"{key}{extra}").unlink(missing_ok=True)


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="spectro-web", docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.middleware("http")
async def sprache_setzen(request: Request, call_next):
    """Sprache je Anfrage festlegen - auch fuer Meldungen tief im Kern."""
    set_current(lang_from(request))
    return await call_next(request)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if AUTH_ENABLED and request.url.path != "/healthz":
        hdr = request.headers.get("authorization", "")
        ok = False
        if hdr.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(hdr[6:]).decode().partition(":")
                ok = (secrets.compare_digest(user, AUTH_USER)
                      and secrets.compare_digest(pw, AUTH_PASS))
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={
                "WWW-Authenticate": 'Basic realm="spectro"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True, "roots": list(ROOTS), "ffmpeg": shutil.which("ffmpeg") or ""}


INDEX_HTML = (BASE / "templates" / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Die Seite kommt mit der Sprache, die der Server gewaehlt hat - sonst
    entschied das Frontend allein nach navigator.language und ignorierte
    LANG_DEFAULT."""
    return INDEX_HTML.replace("__LANG__", lang_from(request))


@app.get("/api/config")
def api_config():
    return {
        "roots": [{"key": r["key"], "label": r["label"], "writable": r["writable"]}
                  for r in ROOTS.values()],
        "cmaps": core.CMAPS,
        "windows": sorted(core.WINDOWS),
        "max_upload_mb": MAX_UPLOAD_MB,
        "languages": list(LANGUAGES),
        "lang": DEFAULT_LANG,
        "defaults": Params().as_dict(),
    }


@app.get("/api/browse")
def api_browse(root: str = "uploads", path: str = "", q: str = ""):
    r = ROOTS.get(root)
    if not r:
        raise HTTPException(404, t("http.unknown_root", root=root))
    base = resolve(root, path, must_be_file=False)
    if not base.is_dir():
        raise HTTPException(400, t("http.not_a_dir"))

    dirs, files = [], []
    try:
        entries = sorted(base.iterdir(), key=lambda e: e.name.lower())
    except PermissionError as e:
        raise HTTPException(403, t("http.no_permission")) from e

    needle = q.lower().strip()
    for e in entries:
        if e.name.startswith(".") or not inside(r["path"], e):
            continue
        rel = str(e.relative_to(r["path"]))
        if e.is_dir():
            dirs.append({"name": e.name, "path": rel})
        elif is_audio(e):
            if needle and needle not in e.name.lower():
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            files.append({"name": e.name, "path": rel, "size": st.st_size,
                          "mtime": int(st.st_mtime),
                          "ext": e.suffix.lower().lstrip(".")})
    parent = str(Path(path).parent) if path not in ("", ".") else None
    return {"root": root, "path": path, "parent": None if parent == "." else parent,
            "dirs": dirs, "files": files, "writable": r["writable"]}


def clean_msg(msg: str) -> str:
    """Nimmt absolute Serverpfade aus Fehlermeldungen, die zum Client gehen."""
    out = str(msg)
    for r in ROOTS.values():
        out = out.replace(str(r["path"]) + "/", "").replace(str(r["path"]), r["label"])
    return out.strip()[:400]


def strip_paths(obj, mapping: dict):
    """Ersetzt absolute Serverpfade in Antworten durch die relativen Pfade.

    Die Analyse arbeitet intern mit vollen Pfaden; nach aussen gehoert der
    Ablageort des Servers nicht in die JSON-Antwort.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "path" and isinstance(v, str) and v in mapping:
                out[k] = mapping[v]
            else:
                out[k] = strip_paths(v, mapping)
        return out
    if isinstance(obj, list):
        return [strip_paths(v, mapping) for v in obj]
    return obj


def lang_from(request: Request) -> str:
    """Sprache aus ?lang=, sonst Accept-Language, sonst Voreinstellung."""
    q = request.query_params.get("lang")
    if q:
        return normalise(q)
    header = request.headers.get("accept-language", "")
    for teil in header.split(","):
        code = normalise(teil.split(";")[0].strip())
        if code in LANGUAGES and teil.strip():
            roh = teil.split(";")[0].strip().replace("_", "-").split("-")[0].lower()
            if roh in LANGUAGES:
                return code
    return DEFAULT_LANG


def params_from_query(qp, lang: str = DEFAULT_LANG) -> Params:
    def num(name, cast, default=None):
        v = qp.get(name)
        if v in (None, ""):
            return default
        try:
            wert = cast(v)
        except ValueError:
            raise HTTPException(400, t("http.bad_value", name=name)) from None
        return finite(name, wert)

    try:
        return Params(
            nfft=num("nfft", int, 2048),
            overlap=num("overlap", float, 0.75),
            window=qp.get("window") or "hann",
            channels=qp.get("channels") or "mix",
            scale=qp.get("scale") or "linear",
            fmin=num("fmin", float, 0.0),
            fmax=num("fmax", float, None),
            db_range=num("db_range", float, 100.0),
            db_top=num("db_top", float, 0.0),
            cmap=qp.get("cmap") or "magma",
            width=num("width", float, 14.0),
            height=num("height", float, 5.0),
            dpi=num("dpi", int, 110),
            max_cols=num("max_cols", int, 4000),
            start=num("start", float, None),
            duration=num("duration", float, None),
            sr=num("sr", int, None),
            raw=qp.get("raw") in ("1", "true"),
            theme=qp.get("theme") or "dark",
            lang=normalise(qp.get("lang") or lang),
            diff_range=num("diff_range", float, 24.0),
        ).validate()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/spectrogram.png")
async def api_spectrogram(request: Request, root: str, path: str):
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    key = cache_key("spec", [f], p.as_dict())
    if (antwort := not_modified(request, key)) is not None:
        return antwort
    hit, boxes_json = cache_get(key)
    if hit:
        return FileResponse(hit, media_type="image/png",
                            headers=png_headers(key, "hit", boxes_json))

    def work():
        a = core.analyse(str(f), p)
        panels = core.build_panels(a, p)
        cut = core.estimate_cutoff(a.mags[0], a.sr, p.nfft)
        sub = (f"{a.info['codec']} · {a.info['sample_rate']/1000:g} kHz · "
               + t("plot.channels", p.lang, n=a.info["channels"])
               + f" · FFT {p.nfft} · {p.window} · {p.scale}")
        if cut:
            sub += " · " + t("plot.cutoff", p.lang, edge=core_khz(cut, p.lang))
        buf = io.BytesIO()
        boxes = core.render(panels, p, buf, title=f.name, subtitle=sub)
        return buf.getvalue(), boxes

    async with _sem():
        try:
            data, boxes = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    await asyncio.to_thread(cache_put, key, data, boxes)
    return Response(data, media_type="image/png",
                    headers=png_headers(key, "miss", json.dumps(boxes)))


@app.get("/api/compare.png")
async def api_compare_png(request: Request, a_root: str, a: str, b_root: str, b: str):
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    align = request.query_params.get("align", "1") in ("1", "true")
    diff = request.query_params.get("diff", "1") in ("1", "true")
    key = cache_key("cmp", [fa, fb], {**p.as_dict(), "align": align, "diff": diff})
    if (antwort := not_modified(request, key)) is not None:
        return antwort
    hit, boxes_json = cache_get(key)
    if hit:
        return FileResponse(hit, media_type="image/png",
                            headers=png_headers(key, "hit", boxes_json))

    def work():
        panels, stats = core.compare(str(fa), str(fb), p, align=align, show_diff=diff)
        buf = io.BytesIO()
        boxes = core.render(panels, p, buf, title=f"{fa.name}   ↔   {fb.name}",
                            subtitle=f"FFT {p.nfft} · {p.window} · {p.scale} · "
                                     + t("plot.offset", p.lang,
                                         offset=stats["offset_s"]))
        return buf.getvalue(), boxes, stats

    async with _sem():
        try:
            data, boxes, stats = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    await asyncio.to_thread(cache_put, key, data, boxes)
    try:
        await asyncio.to_thread(write_atomic, compare_stats_path(fa, fb, p, align),
                                json.dumps(stats, default=str).encode())
    except OSError:
        pass
    return Response(data, media_type="image/png",
                    headers=png_headers(key, "miss", json.dumps(boxes)))


@app.get("/api/compare.json")
async def api_compare_json(request: Request, a_root: str, a: str, b_root: str, b: str):
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    align = request.query_params.get("align", "1") in ("1", "true")

    # Das Bild hat die Kennzahlen in aller Regel schon berechnet - erneutes
    # Rechnen wuerde jede Vergleichsansicht doppelt so teuer machen.
    names = {str(fa): a, str(fb): b}
    cached = compare_stats_path(fa, fb, p, align)
    if cached.exists():
        try:
            stats = json.loads(cached.read_text())
            os.utime(cached, None)
            return strip_paths(stats, names)
        except (OSError, ValueError):
            pass

    def work():
        _, stats = core.compare(str(fa), str(fb), p, align=align, show_diff=False)
        return stats

    async with _sem():
        try:
            stats = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    try:
        await asyncio.to_thread(write_atomic, cached,
                                json.dumps(stats, default=str).encode())
    except OSError:
        pass
    return strip_paths(stats, names)


async def measured(kind: str, files: list, p: Params, extra: dict, compute) -> dict:
    """Rechnet eine Messung unter der Parallelitaetsgrenze und legt sie ab.

    Der Schluessel enthaelt nur, was das Ergebnis beeinflusst: Dateien samt
    Aenderungszeit, Analyseparameter, Sprache - keine Farbskala, keine
    Bildgroesse. Die Oberflaeche laedt den Bericht nach jedem neuen Bild; ohne
    Ablage dekodierte jede Aenderung der Darstellung die Datei fuenfmal.
    """
    key = cache_key(kind, files, {**analysis_params(p, *MESS_IGNORIERT), **extra})
    ablage = CACHE_DIR / f"{key}.result.json"

    def laden():
        daten = json.loads(ablage.read_bytes())
        os.utime(ablage, None)
        return daten

    try:
        return await asyncio.to_thread(laden)
    except (OSError, ValueError):
        pass
    async with _sem():
        try:
            res = await asyncio.to_thread(compute)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    try:
        await asyncio.to_thread(write_atomic, ablage,
                                json.dumps(res, default=str).encode())
    except OSError:
        pass
    return res


@app.get("/api/report")
async def api_report(request: Request, root: str, path: str, loudness: int = 1):
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    rep = await measured("report", [f], p, {"loudness": bool(loudness)},
                         lambda: core.summary(str(f), p, bool(loudness)))
    return strip_paths(rep, {str(f): path})


@app.get("/api/probe")
async def api_probe(request: Request, root: str, path: str):
    f = resolve(root, path)
    try:
        info = await asyncio.to_thread(core.probe, str(f))
    except AudioError as e:
        raise HTTPException(422, clean_msg(e)) from e
    return strip_paths(info, {str(f): path})


@app.get("/api/audio")
async def api_audio(root: str, path: str, start: float = 0.0,
                    duration: float | None = None):
    """Liefert den betrachteten Ausschnitt als MP3 - browserkompatibel fuer alle
    Quellformate (DSD, APE, TrueHD ...) und ermoeglicht Mithoeren beim Zoomen."""
    f = resolve(root, path)
    finite("start", start)
    finite("duration", duration)
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start and start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(f)]
    if duration:
        cmd += ["-t", f"{max(min(duration, 3600), 0.1):.3f}"]
    cmd += ["-map", "a:0", "-vn", "-ac", "2", "-b:a", "160k", "-f", "mp3", "-"]

    async def gen():
        # Platz und Prozess erst hier: beginnt die Antwort nie (Abbruch vor
        # dem ersten Byte), bleibt so nichts belegt und kein ffmpeg zurueck.
        async with _audio_sem():
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                while chunk := await proc.stdout.read(64 * 1024):
                    yield chunk
            finally:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                if proc.returncode not in (0, -9):
                    log.warning("Wiedergabe von %s endete mit ffmpeg-Code %s",
                                f.name, proc.returncode)

    return StreamingResponse(gen(), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store"})


@app.get("/api/nulltest")
async def api_nulltest(request: Request, a_root: str, a: str, b_root: str, b: str):
    """Sample-genaue Nullprobe zweier Dateien."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    return await measured("null", [fa, fb], p, {},
                          lambda: core.null_test(str(fa), str(fb), p))


@app.get("/api/residual")
async def api_residual(request: Request, a_root: str, a: str, b_root: str, b: str,
                       gain_db: float = 0.0):
    """Differenz zweier Fassungen als hoerbare FLAC-Datei."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    gain_db = max(-20.0, min(finite("gain_db", gain_db), 40.0))
    key = residual_key(fa, fb, p, gain_db)
    out = CACHE_DIR / f"{key}.flac"
    name = f"residual_{Path(a).stem}_minus_{Path(b).stem}.flac"

    if not out.exists():
        async with _sem():
            try:
                await asyncio.to_thread(core.null_residual, str(fa), str(fb),
                                        str(out), p, 900.0, gain_db)
            except AudioError as e:
                raise HTTPException(422, clean_msg(e)) from e
        await asyncio.to_thread(maybe_prune, True)
    else:
        os.utime(out, None)
    return FileResponse(out, media_type="audio/flac", filename=name)


@app.get("/api/residual.json")
async def api_residual_json(request: Request, a_root: str, a: str,
                            b_root: str, b: str, gain_db: float = 0.0):
    """Kennzahlen des Residuals, ohne die Datei zu uebertragen."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    gain_db = max(-20.0, min(finite("gain_db", gain_db), 40.0))
    key = residual_key(fa, fb, p, gain_db)
    out = CACHE_DIR / f"{key}.flac"
    meta = CACHE_DIR / f"{key}.res.json"
    if meta.exists() and out.exists():
        try:
            return json.loads(meta.read_text())
        except (OSError, ValueError):
            pass
    async with _sem():
        try:
            info = await asyncio.to_thread(core.null_residual, str(fa), str(fb),
                                           str(out), p, 900.0, gain_db)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    info["path"] = out.name
    try:
        await asyncio.to_thread(write_atomic, meta, json.dumps(info).encode())
    except OSError:
        pass
    await asyncio.to_thread(maybe_prune, True)
    return info


def residual_key(fa: Path, fb: Path, p: Params, gain_db: float) -> str:
    """Wie bei den Messungen: nur, was das Residual veraendert."""
    return cache_key("res", [fa, fb],
                     {**analysis_params(p, *MESS_IGNORIERT), "gain": gain_db})


@app.get("/api/lowfreq")
async def api_lowfreq(request: Request, root: str, path: str):
    """Rumpeln, Plattenwelligkeit und Netzbrumm."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    return await measured("low", [f], p, {}, lambda: core.lowfreq_scan(str(f), p))


@app.get("/api/wowflutter")
async def api_wowflutter(request: Request, root: str, path: str,
                         nominal_hz: float | None = None):
    """Drehzahlabweichung, Wow und Flutter an einem Messton."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    if nominal_hz is not None and not (finite("nominal_hz", nominal_hz) > 0):
        raise HTTPException(400, t("http.bad_value", name="nominal_hz"))
    return await measured("wow", [f], p, {"nominal": nominal_hz},
                          lambda: core.wow_flutter(str(f), p, nominal_hz))


@app.get("/api/sweep")
async def api_sweep(request: Request, root: str, path: str,
                    reference_hz: float = 1000.0):
    """Frequenzgang und Kanaltrennung aus einer Tonfolge."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    if not finite("reference_hz", reference_hz) > 0:
        raise HTTPException(400, t("http.bad_value", name="reference_hz"))
    return await measured("sweep", [f], p, {"reference": reference_hz},
                          lambda: core.tone_sweep(str(f), p, reference_hz))


@app.get("/api/clicks")
async def api_clicks(request: Request, root: str, path: str,
                     threshold_db: float = 14.0):
    """Sucht Knackser und andere Impulsstoerungen."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    threshold_db = max(6.0, min(finite("threshold_db", threshold_db), 40.0))
    return await measured("clicks", [f], p, {"threshold": threshold_db},
                          lambda: core.impulse_scan(str(f), p, threshold_db))


def _scan_setup(root: str, path: str, recursive: int, limit: int,
                seconds: float, lang: str):
    """Gemeinsame Vorbereitung fuer beide Scan-Varianten."""
    r = ROOTS.get(root)
    if not r:
        raise HTTPException(404, t("http.unknown_root", root=root))
    base = resolve(root, path, must_be_file=False)
    if not base.is_dir():
        raise HTTPException(400, t("http.not_a_dir"))

    limit = max(1, min(limit, 2000))
    seconds = max(5.0, min(finite("seconds", seconds), 600.0))
    files, truncated = audio_files(r["path"], base, bool(recursive), limit)
    sprache = normalise(lang or DEFAULT_LANG)
    return (r, files, seconds, truncated, sprache,
            f"quickcheck:{int(seconds)}:{sprache}")


def audio_files(root_path: Path, base: Path, recursive: bool, limit: int):
    """Audiodateien in fester Reihenfolge, hoechstens limit Stueck.

    Liest nur so weit, wie es die Grenze verlangt - vorher wurde erst der
    ganze Baum gelesen und sortiert, bevor das Limit griff. Versteckte
    Ordner und Symlinks nach draussen bleiben aussen vor, wie im Browser.
    """
    out = []
    for ordner, unter, namen in os.walk(base):
        unter[:] = sorted(d for d in unter if not d.startswith(".")) if recursive else []
        for name in sorted(namen):
            if name.startswith("."):
                continue
            f = Path(ordner) / name
            if not is_audio(f) or not inside(root_path, f) or not f.is_file():
                continue
            out.append(f)
            if len(out) > limit:
                return out[:limit], True
    return out, False


async def _scan_one(f: Path, r: dict, root: str, kind: str, seconds: float,
                    sprache: str, refresh: int) -> dict:
    rel = str(f.relative_to(r["path"]))
    if not refresh:
        cached = await asyncio.to_thread(SIDECARS.load, root, rel, f, kind)
        if cached is not None:
            return {**cached, "path": rel, "cached": True}
    async with _scan_sem():
        try:
            res = await asyncio.to_thread(core.quickcheck, str(f),
                                          seconds, 4096, sprache)
        except Exception as e:
            return {"name": f.name, "path": rel, "error": clean_msg(e)[:200],
                    "cached": False}
    await asyncio.to_thread(SIDECARS.save, root, rel, f, kind, res)
    return {**res, "path": rel, "cached": False}


@app.get("/api/scan")
async def api_scan(root: str, path: str = "", recursive: int = 1,
                   limit: int = 300, seconds: float = 60.0, refresh: int = 0,
                   lang: str = DEFAULT_LANG):
    """Prueft einen ganzen Ordner auf Bandbreite und Auffaelligkeiten.

    Ergebnisse landen in der Sidecar-Ablage; beim naechsten Aufruf werden nur
    geaenderte Dateien neu gerechnet. Mit refresh=1 wird alles neu gemessen.
    """
    r, files, seconds, truncated, sprache, kind = await asyncio.to_thread(
        _scan_setup, root, path, recursive, limit, seconds, lang)
    results = await asyncio.gather(*[
        _scan_one(f, r, root, kind, seconds, sprache, refresh) for f in files])
    gerechnet = sum(1 for x in results if not x.get("cached"))
    warn = sum(1 for x in results if (x.get("verdict") or {}).get("level") == "warn")
    return {"root": root, "path": path, "count": len(results),
            "warnings": warn, "computed": gerechnet,
            "from_index": len(results) - gerechnet,
            "index": SIDECARS.enabled,
            "truncated": truncated, "files": results}


@app.get("/api/scan/stream")
async def api_scan_stream(request: Request, root: str, path: str = "",
                          recursive: int = 1, limit: int = 2000,
                          seconds: float = 60.0, refresh: int = 0,
                          lang: str = DEFAULT_LANG):
    """Derselbe Scan, aber als Ereignisstrom.

    Ein Durchlauf ueber tausende Dateien dauert laenger als jeder Reverse Proxy
    auf eine Antwort wartet. Hier kommt jedes Ergebnis einzeln, sobald es
    vorliegt - der Fortschritt ist sichtbar und nichts laeuft in einen Timeout.
    Bricht der Browser ab, endet auch die Verarbeitung.
    """
    r, files, seconds, truncated, sprache, kind = await asyncio.to_thread(
        _scan_setup, root, path, recursive, limit, seconds, lang)

    async def ereignisse():
        def paket(art: str, daten: dict) -> bytes:
            return f"event: {art}\ndata: {json.dumps(daten, default=str)}\n\n".encode()

        yield paket("start", {"total": len(files), "root": root, "path": path,
                              "index": SIDECARS.enabled,
                              "truncated": truncated})
        aufgaben = [asyncio.create_task(
            _scan_one(f, r, root, kind, seconds, sprache, refresh))
            for f in files]
        fertig = warn = gerechnet = 0
        try:
            for task in asyncio.as_completed(aufgaben):
                if await request.is_disconnected():
                    break
                res = await task
                fertig += 1
                if not res.get("cached"):
                    gerechnet += 1
                if (res.get("verdict") or {}).get("level") == "warn":
                    warn += 1
                yield paket("file", {"done": fertig, "total": len(files),
                                     "file": res})
            else:
                yield paket("done", {"count": fertig, "warnings": warn,
                                     "computed": gerechnet,
                                     "from_index": fertig - gerechnet})
        finally:
            for task in aufgaben:
                if not task.done():
                    task.cancel()

    return StreamingResponse(ereignisse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/index")
def api_index_stats():
    """Zustand der Ergebnisablage."""
    return SIDECARS.stats()


@app.delete("/api/index")
def api_index_clear():
    """Verwirft alle gespeicherten Ergebnisse."""
    return {"deleted": SIDECARS.clear()}


def index_quelle(root: str | None, rel: str):
    """Datei zu einem Eintrag der Ergebnisablage - fuer das Aufraeumen."""
    if root in ROOTS:
        return ROOTS[root]["path"] / rel
    if root and os.path.isabs(root):         # Scan der Kommandozeile
        return Path(root) / rel
    return None                              # umbenannte oder entfernte Wurzel


@app.post("/api/index/prune")
def api_index_prune():
    """Entfernt Eintraege zu geloeschten, geaenderten oder nicht mehr
    eingebundenen Dateien und aus frueheren Analyseversionen."""
    return SIDECARS.prune(index_quelle)


def upload_name(roh: str | None) -> str:
    """Dateiname aus dem Upload, ohne Pfadanteile und ohne fuehrende Punkte.

    Ein fuehrender Punkt machte die Datei unsichtbar: der Browser blendet
    solche Namen aus, und "Uploads leeren" uebersprang sie.
    """
    name = os.path.basename((roh or "datei").replace("\\", "/"))
    name = re.sub(r"[^\w.\- ()\[\]#&+,']", "_", name).strip().lstrip(".").strip()
    return name or "upload"


def reserve_upload(name: str) -> Path:
    """Legt den Zielnamen exklusiv an - zwei gleichnamige Uploads zur selben
    Zeit bekommen so sicher verschiedene Namen."""
    stamm, endung = Path(name).stem, Path(name).suffix
    i = 0
    while True:
        ziel = UPLOAD_DIR / (name if i == 0 else f"{stamm}_{i}{endung}")
        try:
            os.close(os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
            return ziel
        except FileExistsError:
            i += 1


class _UploadTeil:
    """Eine Datei im Upload-Strom: geschrieben wird in eine versteckte
    Zwischendatei, erst nach bestandener Pruefung bekommt sie ihren Namen."""

    PUFFER = 1 << 20

    def __init__(self, name: str):
        self.name = name
        fd, tmp = tempfile.mkstemp(dir=UPLOAD_DIR, prefix=".upload-", suffix=".part")
        self.tmp = Path(tmp)
        self.fh = os.fdopen(fd, "wb")
        self.puffer = bytearray()
        self.size = 0
        self.fehler: str | None = None

    async def schreiben(self, daten: bytes, limit: float) -> None:
        if self.fehler:
            return
        self.size += len(daten)
        if self.size > limit:
            self.fehler = t("http.too_large", mb=MAX_UPLOAD_MB)
            await asyncio.to_thread(self.verwerfen)
            return
        self.puffer += daten
        if len(self.puffer) >= self.PUFFER:
            block, self.puffer = bytes(self.puffer), bytearray()
            await asyncio.to_thread(self.fh.write, block)

    def verwerfen(self) -> None:
        try:
            self.fh.close()
        except OSError:
            pass
        self.tmp.unlink(missing_ok=True)

    def abschliessen(self) -> dict:
        """Laeuft im Thread: Rest schreiben, als Audio pruefen, benennen."""
        try:
            self.fh.write(self.puffer)
            self.fh.close()
            core.probe(str(self.tmp))
            ziel = reserve_upload(self.name)
            os.chmod(self.tmp, 0o644)
            os.replace(self.tmp, ziel)
            return {"name": ziel.name, "path": ziel.name, "root": "uploads",
                    "size": self.size}
        except Exception:
            self.verwerfen()
            raise


@app.post("/api/upload", openapi_extra={"requestBody": {"required": True, "content": {
    "multipart/form-data": {"schema": {"type": "object", "required": ["files"],
                                       "properties": {"files": {
                                           "type": "array",
                                           "items": {"type": "string",
                                                     "format": "binary"}}}}}}}})
async def api_upload(request: Request):
    """Nimmt Dateien entgegen und schreibt sie direkt in den Upload-Ordner.

    Der Strom wird selbst zerlegt, statt ihn erst vollstaendig als
    Zwischendatei anzunehmen: dort landete er im Container auf dem tmpfs, also
    im Arbeitsspeicher, und das Groessenlimit griff erst, nachdem alles
    angekommen war. Jetzt endet eine zu grosse Datei beim Ueberschreiten.
    """
    art, optionen = parse_options_header(request.headers.get("content-type", ""))
    if art != b"multipart/form-data" or not optionen.get(b"boundary"):
        raise HTTPException(400, t("http.no_multipart"))
    limit = MAX_UPLOAD_MB * 1024 * 1024
    laenge = request.headers.get("content-length", "")
    if laenge.isdigit() and int(laenge) > limit * MAX_UPLOAD_FILES + (1 << 20):
        raise HTTPException(413, t("http.too_large", mb=MAX_UPLOAD_MB))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Die Zerlegung ruft synchron zurueck; die Ereignisse werden gesammelt und
    # danach asynchron abgearbeitet, damit das Schreiben im Thread laufen kann.
    ereignisse: list = []
    kopf: dict = {"feld": b"", "wert": b"", "alle": {}}

    def header_feld(data, start, end):
        kopf["feld"] += data[start:end]

    def header_wert(data, start, end):
        kopf["wert"] += data[start:end]

    def header_ende():
        kopf["alle"][kopf["feld"].lower()] = kopf["wert"]
        kopf["feld"] = kopf["wert"] = b""

    def header_fertig():
        ereignisse.append(("beginn", kopf["alle"]))
        kopf["alle"] = {}

    parser = MultipartParser(optionen[b"boundary"], {
        "on_header_field": header_feld,
        "on_header_value": header_wert,
        "on_header_end": header_ende,
        "on_headers_finished": header_fertig,
        "on_part_data": lambda data, start, end: ereignisse.append(
            ("daten", bytes(data[start:end]))),
        "on_part_end": lambda: ereignisse.append(("ende", None)),
    })

    saved, errors = [], []
    teil: _UploadTeil | None = None
    anzahl = 0

    async def abarbeiten():
        nonlocal teil, anzahl
        for art_, inhalt in ereignisse:
            if art_ == "beginn":
                _, disp = parse_options_header(inhalt.get(b"content-disposition", b""))
                if b"filename" not in disp:
                    teil = None                      # Formularfeld, keine Datei
                    continue
                anzahl += 1
                name = upload_name(disp[b"filename"].decode("utf-8", "replace"))
                if anzahl > MAX_UPLOAD_FILES:
                    errors.append({"name": name, "error": t(
                        "http.too_many_files", n=MAX_UPLOAD_FILES)})
                    teil = None
                    continue
                teil = await asyncio.to_thread(_UploadTeil, name)
            elif art_ == "daten" and teil is not None:
                await teil.schreiben(inhalt, limit)
            elif art_ == "ende" and teil is not None:
                fertig, teil = teil, None
                if fertig.fehler:
                    errors.append({"name": fertig.name, "error": fertig.fehler})
                    continue
                try:
                    saved.append(await asyncio.to_thread(fertig.abschliessen))
                except Exception as e:
                    errors.append({"name": fertig.name, "error": clean_msg(e)})
        ereignisse.clear()

    try:
        async for chunk in request.stream():
            parser.write(chunk)
            await abarbeiten()
        parser.finalize()
        await abarbeiten()
    except FormParserError as e:
        raise HTTPException(400, t("http.bad_upload")) from e
    finally:
        if teil is not None:                   # Abbruch mitten in einer Datei
            await asyncio.to_thread(teil.verwerfen)
    return {"saved": saved, "errors": errors}


@app.delete("/api/upload")
def api_upload_delete(path: list[str] = Query(...)):
    """Loescht einzelne Uploads. Der Parameter darf mehrfach vorkommen."""
    geloescht, fehler = [], []
    erster_code = None
    for eintrag in path:
        try:
            resolve("uploads", eintrag).unlink()
            geloescht.append(eintrag)
        except HTTPException as e:
            erster_code = erster_code or e.status_code
            fehler.append({"path": eintrag, "error": str(e.detail)})
        except OSError as e:
            erster_code = erster_code or 404
            fehler.append({"path": eintrag, "error": clean_msg(e)})
    # Konnte nichts geloescht werden, ist das ein Fehlschlag und kein Teilerfolg:
    # ein einzelner unzulaessiger Pfad muss weiterhin abgewiesen werden.
    if fehler and not geloescht:
        raise HTTPException(erster_code or 400, fehler[0]["error"])
    return {"deleted": geloescht, "errors": fehler}


@app.delete("/api/uploads")
def api_uploads_clear():
    """Leert den Upload-Ordner vollstaendig."""
    geloescht, bytes_ = [], 0
    for f in sorted(UPLOAD_DIR.iterdir()) if UPLOAD_DIR.exists() else []:
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            bytes_ += f.stat().st_size
            f.unlink()
            geloescht.append(f.name)
        except OSError:
            continue
    return {"deleted": geloescht, "count": len(geloescht), "bytes": bytes_}


@app.get("/api/download")
def api_download(root: str, path: str):
    f = resolve(root, path)
    return FileResponse(f, filename=f.name)
