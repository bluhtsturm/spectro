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
    AUTH_USER/AUTH_PASS  optionale HTTP-Basic-Absicherung
    SHOW_ALL_FILES  1 = auch Dateien ohne bekannte Audio-Endung anzeigen
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import core
from .core import AudioError, Params
from .i18n import LANGUAGES, khz as core_khz, normalise, set_current, t
from .sidecar import SidecarStore

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

_sem = asyncio.Semaphore(MAX_RENDERS)


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

try:
    SIDECARS = SidecarStore(SIDECAR_DIR if SIDECAR_ENABLED else None)
except OSError as exc:                       # z. B. nur lesbar eingehaengt
    log.warning("Ergebnisablage nicht nutzbar (%s) - der Scan rechnet jedes "
                "Mal neu", exc)
    SIDECARS = SidecarStore(None)


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


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

def cache_key(kind: str, files: list, params: dict) -> str:
    ident = []
    for f in files:
        st = f.stat()
        ident.append([str(f), int(st.st_mtime), st.st_size])
    blob = json.dumps([core.ANALYSIS_VERSION, kind, ident, params],
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def cache_get(key: str):
    p = CACHE_DIR / f"{key}.png"
    if not p.exists():
        return None, "[]"
    os.utime(p, None)
    meta = CACHE_DIR / f"{key}.json"
    return p, (meta.read_text() if meta.exists() else "[]")


def stats_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.stats.json"


def cache_put(key: str, data: bytes, boxes: list | None = None) -> Path:
    p = CACHE_DIR / f"{key}.png"
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)
    if boxes is not None:
        (CACHE_DIR / f"{key}.json").write_text(json.dumps(boxes))
    prune_cache()
    return p


def prune_cache() -> None:
    """Raeumt den Cache nach Gesamtgroesse auf - inklusive der Residual-Dateien.

    Zaehlte man nur die PNGs, wuechse der Ordner durch die deutlich groesseren
    FLAC-Residuen unbegrenzt weiter.
    """
    limit = CACHE_MAX_MB * 1024 * 1024
    entries = []
    total = 0
    for f in CACHE_DIR.iterdir():
        if not f.is_file() or f.suffix not in (".png", ".flac"):
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        entries.append((st.st_atime, f, st.st_size))
        total += st.st_size
    entries.sort()
    for _, f, size in entries:
        if total <= limit:
            break
        total -= size
        stem = str(f)[:-len(f.suffix)]
        f.unlink(missing_ok=True)
        for extra in (".json", ".stats.json", ".res.json"):
            Path(stem + extra).unlink(missing_ok=True)


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
    if AUTH_USER and request.url.path != "/healthz":
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


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE / "templates" / "index.html").read_text(encoding="utf-8")


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
        if e.name.startswith("."):
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
            return cast(v)
        except ValueError:
            raise HTTPException(400, t("http.bad_value", name=name)) from None

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
    hit, boxes_json = cache_get(key)
    if hit:
        return FileResponse(hit, media_type="image/png", headers={
            "X-Cache": "hit", "Cache-Control": "public, max-age=86400",
            "X-Plot-Box": boxes_json})

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

    async with _sem:
        try:
            data, boxes = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    cache_put(key, data, boxes)
    return Response(data, media_type="image/png", headers={
        "X-Cache": "miss", "Cache-Control": "public, max-age=86400",
        "X-Plot-Box": json.dumps(boxes)})


@app.get("/api/compare.png")
async def api_compare_png(request: Request, a_root: str, a: str, b_root: str, b: str):
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    align = request.query_params.get("align", "1") in ("1", "true")
    diff = request.query_params.get("diff", "1") in ("1", "true")
    key = cache_key("cmp", [fa, fb], {**p.as_dict(), "align": align, "diff": diff})
    hit, boxes_json = cache_get(key)
    if hit:
        return FileResponse(hit, media_type="image/png",
                            headers={"X-Cache": "hit", "X-Plot-Box": boxes_json})

    def work():
        panels, stats = core.compare(str(fa), str(fb), p, align=align, show_diff=diff)
        buf = io.BytesIO()
        boxes = core.render(panels, p, buf, title=f"{fa.name}   ↔   {fb.name}",
                            subtitle=f"FFT {p.nfft} · {p.window} · {p.scale} · "
                                     + t("plot.offset", p.lang,
                                         offset=stats["offset_s"]))
        return buf.getvalue(), boxes, stats

    async with _sem:
        try:
            data, boxes, stats = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    cache_put(key, data, boxes)
    try:
        stats_path(key).write_text(json.dumps(stats, default=str))
    except OSError:
        pass
    return Response(data, media_type="image/png",
                    headers={"X-Cache": "miss", "X-Plot-Box": json.dumps(boxes)})


@app.get("/api/compare.json")
async def api_compare_json(request: Request, a_root: str, a: str, b_root: str, b: str):
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    align = request.query_params.get("align", "1") in ("1", "true")

    # Das Bild hat die Kennzahlen in aller Regel schon berechnet - erneutes
    # Rechnen wuerde jede Vergleichsansicht doppelt so teuer machen.
    names = {str(fa): a, str(fb): b}
    cached = stats_path(cache_key("cmp", [fa, fb],
                                 {**p.as_dict(), "align": align, "diff": True}))
    if cached.exists():
        try:
            return strip_paths(json.loads(cached.read_text()), names)
        except (OSError, ValueError):
            pass

    def work():
        _, stats = core.compare(str(fa), str(fb), p, align=align, show_diff=True)
        return stats

    async with _sem:
        try:
            stats = await asyncio.to_thread(work)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    return strip_paths(stats, names)


@app.get("/api/report")
async def api_report(request: Request, root: str, path: str, loudness: int = 1):
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))

    async with _sem:
        try:
            rep = await asyncio.to_thread(core.summary, str(f), p, bool(loudness))
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    return strip_paths(rep, {str(f): path})


@app.get("/api/probe")
async def api_probe(request: Request, root: str, path: str):
    core.set_language(lang_from(request))
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
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{max(start, 0):.3f}"]
    cmd += ["-i", str(f)]
    if duration:
        cmd += ["-t", f"{max(min(duration, 3600), 0.1):.3f}"]
    cmd += ["-map", "a:0", "-vn", "-ac", "2", "-b:a", "160k", "-f", "mp3", "-"]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    async def gen():
        try:
            while True:
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    return StreamingResponse(gen(), media_type="audio/mpeg")


@app.get("/api/nulltest")
async def api_nulltest(request: Request, a_root: str, a: str, b_root: str, b: str):
    """Sample-genaue Nullprobe zweier Dateien."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    async with _sem:
        try:
            return await asyncio.to_thread(core.null_test, str(fa), str(fb), p)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e


@app.get("/api/residual")
async def api_residual(request: Request, a_root: str, a: str, b_root: str, b: str,
                       gain_db: float = 0.0):
    """Differenz zweier Fassungen als hoerbare FLAC-Datei."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    gain_db = max(-20.0, min(float(gain_db), 40.0))
    key = cache_key("res", [fa, fb], {**p.as_dict(), "gain": gain_db})
    out = CACHE_DIR / f"{key}.flac"
    name = f"residual_{Path(a).stem}_minus_{Path(b).stem}.flac"

    if not out.exists():
        async with _sem:
            try:
                await asyncio.to_thread(core.null_residual, str(fa), str(fb),
                                        str(out), p, 900.0, gain_db)
            except AudioError as e:
                out.unlink(missing_ok=True)
                raise HTTPException(422, clean_msg(e)) from e
        prune_cache()
    else:
        os.utime(out, None)
    return FileResponse(out, media_type="audio/flac", filename=name)


@app.get("/api/residual.json")
async def api_residual_json(request: Request, a_root: str, a: str,
                            b_root: str, b: str, gain_db: float = 0.0):
    """Kennzahlen des Residuals, ohne die Datei zu uebertragen."""
    fa, fb = resolve(a_root, a), resolve(b_root, b)
    p = params_from_query(request.query_params, lang_from(request))
    gain_db = max(-20.0, min(float(gain_db), 40.0))
    key = cache_key("res", [fa, fb], {**p.as_dict(), "gain": gain_db})
    out = CACHE_DIR / f"{key}.flac"
    meta = CACHE_DIR / f"{key}.res.json"
    if meta.exists() and out.exists():
        try:
            return json.loads(meta.read_text())
        except (OSError, ValueError):
            pass
    async with _sem:
        try:
            info = await asyncio.to_thread(core.null_residual, str(fa), str(fb),
                                           str(out), p, 900.0, gain_db)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e
    info["path"] = out.name
    try:
        meta.write_text(json.dumps(info))
    except OSError:
        pass
    return info


@app.get("/api/lowfreq")
async def api_lowfreq(request: Request, root: str, path: str):
    """Rumpeln, Plattenwelligkeit und Netzbrumm."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    async with _sem:
        try:
            return await asyncio.to_thread(core.lowfreq_scan, str(f), p)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e


@app.get("/api/wowflutter")
async def api_wowflutter(request: Request, root: str, path: str,
                         nominal_hz: float | None = None):
    """Drehzahlabweichung, Wow und Flutter an einem Messton."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    async with _sem:
        try:
            return await asyncio.to_thread(core.wow_flutter, str(f), p, nominal_hz)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e


@app.get("/api/sweep")
async def api_sweep(request: Request, root: str, path: str,
                    reference_hz: float = 1000.0):
    """Frequenzgang und Kanaltrennung aus einer Tonfolge."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    async with _sem:
        try:
            return await asyncio.to_thread(core.tone_sweep, str(f), p, reference_hz)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e


@app.get("/api/clicks")
async def api_clicks(request: Request, root: str, path: str,
                     threshold_db: float = 14.0):
    """Sucht Knackser und andere Impulsstoerungen."""
    f = resolve(root, path)
    p = params_from_query(request.query_params, lang_from(request))
    threshold_db = max(6.0, min(float(threshold_db), 40.0))
    async with _sem:
        try:
            return await asyncio.to_thread(core.impulse_scan, str(f), p, threshold_db)
        except AudioError as e:
            raise HTTPException(422, clean_msg(e)) from e


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
    seconds = max(5.0, min(float(seconds), 600.0))
    it = base.rglob("*") if recursive else base.glob("*")
    files = []
    for f in sorted(it):
        if len(files) >= limit:
            break
        if f.is_file() and not f.name.startswith(".") and is_audio(f):
            files.append(f)
    sprache = normalise(lang or DEFAULT_LANG)
    return r, files, seconds, limit, sprache, f"quickcheck:{int(seconds)}:{sprache}"


async def _scan_one(f: Path, r: dict, root: str, kind: str, seconds: float,
                    sprache: str, refresh: int, sem: asyncio.Semaphore) -> dict:
    rel = str(f.relative_to(r["path"]))
    if not refresh:
        cached = SIDECARS.load(root, rel, f, kind)
        if cached is not None:
            return {**cached, "path": rel, "cached": True}
    async with sem:
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
    r, files, seconds, limit, sprache, kind = _scan_setup(
        root, path, recursive, limit, seconds, lang)
    sem = asyncio.Semaphore(MAX_RENDERS)
    results = await asyncio.gather(*[
        _scan_one(f, r, root, kind, seconds, sprache, refresh, sem) for f in files])
    gerechnet = sum(1 for x in results if not x.get("cached"))
    warn = sum(1 for x in results if (x.get("verdict") or {}).get("level") == "warn")
    return {"root": root, "path": path, "count": len(results),
            "warnings": warn, "computed": gerechnet,
            "from_index": len(results) - gerechnet,
            "index": SIDECARS.enabled,
            "truncated": len(files) >= limit, "files": results}


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
    r, files, seconds, limit, sprache, kind = _scan_setup(
        root, path, recursive, limit, seconds, lang)

    async def ereignisse():
        def paket(art: str, daten: dict) -> bytes:
            return f"event: {art}\ndata: {json.dumps(daten, default=str)}\n\n".encode()

        yield paket("start", {"total": len(files), "root": root, "path": path,
                              "index": SIDECARS.enabled,
                              "truncated": len(files) >= limit})
        sem = asyncio.Semaphore(MAX_RENDERS)
        aufgaben = [asyncio.create_task(
            _scan_one(f, r, root, kind, seconds, sprache, refresh, sem))
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


@app.post("/api/upload")
async def api_upload(files: list[UploadFile] = File(...)):
    if len(files) > 50:
        raise HTTPException(400, t("http.too_many_files", n=50))
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved, errors = [], []
    limit = MAX_UPLOAD_MB * 1024 * 1024
    for uf in files:
        name = re.sub(r"[^\w.\- ()\[\]#&+,']", "_",
                      os.path.basename(uf.filename or "datei")).strip()
        if name in ("", ".", "..") or set(name) <= {"."}:
            name = "upload"
        dest = UPLOAD_DIR / name
        i = 1
        while dest.exists():
            dest = UPLOAD_DIR / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        size = 0
        try:
            with dest.open("wb") as out:
                while chunk := await uf.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError(t("http.too_large", mb=MAX_UPLOAD_MB))
                    out.write(chunk)
            await asyncio.to_thread(core.probe, str(dest))
            saved.append({"name": dest.name, "path": dest.name,
                          "root": "uploads", "size": size})
        except Exception as e:
            dest.unlink(missing_ok=True)
            errors.append({"name": name, "error": clean_msg(e)})
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
