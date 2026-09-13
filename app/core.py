"""Analysekern von spectro.

Diese Datei führt die Module des Kerns zusammen und ist die Schnittstelle nach
außen: CLI, Web-Schicht und Tests sprechen ausschließlich `core` an. Der Code
selbst liegt nach Zuständigkeiten getrennt daneben:

    params   Parameter, Konstanten, Fehlerklasse
    audio    Dekodierung und Messwerte über ffmpeg
    stft     Kurzzeit-Fouriertransformation
    band     Bandkante, Bandbreite, Dauertöne
    render   Frequenzachsen und Spektrogramme
    compare  Ausrichtung, Differenz, Nullprobe, Residual
    measure  Tiefton, Gleichlauf, Frequenzgang, Impulsstörungen, Pegel
    report   zusammengesetzte Berichte

Die Fassade bleibt bewusst bestehen: sie hält die Aufrufstellen stabil und
erlaubt, Module später umzustellen, ohne CLI, API oder Tests anzufassen.
"""

from __future__ import annotations

from .audio import (  # noqa: F401
    _decode_mono,
    _decoder,
    _decoder_error,
    _run,
    loudness,
    probe,
    stereo_stats,
)
from .band import (  # noqa: F401
    EDGE_HINTS,
    LOSSLESS_CODECS,
    NEAR_NYQUIST,
    REFERENCE_NFFT,
    _smooth,
    band_analysis,
    band_energy,
    band_report,
    estimate_cutoff,
    signal_bandwidth,
    spectral_edge,
    tonal_peaks,
)
from .compare import (  # noqa: F401
    Panel,
    _bandpool,
    _colpool,
    _overlap,
    align_shift,
    build_panels,
    compare,
    null_residual,
    null_test,
)
from .measure import (  # noqa: F401
    NOMINAL_TONES,
    _analytic,
    _bandpass,
    _tone_steps,
    _welch,
    clipping_verdict,
    dynamics_note,
    impulse_scan,
    lowfreq_scan,
    tone_sweep,
    wow_flutter,
)
from .params import (  # noqa: F401
    ANALYSIS_VERSION,
    AUDIO_EXT,
    CHUNK_BYTES,
    CMAPS,
    EPS,
    THEMES,
    WINDOWS,
    AudioError,
    Params,
    plt_colormaps,
    set_language,)
from .render import (  # noqa: F401
    _fmt_time,
    _imel,
    _mel,
    pick_ticks,
    remap,
    render,
    resample_cols,
    target_freqs,
)
from .report import quickcheck, summary  # noqa: F401
from .band import to_db  # noqa: F401
from .stft import (  # noqa: F401
    Analysis,
    _channel_labels,
    _ChannelSTFT,
    analyse,
)
