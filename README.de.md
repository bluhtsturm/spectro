# spectro

*[English version of this guide](README.md)*

Spektralanalyse von Audiodateien – als Weboberfläche und als CLI. Dekodiert wird
alles, was ffmpeg beherrscht (FLAC, WAV, DSD, APE, WavPack, TrueHD, MP3, AAC,
Opus, Vorbis, WMA, AC3/DTS sowie Audiospuren aus MKV/MP4/TS).

## Funktionen

- **Spektrogramme** mit linearer, logarithmischer oder Mel-Frequenzachse,
  wählbarer FFT-Größe, Fensterfunktion, Überlappung, Dynamik und Farbskala
- **Vergleichsmodus A/B**: zwei Dateien übereinander plus Differenzbild, mit
  automatischem Ausgleich des Zeitversatzes (Encoder-Delay, anderer Schnitt)
- **Bandbreitenanalyse** mit Bewertung: erkennt bandbegrenzte „Lossless"-Dateien
  (Transcodes) und hochgesampeltes Material
- **Messwerte**: EBU-R128-Lautheit, LRA, True Peak, Crest, Rauschflur,
  tatsächlich genutzte Bittiefe (entlarvt aufgeblasene 24-bit-Dateien),
  Kanalkorrelation und Seitenanteil
- **Ordner-Browser** über beliebig viele read-only eingehängte Medienordner,
  plus Upload per Drag & Drop; Uploads lassen sich auswählen und sammelweise
  löschen, in der Oberfläche wie auf der Kommandozeile
- **Zoom** durch Aufziehen im Bild (Zeit *und* Frequenz), Anhören des sichtbaren
  Ausschnitts mit mitlaufender Abspielmarke, Permalinks
- **Bandkanten-Analyse**: unterscheidet den weichen Höhenabfall echter Aufnahmen
  (Band, Schallplatte) vom harten Steilabfall eines Encoders oder einer
  niedrigeren Abtastrate – abschnittsweise, denn eine *wandernde* Bandgrenze ist
  der verlässlichste Hinweis auf eine verlustbehaftete Quelle
- **Tiefton, Rumpeln, Brumm**: misst den Bereich unter 20 Hz und sucht
  Netzbrumm bei 50/60 Hz samt Oberwellen – mit eigener Auflösung von 0,24 Hz
- **Gleichlauf**: Drehzahlabweichung, Wow und Flutter an einem Messton, samt
  Hinweis auf außermittige Pressungen, wenn die Schwankung der Umdrehung folgt
- **Störungssuche**: findet Knackser und Impulsstörungen über die
  Hochtonhüllkurve, mit anklickbaren Zeitmarken, die direkt an die Stelle zoomen
- **Dauertöne**: schmalbandige Pfeifen aus der Aufnahmekette (Netzteil,
  Bildschirm, Wandler), die über die ganze Aufnahme an derselben Stelle stehen
- **Residual**: die Differenz zweier Fassungen als hörbare Datei. Bei einer
  Restauration steht darin genau das, was Entknackser oder Rauschunterdrückung
  entfernt haben – der Crest-Faktor verrät, ob nur Impulse weggenommen wurden
  oder auch laufendes Signal
- **Nullprobe**: A und B werden sample-genau ausgerichtet, im Pegel abgeglichen
  und subtrahiert. Die verbleibende Nulltiefe sagt, ob zwei Dateien vom selben
  Master stammen – unabhängig von Container und Codec
- **Ergebnisablage**: Scan-Ergebnisse überdauern den Neustart, beim nächsten
  Lauf wird nur Geändertes neu gerechnet – aus 36 Sekunden werden 0,04
- **Sammlungs-Scan**: ganzen Ordner rekursiv prüfen, sortierbare Ergebnistabelle
  mit Bandbreite und Bewertung je Datei, Export als CSV
- **PNG-Cache**, begrenzte Parallelität, streamende Analyse mit konstantem
  Speicherbedarf (eine 12-Minuten-FLAC braucht rund 3 s und ~160 MB RAM)

## Installation mit Docker Compose

```bash
cp .env.example .env
$EDITOR .env          # Medienordner und Port eintragen
docker compose up -d
```

Damit wird das veröffentlichte Image von `ghcr.io` geladen. Wer aus dem
Quelltext bauen will, ersetzt die Zeile `image:` in `docker-compose.yml` durch
`build: .` und ruft `docker compose up -d --build` auf.

Danach läuft die Oberfläche auf `http://<host>:8080`.

Die Medienordner werden in `.env` gesetzt und in `docker-compose.yml` als
Volume eingehängt. Für weitere Ordner beides ergänzen:

```yaml
volumes:
  - "${MUSIC_DIR}:/media/musik:ro"
  - "${RIPS_DIR}:/media/rips:ro"
  - "/srv/nas/podcasts:/media/podcasts:ro"
```

```ini
MEDIA_DIRS=Musik=/media/musik:Vinyl-Rips=/media/rips:Podcasts=/media/podcasts
```

`MEDIA_DIRS` bestimmt Beschriftung und Reihenfolge im Auswahlmenü. Die Ordner
sollten `:ro` eingehängt bleiben – spectro schreibt dort nie. Uploads und Cache
liegen im Named Volume `spectro-data`.

### Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `MEDIA_DIRS` | – | `Label=/pfad` je Ordner, mit `:` getrennt |
| `PORT` | 8080 | Port auf dem Host |
| `MAX_UPLOAD_MB` | 1024 | Größenlimit je hochgeladener Datei |
| `CACHE_MAX_MB` | 2048 | Obergrenze des PNG-Caches (LRU-Bereinigung) |
| `MAX_RENDERS` | halbe CPU-Zahl | gleichzeitige Analysen |
| `AUTH_USER` / `AUTH_PASS` | leer | optionale HTTP-Basic-Absicherung |
| `LANG_DEFAULT` | de | Sprache, wenn der Browser keine Vorgabe schickt |
| `SHOW_ALL_FILES` | 0 | auch Dateien ohne bekannte Audio-Endung anzeigen |
| `SIDECAR` | 1 | Ergebnisablage für den Scan (0 schaltet sie ab) |
| `SIDECAR_DIR` | /data/index | Ort der Ablage (weicht auf `~/.cache/spectro/index` aus) |
| `UPLOAD_DIR` | /data/uploads | Ablage der Uploads |
| `CACHE_DIR` | /data/cache | fertige Bilder und Residuen |
| `LOG_LEVEL` | INFO | Ausführlichkeit der Protokolle |

Uploads und Cache liegen im Named Volume `spectro-data`; dessen Rechte erbt
Docker beim ersten Anlegen aus dem Image. Wer stattdessen ein Bind-Mount
verwendet, muss den Ordner einmalig dem Container-Benutzer geben:
`sudo chown -R 1000:1000 /pfad/zu/data`.

Beim Start protokolliert spectro, welche Medienordner tatsächlich eingebunden
wurden – ein Tippfehler im Pfad oder ein vergessener `volume`-Eintrag steht
dann als Warnung in `docker compose logs`.

Hinter einem Reverse Proxy zusätzlich absichern; die eingebaute Basic-Auth ist
nur für den einfachen Fall gedacht. Pfadangaben der API werden gegen die
konfigurierten Wurzelverzeichnisse geprüft, ein Ausbruch per `../` ist nicht
möglich.

## Bedienung

- Links Ordner wählen, Datei anklicken → Analyse startet.
- **Vergleich A/B** oben umschalten, dann je Datei die Knöpfe `A` und `B`.
- Im Bild einen Bereich **aufziehen** zoomt in Zeit und Frequenz;
  Doppelklick oder `Esc` setzt zurück.
- `Leertaste` spielt den sichtbaren Ausschnitt ab, die Abspielmarke läuft mit.
- Vorlagen (`Lossy-Check`, `Vinyl/Tape`, `Mastering` …) setzen sinnvolle
  Parameterkombinationen in einem Rutsch.
- **Prüfen** in der Seitenleiste scannt den geöffneten Ordner rekursiv; die
  Tabelle lässt sich nach jeder Spalte sortieren und als CSV sichern. Ein Klick
  auf den Dateinamen übernimmt die Datei in die Analyse.
- **Nullprobe** im Vergleichsmodus beantwortet die Frage, die das Differenzbild
  nur andeutet: Nulltiefe unter −60 dB heißt praktisch identisch, −20 bis
  −40 dB ist typisch für eine verlustbehaftete Kodierung derselben Quelle, und
  eine Korrelation nahe null bedeutet schlicht anderes Material.

## CLI

Das Kommandozeilenwerkzeug nutzt denselben Analysekern:

```bash
./spectro.py album.flac                        # Spektrogramm als PNG
./spectro.py --cutoff --json */*.flac          # Analysebericht als JSON
./spectro.py -s log --fft 8192 -c all live.wav # log-Skala, Kanäle einzeln
./spectro.py --compare original.flac rip.m4a -o vergleich.png
./spectro.py --compare a.flac b.flac --null --json   # Nullprobe als JSON
./spectro.py --compare roh.flac restauriert.flac --residual weg.flac
./spectro.py --start 90 --duration 30 --fmax 8000 mitschnitt.opus
./spectro.py --uploads                           # Uploads auflisten
./spectro.py --uploads --delete probe.flac --yes
./spectro.py --uploads --delete-all
```

Im Container:

```bash
docker compose exec spectro python spectro.py --cutoff /media/musik/album/01.flac
```

Wichtige Optionen: `--fft`, `--overlap`, `--window`, `--channels`
(`mix|left|right|mid|side|all`), `--scale`, `--fmin/--fmax`, `--db-range`,
`--cmap`, `--theme`, `--raw`, `--max-cols`, `--no-align`, `--no-diff`, `--null`,
`--clicks`, `--lowfreq`, `--wow`, `--nominal`, `--residual`, `--residual-gain`.

## HTTP-API

Alles, was die Oberfläche kann, ist auch direkt ansprechbar – praktisch für
Skripte und Batch-Prüfungen. Interaktive Doku unter `/api/docs`.

| Endpunkt | Zweck |
|---|---|
| `GET /api/browse?root=&path=` | Ordnerinhalt |
| `GET /api/spectrogram.png?root=&path=&…` | Spektrogramm |
| `GET /api/compare.png?a_root=&a=&b_root=&b=&…` | Vergleichsbild |
| `GET /api/compare.json?…` | Kennzahlen des Vergleichs |
| `GET /api/report?root=&path=` | vollständiger Analysebericht |
| `GET /api/nulltest?a_root=&a=&b_root=&b=` | Nullprobe im Zeitbereich |
| `GET /api/clicks?root=&path=` | Knackser und Impulsstörungen |
| `GET /api/wowflutter?root=&path=` | Drehzahlabweichung, Wow und Flutter |
| `GET /api/lowfreq?root=&path=` | Rumpeln, Plattenwelligkeit, Netzbrumm |
| `GET /api/residual?a_root=&a=&b_root=&b=` | Differenz A−B als FLAC |
| `GET /api/residual.json?…` | Kennzahlen des Residuals |
| `GET /api/scan?root=&path=&recursive=1[&refresh=1]` | Ordner-Prüfung als JSON |
| `GET /api/scan/stream?…` | derselbe Scan als Ereignisstrom |
| `GET /api/index` | Zustand der Ergebnisablage |
| `DELETE /api/index` | Ablage verwerfen |
| `GET /api/audio?root=&path=&start=&duration=` | Ausschnitt als MP3 |
| `POST /api/upload` | Datei-Upload (multipart) |
| `DELETE /api/upload?path=&path=` | einzelne Uploads löschen |
| `DELETE /api/uploads` | Upload-Ordner leeren |

Beispiel – Ordner-Prüfung über die API, nur die Auffälligkeiten:

```bash
curl -s 'http://localhost:8080/api/scan?root=musik&path=Alben&recursive=1' |
  jq -r '.files[] | select(.verdict.level=="warn") | "\(.path): \(.verdict.text)"'
```

Beispiel – ganze Sammlung über die CLI auf Transcodes prüfen:

```bash
find /srv/nas/musik -name '*.flac' -print0 |
  xargs -0 -P4 -n1 ./spectro.py --json --no-image |
  jq -r 'select(.verdict.level=="warn") | "\(.file.name): \(.verdict.text)"'
```

## Hinweise zu den Kennzahlen

Eine Bandkante wird nur gemeldet, wenn der Abfall auch **steil** ist –
gemessen in dB je kHz. Encoder- und Wandlerfilter fallen mit 45 bis 80 dB/kHz,
der Höhenabfall einer Platte oder eines Bandes mit 3 bis 6. Ohne diese Prüfung
meldet jede leise Rillenstelle eine Kante; mit ihr blieb an echtem Material
kein Fehlalarm übrig. Umgekehrt gilt: fehlt die Kante, ist die Datei **nicht**
als verlustfrei bewiesen – ein Encoder mit hoher Bitrate und ohne Tiefpass
hinterlässt keine sichtbare Spur, und genau so ein Fall ließ sich hier weder
über das Spektrum noch über das Granulenraster des Encoders nachweisen.

Die **Bandkante** ist nicht dasselbe wie die **Signalbandbreite**. Ein Rip von
Band oder Schallplatte fällt oberhalb von 12–15 kHz weich ab – das ist die
Aufnahme, kein Defekt, und wird nicht bemängelt. Gemeldet wird nur ein
Steilabfall in einen flachen Boden. Steht er in fast allen Abschnitten an
derselben Stelle, ist es eine feste Bandbegrenzung; wandert er mit dem Material,
war ein verlustbehafteter Encoder am Werk, der in leisen Passagen die Höhen
wegwirft. Liegt die Kante direkt unter der Nyquist-Frequenz, ist es schlicht das
Antialiasing-Filter des Wandlers und völlig normal.

Das **Residual** wird nach Ausrichtung und Pegelabgleich gebildet und dann
zerlegt. Ein hoher Crest-Faktor gegenüber dem Original bedeutet, dass fast nur
kurze Impulse entfernt wurden – Knackser. Getrennt ausgewiesen wird außerdem,
wie viel in leisen und in lauten Abschnitten verschwindet: wird in leisen
Stellen praktisch alles entfernt, arbeitet ein Gate oder eine kräftige
Rauschunterdrückung. Am aussagekräftigsten ist die Formkorrelation: folgt das
spektrale Profil des Entfernten dem des Programms (r > 0,8), verschwindet nicht
nur ein Rauschteppich, sondern Anteile der Musik selbst.

Bei der Erkennung hochgesampelter Dateien zählt nicht die Fundstelle der Kante,
sondern wo das Spektrum den **Rauschboden** erreicht – das ist die
Nyquist-Frequenz der ursprünglichen Abtastrate. Die Kante selbst liegt im
Übergangsbereich davor und würde eine 48-kHz-Quelle fälschlich als 44,1 kHz
ausweisen.

Die **Störungssuche** vergleicht die Hochtonhüllkurve mit ihrem lokalen
Untergrund und verlangt zusätzlich, dass der Bass nicht mitgeht – sonst würde
jeder Schlagzeugeinsatz als Knackser gelten. Auf digitalem Material bleiben
so etwa ein bis zwei Fehltreffer je Minute; die Zeitmarken lassen sich in der
Oberfläche anklicken und nachhören.

Die **echte Bittiefe** stammt aus `astats` und zählt, wie viele Bits tatsächlich
belegt sind. Liegt sie unter der deklarierten Container-Bittiefe (etwa 16 von
24 bit), sind die untersten Bits konstant null – die Datei wurde also
hochgerechnet. Bei verlustbehafteten Quellen wird der Wert nicht ausgewiesen:
dort liefert der Decoder Fließkomma-Samples, die Zahl würde nur den Decoder
beschreiben.

Der **Ordner-Scan** analysiert je Datei einen 60-Sekunden-Ausschnitt aus der
Mitte und läuft mit `MAX_RENDERS` parallel. Die Ergebnisse landen in der
Ablage; ein zweiter Lauf über denselben Ordner kostet dann nur noch
Millisekunden, und geänderte Dateien werden an Änderungszeit und Größe
erkannt. Die Oberfläche nutzt `/api/scan/stream` und zeigt jedes Ergebnis, sobald es
vorliegt – der Fortschritt ist sichtbar, der Lauf lässt sich anhalten, und
nichts läuft in einen Timeout. Für einen unbeaufsichtigten ersten Durchlauf
über eine große Sammlung ist die CLI weiterhin das bessere Werkzeug:

```bash
./spectro.py --scan /srv/nas/musik --index ~/.cache/spectro --csv bericht.csv
```

## Mitarbeit

```bash
pip install -r requirements-dev.txt
pytest                 # 233 Tests, rund 95 Sekunden
pytest --ignore=tests/test_browser.py   # ohne Browser, rund 60 Sekunden
ruff check app spectro.py tests
```

Die Testsuite erzeugt alle Prüfsignale selbst mit ffmpeg; im Repository liegt
kein Audiomaterial. Zwölf der Tests bedienen die Oberfläche in einem echten
Chromium und scheitern bei jedem Konsolen- oder Seitenfehler – sie brauchen
`playwright install chromium` und überspringen sich, wenn er fehlt.

Der Analysekern ist nach Zuständigkeiten getrennt – `params`, `audio`, `stft`,
`band`, `render`, `compare`, `measure`, `report` –, wobei `core.py` als Fassade
die Schnittstelle stabil hält. Wer eine Schwelle ändern möchte, sollte vorher [CALIBRATION.de.md](CALIBRATION.de.md) lesen: dort steht, aus welchen
Messungen die Zahlen stammen und welche Fehlschlüsse dahinterstecken. Die
Tests sind so geschrieben, dass sie genau diese Fallstricke abdecken – etwa
dass eine Auslaufrille nicht als Transcode gemeldet wird und eine leise
24-bit-Aufnahme nicht als hochgerechnet.

Die Texte der Oberfläche stehen in `app/i18n.py` (Bewertungen, CLI) und
`app/static/i18n.js` (Oberfläche). Eine weitere Sprache ist je ein zusätzlicher
Eintrag; am Analysecode ändert sich nichts. Ein Test prüft, dass alle Sprachen
dieselben Schlüssel und dieselben Platzhalter tragen.

## Veröffentlichungen

Ein Tag `v1.2.3` baut ein Image für amd64 und arm64 und veröffentlicht es auf
`ghcr.io`. [CHANGELOG.md](CHANGELOG.md) hält fest, was sich geändert hat;
`ANALYSIS_VERSION` in `app/core.py` steigt, sobald sich Messung oder Bewertung
ändern – Cache und Ergebnisablage werden dadurch ungültig, damit kein alter
Befund ein Update überlebt.

## Grenzen

Alle Einstufungen sind Heuristiken und an echten Aufnahmen kalibriert: Rips von
Schallplatte und Band, Leerlaufmitschnitte einer Aufnahmekette und zwei
Encoder-Leitern aus je zehn Fassungen zweier Quellen. Über zwei Leitern wurden acht
beziehungsweise neun von zehn erkannt. AAC 256 begrenzt bei 96,9 % der
Nyquist-Frequenz und ist dort nicht vom Antialiasing-Filter eines Wandlers zu
unterscheiden; und eine Quelle, die oberhalb von 19 kHz wenig hergibt, lässt
dem Encoder nichts zum Abschneiden – solche Dateien sind für diese Art der
Analyse unsichtbar. Transcodes mit künstlicher
Rauschauffüllung oberhalb der Grenzfrequenz lassen sich ebenfalls nicht
erkennen. Bei der Störungssuche gilt: was sie
findet, ist ein Vorschlag zum Nachhören, keine Diagnose.
