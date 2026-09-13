"""Vergleich zweier Aufnahmen: Ausrichtung, Differenz, Nullprobe, Residual.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

import numpy as np

from .audio import _decode_mono, _decoder, _decoder_error, probe
from .band import band_report, estimate_cutoff, to_db
from .i18n import khz as _khz
from .i18n import t
from .params import EPS, AudioError, Params
from .render import resample_cols
from .stft import Analysis, analyse


def _overlap(a: np.ndarray, b: np.ndarray, lag: int):
    """Schneidet beide Spektren auf den gemeinsamen Bereich fuer Versatz `lag`."""
    if lag > 0:
        a2, b2 = a[:, lag:], b
    elif lag < 0:
        a2, b2 = a, b[:, -lag:]
    else:
        a2, b2 = a, b
    n = min(a2.shape[1], b2.shape[1])
    return a2[:, :n], b2[:, :n]


def _bandpool(x: np.ndarray, bands: int = 64) -> np.ndarray:
    """Mittelt die Frequenzbins zu wenigen Baendern - macht den Abgleich
    schnell und unempfindlich gegen Encoder-Feinheiten."""
    n = x.shape[0]
    if n <= bands:
        return x
    edges = np.linspace(0, n, bands + 1).astype(int)
    paare = zip(edges[:-1], edges[1:], strict=False)
    return np.stack([x[a:max(b, a + 1)].mean(axis=0) for a, b in paare])


def _colpool(x: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return x
    n = (x.shape[1] // factor) * factor
    if n < factor:
        return x
    return x[:, :n].reshape(x.shape[0], n // factor, factor).mean(axis=2)


def align_shift(a: np.ndarray, b: np.ndarray, max_shift_cols: int = 600) -> int:
    """Zeitversatz zwischen zwei Spektrogrammen in Spalten.

    Grob-zu-fein-Suche direkt am spektralen Abstand: erst auf stark
    reduzierten Matrizen alle Versaetze durchprobieren, dann um den besten
    Treffer herum feinjustieren. Das ist robuster als eine reine
    Huellkurven-Korrelation, die bei gleichfoermigem Material (Rauschen,
    Dauertoene, Ambient) gern danebenliegt.
    """
    if a.shape[1] < 8 or b.shape[1] < 8:
        return 0
    ncols = min(a.shape[1], b.shape[1])
    # nie mehr als ein Viertel der kuerzeren Aufnahme verschieben - echte
    # Encoder-Delays und Schnittversaetze sind klein gegen die Spieldauer
    lim = int(min(max_shift_cols, 0.25 * ncols))
    if lim < 1:
        return 0

    ba, bb = _bandpool(a), _bandpool(b)
    k = max(1, int(np.ceil(min(ba.shape[1], bb.shape[1]) / 400)))
    ca, cb = _colpool(ba, k), _colpool(bb, k)
    min_overlap = max(8, int(0.7 * min(ca.shape[1], cb.shape[1])))

    def score(x_all, y_all, lag, need):
        x, y = _overlap(x_all, y_all, lag)
        if x.shape[1] < need:
            return None
        return float(np.abs(x - y).mean())

    # leichte Bevorzugung kleiner Versaetze: periodisches Material (Loops,
    # Tremolo, Beats) passt sonst auch bei voellig falschem Lag gut zusammen
    def penalised(sc, lag):
        return sc * (1.0 + 0.08 * abs(lag) / max(lim, 1))

    best, best_lag = None, 0
    for lag in range(-(lim // k), lim // k + 1):
        sc = score(ca, cb, lag, min_overlap)
        if sc is not None:
            sc = penalised(sc, lag * k)
            if best is None or sc < best:
                best, best_lag = sc, lag

    fine_need = max(8, int(0.7 * min(ba.shape[1], bb.shape[1])))
    best, out = None, 0
    for lag in range(best_lag * k - k, best_lag * k + k + 1):
        if abs(lag) > lim:
            continue
        sc = score(ba, bb, lag, fine_need)
        if sc is not None:
            sc = penalised(sc, lag)
            if best is None or sc < best:
                best, out = sc, lag
    # nur ausrichten, wenn es den Abstand gegenueber "kein Versatz" senkt
    zero = score(ba, bb, 0, fine_need)
    if zero is not None and best is not None and zero <= best * 1.02:
        return 0
    return out


@dataclass
class Panel:
    db: np.ndarray
    label: str
    sr: int
    t0: float
    t1: float
    kind: str = "spec"      # spec | diff
    note: str = ""


def build_panels(analysis: Analysis, p: Params, prefix: str = "") -> list:
    ref = max((float(m.max()) for m in analysis.mags), default=1.0) if p.normalize else 1.0
    panels = []
    for mag, label in zip(analysis.mags, analysis.labels, strict=False):
        panels.append(Panel(
            db=to_db(mag, ref or 1.0),
            label=f"{prefix}{label}" if prefix else label,
            sr=analysis.sr, t0=analysis.t0, t1=analysis.t0 + analysis.duration,
        ))
    return panels


def compare(path_a: str, path_b: str, p: Params, align: bool = True,
            show_diff: bool = True) -> tuple:
    """Analysiert zwei Dateien mit identischen Parametern und bildet die Differenz."""
    p = p.validate()
    ia, ib = probe(path_a), probe(path_b)
    # gemeinsame Samplerate: die kleinere der beiden, damit beide Bilder
    # dieselbe Frequenzachse haben
    sr = int(p.sr or min(ia["sample_rate"], ib["sample_rate"]))
    # Ein Differenzbild ueber mehrere Kanaele hinweg ist nicht definiert -
    # verglichen wird die Summe, sonst waere stillschweigend nur Kanal 1 drin.
    ch = "mix" if p.channels == "all" else p.channels
    pa = Params(**{**p.as_dict(), "sr": sr, "channels": ch})
    a = analyse(path_a, pa)
    b = analyse(path_b, pa)

    ma = a.mags[0]
    mb = b.mags[0]

    # Beide Spektrogramme muessen dieselbe Spaltendauer haben. Das Pooling
    # arbeitet in Zweierpotenzen, also bekommen unterschiedlich lange Dateien
    # sonst verschiedene Zeitraster - Ausrichtung und Differenz waeren dann
    # schlicht falsch. Die feinere Seite wird auf das groebere Raster gebracht.
    col_a = a.duration / max(ma.shape[1], 1)
    col_b = b.duration / max(mb.shape[1], 1)
    hop_eff = max(col_a, col_b)
    if col_a < hop_eff * 0.999:
        ma = resample_cols(ma, max(1, int(round(a.duration / hop_eff))))
    if col_b < hop_eff * 0.999:
        mb = resample_cols(mb, max(1, int(round(b.duration / hop_eff))))

    offset = 0.0
    da = to_db(ma, float(ma.max()) or 1.0)
    db_ = to_db(mb, float(mb.max()) or 1.0)
    if align:
        shift = align_shift(da, db_)
        offset = shift * hop_eff
        if shift > 0:
            da = da[:, shift:]
        elif shift < 0:
            db_ = db_[:, -shift:]

    chan = a.labels[0] if a.labels else "Summe"
    panels = [
        Panel(da, f"A: {ia['name']} · {chan}", sr, a.t0, a.t0 + a.duration),
        Panel(db_, f"B: {ib['name']} · {chan}", sr, b.t0, b.t0 + b.duration),
    ]

    stats = {
        "a": {**ia, "cutoff": estimate_cutoff(ma, sr, p.nfft)},
        "b": {**ib, "cutoff": estimate_cutoff(mb, sr, p.nfft)},
        "offset_s": round(offset, 4),
    }
    for key, mag_, info_, pfad in (("a", ma, ia, path_a), ("b", mb, ib, path_b)):
        band = band_report(pfad, pa, mag_, sr, info_["codec"])
        stats[key]["band"] = band
        stats[key]["verdict"] = band["verdict"]
        stats[key]["cutoff"] = band["edge_hz"] or band["signal_bandwidth_hz"]

    if show_diff:
        n = min(da.shape[1], db_.shape[1])
        if n >= 2:
            x, y = da[:, :n], db_[:, :n]
        else:
            n = max(da.shape[1], db_.shape[1])
            x, y = resample_cols(da, n), resample_cols(db_, n)
        floor = p.db_top - p.db_range
        d = np.maximum(x, floor) - np.maximum(y, floor)
        # Kennzahlen nur im gemeinsam belegten Band - sonst dominiert die
        # abgeschnittene Bandbreite der verlustbehafteten Datei alles
        cut = min(filter(None, (stats["a"]["cutoff"], stats["b"]["cutoff"],
                                sr / 2))) if any(
            (stats["a"]["cutoff"], stats["b"]["cutoff"])) else sr / 2
        kmax = max(4, int(cut / (sr / p.nfft)))
        dband = d[:kmax]
        panels.append(Panel(
            d, t("plot.difference", p.lang), sr, 0.0, n * hop_eff, kind="diff",
            note=t("plot.diff_note", p.lang, band=_khz(cut, p.lang),
                   median=float(np.median(dband)),
                   p90=float(np.percentile(np.abs(dband), 90))),
        ))
        stats["diff"] = {
            "band_hz": round(float(cut), 1),
            "median_db": round(float(np.median(dband)), 2),
            "mean_abs_db": round(float(np.abs(dband).mean()), 2),
            "p90_abs_db": round(float(np.percentile(np.abs(dband), 90)), 2),
            "max_abs_db": round(float(np.abs(dband).max()), 2),
        }
    return panels, stats


# --------------------------------------------------------------------------


def null_test(path_a: str, path_b: str, p: Params | None = None,
              max_seconds: float = 300.0) -> dict:
    """Sample-genaue Nullprobe: A und B ausrichten, Pegel angleichen, subtrahieren.

    Das Spektrogramm zeigt Unterschiede, die Nullprobe misst sie. Bleibt nach
    Ausrichtung und Verstaerkungsabgleich kaum Restsignal uebrig, stammen
    beide Dateien vom selben Master - unabhaengig von Container und Codec.
    """
    p = (p or Params()).validate()
    ia, ib = probe(path_a), probe(path_b)
    sr = int(p.sr or min(ia["sample_rate"], ib["sample_rate"]))

    a = _decode_mono(path_a, sr, p.start, p.duration, max_seconds)
    b = _decode_mono(path_b, sr, p.start, p.duration, max_seconds)
    if a.size < sr or b.size < sr:
        raise AudioError(t("err.too_short_null", p.lang))

    # Grobversatz ueber die Kreuzkorrelation eines Ausschnitts aus der Mitte
    win = min(int(30 * sr), a.size, b.size)
    ca = a[(a.size - win) // 2:(a.size - win) // 2 + win].astype(np.float64)
    cb = b[(b.size - win) // 2:(b.size - win) // 2 + win].astype(np.float64)
    n = 1 << int(np.ceil(np.log2(2 * win)))
    fa = np.fft.rfft(ca - ca.mean(), n)
    fb = np.fft.rfft(cb - cb.mean(), n)
    xc = np.fft.irfft(fa * np.conj(fb), n)
    xc = np.concatenate((xc[-(win - 1):], xc[:win]))
    lag = int(np.argmax(np.abs(xc))) - (win - 1)
    lag += ((a.size - win) // 2) - ((b.size - win) // 2)

    x, y = (a[lag:], b) if lag > 0 else (a, b[-lag:]) if lag < 0 else (a, b)
    m = min(x.size, y.size)
    x, y = x[:m].astype(np.float64), y[:m].astype(np.float64)
    if m < sr:
        raise AudioError(t("err.no_overlap", p.lang))

    # Pegel per kleinster Quadrate angleichen (unterschiedliche Aussteuerung)
    ref_x = float(np.sqrt((x * x).mean()))
    ref_y = float(np.sqrt((y * y).mean()))
    if ref_x < 1e-6 or ref_y < 1e-6:
        raise AudioError(t("err.silent", p.lang))
    denom = float((y * y).sum()) + EPS
    gain = float((x * y).sum()) / denom
    if not np.isfinite(gain) or abs(gain) > 1000 or abs(gain) < 1e-3:
        gain = ref_x / (ref_y + EPS)      # Rueckfall auf reinen Pegelabgleich
    resid = x - gain * y

    def rms(v):
        return float(np.sqrt((v * v).mean()) + EPS)

    rms_a, rms_r = rms(x), rms(resid)
    corr = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + EPS))

    depth = float(20 * np.log10(rms_r / (rms_a + EPS)))

    # Die Korrelation entscheidet zuerst, ob ueberhaupt dasselbe Material
    # vorliegt - erst danach sagt die Nulltiefe etwas ueber den Unterschied.
    if corr < 0.5:
        level, text = "warn", t("null.unrelated", p.lang, corr=corr)
    elif depth < -60:
        level, text = "ok", t("null.identical", p.lang)
    elif depth < -18:
        level, text = "ok", t("null.lossy", p.lang, depth=depth)
    elif depth < -8:
        level, text = "warn", t("null.mastering", p.lang, depth=depth)
    else:
        level, text = "warn", t("null.distant", p.lang, depth=depth)

    return {
        "sample_rate": sr,
        "offset_samples": int(lag),
        "offset_ms": round(lag / sr * 1000, 3),
        "gain_db": round(float(20 * np.log10(abs(gain) + EPS)), 3),
        "correlation": round(corr, 5),
        "residual_db": round(float(depth), 2),
        "residual_peak_db": round(float(20 * np.log10(np.abs(resid).max() + EPS)), 2),
        "analysed_seconds": round(m / sr, 2),
        "verdict": {"level": level, "text": text},
    }


def null_residual(path_a: str, path_b: str, out_path: str,
                  p: Params | None = None, max_seconds: float = 900.0,
                  gain_db: float = 0.0) -> dict:
    """Schreibt die Differenz zweier Fassungen als hoerbare Audiodatei.

    Das Differenzbild zeigt, *dass* sich zwei Fassungen unterscheiden - diese
    Datei laesst hoeren, *was* der Unterschied ist. Bei einer Restauration
    steht im Residual genau das, was der Entknackser oder die
    Rauschunterdrueckung entfernt hat: idealerweise nur Stoerungen, im
    ungoenstigen Fall auch Anteile der Musik.
    """
    p = (p or Params()).validate()
    ia, ib = probe(path_a), probe(path_b)
    sr = int(p.sr or min(ia["sample_rate"], ib["sample_rate"]))
    ch = 2 if min(ia["channels"], ib["channels"]) >= 2 else 1

    def decode(path):
        proc = _decoder(path, sr, ch, p.start, p.duration or max_seconds)
        try:
            raw = proc.stdout.read()
        finally:
            proc.stdout.close()
            proc.wait()
            err = _decoder_error(proc)
        if not raw:
            raise AudioError(f"keine Samples aus {os.path.basename(path)}: {err[:200]}")
        return np.frombuffer(raw, dtype=np.float32).reshape(-1, ch).astype(np.float64)

    A, B = decode(path_a), decode(path_b)

    # Versatz auf der Summe bestimmen, dann beide Kanaele gleich verschieben
    ma = A.mean(axis=1)
    mb = B.mean(axis=1)
    win = min(int(30 * sr), ma.size, mb.size)
    ca = ma[(ma.size - win) // 2:(ma.size - win) // 2 + win]
    cb = mb[(mb.size - win) // 2:(mb.size - win) // 2 + win]
    n = 1 << int(np.ceil(np.log2(2 * win)))
    xc = np.fft.irfft(np.fft.rfft(ca - ca.mean(), n) * np.conj(np.fft.rfft(cb - cb.mean(), n)), n)
    xc = np.concatenate((xc[-(win - 1):], xc[:win]))
    lag = int(np.argmax(np.abs(xc))) - (win - 1)
    lag += ((ma.size - win) // 2) - ((mb.size - win) // 2)

    if lag > 0:
        A = A[lag:]
    elif lag < 0:
        B = B[-lag:]
    m = min(A.shape[0], B.shape[0])
    A, B = A[:m], B[:m]
    if m < sr // 10:
        raise AudioError(t("err.no_overlap", p.lang))

    denom = float((B * B).sum()) + EPS
    gain = float((A * B).sum()) / denom
    if not np.isfinite(gain) or not 1e-3 < abs(gain) < 1e3:
        gain = 1.0
    resid = A - gain * B

    def rms(v):
        return float(np.sqrt((v * v).mean()) + EPS)

    depth = 20 * np.log10(rms(resid) / (rms(A) + EPS))
    peak = float(np.abs(resid).max())
    crest_r = 20 * np.log10((peak + EPS) / rms(resid))
    crest_a = 20 * np.log10((float(np.abs(A).max()) + EPS) / rms(A))

    boost = 10 ** (gain_db / 20.0)
    outbuf = np.clip(resid * boost, -1.0, 1.0).astype(np.float32)

    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr),
           "-ac", str(ch), "-i", "-", "-c:a", "flac", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = proc.communicate(outbuf.tobytes())
    if proc.returncode != 0:
        raise AudioError(f"ffmpeg: {err.decode(errors='replace')[:200]}")

    # --- Zerlegung: was erklaert die Differenz? -------------------------------
    mono_a = A.mean(axis=1)
    mono_r = resid.mean(axis=1)
    nf, hp = 4096, 2048
    stats_extra: dict = {}
    if mono_a.size > nf * 4:
        nfr = 1 + (mono_a.size - nf) // hp
        FA = np.lib.stride_tricks.sliding_window_view(mono_a, nf)[::hp][:nfr]
        FR = np.lib.stride_tricks.sliding_window_view(mono_r, nf)[::hp][:nfr]
        ea = 10 * np.log10((FA ** 2).mean(axis=1) + 1e-30)
        er = 10 * np.log10((FR ** 2).mean(axis=1) + 1e-30)
        order = np.argsort(ea)
        k = max(1, nfr // 3)
        stats_extra["quiet_rel_db"] = round(float(np.mean(er[order[:k]] - ea[order[:k]])), 1)
        stats_extra["loud_rel_db"] = round(float(np.mean(er[order[-k:]] - ea[order[-k:]])), 1)

        # Spektralform des Entfernten gegen die des Programms - in den lauten
        # Abschnitten. Aehnliche Form heisst: es wurde Programm entfernt, nicht
        # nur ein Rauschteppich.
        win = np.hanning(nf)
        SA = np.abs(np.fft.rfft(FA[order[-k:]] * win, axis=1)) ** 2
        SR = np.abs(np.fft.rfft(FR[order[-k:]] * win, axis=1)) ** 2
        dfr = sr / nf
        lo_i, hi_i = int(200 / dfr), int(min(8000, sr / 2 - 100) / dfr)
        if hi_i - lo_i > 16:
            sa = 10 * np.log10(SA[:, lo_i:hi_i].mean(axis=0) + 1e-30)
            sb = 10 * np.log10(SR[:, lo_i:hi_i].mean(axis=0) + 1e-30)
            with np.errstate(invalid="ignore"):
                c = float(np.corrcoef(sa - sa.mean(), sb - sb.mean())[0, 1])
            stats_extra["shape_correlation"] = round(c if np.isfinite(c) else 0.0, 3)

    spiky = crest_r - crest_a
    shape = stats_extra.get("shape_correlation")
    loud = stats_extra.get("loud_rel_db")
    quiet = stats_extra.get("quiet_rel_db")

    parts = []
    if spiky > 20:
        parts.append(t("res.impulses", p.lang))
        level = "ok"
    else:
        level = "ok"
        if quiet is not None and quiet > -6:
            parts.append(t("res.gate", p.lang))
        if loud is not None:
            parts.append(t("res.loud", p.lang, db=abs(loud)))
            if loud > -12:
                level = "warn"
        if shape is not None and shape > 0.8 and (loud is None or loud > -20):
            parts.append(t("res.follows", p.lang, r=shape))
            level = "warn"
        elif shape is not None and shape < 0.5:
            parts.append(t("res.noise", p.lang))
    if not parts:
        parts.append(t("res.mixed", p.lang))
    verdict = {"level": level, "text": " ".join(parts)}

    return {
        "path": out_path,
        "sample_rate": sr, "channels": ch,
        "crest_db": round(float(crest_r), 1),
        "source_crest_db": round(float(crest_a), 1),
        **stats_extra,
        "verdict": verdict,
        "offset_samples": int(lag),
        "offset_ms": round(lag / sr * 1000, 3),
        "gain_db": round(float(20 * np.log10(abs(gain) + EPS)), 3),
        "residual_db": round(float(depth), 2),
        "residual_peak_db": round(float(20 * np.log10(peak + EPS)), 2),
        "applied_gain_db": gain_db,
        "seconds": round(m / sr, 2),
    }


# --------------------------------------------------------------------------
