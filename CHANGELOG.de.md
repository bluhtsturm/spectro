# Changelog

*[English version](CHANGELOG.md)*

Alle nennenswerten Änderungen. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
[SemVer](https://semver.org/lang/de/).

Die Analyseversion (`ANALYSIS_VERSION` in `app/core.py`) wird erhöht, sobald
sich Messung oder Bewertung ändern. Cache und Ergebnisablage werden dadurch
ungültig, damit nach einem Update keine alten Bewertungen ausgeliefert werden.

## [Unreleased]

### Neu

- Jeder Tag legt auch seine Release-Seite auf GitHub an, aus dem passenden
  Abschnitt beider Changelogs (Englisch oben, Deutsch darunter). Für ältere
  Tags legt der Workflow *Release-Seite* sie von Hand an
- Probe der Veröffentlichung: Pull Requests, die den Workflow *Release*, das
  Dockerfile oder die festgelegten Fassungen ändern, bauen das Image für amd64
  und arm64 ohne es zu veröffentlichen und starten beide – arm64 emuliert mit
  QEMU. Bisher wurde das arm64-Image nie gestartet, und ein kaputter Bau fiel
  erst beim nächsten Tag auf. Von Hand gestartet ist *Release* jetzt ebenfalls
  eine Probe; vorher veröffentlichte es den aktuellen Stand von main als
  `latest`

### Geändert

- Die festgelegten Fassungen entstehen jetzt mit pip-compile: `requirements.in`
  und `requirements-dev.in` nennen die Untergrenzen, `requirements.txt` und
  `requirements-dev.txt` die aufgelösten Fassungen und ersetzen
  `requirements-lock.txt`. Dependabot löst bei jeder Aktualisierung alles neu
  auf, voneinander abhängige Pakete bleiben so zueinander passend – seine
  erste Aktualisierung hatte `pydantic-core` ohne `pydantic` angehoben und ließ
  sich nicht installieren
- Auch Test- und Lint-Werkzeuge sind festgelegt; eine neue Fassung von pytest
  oder ruff verändert die CI nicht mehr von selbst
- numpy 2.5.3 und contourpy 1.4.0; alle Messungen liefern dieselben Ergebnisse
  wie vorher
- GitHub Actions in ihren Node-24-Fassungen: `checkout` 7, `setup-python` 7,
  `upload-artifact` 7, `setup-qemu-action` 4, `setup-buildx-action` 4,
  `login-action` 4, `metadata-action` 6, `build-push-action` 7. Dependabot
  fasst Actions-Aktualisierungen jetzt in einem Pull Request zusammen

### Behoben

- Auf der Release-Seite brachen Sätze mitten in der Zeile um, weil GitHub dort
  jeden Zeilenumbruch des Changelogs anzeigt
- Eine Ergebniskarte verschwand wieder, wenn der Bericht erst nach ihr ankam:
  wer Störungssuche, Nullprobe, Residual, Gleichlauf oder Frequenzgang
  startete, während der Bericht noch rechnete, verlor dieses Ergebnis. Der
  Bericht ersetzt jetzt nur seinen eigenen Platzhalter, und ein Bericht zu
  einem inzwischen ersetzten Bild wird verworfen

## [1.1.0] – 26.09.2026

Analyseversion unverändert (12): Scan-Ergebnisse und die Bewertung einzelner
Dateien bleiben gleich, die Ergebnisablage der Oberfläche muss nicht neu
gerechnet werden. Der Bild-Cache wird einmal neu gefüllt (neue
`RENDER_VERSION`). Scans der Kommandozeile legen ihre Ergebnisse jetzt unter
dem Scan-Ordner ab statt unter `cli` und rechnen deshalb einmal neu;
`--prune` räumt die alten Einträge weg.

### Behoben

- `--cutoff` auf der Kommandozeile urteilte bei der FFT-Größe des Bildes
  (Standard 2048) statt bei der Bezugsauflösung 4096 und konnte deshalb
  anders ausfallen als Oberfläche und `--json`
- Das Bandurteil übernahm ein vorhandenes Spektrum auch dann, wenn es aus
  einem einzelnen Kanal oder mit anderer Überlappung entstanden war
- Die Kennzahlen eines Vergleichs wurden neu gerechnet, sobald sich nur die
  Darstellung änderte (Differenzbereich, Differenzbild aus, Farbskala,
  Bildgröße); sie liegen jetzt unabhängig davon im Cache
- Residual und Cache-Dateien werden über eine eigene Zwischendatei
  geschrieben: ein Abbruch oder zwei gleichzeitige Anfragen hinterlassen keine
  halbe Datei mehr, die danach als gültig ausgeliefert würde
- Die Energieverteilung zählte die Grenzfrequenzen doppelt, die Anteile
  ergaben zusammen etwas mehr als 100 %
- Der CSV-Export der Oberfläche hatte zwei unübersetzte Spaltenköpfe
- `numpy>=2.0` als Mindestversion: die Gleichlaufmessung nutzt
  `np.trapezoid`, das es vorher nicht gab
- Uploads werden beim Empfang geprüft und direkt in den Upload-Ordner
  geschrieben. Vorher landete jede Datei erst vollständig auf dem tmpfs des
  Containers – also im Arbeitsspeicher –, bevor das Größenlimit griff
- Upload-Namen mit führendem Punkt waren unsichtbar und ließen sich über die
  Oberfläche nicht löschen; gleichnamige Uploads zur selben Zeit konnten sich
  überschreiben
- Ein gesetztes `AUTH_PASS` ohne `AUTH_USER` schaltete die Anmeldung still ab
- Bilder wurden als `public` einen Tag lang gecacht: hinter der Anmeldung
  durften Proxys sie speichern, und eine geänderte Datei blieb im Browser alt.
  Jetzt `private` mit `ETag`, der Browser fragt nach und bekommt 304
- Symlinks aus einem Medienordner heraus erschienen im Browser (und scheiterten
  beim Öffnen) und wurden vom Scan analysiert; jetzt gilt überall dieselbe Regel
- NaN und Unendlich als Parameter endeten als Serverfehler statt als 400
- Jeder Scan brachte seine eigene Parallelitätsgrenze mit, die Wiedergabe gar
  keine: zwei Scans und ein paar Wiedergaben vervielfachten die ffmpeg-Läufe
- Die Oberfläche richtete ihre Sprache allein nach dem Browser und ignorierte
  `LANG_DEFAULT`; jetzt entscheidet der Server wie für die Bewertungen
- Fehler beim Löschen von Uploads wurden in der Oberfläche verschluckt
- Meldungen der Parameterprüfung und einige Fehler aus dem Kern waren nur
  deutsch; Hilfe und Ausgaben der Kommandozeile ebenso
- Der Scan der Kommandozeile brach bei einem unerwarteten Fehler in einer
  einzelnen Datei komplett ab, und verschiedene Scan-Ordner teilten sich in der
  Ergebnisablage einen Schlüssel

### Geändert

- Die Störungssuche arbeitet streamend: zehn Minuten in 44,1 kHz brauchen
  31 MB statt 2,5 GB und sind siebenmal so schnell
- Das Residual rechnet blockweise: fünf Minuten 96 kHz Stereo brauchen 630 MB
  statt 3,1 GB. Die Länge ist wie dokumentiert auf `max_seconds` begrenzt,
  auch wenn eine längere `duration` angefragt wird
- Bildzeilen, die mehrere FFT-Bins abdecken, zeigen den lautesten davon statt
  einer Stichprobe. Bei FFT 16384 fielen vorher 14 von 15 Bins durch, ein
  schmaler Ton war je nach Lage sichtbar oder nicht. Rauschen wirkt bei großer
  FFT dafür etwas heller; die Standardansicht (FFT 2048, linear) ist unverändert
- Die Bandkantensuche rechnet vektorisiert: dasselbe Ergebnis, dreimal so
  schnell – der Sammlungs-Scan wird dadurch spürbar schneller
- Bericht, Nullprobe, Störungssuche, Tiefton, Gleichlauf und Frequenzgang
  landen im Cache, mit einem Schlüssel nur aus den Parametern, die das Ergebnis
  ändern. Vorher dekodierte jede Änderung der Farbskala die Datei fünfmal neu
- Dateizugriffe des Scans, der Ablage und des Caches laufen außerhalb der
  Ereignisschleife; der Cache wird höchstens alle 30 Sekunden aufgeräumt
- Die Scan-Grenze gilt über alle Scans gemeinsam (`SCAN_JOBS`), die Wiedergabe
  hat eine eigene (`MAX_STREAMS`)
- Image und CI installieren feste Fassungen aus `requirements-lock.txt`;
  Dependabot hält sie, die Actions und das Basis-Image aktuell.
  `python-multipart>=0.0.18`

### Neu

- A/B-Umschalten beim Hören im Vergleich (Knopf oder Taste `X`): es geht an
  derselben musikalischen Stelle weiter, mit Versatzausgleich – sample-genau,
  sobald die Nullprobe gelaufen ist
- Anhebung des Residuals in dB direkt in der Oberfläche
- Upload-Fortschritt je Datei; die Oberfläche lädt Dateien einzeln hoch
- Ergebnisablage aufräumen: `POST /api/index/prune` und `--prune` entfernen
  Einträge zu gelöschten, geänderten oder nicht mehr eingebundenen Dateien und
  aus älteren Analyseversionen
- `--jobs` für den Scan der Kommandozeile (Standard: halbe CPU-Zahl)

## [1.0.1] – 13.09.2026

Analyseversion unverändert (12).

### Behoben

- Die Ergebnisablage prüfte nur, ob sich ihr Ordner anlegen ließ. Ein
  vorhandener, aber schreibgeschützter Ordner galt deshalb als nutzbar: die
  Ablage meldete sich aktiv, verwarf aber jeden Eintrag, und jeder Scan rechnete
  alles neu, ohne dass es auffiel. Beim Start schreibt sie jetzt eine Probedatei
- Ein unbrauchbarer Ablagepfad schaltete die Ablage ganz ab. Jetzt weicht sie
  auf `~/.cache/spectro/index` aus und schreibt eine Warnung ins Protokoll

### Geändert

- CI und Release nutzen `actions/checkout@v5` und `actions/setup-python@v6`

## [1.0.0] – 12.09.2026

Erste Fassung. Analyseversion 12.

### Enthalten

- Spektrogramme mit linearer, logarithmischer und Mel-Achse, Zoom in Zeit und
  Frequenz, Wiedergabe des sichtbaren Ausschnitts
- Bandkanten-Analyse mit Steilheitsprüfung, Erkennung hochgesampelter Dateien
  über den Stoppbandbeginn
- Vergleich A/B mit Differenzbild, automatischem Versatzausgleich, Nullprobe
  und hörbarem Residual samt Zerlegung
- Störungssuche mit Bassgegenprobe, Tieftonanalyse (Rumpeln, Netzbrumm),
  Dauerton-Erkennung
- Messwerte nach EBU R128, echte Bittiefe, Stereo-Kennzahlen
- Gleichlaufmessung an einem Messton: Drehzahlabweichung, Wow und Flutter
- Sammlungs-Scan mit Ergebnisablage und Ereignisstrom, CSV-Export
- Weboberfläche, HTTP-API und Kommandozeilenwerkzeug, deutsch und englisch
- Upload-Verwaltung: auswählen und sammelweise löschen, auch über die CLI
- 226 Tests, alle Prüfsignale werden mit ffmpeg erzeugt, darunter zwölf
  Oberflächentests im echten Browser

### An echtem Material kalibriert

Die Schwellen stammen aus Messungen an Rips von Schallplatte und Tonband, an
Leerlaufmitschnitten der Aufnahmekette und an zwei Encoder-Leitern aus je zehn
Fassungen zweier Quellen. [CALIBRATION.de.md](CALIBRATION.de.md) dokumentiert jede Zahl samt der
Fehlschlüsse, die dahinterstecken.

### Bekannte Grenzen

- Verlustbehaftete Quellen ohne Encoder-Tiefpass lassen sich am Spektrum nicht
  nachweisen. Über zwei Leitern wurden acht bzw. neun von zehn Fassungen
  erkannt. AAC 256 begrenzt bei 96,9 % der Nyquist-Frequenz und ist dort nicht
  vom Antialiasing-Filter eines Wandlers zu unterscheiden (CALIBRATION.de.md,
  Abschnitte 2 und 11)
- Die Schwellen sind an einer überschaubaren Zahl echter Aufnahmen kalibriert
