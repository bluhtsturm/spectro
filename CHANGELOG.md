# Changelog

*[Deutsche Fassung](CHANGELOG.de.md)*

All notable changes. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows
[SemVer](https://semver.org/).

The analysis version (`ANALYSIS_VERSION` in `app/core.py`) goes up whenever a
measurement or a verdict changes. That invalidates cache and result index, so
that no stale verdicts are served after an update.

## [Unreleased]

Analysis version unchanged (12): scan results and the verdicts on individual
files stay the same, the result index of the interface does not need to be
recomputed. The image cache is refilled once (new `RENDER_VERSION`). Command
line scans now file their results under the scanned folder instead of under
`cli` and therefore compute once more; `--prune` removes the old entries.

### Fixed

- `--cutoff` on the command line judged at the FFT size of the image (default
  2048) instead of the reference resolution 4096 and could therefore differ
  from the interface and from `--json`
- The band verdict reused an existing spectrum even when it came from a single
  channel or a different overlap
- The metrics of a comparison were recomputed as soon as only the display
  changed (difference range, difference view off, colour map, image size); they
  are now cached independently of it
- Residual and cache files are written through a temporary file of their own:
  an interruption or two simultaneous requests no longer leave a half-written
  file that would afterwards be served as valid
- The energy distribution counted the boundary frequencies twice, the shares
  added up to slightly more than 100 %
- The CSV export of the interface had two untranslated column headers
- `numpy>=2.0` as the minimum version: the speed stability measurement uses
  `np.trapezoid`, which did not exist before
- Uploads are checked while they arrive and written straight into the upload
  folder. Before, every file first landed completely on the container's tmpfs –
  that is, in memory – before the size limit applied
- Upload names with a leading dot were invisible and could not be deleted from
  the interface; uploads of the same name at the same time could overwrite each
  other
- Setting `AUTH_PASS` without `AUTH_USER` silently disabled authentication
- Images were cached as `public` for a day: behind the login, proxies were
  allowed to store them, and a changed file stayed stale in the browser. Now
  `private` with an `ETag`; the browser revalidates and gets a 304
- Symlinks leading out of a media folder showed up in the browser (and failed
  when opened) and were analysed by the scan; the same rule now applies
  everywhere
- NaN and infinity as parameters ended as a server error instead of a 400
- Every scan brought its own concurrency limit, playback had none at all: two
  scans and a few playbacks multiplied the number of ffmpeg processes
- The interface picked its language from the browser alone and ignored
  `LANG_DEFAULT`; now the server decides, as it does for the verdicts
- Errors when deleting uploads were swallowed by the interface
- Messages of the parameter check and some errors from the core were German
  only; so were the help and output of the command line
- The command line scan aborted completely on an unexpected error in a single
  file, and different scan folders shared one key in the result index

### Changed

- The impulse scan streams: ten minutes at 44.1 kHz need 31 MB instead of
  2.5 GB and run seven times as fast
- The residual is computed block by block: five minutes of 96 kHz stereo need
  630 MB instead of 3.1 GB. As documented, its length is capped at
  `max_seconds`, even if a longer `duration` is requested
- Image rows that cover several FFT bins show the loudest of them instead of a
  sample. At FFT 16384, 14 of 15 bins used to fall through the gaps, and a
  narrow tone was visible or not depending on where it sat. In return, noise
  looks somewhat brighter at large FFT sizes; the default view (FFT 2048,
  linear) is unchanged
- The band edge search is vectorised: same result, three times as fast – which
  noticeably speeds up the collection scan
- Report, null test, impulse scan, low end, speed stability and frequency
  response are cached, keyed only by the parameters that change the result.
  Before, every change of the colour map decoded the file five more times
- File access of the scan, the result index and the cache runs outside the
  event loop; the cache is pruned at most every 30 seconds
- The scan limit applies across all scans together (`SCAN_JOBS`), playback has
  its own (`MAX_STREAMS`)
- Image and CI install pinned versions from `requirements-lock.txt`;
  Dependabot keeps them, the actions and the base image up to date.
  `python-multipart>=0.0.18`

### Added

- A/B switching while listening in comparison mode (button or key `X`):
  playback continues at the same musical spot with the time offset compensated
  – sample-accurately once the null test has run
- Residual boost in dB directly in the interface
- Upload progress per file; the interface uploads files one at a time
- Result index cleanup: `POST /api/index/prune` and `--prune` remove entries
  of deleted, changed or no longer mounted files and of older analysis versions
- `--jobs` for the command line scan (default: half the CPU count)

## [1.0.0] – 2026-09-12

First release. Analysis version 12.

### Included

- Spectrograms with linear, logarithmic and mel frequency axis, zoom in time and
  frequency, playback of the visible section
- Band edge analysis with steepness check, detection of upsampled files by the
  start of the stopband
- A/B comparison with difference view, automatic offset compensation, null test
  and audible residual including its breakdown
- Impulse scan with bass counter-check, low end analysis (rumble, mains hum),
  steady tone detection
- Measurements according to EBU R128, real bit depth, stereo metrics
- Speed stability from a test tone: speed deviation, wow and flutter
- Collection scan with result index and event stream, CSV export
- Web interface, HTTP API and command line tool, in German and English
- Upload management: select and delete in bulk, also from the CLI
- 226 tests, every test signal generated with ffmpeg, twelve of them interface
  tests in a real browser

### Calibrated on real material

The thresholds come from measurements on record and tape rips, idle recordings
of the capture chain and two encoder ladders of ten versions each from two
sources. [CALIBRATION.md](CALIBRATION.md) documents every number together with
the false conclusions behind it.

### Known limits

- Lossy sources without an encoder lowpass cannot be proven from the spectrum.
  Across two ladders, eight and nine of ten versions were detected. AAC 256
  band-limits at 96.9 % of the Nyquist frequency, where it cannot be told apart
  from a converter's anti-aliasing filter (CALIBRATION.md, sections 2 and 11)
- The thresholds are calibrated on a limited number of real recordings
