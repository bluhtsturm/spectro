"""Parameter, Konstanten und die Fehlerklasse der Analyse.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import numpy as np

from .i18n import normalise, set_current as _set_lang


ANALYSIS_VERSION = 12

def set_language(lang: str) -> str:
    """Setzt die Sprache fuer Meldungen ausserhalb einer Analyse.

    Gilt fuer den laufenden Kontext - Anfrage, Task oder Thread -, nicht
    prozessweit: sonst wuerde eine gleichzeitige Anfrage in einer anderen
    Sprache die Meldungen dieser hier umstellen.
    """
    return _set_lang(lang)

CHUNK_BYTES = 1 << 20
EPS = 1e-12

WINDOWS = {
    "hann": np.hanning,
    "hamming": np.hamming,
    "blackman": np.blackman,
    "bartlett": np.bartlett,
    "rect": np.ones,
}

# Bewusst breit gehalten: alles, was ffmpeg dekodieren kann. Enthaelt auch
# Videocontainer (dann wird die erste Audiospur analysiert) und Playlists-lose
# Exoten wie Monkey's Audio, TAK, Shorten oder DSD.
AUDIO_EXT = {
    # verlustfrei / unkomprimiert
    "flac", "wav", "w64", "rf64", "aiff", "aif", "aifc", "caf", "au", "snd",
    "alac", "ape", "wv", "tta", "tak", "shn", "als", "mlp", "thd", "truehd",
    "dsf", "dff", "dsdiff", "bwf", "8svx", "voc", "sln", "pcm", "raw",
    # verlustbehaftet
    "mp3", "mp2", "mp1", "m4a", "m4b", "aac", "adts", "ogg", "oga", "opus",
    "spx", "vorbis", "wma", "asf", "ac3", "eac3", "dts", "dtshd", "amr",
    "awb", "gsm", "mpc", "mp+", "ra", "rm", "qcp", "aa", "aax", "sbc",
    # Container mit Audiospur
    "mka", "mkv", "mp4", "mov", "m4v", "webm", "avi", "ts", "m2ts", "mts",
    "vob", "flv", "3gp", "3g2", "wtv", "ogv", "mxf",
}

CMAPS = ["magma", "inferno", "viridis", "plasma", "turbo", "cividis",
         "gray", "bone", "afmhot", "nipy_spectral", "jet"]

THEMES = {
    "dark": {"bg": "#14161a", "fg": "#e6e8ec", "grid": "#ffffff"},
    "light": {"bg": "#ffffff", "fg": "#1a1a1a", "grid": "#000000"},
}


def plt_colormaps() -> set:
    """Alle in matplotlib verfuegbaren Colormap-Namen (fuer die Validierung)."""
    try:
        import matplotlib
        return set(matplotlib.colormaps)
    except Exception:
        return set(CMAPS)


# --------------------------------------------------------------------------


class AudioError(RuntimeError):
    pass


@dataclass
class Params:
    nfft: int = 2048
    overlap: float = 0.75
    window: str = "hann"
    channels: str = "mix"          # mix | left | right | mid | side | all
    scale: str = "linear"          # linear | log | mel
    fmin: float = 0.0
    fmax: float | None = None
    db_range: float = 100.0
    db_top: float = 0.0
    cmap: str = "magma"
    width: float = 14.0
    height: float = 5.0
    dpi: int = 110
    max_cols: int = 4000
    start: float | None = None
    duration: float | None = None
    sr: int | None = None
    raw: bool = False
    theme: str = "dark"
    lang: str = "de"               # Sprache der Bewertungstexte
    normalize: bool = True         # auf Spitzenpegel normieren
    diff_range: float = 24.0       # +/- dB im Differenzbild

    def validate(self) -> Params:
        if self.nfft < 32 or self.nfft & (self.nfft - 1):
            raise ValueError("nfft muss eine Zweierpotenz >= 32 sein")
        if not 0.0 <= self.overlap <= 0.95:
            raise ValueError("overlap muss zwischen 0 und 0.95 liegen")
        if self.window not in WINDOWS:
            raise ValueError(f"unbekanntes Fenster: {self.window}")
        if self.scale not in ("linear", "log", "mel"):
            raise ValueError(f"unbekannte Skala: {self.scale}")
        if self.channels not in ("mix", "left", "right", "mid", "side", "all"):
            raise ValueError(f"unbekannter Kanalmodus: {self.channels}")
        if not re.fullmatch(r"[A-Za-z0-9_]+", self.cmap):
            raise ValueError("ungueltige Colormap")
        if self.cmap not in CMAPS and self.cmap not in plt_colormaps():
            raise ValueError(f"unbekannte Colormap: {self.cmap}")
        if self.theme not in THEMES:
            raise ValueError(f"unbekanntes Theme: {self.theme}")
        self.lang = normalise(self.lang)
        self.max_cols = int(np.clip(self.max_cols, 100, 20000))
        self.dpi = int(np.clip(self.dpi, 40, 300))
        self.width = float(np.clip(self.width, 3, 60))
        self.height = float(np.clip(self.height, 2, 20))
        self.db_range = float(np.clip(self.db_range, 10, 200))
        self.diff_range = float(np.clip(self.diff_range, 1, 120))

        # Frequenzgrenzen zurechtruecken statt spaeter eine unlesbare Achse
        # zu zeichnen: negative Werte, vertauschte oder gleiche Grenzen
        self.fmin = max(0.0, float(self.fmin or 0.0))
        if self.fmax is not None:
            self.fmax = float(self.fmax)
            if self.fmax <= 0:
                self.fmax = None
        if self.fmax is not None:
            if self.fmax < self.fmin:
                self.fmin, self.fmax = self.fmax, self.fmin
            if self.fmax - self.fmin < 1.0:
                raise ValueError("fmin und fmax liegen zu dicht beieinander")

        if self.start is not None:
            self.start = max(0.0, float(self.start))
        if self.duration is not None:
            self.duration = float(self.duration)
            if self.duration <= 0:
                self.duration = None
        if self.sr is not None:
            self.sr = int(self.sr)
            if not 1000 <= self.sr <= 768000:
                raise ValueError("sr muss zwischen 1000 und 768000 Hz liegen")
        return self

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
