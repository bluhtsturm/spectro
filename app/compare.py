"""Vergleich zweier Aufnahmen: Ausrichtung, Differenz, Nullprobe, Residual.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
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

    # Die Kennzahlen der Differenz entstehen immer, das Bild nur auf Wunsch:
    # so haengen die Kennzahlen nicht davon ab, ob jemand das Differenzbild
    # eingeschaltet hat, und lassen sich fuer beide Faelle gemeinsam cachen.
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
    median = float(np.median(dband))
    p90 = float(np.percentile(np.abs(dband), 90))
    stats["diff"] = {
        "band_hz": round(float(cut), 1),
        "median_db": round(median, 2),
        "mean_abs_db": round(float(np.abs(dband).mean()), 2),
        "p90_abs_db": round(p90, 2),
        "max_abs_db": round(float(np.abs(dband).max()), 2),
    }
    if show_diff:
        panels.append(Panel(
            d, t("plot.difference", p.lang), sr, 0.0, n * hop_eff, kind="diff",
            note=t("plot.diff_note", p.lang, band=_khz(cut, p.lang),
                   median=median, p90=p90),
        ))
    return panels, stats


# --------------------------------------------------------------------------


def _coarse_lag(a: np.ndarray, b: np.ndarray, sr: int) -> int:
    """Versatz von A gegen B in Samples, per Kreuzkorrelation der Mitte.

    Korreliert wird ein Ausschnitt von hoechstens 30 s aus der Mitte beider
    Dateien; mehrkanalige Signale (Form (n, Kanaele)) gehen als Summe ein.
    Positiv heisst: A beginnt spaeter.
    """
    win = min(int(30 * sr), a.shape[0], b.shape[0])
    sa, sb = (a.shape[0] - win) // 2, (b.shape[0] - win) // 2

    def mitte(x: np.ndarray, s: int) -> np.ndarray:
        seg = x[s:s + win]
        seg = (seg.mean(axis=1, dtype=np.float64) if seg.ndim == 2
               else seg.astype(np.float64))
        return seg - seg.mean()

    n = 1 << int(np.ceil(np.log2(2 * win)))
    xc = np.fft.irfft(np.fft.rfft(mitte(a, sa), n)
                      * np.conj(np.fft.rfft(mitte(b, sb), n)), n)
    xc = np.concatenate((xc[-(win - 1):], xc[:win]))
    return int(np.argmax(np.abs(xc))) - (win - 1) + sa - sb


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

    lag = _coarse_lag(a, b, sr)

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


def _write_flac(out_path: str, sr: int, ch: int, blocks) -> None:
    """Kodiert float32-Bloecke als FLAC - erst unter eigenem Namen, dann
    umbenannt.

    Ein abgebrochener Lauf - Fehler, Neustart, zwei gleichzeitige Anfragen -
    hinterlaesst so nie eine halbe Datei unter dem endgueltigen Namen, die
    danach als gueltiges Ergebnis ausgeliefert wuerde.
    """
    ziel = os.path.abspath(out_path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ziel),
                               prefix=os.path.basename(ziel) + ".", suffix=".part")
    os.close(fd)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr),
           "-ac", str(ch), "-i", "-", "-c:a", "flac", "-f", "flac", tmp]
    # Fehlerausgabe in eine Datei statt in eine Pipe, die niemand liest,
    # waehrend stdin beschrieben wird (siehe _decoder)
    with tempfile.TemporaryFile() as errfile:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errfile)
            try:
                for blk in blocks:
                    proc.stdin.write(blk)
            except BrokenPipeError:
                pass                          # ffmpeg ist ausgestiegen, s. u.
            finally:
                proc.stdin.close()
                proc.wait()
            if proc.returncode != 0:
                errfile.seek(0)
                err = errfile.read().decode(errors="replace")
                raise AudioError(f"ffmpeg: {err[:200]}")
            os.replace(tmp, ziel)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def null_residual(path_a: str, path_b: str, out_path: str,
                  p: Params | None = None, max_seconds: float = 900.0,
                  gain_db: float = 0.0) -> dict:
    """Schreibt die Differenz zweier Fassungen als hoerbare Audiodatei.

    Das Differenzbild zeigt, *dass* sich zwei Fassungen unterscheiden - diese
    Datei laesst hoeren, *was* der Unterschied ist. Bei einer Restauration
    steht im Residual genau das, was der Entknackser oder die
    Rauschunterdrueckung entfernt hat: idealerweise nur Stoerungen, im
    ungoenstigen Fall auch Anteile der Musik.

    Beide Fassungen liegen einmal als float32 im Speicher; Pegelabgleich,
    Residual und Zerlegung entstehen blockweise. Frueher lagen beide Dateien,
    ihre Summen und das Residual gleichzeitig in doppelter Genauigkeit vor -
    bei 15 Minuten 96 kHz Stereo mehrere Gigabyte.
    """
    p = (p or Params()).validate()
    ia, ib = probe(path_a), probe(path_b)
    sr = int(p.sr or min(ia["sample_rate"], ib["sample_rate"]))
    ch = 2 if min(ia["channels"], ib["channels"]) >= 2 else 1
    laenge = min(float(p.duration or max_seconds), max_seconds)

    def decode(path):
        proc = _decoder(path, sr, ch, p.start, laenge)
        try:
            raw = proc.stdout.read()
        finally:
            proc.stdout.close()
            proc.wait()
            err = _decoder_error(proc)
        n = len(raw) // (4 * ch)
        if not n:
            raise AudioError(f"keine Samples aus {os.path.basename(path)}: {err[:200]}")
        # ohne Kopie: das Array teilt sich den Speicher mit den gelesenen Bytes
        return np.frombuffer(raw, dtype=np.float32, count=n * ch).reshape(-1, ch)

    A, B = decode(path_a), decode(path_b)

    # Versatz auf der Summe bestimmen, dann beide Kanaele gleich verschieben
    lag = _coarse_lag(A, B, sr)
    if lag > 0:
        A = A[lag:]
    elif lag < 0:
        B = B[-lag:]
    m = min(A.shape[0], B.shape[0])
    A, B = A[:m], B[:m]
    if m < sr // 10:
        raise AudioError(t("err.no_overlap", p.lang))

    nf, hp = 4096, 2048                     # Rahmen der Zerlegung
    schritt = hp * 64                       # Blockgroesse, Vielfaches von hp

    def bloecke():
        for s in range(0, m, schritt):
            yield (s, A[s:s + schritt].astype(np.float64),
                   B[s:s + schritt].astype(np.float64))

    # Pegel per kleinster Quadrate angleichen (unterschiedliche Aussteuerung)
    saa = sbb = sab = peak_a = 0.0
    for _, a, b in bloecke():
        saa += float((a * a).sum())
        sbb += float((b * b).sum())
        sab += float((a * b).sum())
        peak_a = max(peak_a, float(np.abs(a).max()))
    gain = sab / (sbb + EPS)
    if not np.isfinite(gain) or not 1e-3 < abs(gain) < 1e3:
        gain = 1.0

    # Residual blockweise bilden und direkt zum Encoder schicken. Nebenbei
    # die Energie je halbem Rahmen sammeln: zwei benachbarte Haelften ergeben
    # einen Rahmen der Zerlegung, ohne das Residual ganz vorzuhalten.
    boost = 10 ** (gain_db / 20.0)
    nblk = m // hp
    e_a, e_r = np.zeros(nblk), np.zeros(nblk)
    srr = peak_r = 0.0

    def residual_bloecke():
        nonlocal srr, peak_r
        for s, a, b in bloecke():
            r = a - gain * b
            srr += float((r * r).sum())
            peak_r = max(peak_r, float(np.abs(r).max()))
            k0 = s // hp
            k1 = min((s + a.shape[0]) // hp, nblk)
            voll = (k1 - k0) * hp
            if voll > 0:
                ma = a[:voll].mean(axis=1).reshape(-1, hp)
                mr = r[:voll].mean(axis=1).reshape(-1, hp)
                e_a[k0:k1] = (ma * ma).sum(axis=1)
                e_r[k0:k1] = (mr * mr).sum(axis=1)
            yield np.clip(r * boost, -1.0, 1.0).astype(np.float32).tobytes()

    _write_flac(out_path, sr, ch, residual_bloecke())

    n_werte = m * ch
    rms_a = float(np.sqrt(saa / n_werte)) + EPS
    rms_r = float(np.sqrt(srr / n_werte)) + EPS
    depth = 20 * np.log10(rms_r / (rms_a + EPS))
    peak = peak_r
    crest_r = 20 * np.log10((peak + EPS) / rms_r)
    crest_a = 20 * np.log10((peak_a + EPS) / rms_a)

    # --- Zerlegung: was erklaert die Differenz? -------------------------------
    stats_extra: dict = {}
    if m > nf * 4:
        ea = 10 * np.log10((e_a[:-1] + e_a[1:]) / nf + 1e-30)
        er = 10 * np.log10((e_r[:-1] + e_r[1:]) / nf + 1e-30)
        nfr = ea.size
        order = np.argsort(ea)
        k = max(1, nfr // 3)
        stats_extra["quiet_rel_db"] = round(float(np.mean(er[order[:k]] - ea[order[:k]])), 1)
        stats_extra["loud_rel_db"] = round(float(np.mean(er[order[-k:]] - ea[order[-k:]])), 1)

        # Spektralform des Entfernten gegen die des Programms - in den lauten
        # Abschnitten. Aehnliche Form heisst: es wurde Programm entfernt, nicht
        # nur ein Rauschteppich. Gemittelt wird in Gruppen von Rahmen.
        win = np.hanning(nf)
        sa_sum = np.zeros(nf // 2 + 1)
        sr_sum = np.zeros(nf // 2 + 1)
        laut = np.sort(order[-k:])
        for teil in np.array_split(laut, max(1, laut.size // 64)):
            idx = teil[:, None] * hp + np.arange(nf)
            fa = A[idx].astype(np.float64)                 # (Rahmen, nf, Kanaele)
            fr = (fa - gain * B[idx].astype(np.float64)).mean(axis=2)
            fa = fa.mean(axis=2)
            sa_sum += (np.abs(np.fft.rfft(fa * win, axis=1)) ** 2).sum(axis=0)
            sr_sum += (np.abs(np.fft.rfft(fr * win, axis=1)) ** 2).sum(axis=0)
        dfr = sr / nf
        lo_i, hi_i = int(200 / dfr), int(min(8000, sr / 2 - 100) / dfr)
        if hi_i - lo_i > 16:
            sa = 10 * np.log10(sa_sum[lo_i:hi_i] / k + 1e-30)
            sb = 10 * np.log10(sr_sum[lo_i:hi_i] / k + 1e-30)
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
