# Calibration

This document records **why** the thresholds in `app/core.py` are what they are,
and which false conclusions lie behind them. Anyone wanting to change a number
will find here the measurements that led to it — and in `tests/` the cases that
must not break in the process.

*[Deutsche Fassung](CALIBRATION.de.md)*

All values come from measurements on real recordings: rips from record and tape
(44.1/48/96 kHz, 16 and 24 bit), idle recordings of the capture chain, and a
FLAC file demonstrably produced from an MP3. The recordings themselves are not
in the repository for copyright reasons; the test suite generates its own test
signals with ffmpeg.

---

## 1. Band edge: steepness, not level drop

**The rule.** A band limit is only reported when the spectrum drops by at least
15 dB **and** that drop is steeper than 10 dB/kHz (`spectral_edge`, `min_drop`,
`min_steepness`).

**Why.** The first approach looked for the point where energy had fallen 50 dB
below the maximum. That measures the recording's high-frequency rolloff, not the
chain's band limit — and it got every single real case wrong: tape recordings
were reported as "possible transcode", while a file actually produced from an
MP3 passed as "full band, consistent with lossless".

Steepness measured at the location of the edge:

| Material | dB/kHz |
|---|---|
| encoder lowpass (MP3 128k, AAC 96k) | 45–80 |
| resampler and converter filters | 11–18 |
| high-frequency rolloff of record and tape | 3–6 |

The threshold of 10 dB/kHz separates the upper two groups from the lower one.
An encoder ladder (section 11) later confirmed this across ten versions from a
single source: 36 to 60 dB/kHz.
After it was introduced, not a single false positive remained across 13 real
files.

**Traps.**

- *A quiet spot in a groove looks like an edge.* In calm sections of a run-out
  groove the high-frequency part of the groove noise sinks far enough that a
  pure level comparison finds a drop of more than 15 dB. Only the steepness
  tells that apart from a filter.
- *An ideal brick wall is located too low.* Searching for the largest distance
  between "just below" and "above" lands up to 2 kHz too low when the drop is
  very steep, because the upper comparison window already sits entirely in the
  stopband. The steepness would then be measured at a still-flat spot and the
  edge would fail its own check. That is why the coarse search is followed by a
  refinement at the steepest gradient (`test_steilabfall_wird_erkannt`).

---

## 2. A wandering band edge proves **nothing**

**The rule.** If the edge moves between time sections, that is reported but not
treated as a finding (`pattern = "vereinzelt"`, level `ok`).

**Why.** For a while an edge appearing in some sections counted as the
fingerprint of an encoder discarding highs in quiet passages. The numbers
refute it:

| File | sections with an edge (nfft 8192) |
|---|---|
| demonstrably from MP3 | 3 of 16 |
| run-out groove, real record | 6 of 16 |
| lead-in groove, real record | 9 of 16 |

The real record scored "more suspicious" than the real transcode. The earlier
detection rested entirely on where the threshold sat — on a collection of
analogue rips it would have produced false alarms in droves.

**What also did not work.** MP3 works in granules of 1152 samples, which at
44.1 kHz would correspond to a modulation at 38.28 Hz. Nothing of that shows in
the spectral flux: peaks sat between 5 and 10 dB above their surroundings for
every file, plain FLAC included.

**Consequence for the wording.** A missing edge does **not** prove a file is
lossless. Encoders running at high bitrates without a lowpass leave no spectral
trace. The verdict text says so explicitly.

---

## 3. Upsampled files: the stopband is what counts

**The rule.** The source rate is not derived from the edge but from the point
where the spectrum has fallen 40 dB below the level at the edge. That point is
compared against 22.05 / 24 / 44.1 kHz (± 1.8 kHz).

**Why.** The edge sits in the filter's transition band, well below the source's
Nyquist frequency. For 96 kHz files with a 48 kHz source it lands at
22.2–22.8 kHz and was therefore wrongly reported as a 44.1 kHz source (Nyquist
22.05 kHz).

Comparison of definitions on four real 96 kHz files with a known 48 kHz source
(so the true limit is 24.0 kHz):

| Definition | measured values |
|---|---|
| noise floor + 6 dB | 23.20 / 23.45 / 24.46 / 24.70 kHz |
| noise floor + 20 dB | 22.36 / 22.73 / 23.96 / 24.30 kHz |
| **40 dB below the edge level** | **24.07 / 24.21 / 24.29 / 24.35 kHz** |

Only the last definition hits the true limit within ±0.4 kHz. The other two
scatter by more than a kilohertz and depend on how deep the file's noise floor
happens to be.

**Trap.** The check runs on the whole-file spectrum, not per section. In quiet
passages the drop does not reach the threshold — otherwise, of two recordings
from the same chain, one got a warning and the other did not.

---

## 4. Bit depth: the second value, not the first

**The rule.** `astats` reports "Bit depth: A/B". What is evaluated is **B**
(bits excluding constantly zeroed low bits), compared with the depth declared by
the container. A difference of 2 bits or more counts as upsampled.

**Why.** A depends on how hard the material is driven. Measured:

| File | A/B | ffprobe | Verdict |
|---|---|---|---|
| genuine 16-bit file | 12/16 | 16 | fine |
| 16-bit content in a 24-bit shell | 12/16 | 24 | upsampled |
| loud genuine 24-bit recording | 23/24 | 24 | fine |
| **quiet genuine 24-bit recording** | **16/24** | 24 | **fine** |

The first version evaluated A and would have reported every quiet 24-bit
recording as upsampled.

**Two further traps.**

- *The filter chain corrupts the measurement.* `ebur128` works internally at
  double precision. With `astats` behind it in the same chain, it measures the
  converted samples and reports nonsense — observed was "40 of 44 bit" instead
  of the correct 20 of 24. An `asplit` separates the branches.
- *For lossy sources the value is meaningless*, because the decoder delivers
  floating point. It is not reported there.

---

## 5. Impulse scan: the bass counter-check

**The rule.** An event counts when the high-frequency envelope (from 6 kHz)
exceeds its local background by 14 dB, lasts at most 6 ms, **and** the bass
follows by at least 6 dB less.

**Why the counter-check.** Without it every drum hit counts as a click. Event
rates per minute:

| Material | without counter-check | with counter-check |
|---|---|---|
| lead-in groove, record | 132.6 | 124.3 |
| click passage, record | 115.8 | 112.4 |
| tape recording | 12.6 | 10.6 |
| digital music (false-positive reference) | 1.2 | 1.0 |

Detection loses about 3 % on real material and pushes false hits down to roughly
one per minute.

**Background as a block median.** The local background is formed over blocks of
0.5 seconds and connected linearly. A running median would be cleaner but costs
several times the computation; the block variant processes a five-minute
recording in a little over two seconds.

**Limit.** What the scan finds is a suggestion to listen to. The timestamps can
be clicked in the interface; they zoom the spectrogram to the spot.

---

## 6. Low end: absolute level alongside the ratio

**The rule.** A rumble warning needs both: content below 20 Hz less than 12 dB
under the overall level **and** above −55 dBFS in absolute terms. Hum peaks are
only considered from −95 dBFS upwards.

**Why.** In a silent recording the sub-bass inevitably sits close to the overall
level, because both are the noise floor. Without the absolute threshold an idle
recording at −82 dBFS produced a rumble warning. Likewise, a −110 dBFS artefact
in a silent recording appeared in the report as "mains hum".

**Its own resolution.** The analysis downsamples to 4 kHz and works with 16k
windows, so 0.24 Hz per bin. At the resolution of the image analysis (23 Hz at
48 kHz) 50 Hz and 60 Hz could not be told apart.

**A trap from practice.** A first measurement showed 30 dB of rumble with the
turntable running. On checking, that came from **one** impulse (lowering the
stylus); the median was at −75 dBFS. That is why the evaluation works throughout
with medians over time windows, not means.

---

## 7. Steady tones: four conditions at once

**The rule.** A tone counts as interference when it is narrow (at most 60 Hz at
−6 dB), quiet relative to the programme (at least 30 dB below the maximum),
louder than −95 dB (below that they are quantisation artefacts), and present at
the same place in at least 80 % of the time sections.

**Why all four.** With only two conditions the check reported held musical notes
around 1 kHz. The −95 dB floor additionally removed artefacts above the band
limit of lossy files, which sat between −108 and −125 dB.

**What it is good for.** On a real chain the check found a tone at 19.37 kHz
present in recordings from both turntable *and* tape deck, but not when no
device was running — so an interference from the capture environment, not from
the medium.

---

## 8. Residual: crest alone is not enough

**The rule.** The difference of two versions is formed after alignment and level
matching and judged by four figures: crest relative to the original, the share
in quiet and in loud sections, and the correlation of the spectral shape with
the programme.

**Why not crest alone.** Measured on restorations:

| Processing | crest of the residual | crest of the source |
|---|---|---|
| declicking only | 48 dB | 20 dB |
| noise reduction | 38 dB | 20 dB |

The distance separates the two cases but says nothing about *what* a noise
reduction removed. That needs the shape: if the spectral profile of what was
removed follows the programme (r > 0.8), it is not merely a noise floor
disappearing. On a real restoration chain r = 0.93 to 0.98 was measured, with a
residual 8 to 12 dB below the original in the music passages.

**What the matching can and cannot do.** A constant level difference is
completely factored out. Beyond that it was tested how much an optimal linear
filter, a per-frame level match and a per-band per-frame match explain
additionally:

| Matching | residual |
|---|---|
| constant level | −10.4 dB |
| optimal linear filter | −12.8 dB |
| level per time frame | −11.1 dB |
| filter per band and time frame | −11.2 dB |

So the difference was neither equalisation nor dynamics. For comparison: plain
declicking of the same recording gives −29 dB. The more elaborate matchings are
not in the program, because in this measurement they contributed almost nothing.

---

## 9. Aligning two recordings

**The rule.** Coarse-to-fine search directly on the spectral distance, capped at
a quarter of the shorter recording, with at least 70 % overlap and a slight
preference for small offsets.

**Why not envelope cross-correlation.** With uniform material (noise, steady
tones, groove noise) it goes astray: in a test with an artificial offset of
430 ms it returned 4.3 seconds — worse than no alignment at all. The
coarse-to-fine search found the offset exactly and dropped the residual from
15.7 to 0.6 dB.

**Why the cap.** Without it the search shifted by several seconds on periodic
material (loops, tremolo), because there a completely wrong offset also fits
well.

---

## 10. Comparing files of different length

The column pooling works in powers of two. Files of different length therefore
get different time grids — measured were 10.67 ms against 42.67 ms per column.
Without alignment the difference view compared different points in time. The
finer side is therefore brought onto the coarser grid.

---

## 11. Encoder ladder: what a band edge reveals — and what it does not

All versions come from **one** lossless source, encoded in a single pass. What
was measured is the edge in the whole-file spectrum:

| Version | Edge | % Nyquist | Steepness | detected |
|---|---|---|---|---|
| MP3 128 | 15.95 kHz | 72 % | 55 dB/kHz | yes |
| MP3 192 | 16.00 kHz | 73 % | 36 dB/kHz | yes |
| MP3 256 | 19.11 kHz | 87 % | 37 dB/kHz | yes |
| MP3 320 | 20.14 kHz | 91 % | 59 dB/kHz | yes |
| MP3 V0 | – | – | – | **no** |
| AAC 128 | 19.93 kHz | 90 % | 59 dB/kHz | yes |
| AAC 256 | – | – | – | **no** |
| Opus 96 | 20.48 kHz | 85 % | 59 dB/kHz | yes |
| Opus 192 | 20.46 kHz | 85 % | 60 dB/kHz | yes |
| Vorbis q6 | 19.94 kHz | 90 % | 45 dB/kHz | yes |
| source (FLAC) | – | – | – | – (correct) |

**First conclusion: the frequency names no bitrate.** 128 and 192 kbit/s sit
50 Hz apart; around 20 kHz MP3 320, AAC 128, Vorbis and Opus all meet. The
earlier lookup table came from literature values and would have reported
MP3 128 as "around 160 kbit/s". It was replaced by three coarse ranges that
only distinguish low, medium and high bitrate and state explicitly that format
and rate remain open.

**Second conclusion: the "near Nyquist" threshold sat too low.** It was at 90 %
and thereby cut off MP3 320 (91 %), AAC 128 (90 %) and Vorbis (90 %). The
anti-aliasing filter of a 48 kHz converter, by contrast, measures at 97 %. The
threshold now sits at **94 %**, with roughly three percentage points of margin
on either side. Detection across the ladder rose from five to eight out of ten,
without any analogue recording newly triggering.

**Third conclusion: the whole file decides.** MP3 320 showed the edge in only
2 of 16 sections, AAC 128 in none at all — in the whole-file spectrum it was
unmistakable in both. The section-wise evaluation now only serves as additional
information.

**The remaining gap is measured, not assumed.** MP3 V0 and AAC 256 have no band
limit: their spectrum follows the source up to 22 kHz. With this material the
source had little to offer above 19 kHz anyway (already 60 dB below maximum
there), so the encoders had nothing to cut. Such files cannot be identified as
lossy from the spectrum — the verdict says so explicitly.

### Cross-check with a second ladder

The same ten versions, produced from a **different** source:

| Version | Ladder 1 | Ladder 2 |
|---|---|---|
| MP3 128 | 15.95 kHz | 15.97 kHz |
| MP3 192 | 16.00 kHz | **18.11 kHz** |
| MP3 256 | 19.11 kHz | 19.40 kHz |
| MP3 320 | 20.14 kHz | 20.07 kHz |
| MP3 V0 | **none** | **20.19 kHz** |
| AAC 128 | 19.93 kHz | 19.91 kHz |
| AAC 256 | none | none |
| Opus 96 | 20.48 kHz | 20.38 kHz |
| Opus 192 | 20.46 kHz | 19.97 kHz |
| Vorbis q6 | 19.94 kHz | 18.97 kHz |
| detected | 8 of 10 | 9 of 10 |

**MP3 192 differs by 2.1 kHz at the same setting** — which does not merely
confirm the statement in section 11 but sharpens it: the band limit depends on
the material as much as on the bitrate. An encoder lowers it when the programme
offers nothing up there.

**MP3 V0 was detected in ladder 2 but not in ladder 1.** So the blind spot is
not the encoder but the source: if it already carried little above 19 kHz, the
encoder had nothing to cut and no edge remains to find.

**AAC 256 went undetected in both ladders.** In ladder 2 it shows an edge at
21.4 kHz, that is 96.9 % of the Nyquist frequency — exactly where a converter's
anti-aliasing filter sits too (measured 96.6 %). At that position the two
cannot be told apart; a higher threshold would report every native recording as
a transcode. That is a limit in principle, not a matter of settings.

### Resolution must not decide the verdict

The cross-check revealed that the same file was judged differently depending on
the FFT size:

| File | nfft 1024 | 2048 | 4096 | 8192 | 16384 |
|---|---|---|---|---|---|
| MP3 V0 (ladder 2) | 20.16 k | 20.16 k | 20.19 k | 20.80 k | 21.50 k |
| Vorbis q6 (ladder 2) | 18.78 k | 18.76 k | 18.97 k | 20.69 k | 21.21 k |

Both flipped from "constant band edge" to "no steep drop" at 8192 or 16384,
because the edge wandered past the 94 percent threshold. The cause is the
measurement itself: with a long window the noise floor lies lower, the
transition stretches further, and the steepest point sits higher. Neither a
level-based edge definition nor averaging bins down to a coarser grid
compensated for it — the differences are physical, not numerical.

The band analysis therefore always judges at **nfft 4096**, regardless of the
size chosen for display. If the setting matches, the existing spectrum is used;
otherwise a dedicated analysis runs. That costs 0.8 seconds on a five-minute
file and makes the verdict reproducible.

### Lossless oddities

The same material as WAV, ALAC, WavPack and Monkey's Audio — the decoded tracks
have identical checksums. All four reports agree in every field, and the null
test against the WAV reference gives −221.69 dB. Decoding path and evaluation
of the container metadata therefore treat the formats alike.

In the process it became clear that the pattern **"occasional edge" never said
anything.** Since the whole file decides the band limit (section 11), it only
appeared where the whole-file spectrum shows no edge at all — across 41 files
checked, exclusively for this clean lossless sample, in 4 of 16 sections at
12.8 kHz. Individual sections of a recording satisfy the edge condition purely
by chance. The classification was therefore dropped; the section counts remain
in the report as a metric.

### Mains hum: sensitivity depends on the programme, not on a fixed level

Tested with a sawtooth — the same waveform real mains hum shows, so with all
harmonics — mixed under hum-free programme:

| Mixing level | Level of the peak | detected |
|---|---|---|
| −30 dB | −40 dBFS | yes, mains frequency identified correctly |
| −45 dB | −53 dBFS | no |
| −60 dB and quieter | – | no |

That looks strict but is right: in the programme the region around 50 to 60 Hz
already sits at −57 dBFS, so hum at −53 dBFS barely rises above its own
surroundings (prominence 0 dB) and is neither measurable nor audible. For
comparison a real lead-in groove: there the hum sits at −71 dBFS while the
groove noise beside it sits at −93 dBFS — prominence 21 dB, easily found.

**What matters is therefore the distance to the local background, not the
absolute level.** The threshold of 8 dB prominence stands unchanged; quiet hum
under strong bass goes undetected because it genuinely disappears there.

On this occasion it emerged that `mains_hz` named a frequency even when no peak
had been found at all — that value was guesswork. It is now empty as long as
nothing was found.

### Clipping: flat factor and peak rate, not true peak

Measured on a master from the loudness-war era against eleven other
recordings:

| Recording | LUFS | True peak | Flat factor | Peaks per minute |
|---|---|---|---|---|
| loudness-war master | −7.4 | +0.4 dBTP | **0.99** | **151** |
| loud source material 1 | −4.6 | +1.9 dBTP | 0.0 | 1.5 |
| loud source material 2 | −7.7 | +0.1 dBTP | 0.0 | 8.5 |
| MP3 320 of the same source | −4.6 | +2.0 dBTP | 0.0 | 0.4 |
| tape | −14.7 | −1.2 dBTP | 0.0 | 0.2 |
| lead-in groove | −40.8 | −9.8 dBTP | 0.0 | 0.4 |

**True peak alone is no criterion.** It exceeded full scale in five of twelve
recordings, among them clean but merely loud versions — one at +2.0 dBTP
without the master being flattened at all. It is therefore only reported as a
milder note.

**Flat factor and peak rate separate cleanly:** zero against 0.99, and 0.4 to
8.5 against 151 per minute. Together they trigger the warning.

What is counted is the rate per minute, not the absolute number — a long
recording inevitably accumulates more peaks otherwise.

**An anchor to the level is required.** In digital silence every sample sits at
the signal's extreme, so `astats` counts each one as a peak: 2.6 million per
minute for an empty file. The assessment therefore also requires a peak level
above −1 dBFS.

Incidentally a known effect showed up on real material: the same source rose
from +1.9 to +2.0 dBTP through MP3 encoding.

### Mains hum versus musical bass: the prominence threshold sat too low

A commercial master from the loudness-war era pushed the check into a false
verdict: it reported "mains hum at 60 Hz and its harmonics, strongest at
180 Hz". That was in fact a bass component of the music. The comparison across
eleven recordings:

| Recording | Candidate | Prominence |
|---|---|---|
| turntable idling (hum confirmed) | 50 Hz | 39.5 dB |
| lead-in groove (hum confirmed) | 50 Hz | 23.7 dB |
| vinyl rip with music (hum confirmed) | 50 Hz | 15.9 dB |
| **pop master** | 180 Hz | **9.9 dB** |
| **loud source material** | 60 Hz | **10.1 dB** |
| **CD sample** | 240 Hz | **9.7 dB** |
| tape deck idling | 150 Hz | 9.8 dB |

The groups separate cleanly between 10.1 and 15.9 dB. The threshold now sits at
**14 dB** instead of 8. Time constancy was no use here: the master's 180 Hz
component was present in all eight time sections, exactly like real hum.

The price is lower sensitivity. In the mixing test of the previous section a
hum added at −40 dBFS had a prominence of 10.3 dB — it would no longer be
reported. That is the right call: at 10 dB prominence hum cannot be told apart
from music, and a warning on every pop master would be worthless.

### Limited is not clipped

A second example from the loudness-war era sat even higher than the first at
−4.9 LUFS with a crest factor of 8.6 dB — yet showed a flat factor of 0.0 and a
single sample at full scale. So the master is hard-limited, not clipped, and
the clipping check rightly stayed silent.

That left the program saying nothing at all about an obviously squashed master.
Comparing ten recordings gives a clean separation:

| Group | Crest factor | Loudness |
|---|---|---|
| loud masters | 7.6 – 12.2 dB | −4.6 to −9.2 LUFS |
| rips from record and tape | 15.7 – 27.3 dB | −14.7 to −40.8 LUFS |

Since the change the report states, at a crest factor below 12.5 dB and a
loudness above −12 LUFS, that the master is heavily compressed — without a
warning level, because that is a production decision and not a defect.

### Speed stability: calibrated against known fluctuation

The measurement takes the instantaneous frequency of a test tone from the
Hilbert transform of the narrowband-filtered signal; its modulation spectrum
separates wow (0.2–6 Hz) from flutter (6–100 Hz). It was verified against
artificially generated tones with an exactly specified RMS value:

| Specified | measured | modulation frequency |
|---|---|---|
| 0.00 % (unmodulated) | 0.000 % | – |
| 0.10 % at 0.55 Hz | 0.098 % | 0.49 Hz |
| 0.30 % at 0.55 Hz | 0.295 % | 0.49 Hz |
| 0.50 % at 3.0 Hz | 0.500 % | 2.93 Hz |

The deviation stays below two percent of the reading, and an unmodulated tone
gives exactly zero. The modulation spectrum resolves 0.24 Hz, which is why
0.55 Hz appears as 0.49 Hz.

**A steady tone is required.** The criterion is the share of the spectral peak
in total energy: pure noise 0.003, music 0.05, a test tone 0.48 to 1.00. The
threshold sits at 0.20.

**On a real test record** (315 Hz per DIN, captured through a turntable):
carrier frequency 312.0 Hz, so 0.95 % slow; wow 0.148 %, flutter 0.076 %. The
strongest fluctuation sat at 0.49 Hz, in step with one revolution at 33 rpm — a
hint at an off-centre pressing or a concentricity error, which the report now
names explicitly.

Implemented without scipy: analytic signal, bandpass and averaged power
spectral density are a few lines of numpy, and the results match the scipy
version to three decimal places.

### Layout of the analysis core

`app/core.py` is now only a facade: it brings the modules together and remains
the interface for CLI, web layer and tests. The code sits beside it, separated
by responsibility.

| Module | Lines | Contents |
|---|---|---|
| `params.py` | 160 | parameters, constants, error class |
| `audio.py` | 223 | decoding and measurements via ffmpeg |
| `stft.py` | 152 | short-time Fourier transform |
| `band.py` | 351 | band edge, bandwidth, steady tones |
| `render.py` | 197 | frequency axes and spectrograms |
| `compare.py` | 460 | alignment, difference, null test, residual |
| `measure.py` | 587 | low end, speed, response, impulses, levels |
| `report.py` | 83 | composed reports |
| `core.py` | 98 | facade |

Previously all of this lived in one file of 2123 lines with 48 functions. While
removing a single pattern from it I once deleted seven functions by accident —
exactly the failure such a file invites.

The split changes no behaviour. That is shown twice over: every test passes
unchanged, and a report across three files yields the same checksum before and
after.

### The result index must be writable, not merely present

A CI run reported a failure that never occurred locally: after a second scan not
a single result came from the index. The cause was not the index itself but the
default path `/data/index`. Locally the suite ran as root and could create it;
on the runner it could not — and the index silently switched itself off.

Two things were wrong with that. First, `SidecarStore` only checked whether the
folder could be created. An existing but read-only folder therefore counted as
usable: the index reported itself active while discarding every entry, and every
scan recomputed everything without anyone noticing. It now writes a file at
startup and removes it again.

Second, an unusable path disabled the index entirely. It now falls back to
`~/.cache/spectro/index` and writes a warning to the log. Inside the container
nothing changes; outside it, the scan works even without `SIDECAR_DIR` set.

The test environment now sets the path itself, and the test additionally asserts
that the index is active at all — otherwise the cause is once again nowhere to
be found.
