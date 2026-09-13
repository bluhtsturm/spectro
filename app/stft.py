"""Kurzzeit-Fouriertransformation und Zeitraster.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .audio import _decoder, _decoder_error, probe
from .i18n import current as _current_lang
from .i18n import t
from .params import CHUNK_BYTES, WINDOWS, AudioError, Params


@dataclass
class _ChannelSTFT:
    """Inkrementelle STFT mit adaptivem Max-Pooling (konstanter Speicher)."""
    nfft: int
    hop: int
    window: np.ndarray
    max_cols: int
    buf: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    cols: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    pool: int = 1

    def feed(self, samples: np.ndarray) -> None:
        self.buf = np.concatenate((self.buf, samples)) if self.buf.size else samples
        if self.buf.size < self.nfft:
            return
        n = 1 + (self.buf.size - self.nfft) // self.hop
        view = np.lib.stride_tricks.sliding_window_view(self.buf, self.nfft)[::self.hop][:n]
        spec = np.abs(np.fft.rfft(view * self.window, axis=1)).astype(np.float32)
        self.buf = self.buf[n * self.hop:].copy()
        for row in spec:
            self._push(row)

    def _push(self, row: np.ndarray) -> None:
        self.pending.append(row)
        if len(self.pending) >= self.pool:
            self.cols.append(np.maximum.reduce(self.pending))
            self.pending.clear()
            if len(self.cols) >= 2 * self.max_cols:
                arr = np.array(self.cols)
                if arr.shape[0] % 2:
                    arr = arr[:-1]
                self.cols = list(np.maximum(arr[0::2], arr[1::2]))
                self.pool *= 2

    def finish(self) -> np.ndarray:
        if self.pending:
            self.cols.append(np.maximum.reduce(self.pending))
            self.pending.clear()
        if not self.cols:
            return np.zeros((self.nfft // 2 + 1, 1), dtype=np.float32)
        return np.array(self.cols, dtype=np.float32).T  # (bins, frames)


@dataclass
class Analysis:
    mags: list           # je Kanal: (bins, frames) Magnituden
    sr: int
    duration: float      # tatsaechlich analysierte Laenge in Sekunden
    t0: float            # Startzeit im Original
    info: dict
    labels: list


def analyse(path: str, p: Params) -> Analysis:
    """Dekodiert die Datei streamend und liefert die STFT-Magnituden."""
    p.validate()
    info = probe(path)
    sr = int(p.sr or info["sample_rate"])
    src_ch = info["channels"]

    if p.channels == "all":
        n_out, stream_ch = src_ch, src_ch
        labels = _channel_labels(info, src_ch, p.lang)
    elif p.channels in ("left", "right", "mid", "side") and src_ch >= 2:
        n_out, stream_ch = 1, src_ch
        labels = [t(f"ch.{p.channels}", p.lang)]
    else:
        n_out, stream_ch = 1, 1
        labels = [t("ch.mono_sum" if src_ch > 1 else "ch.mono", p.lang)]

    win = WINDOWS[p.window](p.nfft).astype(np.float32)
    hop = max(1, int(round(p.nfft * (1.0 - p.overlap))))
    engines = [_ChannelSTFT(p.nfft, hop, win, p.max_cols) for _ in range(n_out)]

    proc = _decoder(path, sr, stream_ch, p.start, p.duration)
    total = 0
    tail = b""
    frame = 4 * stream_ch
    try:
        while True:
            chunk = proc.stdout.read(CHUNK_BYTES)
            if not chunk:
                break
            chunk = tail + chunk
            usable = len(chunk) - (len(chunk) % frame)
            tail = chunk[usable:]
            block = np.frombuffer(chunk[:usable], dtype=np.float32)
            if stream_ch > 1:
                block = block.reshape(-1, stream_ch)
                total += block.shape[0]
                if p.channels == "all":
                    for i, eng in enumerate(engines):
                        eng.feed(np.ascontiguousarray(block[:, i]))
                elif p.channels == "left":
                    engines[0].feed(np.ascontiguousarray(block[:, 0]))
                elif p.channels == "right":
                    engines[0].feed(np.ascontiguousarray(block[:, 1]))
                elif p.channels == "mid":
                    engines[0].feed(((block[:, 0] + block[:, 1]) * 0.5).astype(np.float32))
                elif p.channels == "side":
                    engines[0].feed(((block[:, 0] - block[:, 1]) * 0.5).astype(np.float32))
                else:
                    engines[0].feed(block.mean(axis=1).astype(np.float32))
            else:
                total += block.size
                engines[0].feed(block)
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()
        err = _decoder_error(proc)

    if proc.returncode not in (0, None) and total == 0:
        raise AudioError(f"ffmpeg: {err[:400]}")
    if total == 0:
        raise AudioError(t("err.no_samples", _current_lang()))

    return Analysis([e.finish() for e in engines], sr, total / sr,
                    float(p.start or 0.0), info, labels)


def _channel_labels(info: dict, n: int, lang: str = "de") -> list:
    layout = (info.get("channel_layout") or "").lower()
    if n == 2:
        return [t("ch.left", lang), t("ch.right", lang)]
    if "5.1" in layout and n == 6:
        return ["L", "R", "C", "LFE", "Ls", "Rs"]
    if "7.1" in layout and n == 8:
        return ["L", "R", "C", "LFE", "Ls", "Rs", "Lb", "Rb"]
    return [t("ch.n", lang, n=i + 1) for i in range(n)]


# --------------------------------------------------------------------------
