"""Zusammengesetzte Berichte über eine Datei.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations


from .audio import loudness, probe, stereo_stats
from .band import band_analysis, band_energy, band_report, tonal_peaks
from .measure import clipping_verdict, dynamics_note, lowfreq_scan
from .params import AudioError, Params
from .stft import analyse


def summary(path: str, p: Params, with_loudness: bool = True) -> dict:
    """Kompletter Analysebericht einer Datei (fuer API/CLI --json)."""
    a = analyse(path, p)
    mag = a.mags[0]
    band = band_report(path, p, mag, a.sr, a.info["codec"])
    rep = {
        "file": a.info,
        "analysed_duration": round(a.duration, 3),
        "columns": int(mag.shape[1]),
        "cutoff_hz": band["edge_hz"] or band["signal_bandwidth_hz"],
        "band": band,
        "tones": tonal_peaks(mag, a.sr, p.nfft),
        "verdict": band["verdict"],
        "bands": band_energy(mag, a.sr, p.nfft),
    }
    if with_loudness:
        try:
            rep["lowfreq"] = lowfreq_scan(path, p)
        except AudioError:
            pass
        loud = loudness(path, p.start, p.duration)
        # Bei verlustbehafteten Quellen liefert der Decoder Fliesskomma-Samples;
        # eine "genutzte Bittiefe" waere dort eine Eigenschaft des Decoders,
        # nicht der Datei - deshalb nur bei ganzzahligem PCM ausweisen.
        fmt = (a.info.get("sample_fmt") or "")
        if not fmt.startswith(("s16", "s32", "u8", "s64")):
            loud.pop("bit_depth_used", None)
            loud.pop("bit_depth_effective", None)
        else:
            loud["bit_depth_container"] = int(
                a.info.get("bits") or loud.get("bit_depth_effective") or 0) or None
        rep["loudness"] = loud
        st = stereo_stats(path, p)
        if st:
            rep["stereo"] = st
        clip = clipping_verdict(loud, a.info.get("duration") or a.duration, p.lang)
        if clip:
            rep["clipping"] = clip
        dyn = dynamics_note(loud, p.lang)
        if dyn:
            rep["dynamics"] = dyn
    return rep


def quickcheck(path: str, seconds: float = 60.0, nfft: int = 4096,
               lang: str = "de") -> dict:
    """Schnellpruefung fuer Sammlungs-Scans: Eckdaten, Bandbreite, Bewertung.

    Analysiert nur einen Ausschnitt aus der Mitte - das reicht fuer die
    Bandbreite und haelt den Durchsatz hoch.
    """
    info = probe(path)
    dur = info.get("duration") or 0.0
    start = max(0.0, (dur - seconds) / 2) if dur > seconds else None
    p = Params(nfft=nfft, overlap=0.5, max_cols=800, start=start,
               duration=min(seconds, dur) if dur else seconds, lang=lang)
    a = analyse(path, p)
    band = band_analysis(a.mags[0], a.sr, nfft, info["codec"], lang=lang)
    return {
        "name": info["name"], "codec": info["codec"],
        "sample_rate": info["sample_rate"], "channels": info["channels"],
        "bit_rate": info["bit_rate"], "duration": info["duration"],
        "size": info["size"],
        "cutoff_hz": band["edge_hz"] or band["signal_bandwidth_hz"],
        "edge_hz": band["edge_hz"], "pattern": band["pattern"],
        "verdict": band["verdict"],
    }
