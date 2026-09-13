"""Bandkante, Bandbreite, Dauertöne und Energieverteilung.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import numpy as np

from .i18n import khz as _khz
from .i18n import t
from .params import EPS, Params
from .stft import analyse


def to_db(mag: np.ndarray, ref: float) -> np.ndarray:
    return 20 * np.log10(np.maximum(mag, EPS) / max(ref, EPS))


def estimate_cutoff(mag: np.ndarray, sr: int, nfft: int, drop_db: float = 50.0):
    """Hoechste Frequenz, deren Langzeitpegel noch drop_db unter dem Peak liegt."""
    power = (mag.astype(np.float64) ** 2).mean(axis=1)
    db = 10 * np.log10(power + EPS)
    peak = db.max()
    above = np.nonzero(db > peak - drop_db)[0]
    if above.size == 0:
        return None
    return float(above[-1] * sr / nfft)


def _smooth(db: np.ndarray, bins: int) -> np.ndarray:
    if bins < 2:
        return db
    return np.convolve(db, np.ones(bins) / bins, mode="same")


def spectral_edge(med_db: np.ndarray, sr: int, nfft: int,
                  min_drop: float = 15.0, min_hz: float = 7000.0,
                  min_steepness: float = 10.0):
    """Sucht einen Steilabfall im Spektrum: Pegel knapp darunter gegen Boden darueber.

    Unterscheidet die harte Bandkante einer Kodier- oder Abtaststufe vom
    weichen Hoehenabfall echter Aufnahmen (Band, Schallplatte, alte Baender).
    """
    df = sr / nfft
    sm = _smooth(med_db, max(1, int(150 / df)))
    nyq = sr / 2
    lo_i, hi_i = max(int(min_hz / df), 4), int(0.995 * nyq / df)
    best = None
    for i in range(lo_i, hi_i):
        f = i * df
        b0, b1 = max(4, int((f - 1500) / df)), i
        a0, a1 = int((f + 300) / df), int(min(f + 4000, nyq) / df)
        if b1 - b0 < 3 or a1 - a0 < 3:
            continue
        drop = float(np.median(sm[b0:b1]) - np.median(sm[a0:a1]))
        if best is None or drop > best[0]:
            best = (drop, f, float(np.median(sm[a0:a1])))
    if best is None or best[0] < min_drop:
        return None

    # Die Suche nach dem groessten Abstand zwischen "knapp darunter" und
    # "darueber" trifft die Kante nur grob: bei einem sehr steilen Abfall
    # liegt das Maximum bis zu 2 kHz zu tief, weil das obere Fenster schon
    # vorher ganz im Sperrbereich liegt. Deshalb den Punkt des staerksten
    # Gefaelles in der Umgebung suchen.
    i_best = int(best[1] / df)
    lo_r = max(1, i_best - int(500 / df))
    hi_r = min(sm.size - 2, i_best + int(4000 / df))
    if hi_r > lo_r + 2:
        step = max(1, int(200 / df))
        grad = sm[lo_r:hi_r - step] - sm[lo_r + step:hi_r]
        i_best = lo_r + int(np.argmax(grad))
    hz = i_best * df

    # Steilheit an der Fundstelle: ein Encoder- oder Wandlerfilter faellt mit
    # 45 bis 80 dB/kHz ab, der Hoehenabfall einer Platte oder eines Bandes mit
    # 3 bis 6. Ohne diese Pruefung meldet jede leise Rillenstelle eine Kante.
    a = max(1, int((hz - 500) / df))
    b = min(sm.size - 1, int((hz + 500) / df))
    steep = (sm[a] - sm[b]) / max((b - a) * df / 1000, 1e-6)
    if steep < min_steepness:
        return None
    return {"hz": round(hz, 1), "drop_db": round(best[0], 1),
            "floor_db": round(best[2], 1), "steepness_db_per_khz": round(float(steep), 1)}


def signal_bandwidth(med_db: np.ndarray, sr: int, nfft: int,
                     drop_db: float = 50.0):
    """Wo die Signalenergie endet - der weiche Hoehenabfall, keine Bandkante."""
    df = sr / nfft
    sm = _smooth(med_db, max(1, int(150 / df)))
    above = np.nonzero(sm > sm.max() - drop_db)[0]
    return round(float(above[-1] * df), 1) if above.size else None


# Ab welchem Anteil der Nyquist-Frequenz eine Kante als Antialiasing-Filter
# des Wandlers gilt und nicht als Bandbegrenzung. An einer Encoder-Leiter
# gemessen: Encoder-Tiefpaesse lagen zwischen 72 und 91 %, das Filter eines
# 48-kHz-Wandlers bei 97 %. Die Schwelle liegt mit Abstand dazwischen.
NEAR_NYQUIST = 0.94

# Feste Auflösung fuer das Bandkanten-Urteil. Die Lage einer Steilkante haengt
# vom Analysefenster ab: bei langem Fenster liegt der Rauschboden tiefer, der
# Uebergang zieht sich, und die steilste Stelle wandert nach oben. Gemessen an
# einer Encoder-Leiter verschob sich dieselbe Kante zwischen nfft 4096 und
# 16384 um 1,3 kHz - genug, um ein Urteil kippen zu lassen. Deshalb urteilt die
# Bandanalyse immer bei dieser Groesse, unabhaengig von der Bildeinstellung.
REFERENCE_NFFT = 4096

LOSSLESS_CODECS = {
    "flac", "alac", "wavpack", "ape", "tta", "tak", "shorten", "mlp", "truehd",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_f64le",
    "pcm_s16be", "pcm_s24be", "pcm_s32be", "dsd_lsbf", "dsd_msbf", "dsd_lsbf_planar",
}

# Was eine Bandgrenze ueber die Herkunft verraet - und was nicht. An einer
# Encoder-Leiter aus einer Quelle gemessen (Werte in kHz):
#   MP3 128 -> 15,95   MP3 192 -> 16,00   MP3 256 -> 19,11   MP3 320 -> 20,14
#   AAC 128 -> 19,93   Vorbis q6 -> 19,94   Opus 96/192 -> 20,47
# Die Frequenz benennt also weder Format noch Bitrate: 128 und 192 kbit/s
# liegen 50 Hz auseinander, und im Bereich um 20 kHz treffen sich vier
# verschiedene Encoder. Deshalb nur noch grobe Bereiche.
EDGE_HINTS = [(17.5, "hint.low"), (19.5, "hint.mid"), (99.0, "hint.high")]


def band_analysis(mag: np.ndarray, sr: int, nfft: int, codec: str = "",
                  blocks: int = 16, lang: str = "de") -> dict:
    """Bandkante und Bandbreite - abschnittsweise, damit sich zeigt, ob die
    Grenze konstant ist oder mit dem Material wandert.

    Eine konstante Kante deutlich unter der Nyquist-Frequenz stammt von einer
    festen Bandbegrenzung (Encoder-Tiefpass oder eine niedrigere Abtastrate in
    der Kette). Eine wandernde Kante ist der Fingerabdruck einer
    verlustbehafteten Kodierung: in leisen Passagen wirft der Encoder die
    Hoehen weg, in lauten behaelt er sie.
    """
    P = mag.astype(np.float64) ** 2
    nyq = sr / 2
    lossless = codec.lower() in LOSSLESS_CODECS

    full = 10 * np.log10(np.median(P, axis=1) + 1e-30)
    full -= full.max()
    bw = signal_bandwidth(full, sr, nfft)
    full_edge = spectral_edge(full, sr, nfft)

    nb = int(np.clip(P.shape[1] // 25, 1, blocks))
    hits, spans = [], 0
    for ix in np.array_split(np.arange(P.shape[1]), nb):
        if ix.size < 3:
            continue
        spans += 1
        med = 10 * np.log10(np.median(P[:, ix], axis=1) + 1e-30)
        e = spectral_edge(med - med.max(), sr, nfft)
        if e and e["hz"] < NEAR_NYQUIST * nyq:
            hits.append(e)
    share = len(hits) / spans if spans else 0.0
    edges = [h["hz"] for h in hits]
    edge = float(np.median(edges)) if edges else None
    spread = (float(np.percentile(edges, 90) - np.percentile(edges, 10))
              if len(edges) > 2 else 0.0)

    out = {
        "signal_bandwidth_hz": bw,
        "edge_hz": round(edge, 1) if edge else None,
        "edge_share": round(share, 2),
        "edge_spread_hz": round(spread, 1),
        "edge_drop_db": round(float(np.median([h["drop_db"] for h in hits])), 1) if hits else None,
        "floor_db": round(float(np.median([h["floor_db"] for h in hits])), 1) if hits else None,
        "blocks": spans,
        "blocks_with_edge": len(hits),
    }

    def khz(v):
        return _khz(v, lang)

    hint_key = next((k for grenze, k in EDGE_HINTS
                     if edge and edge / 1000 < grenze), None)
    hint = t(hint_key, lang) if hint_key else None

    # Hochgesampeltes Material ist eine Eigenschaft der ganzen Datei, nicht
    # einzelner Abschnitte: in leisen Passagen erreicht der Abfall die Schwelle
    # nicht, obwohl die Bandgrenze natuerlich weiterbesteht. Deshalb hier das
    # Gesamtspektrum befragen.
    if full_edge and full_edge["hz"] < NEAR_NYQUIST * nyq:
        # Nicht die Fundstelle der Kante zaehlt, sondern wo das Spektrum den
        # Boden erreicht: das ist die Nyquist-Frequenz der urspruenglichen
        # Abtastrate. Die Kante selbst liegt im Uebergangsbereich davor und
        # wuerde 48 kHz faelschlich als 44,1 kHz ausweisen.
        df_ = sr / nfft
        sm_ = _smooth(full, max(1, int(150 / df_)))
        start = int(full_edge["hz"] / df_)
        below = np.nonzero(sm_[start:] < sm_[start] - 40)[0]
        if below.size == 0:
            floor_lvl = float(np.median(sm_[int(0.98 * sm_.size):]))
            below = np.nonzero(sm_[start:] < floor_lvl + 6)[0]
        stop_hz = (start + below[0]) * df_ if below.size else full_edge["hz"]
        out["stopband_hz"] = round(float(stop_hz), 1)

        cands = sorted((abs(stop_hz - r / 2), r)
                       for r in (44100, 48000, 88200) if sr > 1.5 * r)
        for dist, rate in cands[:1]:
            if dist < 1800:
                out.update({"pattern": "hochgesampelt", "source_rate_hint": rate,
                            "edge_hz": full_edge["hz"],
                            "edge_drop_db": full_edge["drop_db"],
                            "floor_db": full_edge["floor_db"]})
                schluessel = ("band.upsampled_sharp"
                              if abs(stop_hz - full_edge["hz"]) < 500
                              else "band.upsampled_slope")
                wie = t(schluessel, lang, stop=khz(stop_hz),
                        edge=khz(full_edge["hz"]), floor=full_edge["floor_db"])
                out["verdict"] = {"level": "warn", "text": t(
                    "band.upsampled", lang, how=wie,
                    rate=t(f"rate.{rate}", lang), sr=sr / 1000)}
                return out

        # Eine feste Bandbegrenzung. Sie muss nicht in jedem Abschnitt
        # auffallen - bei hohen Bitraten sass die Kante im Gesamtspektrum
        # unuebersehbar, in einzelnen Abschnitten aber nur selten.
        out.update({"pattern": "konstant", "edge_hz": full_edge["hz"],
                    "edge_drop_db": full_edge["drop_db"],
                    "floor_db": full_edge["floor_db"]})
        edge = full_edge["hz"]
        hint_key = next((k for grenze, k in EDGE_HINTS if edge / 1000 < grenze), None)
        hint = t(hint_key, lang) if hint_key else None
        if lossless:
            zusatz = t("band.transcode_hint", lang, what=hint) if hint else ""
            out["verdict"] = {"level": "warn", "text": t(
                "band.transcode", lang, edge=khz(edge), hint=zusatz)}
        else:
            zusatz = t("band.limited_hint", lang, what=hint) if hint else ""
            out["verdict"] = {"level": "ok", "text": t(
                "band.limited", lang, edge=khz(edge), hint=zusatz)}
        return out

    # Ohne Kante im Gesamtspektrum gilt die Datei als vollbandig. Der
    # abschnittsweise Befund bleibt als Kennzahl erhalten, fuehrt aber zu
    # keiner eigenen Einstufung mehr: an 41 Dateien gemessen zeigte er nie
    # etwas Echtes an, sobald die Ganzdatei entscheidet - einzelne Abschnitte
    # einer sauberen verlustfreien Aufnahme erfuellen die Kantenbedingung rein
    # zufaellig.
    out["pattern"] = "voll"
    if bw:
        weich = t("band.soft", lang) if bw < 0.75 * nyq else ""
        txt = t("band.none", lang, bw=khz(bw), soft=weich)
    else:
        txt = t("band.none_nobw", lang)
    out["verdict"] = {"level": "ok", "text": txt}
    return out


def tonal_peaks(mag: np.ndarray, sr: int, nfft: int, min_hz: float = 5000.0,
                min_prominence: float = 10.0, min_share: float = 0.8,
                max_level_db: float = -30.0, min_level_db: float = -95.0,
                blocks: int = 8, limit: int = 6) -> list:
    """Findet schmalbandige Dauertoene - Pfeifen und Einstreuungen der Aufnahmekette.

    Drei Bedingungen muessen zusammenkommen, sonst meldet die Pruefung jede
    gehaltene Note: der Ton muss schmal sein (wenige Bins), leise gegenueber
    dem Programm, und er muss in fast allen Zeitabschnitten an derselben
    Stelle stehen. Musik wandert, eine Einstreuung nicht.
    """
    P = mag.astype(np.float64) ** 2
    df = sr / nfft
    nb = int(np.clip(P.shape[1] // 20, 1, blocks))
    if nb < 3 or P.shape[1] < 24:
        return []
    lo = max(2, int(min_hz / df))
    hi = min(P.shape[0] - 2, int(0.98 * (sr / 2) / df))
    if hi - lo < 8:
        return []

    kw = max(3, int(400 / df)) | 1
    max_width = max(2, int(np.ceil(60 / df)))     # hoechstens ~60 Hz breit
    seen: dict = {}
    for bi, ix in enumerate(np.array_split(np.arange(P.shape[1]), nb)):
        med = 10 * np.log10(np.median(P[:, ix], axis=1) + 1e-30)
        ref = med.max()
        seg = med[lo:hi]
        prom = seg - _smooth(seg, kw)
        for i in np.nonzero(prom > min_prominence)[0]:
            if not (0 < i < seg.size - 1 and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]):
                continue
            lvl = seg[i] - ref
            if lvl > max_level_db:                # zu laut -> das ist Programm
                continue
            if lvl < min_level_db:                # unterhalb jeder Hoerbarkeit,
                continue                          # meist Quantisierungsartefakte
            l = r = i                              # Breite bei -6 dB bestimmen
            while l > 0 and seg[l] > seg[i] - 6:
                l -= 1
            while r < seg.size - 1 and seg[r] > seg[i] - 6:
                r += 1
            if r - l > max_width:
                continue
            key = int(round((lo + i) * df / 25))   # 25-Hz-Raster
            e = seen.setdefault(key, {"hz": [], "prom": [], "lvl": [], "blocks": set()})
            e["hz"].append((lo + i) * df)
            e["prom"].append(float(prom[i]))
            e["lvl"].append(float(seg[i] - ref))
            e["blocks"].add(bi)

    out = []
    for e in seen.values():
        share = len(e["blocks"]) / nb
        if share < min_share:
            continue
        out.append({"hz": round(float(np.median(e["hz"])), 1),
                    "prominence_db": round(float(np.median(e["prom"])), 1),
                    "level_db": round(float(np.median(e["lvl"])), 1),
                    "share": round(share, 2)})
    out.sort(key=lambda d: -d["prominence_db"])
    return out[:limit]


def band_energy(mag: np.ndarray, sr: int, nfft: int) -> list:
    """Mittlere Energie in Oktavbaendern (fuer eine kompakte Kennzahl)."""
    edges = [0, 60, 120, 250, 500, 1000, 2000, 4000, 8000, 16000, sr / 2]
    df = sr / nfft
    power = (mag.astype(np.float64) ** 2).mean(axis=1)
    total = power.sum() + EPS
    out = []
    for lo, hi in zip(edges[:-1], edges[1:], strict=False):
        if lo >= sr / 2:
            break
        i0, i1 = int(lo / df), min(int(hi / df) + 1, power.size)
        out.append({"lo": lo, "hi": min(hi, sr / 2),
                    "share": float(power[i0:i1].sum() / total)})
    return out




def band_report(path: str, p: Params, mag=None, sr: int | None = None,
                codec: str = "", lang: str | None = None) -> dict:
    """Bandanalyse bei der Bezugsaufloesung.

    Passt die Bildeinstellung dazu, wird das vorhandene Spektrum verwendet;
    sonst wird eigens dafuer noch einmal analysiert. Das kostet einen weiteren
    Dekodierdurchgang, macht das Urteil aber unabhaengig davon, welche
    FFT-Groesse jemand fuer die Darstellung gewaehlt hat.
    """
    lang = lang or p.lang
    if mag is not None and p.nfft == REFERENCE_NFFT and sr:
        return band_analysis(mag, sr, REFERENCE_NFFT, codec, lang=lang)
    ref = Params(**{**p.as_dict(), "nfft": REFERENCE_NFFT,
                    "overlap": 0.5, "channels": "mix"})
    a = analyse(path, ref)
    return band_analysis(a.mags[0], a.sr, REFERENCE_NFFT, a.info["codec"], lang=lang)
