"""Gemeinsame Fixtures.

Alle Prüfsignale werden mit ffmpeg erzeugt, nichts davon liegt im Repository.
Das hält es klein, vermeidet Urheberrechtsfragen und macht nachvollziehbar,
welche Eigenschaft ein Testfall eigentlich prüft.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import core  # noqa: E402,F401

SR = 44100


def ff(args: list[str]) -> None:
    cp = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[:500])


def write_pcm(path: Path, x: np.ndarray, sr: int, channels: int = 1,
              sample_fmt: str = "s16", bits: int | None = None) -> Path:
    """Schreibt ein numpy-Array als FLAC."""
    raw = np.clip(x, -1.0, 1.0).astype(np.float32).tobytes()
    args = ["-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
            "-c:a", "flac", "-sample_fmt", sample_fmt]
    if bits:
        args += ["-bits_per_raw_sample", str(bits)]
    args += [str(path)]
    cp = subprocess.run(["ffmpeg", "-v", "error", "-y", *args],
                        input=raw, capture_output=True)
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.decode(errors="replace")[:500])
    return path


def noise(n: int, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 0.05, n).astype(np.float32)


def tone(n: int, f: float, sr: int = SR, amp: float = 0.2) -> np.ndarray:
    t = np.arange(n) / sr
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


# --------------------------------------------------------------------------
# Vollband, verlustfrei
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fullband(media) -> Path:
    """Rauschen plus Ton, Inhalt bis zur Nyquist-Frequenz."""
    p = media / "fullband.flac"
    if not p.exists():
        n = SR * 8
        x = noise(n) + tone(n, 440) + tone(n, 8000, amp=0.05)
        write_pcm(p, x, SR)
    return p


@pytest.fixture(scope="session")
def lossy(media, fullband) -> Path:
    """Aus derselben Quelle als MP3 mit 128 kbit/s: harte Kante um 16 kHz."""
    p = media / "lossy.mp3"
    if not p.exists():
        # 64 kbit/s: die Bandbegrenzung liegt deutlich unter der Nyquist-
        # Frequenz und ist damit als Encoder-Tiefpass erkennbar
        ff(["-i", str(fullband), "-b:a", "64k", str(p)])
    return p


@pytest.fixture(scope="session")
def upsampled(media) -> Path:
    """Mit 48 kHz erzeugt, auf 96 kHz hochgerechnet - Stoppband bei 24 kHz."""
    p = media / "upsampled.flac"
    if not p.exists():
        src = media / "_src48.flac"
        n = 48000 * 8
        write_pcm(src, noise(n, seed=3) + tone(n, 1000, sr=48000), 48000)
        # scharfer Resampler: bildet die Bandgrenze so ab, wie sie in echten
        # hochgerechneten Dateien aussieht
        ff(["-i", str(src), "-af", "aresample=96000:resampler=soxr:precision=28",
            "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(p)])
    return p


@pytest.fixture(scope="session")
def analog_rolloff(media) -> Path:
    """Weicher Höhenabfall wie bei Band und Schallplatte.

    Der wichtigste Fehlalarm-Testfall: fällt die Steilheitsprüfung weg, wird
    dieses Signal als verlustbehafteter Transcode gemeldet.
    """
    p = media / "analog.flac"
    if not p.exists():
        src = media / "_analog_src.flac"
        n = 48000 * 10
        write_pcm(src, noise(n, seed=5) * 3, 48000)
        ff(["-i", str(src), "-af", "lowpass=f=6000:poles=2",
            "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(p)])
    return p


# --------------------------------------------------------------------------
# Störungen
# --------------------------------------------------------------------------

CLICK_TIMES = [1.0, 2.5, 3.25, 5.0, 6.75]


def _brickwall(media: Path, zwischenrate: int, ziel: Path, seed: int) -> None:
    """Erzeugt eine echte Steilkante bei zwischenrate/2.

    Über einen Tiefpass geht das nicht: ffmpegs `lowpass` fällt so weich ab,
    dass die steilste Stelle weit über der Eckfrequenz liegt. Ein Umweg über
    eine niedrigere Abtastrate liefert dagegen genau die Brickwall, die auch
    ein Encoder oder ein Wandler hinterlässt.
    """
    src = media / f"_bw{zwischenrate}_src.flac"
    zwischen = media / f"_bw{zwischenrate}_mid.flac"
    write_pcm(src, noise(SR * 8, seed=seed) * 3, SR)
    ff(["-i", str(src), "-af",
        f"aresample={zwischenrate}:resampler=soxr:precision=28", str(zwischen)])
    ff(["-i", str(zwischen), "-af",
        f"aresample={SR}:resampler=soxr:precision=28", str(ziel)])


@pytest.fixture(scope="session")
def brickwall_20k(media) -> Path:
    """Steilkante bei 20 kHz - 91 % der Nyquist-Frequenz.

    So sieht ein Encoder-Tiefpass mit hoher Bitrate aus. An einer echten
    Encoder-Leiter gemessen lagen alle zwischen 72 und 91 %.
    """
    p = media / "brickwall20k.flac"
    if not p.exists():
        _brickwall(media, 40000, p, seed=41)
    return p


@pytest.fixture(scope="session")
def antialias(media) -> Path:
    """Kante bei 21,5 kHz - 97 % der Nyquist-Frequenz.

    Das ist das Antialiasing-Filter eines Wandlers und darf nicht als
    Bandbegrenzung gelten. Gemessen an einem 48-kHz-Wandler: 97 %.
    """
    p = media / "antialias.flac"
    if not p.exists():
        _brickwall(media, 43000, p, seed=43)
    return p


@pytest.fixture(scope="session")
def clicks(media) -> Path:
    """Rauschteppich mit fünf Impulsen an bekannten Zeitpunkten."""
    p = media / "clicks.flac"
    if not p.exists():
        n = SR * 8
        # Rauschteppich bewusst leise: die Impulse liegen damit rund 24 dB
        # darueber, wie die kraeftigen Knackser einer Schallplatte
        x = noise(n, seed=7) * 0.2 + tone(n, 300, amp=0.15)
        for t in CLICK_TIMES:
            i = int(t * SR)
            x[i:i + 3] += np.array([0.9, -0.75, 0.55], dtype=np.float32)
        write_pcm(p, x, SR)
    return p


@pytest.fixture(scope="session")
def hum(media) -> Path:
    """Programm mit kräftigem 50-Hz-Brumm samt Oberwellen."""
    p = media / "hum.flac"
    if not p.exists():
        n = SR * 10
        x = noise(n, seed=11) + tone(n, 700, amp=0.15)
        for k, amp in ((1, 0.02), (2, 0.008), (3, 0.012)):
            x = x + tone(n, 50.0 * k, amp=amp)
        write_pcm(p, x, SR)
    return p


def _saegezahn(n: int, f: float, sr: int = SR, amp: float = 0.5) -> np.ndarray:
    """Sägezahn: alle Harmonischen, wie sie echter Netzbrumm zeigt."""
    t = np.arange(n) / sr
    return (amp * 2 * (t * f - np.floor(0.5 + t * f))).astype(np.float32)


@pytest.fixture(scope="session")
def hum60(media) -> Path:
    """Programm mit 60-Hz-Brumm - die Erkennung muss 60 von 50 Hz trennen."""
    p = media / "hum60.flac"
    if not p.exists():
        n = SR * 12
        x = noise(n, seed=53) * 0.05 + tone(n, 900, amp=0.1)
        x = x + _saegezahn(n, 60.0, amp=0.03)
        write_pcm(p, x, SR)
    return p


@pytest.fixture(scope="session")
def rumble(media) -> Path:
    """Programm mit starkem Tiefstton unter 20 Hz."""
    p = media / "rumble.flac"
    if not p.exists():
        n = SR * 10
        x = noise(n, seed=13) * 0.3 + tone(n, 1000, amp=0.1) + tone(n, 8.0, amp=0.5)
        write_pcm(p, x, SR)
    return p


@pytest.fixture(scope="session")
def silence(media) -> Path:
    """Nahezu still - darf weder Brumm noch Rumpeln melden."""
    p = media / "silence.flac"
    if not p.exists():
        n = SR * 6
        write_pcm(p, noise(n, seed=17) * 1e-7, SR)   # quantisiert zu digitaler Null
    return p


# --------------------------------------------------------------------------
# Bittiefe
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def uebersteuert(media) -> Path:
    """Ein Master, das an der Vollaussteuerung klebt.

    Nachgebaut nach einer echten Aufnahme aus der Lautheitskrieg-Ära: dort
    lagen 151 Samples je Minute an der Vollaussteuerung und der Flat factor bei
    0,99, während zwölf andere Aufnahmen - darunter zwei ebenfalls sehr laute -
    ausnahmslos 0,0 zeigten.
    """
    p = media / "uebersteuert.flac"
    if not p.exists():
        n = SR * 20
        x = (noise(n, seed=59) * 6 + tone(n, 220, amp=0.9)
             + tone(n, 55, amp=0.9)).astype(np.float32)
        write_pcm(p, np.clip(x, -1.0, 1.0), SR)
    return p


@pytest.fixture(scope="session")
def fake24(media, fullband) -> Path:
    """16-bit-Inhalt in einer 24-bit-Hülle."""
    p = media / "fake24.flac"
    if not p.exists():
        tmp = media / "_16.flac"
        ff(["-i", str(fullband), "-sample_fmt", "s16", str(tmp)])
        ff(["-i", str(tmp), "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(p)])
    return p


@pytest.fixture(scope="session")
def quiet24(media) -> Path:
    """Echte, aber leise 24-bit-Aufnahme - darf nicht als hochgerechnet gelten."""
    p = media / "quiet24.flac"
    if not p.exists():
        n = SR * 6
        write_pcm(p, noise(n, seed=19) * 0.02, SR, sample_fmt="s32", bits=24)
    return p


# --------------------------------------------------------------------------
# Paare für Vergleich, Nullprobe und Residual
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def declicked(media, clicks) -> Path:
    """Dieselbe Aufnahme, Impulse entfernt."""
    p = media / "declicked.flac"
    if not p.exists():
        ff(["-i", str(clicks), "-af", "adeclick=threshold=2", str(p)])
    return p


@pytest.fixture(scope="session")
def delayed(media, fullband) -> Path:
    """Um 250 ms verzögerte Fassung - für den Versatzausgleich."""
    p = media / "delayed.flac"
    if not p.exists():
        ff(["-i", str(fullband), "-af", "adelay=250:all=1", str(p)])
    return p


@pytest.fixture(scope="session")
def longer(media) -> Path:
    """Deutlich längere Datei: erzwingt ein anderes Spalten-Pooling."""
    p = media / "longer.flac"
    if not p.exists():
        n = SR * 200
        write_pcm(p, noise(n, seed=23) + tone(n, 440), SR)
    return p


@pytest.fixture(scope="session")
def unrelated(media) -> Path:
    p = media / "unrelated.flac"
    if not p.exists():
        n = SR * 8
        write_pcm(p, noise(n, seed=101) + tone(n, 617, amp=0.3), SR)
    return p


@pytest.fixture(scope="session")
def broken(media) -> Path:
    """Kaputte Datei: muss sauber als AudioError enden, nicht blockieren."""
    p = media / "broken.flac"
    if not p.exists():
        p.write_bytes(b"fLaC" + bytes(np.random.default_rng(29)
                                      .integers(0, 256, 8000, dtype=np.uint8)))
    return p
