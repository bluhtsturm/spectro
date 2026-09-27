# spectro

Spectral analysis of audio files — as a web interface and as a command line
tool. Decoding goes through ffmpeg, so anything it handles works: FLAC, WAV,
DSD, APE, WavPack, TrueHD, MP3, AAC, Opus, Vorbis, WMA, AC3/DTS, as well as the
audio tracks inside MKV/MP4/TS.

*[Deutsche Fassung dieser Anleitung](README.de.md)*

## What it does

- **Spectrograms** with linear, logarithmic or mel frequency axis, selectable
  FFT size, window function, overlap, dynamic range and colour map
- **Band edge analysis**: separates the gentle high-frequency rolloff of real
  recordings (tape, records) from the hard cliff of an encoder or a lower
  sample rate — section by section, because a *wandering* band limit is the
  most reliable hint at a lossy source
- **A/B comparison**: two files stacked plus a difference view, with automatic
  compensation of time offsets (encoder delay, different edit points)
- **Residual**: the difference between two versions as an audible file. After
  a restoration it contains exactly what the declicker or noise reduction
  removed — the crest factor tells you whether only impulses were taken out or
  running signal as well
- **Null test**: A and B are aligned sample-accurately, level-matched and
  subtracted. The remaining null depth says whether two files come from the
  same master, regardless of container and codec
- **Low end, rumble, hum**: measures below 20 Hz and looks for mains hum at
  50/60 Hz and its harmonics — at its own resolution of 0.24 Hz
- **Speed stability**: speed deviation, wow and flutter from a test tone,
  including a pointer at off-centre pressings when the fluctuation follows the
  rotation
- **Impulse scan**: finds clicks through the high-frequency envelope, with
  clickable timestamps that zoom straight to the spot
- **Steady tones**: narrowband whistles from the capture chain (power supply,
  monitor, converter) that sit at the same place throughout a recording
- **Measurements**: EBU R128 loudness, LRA, true peak, crest, noise floor, the
  bit depth actually in use (exposes inflated 24-bit files), channel
  correlation and side content
- **Result index**: scan results survive a restart, and the next run only
  re-analyses what changed — 36 seconds become 0.04
- **Collection scan**: check a whole folder recursively, sortable result table
  with band edge and verdict per file, CSV export
- **Folder browser** across any number of read-only mounted media folders, plus
  drag & drop upload; uploads can be selected and deleted in bulk, from the
  interface or the command line
- **Zoom** by dragging a rectangle in the image (time *and* frequency), playback
  of the visible section with a moving playhead, permalinks
- **PNG cache**, limited concurrency, streaming analysis with constant memory
  use (a 12-minute FLAC takes around 3 s and ~160 MB of RAM)
- **German and English** throughout: interface, verdicts and CLI

## Installation with Docker Compose

```bash
cp .env.example .env
$EDITOR .env          # media folders and port
docker compose up -d
```

That pulls the published image from `ghcr.io`. To build from source instead,
swap the `image:` line in `docker-compose.yml` for `build: .` and run
`docker compose up -d --build`.

The interface then runs on `http://<host>:8080`.

Media folders are set in `.env` and mounted as volumes in
`docker-compose.yml`. For further folders, add both:

```yaml
volumes:
  - "${MUSIC_DIR}:/media/music:ro"
  - "${RIPS_DIR}:/media/rips:ro"
  - "/srv/nas/podcasts:/media/podcasts:ro"
```

```ini
MEDIA_DIRS=Music=/media/music:Vinyl rips=/media/rips:Podcasts=/media/podcasts
```

`MEDIA_DIRS` determines the label and the order in the selection menu. Keep the
folders mounted `:ro` — spectro never writes there. Uploads, cache and the
result index live in the named volume `spectro-data`; Docker takes their
ownership from the image when the volume is first created. If you prefer a bind
mount, hand the folder to the container user once:
`sudo chown -R 1000:1000 /path/to/data`.

At startup spectro logs which media folders were actually mounted — a typo in a
path or a forgotten `volume` entry shows up as a warning in
`docker compose logs`.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `MEDIA_DIRS` | – | `Label=/path` per folder, separated by `:` |
| `PORT` | 8080 | port on the host |
| `LANG_DEFAULT` | de | language when the browser sends no preference; also the CLI default |
| `MAX_UPLOAD_MB` | 1024 | size limit per uploaded file, enforced while receiving |
| `CACHE_MAX_MB` | 2048 | upper bound of the PNG/audio cache (LRU eviction) |
| `MAX_RENDERS` | half the CPU count | concurrent analyses |
| `SCAN_JOBS` | like `MAX_RENDERS` | files checked at once, across all running scans |
| `MAX_STREAMS` | twice `MAX_RENDERS`, at least 4 | concurrent playback streams |
| `AUTH_USER` / `AUTH_PASS` | empty | optional HTTP basic authentication, active as soon as either is set |
| `SHOW_ALL_FILES` | 0 | also list files without a known audio extension |
| `SIDECAR` | 1 | result index for the scan (0 disables it) |
| `SIDECAR_DIR` | /data/index | where the index lives (falls back to `~/.cache/spectro/index`) |
| `UPLOAD_DIR` | /data/uploads | where uploads are stored |
| `CACHE_DIR` | /data/cache | rendered images and residuals |
| `LOG_LEVEL` | INFO | log verbosity |

Put a reverse proxy in front of it for anything beyond a private network; the
built-in basic authentication covers the simple case only. Path parameters of
the API are checked against the configured roots, so `../` cannot break out.

## Using it

- Pick a folder on the left, click a file — the analysis starts.
- Switch to **Compare A/B** at the top, then use the `A` and `B` buttons per
  file.
- **Dragging a rectangle** in the image zooms in time and frequency; a double
  click or `Esc` resets it.
- `Space` plays the visible section, the playhead follows along. In comparison
  mode **Listening: A/B** (or `X`) switches to the other file at the same musical
  spot – the time offset between both is taken into account, sample-accurately
  once the null test has run.
- **Residual** takes a boost in dB, so that quiet remains become audible.
- Uploads show their progress per file; the size limit applies per file.
- Presets (`Lossy check`, `Vinyl/tape`, `Mastering` …) set sensible parameter
  combinations in one go.
- **Scan** in the sidebar walks the open folder recursively; the table sorts by
  every column and exports as CSV. Clicking a file name loads it for analysis.
- **Null test** in comparison mode answers what the difference view only hints
  at: a null depth below −60 dB means practically identical, −20 to −40 dB is
  typical for a lossy encoding of the same source, and a correlation near zero
  simply means different material.
- The **language** switch sits in the top right; `?lang=en` works as well, and
  without it the browser's `Accept-Language` decides, then `LANG_DEFAULT`.

## Command line

The command line tool shares the analysis core:

```bash
./spectro.py album.flac                        # spectrogram as PNG
./spectro.py --cutoff --json */*.flac          # analysis report as JSON
./spectro.py -s log --fft 8192 -c all live.wav # log scale, channels separately
./spectro.py --compare original.flac rip.m4a -o comparison.png
./spectro.py --compare a.flac b.flac --null --json
./spectro.py --compare raw.flac restored.flac --residual removed.flac
./spectro.py --scan /srv/nas/music --index ~/.cache/spectro --csv report.csv
./spectro.py --scan /srv/nas/music --index ~/.cache/spectro -j 8   # 8 files at once
./spectro.py --prune --index ~/.cache/spectro   # drop entries of deleted files
./spectro.py --start 90 --duration 30 --fmax 8000 recording.opus
./spectro.py --lang en --cutoff --lowfreq --clicks album.flac
./spectro.py --uploads                           # list uploads
./spectro.py --uploads --delete probe.flac --yes
./spectro.py --uploads --delete-all
```

Inside the container:

```bash
docker compose exec spectro python spectro.py --cutoff /media/music/album/01.flac
```

Important options: `--fft`, `--overlap`, `--window`, `--channels`
(`mix|left|right|mid|side|all`), `--scale`, `--fmin/--fmax`, `--db-range`,
`--cmap`, `--theme`, `--raw`, `--max-cols`, `--no-align`, `--no-diff`, `--null`,
`--residual`, `--residual-gain`, `--clicks`, `--lowfreq`, `--wow`, `--nominal`, `--scan`, `--index`,
`--refresh`, `--prune`, `--jobs`, `--csv`, `--sweep`, `--lang`. Help and output follow
`--lang`; without it `LANG_DEFAULT` decides, otherwise German.

## HTTP API

Everything the interface can do is reachable directly — useful for scripts and
batch checks. Interactive documentation at `/api/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/browse?root=&path=` | folder contents |
| `GET /api/spectrogram.png?root=&path=&…` | spectrogram |
| `GET /api/compare.png?a_root=&a=&b_root=&b=&…` | comparison image |
| `GET /api/compare.json?…` | metrics of the comparison |
| `GET /api/report?root=&path=` | full analysis report incl. clipping assessment |
| `GET /api/nulltest?a_root=&a=&b_root=&b=` | null test in the time domain |
| `GET /api/clicks?root=&path=` | clicks and impulse noise |
| `GET /api/wowflutter?root=&path=` | speed deviation, wow and flutter |
| `GET /api/lowfreq?root=&path=` | rumble, warp, mains hum |
| `GET /api/residual?a_root=&a=&b_root=&b=` | difference A−B as FLAC |
| `GET /api/residual.json?…` | metrics of the residual |
| `GET /api/scan?root=&path=&recursive=1[&refresh=1]` | folder check as JSON |
| `GET /api/scan/stream?…` | same scan as a server-sent event stream |
| `GET /api/index` · `DELETE /api/index` | state of the result index · discard it |
| `GET /api/audio?root=&path=&start=&duration=` | section as MP3 |
| `POST /api/upload` | file upload (multipart) |
| `DELETE /api/upload?path=&path=` | delete individual uploads |
| `DELETE /api/uploads` | empty the upload folder |
| `GET /api/sweep?root=&path=&reference_hz=` | frequency response and channel separation |
| `GET /api/probe?root=&path=` | technical data of the first audio stream |
| `GET /api/download?root=&path=` | the original file |
| `GET /api/config` | folders, colour maps, windows, defaults |
| `POST /api/index/prune` | drop index entries of deleted or changed files |
| `GET /healthz` | health check, answers without authentication |

Every endpoint accepts `?lang=de|en`. Measurements are kept in the cache, keyed
only by what changes the result – a different colour map does not recompute a
report. Images come with an `ETag`; the browser revalidates instead of holding a
stale picture.

The `pattern` field of reports and scans uses fixed identifiers regardless of the
language: `voll` (no steep drop), `konstant` (constant band edge) and
`hochgesampelt` (upsampled). The readable text is in `verdict.text`.

Example — folder check through the API, flagged files only:

```bash
curl -s 'http://localhost:8080/api/scan?root=music&path=Albums&recursive=1&lang=en' |
  jq -r '.files[] | select(.verdict.level=="warn") | "\(.path): \(.verdict.text)"'
```

Example — check a whole collection for transcodes from the command line:

```bash
find /srv/nas/music -name '*.flac' -print0 |
  xargs -0 -P4 -n1 ./spectro.py --json --no-image |
  jq -r 'select(.verdict.level=="warn") | "\(.file.name): \(.verdict.text)"'
```

## Notes on the measurements

A band edge is only reported when the drop is also **steep** — measured in dB
per kHz. Encoder and converter filters fall at 45 to 80 dB/kHz, the high
frequency rolloff of a record or a tape at 3 to 6. Without that check every
quiet spot in a run-out groove reports an edge; with it, no false positive
remained across the real recordings used for calibration. The converse holds
too: a missing edge does **not** prove a file is lossless — an encoder running
at a high bitrate without a lowpass leaves no visible trace.

The **band edge** is not the same as the **signal bandwidth**. A rip from tape
or record falls off gently above 12–15 kHz; that is the recording, not a defect,
and it is not flagged. Only a steep drop into a flat floor is reported. If it
sits at the same place in nearly every section, it is a fixed band limit; if it
moves with the material, that alone means nothing. When the edge sits just below
the Nyquist frequency it is simply the converter's anti-aliasing filter and
entirely normal.

For upsampled files what counts is not where the edge was found but where the
spectrum reaches the **noise floor** — that is the Nyquist frequency of the
original sample rate. The edge itself lies in the transition band before it and
would report a 48 kHz source as 44.1 kHz.

The **real bit depth** comes from `astats` and counts how many bits are actually
occupied. If it falls below the declared container depth (say 16 out of 24 bit),
the lowest bits are constantly zero and the file was scaled up. For lossy
sources the value is not shown, because there the decoder delivers floating
point and the number would describe the decoder.

The **impulse scan** compares the high-frequency envelope with its local
background and additionally requires the bass not to follow — otherwise every
drum hit would count as a click. On digital material this leaves roughly one or
two false hits per minute; the timestamps can be clicked in the interface and
listened to.

The **residual** is built after alignment and level matching, then broken down.
A high crest factor relative to the original means almost only short impulses
were removed — clicks. Reported separately is how much disappears in quiet and
in loud sections: if practically everything goes in the quiet parts, a gate or a
strong noise reduction is at work. The most telling number is the shape
correlation: if the spectral profile of what was removed follows the programme
(r > 0.8), it is not merely a noise floor disappearing but parts of the music
itself.

The **folder scan** analyses a 60-second excerpt from the middle of each file
and checks `SCAN_JOBS` files at once – shared by all scans, so a second browser
tab does not double the load. Results go into the index; a second run
over the same folder then costs milliseconds, and changed files are recognised
by modification time and size. The interface uses `/api/scan/stream`, which
delivers every result as it arrives: progress is visible, the scan can be
stopped, and nothing runs into the reverse proxy's timeout. Closing the browser
ends the processing. For an unattended first pass over a large collection the
CLI is still the better tool:

```bash
./spectro.py --scan /srv/nas/music --index ~/.cache/spectro --csv report.csv
```

Where one image row covers several FFT bins – large FFT sizes, the upper octaves
of the log and mel axes – the row shows the loudest bin, as the time axis does
for its columns. A narrow tone therefore never falls between two rows; in return,
noise looks somewhat brighter at large FFT sizes than at small ones.

The **impulse scan** reads the file in blocks and needs about 30 MB regardless of
its length. The **residual** holds both versions once in memory (for five minutes
of 96 kHz stereo about 630 MB) and computes the rest block by block.

## Contributing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                 # 312 tests, about 110 seconds
pytest --ignore=tests/test_browser.py   # without a browser, about 80 seconds
ruff check app spectro.py tests
```

The test suite generates every test signal with ffmpeg; no audio ships in the
repository. Fifteen of the tests drive the interface in a real Chromium and fail
on any console or page error – they need `playwright install chromium` and skip
themselves when it is missing.

The analysis core is split by responsibility — `params`, `audio`, `stft`,
`band`, `render`, `compare`, `measure`, `report` — with `core.py` as a facade
that keeps the interface stable. Before changing a threshold, please read
[CALIBRATION.md](CALIBRATION.md): it documents which measurements the numbers
come from and which false conclusions lie behind them. The tests are written to
cover exactly those traps — that a run-out groove is not reported as a
transcode, and that a quiet 24-bit recording is not reported as upsampled.

Interface texts live in `app/i18n.py` (verdicts, CLI) and
`app/static/i18n.js` (interface). A new language is one more entry in each; no
analysis code changes. A test checks that all languages carry the same keys and
the same placeholders.

## Limits

All classifications are heuristics, calibrated against real recordings: rips
from record and tape, idle recordings of a capture chain, and two encoder ladders
of ten versions each from two different sources. Across two ladders eight and nine of ten were detected. AAC 256
band-limits at 96.9 % of the Nyquist frequency, where it cannot be told apart
from a converter's anti-aliasing filter, and a source that carries little above
19 kHz leaves an encoder nothing to cut — such files are invisible to this kind
of analysis. Transcodes with artificial noise filled in above the cutoff cannot be
detected from the spectrum either. For the impulse scan: what it finds is a suggestion to listen to, not a
diagnosis.

## Releases

Tagging `v1.2.3` builds a multi-architecture image (amd64 and arm64),
publishes it to `ghcr.io` and then creates the GitHub release page from the
matching section of both changelogs – English on top, German below. For an
older tag the page can be created by hand with the *Release-Seite* workflow.
Pull requests that change the *Release* workflow, the Dockerfile or the pinned
versions run the same build as a probe without publishing and start both
images – the arm64 one emulated with QEMU. Started by hand, *Release* is a
probe as well.
[CHANGELOG.md](CHANGELOG.md) records what changed;
`ANALYSIS_VERSION` in `app/core.py` goes up whenever a measurement or a verdict
changes, which invalidates cache and result index so that no stale verdicts
survive an update.

Image and CI install pinned versions. `requirements.in` and
`requirements-dev.in` state the lower bounds; `requirements.txt` and
`requirements-dev.txt` are generated from them with pip-compile under
Python 3.12, the version of the image:

```bash
pip-compile --strip-extras --output-file=requirements.txt requirements.in
pip-compile --strip-extras --output-file=requirements-dev.txt requirements-dev.in
```

Dependabot proposes updates to the pins, the actions and the base image as pull
requests; for the pins it re-runs pip-compile, so packages that depend on each
other are updated together.

## License

MIT — see [LICENSE](LICENSE).
