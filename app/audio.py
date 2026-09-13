"""Dekodierung und Messwerte über ffmpeg.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

import numpy as np

from .i18n import current as _current_lang
from .i18n import t
from .params import CHUNK_BYTES, EPS, AudioError, Params


def _run(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError as e:
        raise AudioError(t("err.no_ffmpeg", _current_lang())) from e
    except subprocess.TimeoutExpired as e:
        raise AudioError(t("err.timeout", _current_lang())) from e


def probe(path: str) -> dict:
    """Technische Eckdaten der ersten Audiospur."""
    cp = _run([
        "ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
        "stream=sample_rate,channels,channel_layout,codec_name,codec_long_name,"
        "bits_per_raw_sample,bit_rate,sample_fmt:format=duration,format_name,"
        "bit_rate,size",
        "-of", "json", path,
    ], timeout=120)
    if cp.returncode != 0:
        raise AudioError(f"ffprobe: {cp.stderr.decode(errors='replace').strip()[:400]}")

    data = json.loads(cp.stdout or b"{}")
    if not data.get("streams"):
        raise AudioError(t("err.no_stream", _current_lang()))
    st, fmt = data["streams"][0], data.get("format", {})

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {
        "path": path,
        "name": os.path.basename(path),
        "sample_rate": _int(st.get("sample_rate")) or 44100,
        "channels": _int(st.get("channels")) or 1,
        "channel_layout": st.get("channel_layout"),
        "codec": st.get("codec_name", "?"),
        "codec_long": st.get("codec_long_name"),
        "sample_fmt": st.get("sample_fmt"),
        "bits": _int(st.get("bits_per_raw_sample")),
        "bit_rate": _int(st.get("bit_rate")) or _int(fmt.get("bit_rate")),
        "container": fmt.get("format_name"),
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "size": _int(fmt.get("size")),
    }


def _decoder(path: str, sr: int, channels: int, start, duration) -> subprocess.Popen:
    """Startet ffmpeg, das rohe float32-Samples auf stdout schreibt.

    Die Fehlerausgabe landet in einer temporaeren Datei statt in einer Pipe:
    bei stark beschaedigten Dateien schreibt ffmpeg Zehntausende Zeilen, und
    eine ungeleerte stderr-Pipe (64 KB Puffer) laesst Encoder und Leser
    gegenseitig blockieren - der Aufruf haengt dann endlos.
    """
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{float(start)}"]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", f"{float(duration)}"]
    cmd += ["-map", "a:0", "-vn", "-sn", "-dn",
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ac", str(channels), "-ar", str(sr), "-"]
    errfile = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errfile)
    proc._spectro_err = errfile          # type: ignore[attr-defined]
    return proc


def _decoder_error(proc: subprocess.Popen) -> str:
    """Liest die gesammelte Fehlerausgabe eines mit _decoder gestarteten ffmpeg."""
    f = getattr(proc, "_spectro_err", None)
    if f is None:
        return ""
    try:
        f.seek(0)
        return f.read().decode(errors="replace").strip()[-2000:]
    except (OSError, ValueError):
        return ""
    finally:
        try:
            f.close()
        except OSError:
            pass


def loudness(path: str, start=None, duration=None) -> dict:
    """Lautheit (EBU R128), Pegel und Rauschflur ueber ffmpeg-Filter.

    Liefert unter anderem die tatsaechlich genutzte Bittiefe - damit faellt
    auf, wenn eine 24-bit-Datei in Wahrheit nur 16 echte Bits enthaelt.
    """
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-nostdin"]
    if start:
        cmd += ["-ss", f"{float(start)}"]
    cmd += ["-i", path]
    if duration:
        cmd += ["-t", f"{float(duration)}"]
    # asplit: ebur128 rechnet intern in doppelter Genauigkeit. Haengt astats
    # in derselben Kette dahinter, misst es die konvertierten Samples und
    # meldet unsinnige Bittiefen (z. B. 40/44 statt 20/24).
    cmd += ["-map", "a:0", "-vn", "-filter_complex",
            "[0:a]asplit=2[e][s];"
            "[e]ebur128=peak=true:framelog=verbose[eo];"
            "[s]astats=measure_perchannel=none[so]",
            "-map", "[eo]", "-map", "[so]", "-f", "null", "-"]
    txt = _run(cmd).stderr.decode(errors="replace")

    out: dict = {}
    pats = {
        "lufs_integrated": r"I:\s*(-?\d+\.?\d*)\s*LUFS",
        "lra": r"LRA:\s*(-?\d+\.?\d*)\s*LU",
        "true_peak_dbfs": r"True peak:\s*\n\s*Peak:\s*(-?\d+\.?\d*)\s*dBFS",
        "peak_dbfs": r"Peak level dB:\s*(-?\d+\.?\d*)",
        "rms_dbfs": r"RMS level dB:\s*(-?\d+\.?\d*)",
        "rms_peak_dbfs": r"RMS peak dB:\s*(-?\d+\.?\d*)",
        "noise_floor_dbfs": r"Noise floor dB:\s*(-?\d+\.?\d*)",
        "flat_factor": r"Flat factor:\s*(-?\d+\.?\d*)",
        "abs_peak_count": r"Abs Peak count:\s*(\d+)",
        "dc_offset": r"DC offset:\s*(-?\d+\.?\d*)",
        "samples": r"Number of samples:\s*(\d+)",
    }
    for key, pat in pats.items():
        m = re.findall(pat, txt)
        if m:
            try:
                out[key] = float(m[-1])
            except (ValueError, TypeError):
                pass

    # astats meldet "Bit depth: A/B/...": A haengt vom Aussteuerungsgrad ab,
    # B ist die Bittiefe ohne die konstant genullten untersten Bits. Nur B ist
    # geeignet, um aufgeblasene Dateien zu erkennen (16 bit in 24-bit-Huelle).
    m = re.findall(r"Bit depth:\s*(\d+)/(\d+)", txt)
    if m:
        out["bit_depth_used"] = int(m[-1][0])
        out["bit_depth_effective"] = int(m[-1][1])
    if "peak_dbfs" in out and "rms_dbfs" in out:
        out["crest_db"] = round(out["peak_dbfs"] - out["rms_dbfs"], 2)
    return out


# --------------------------------------------------------------------------


def _decode_mono(path: str, sr: int, start=None, duration=None,
                 max_seconds: float = 600.0) -> np.ndarray:
    """Dekodiert die Datei als Mono-float32 (gedeckelt auf max_seconds)."""
    dur = duration if duration else max_seconds
    proc = _decoder(path, sr, 1, start, min(float(dur), max_seconds))
    try:
        data = proc.stdout.read()
    finally:
        proc.stdout.close()
        proc.wait()
        err = _decoder_error(proc)
    if not data and proc.returncode not in (0, None):
        raise AudioError(f"ffmpeg: {err[:300]}")
    return np.frombuffer(data, dtype=np.float32).copy()


def stereo_stats(path: str, p: Params) -> dict:
    """Korrelation und Seitenanteil - zeigt Mono-Faltungen und Phasenprobleme."""
    info = probe(path)
    if info["channels"] < 2:
        return {}
    sr = 22050
    proc = _decoder(path, sr, 2, p.start, p.duration)
    n, sxy, sxx, syy, sm, ss = 0, 0.0, 0.0, 0.0, 0.0, 0.0
    tail = b""
    while True:
        chunk = proc.stdout.read(CHUNK_BYTES)
        if not chunk:
            break
        chunk = tail + chunk
        usable = len(chunk) - (len(chunk) % 8)
        tail = chunk[usable:]
        b = np.frombuffer(chunk[:usable], dtype=np.float32).reshape(-1, 2).astype(np.float64)
        l, r = b[:, 0], b[:, 1]
        n += l.size
        sxy += float((l * r).sum())
        sxx += float((l * l).sum())
        syy += float((r * r).sum())
        sm += float((((l + r) / 2) ** 2).sum())
        ss += float((((l - r) / 2) ** 2).sum())
    proc.stdout.close()
    proc.wait()
    _decoder_error(proc)
    if not n:
        return {}
    corr = sxy / (np.sqrt(sxx * syy) + EPS)
    return {
        "correlation": round(float(corr), 4),
        "side_ratio_db": round(float(10 * np.log10((ss + EPS) / (sm + EPS))), 2),
        "identical_channels": bool(ss / (sm + EPS) < 1e-9),
    }


# --------------------------------------------------------------------------
