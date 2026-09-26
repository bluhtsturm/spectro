# Changelog

Alle nennenswerten Änderungen. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
[SemVer](https://semver.org/lang/de/).

Die Analyseversion (`ANALYSIS_VERSION` in `app/core.py`) wird erhöht, sobald
sich Messung oder Bewertung ändern. Cache und Ergebnisablage werden dadurch
ungültig, damit nach einem Update keine alten Bewertungen ausgeliefert werden.

## [Unreleased]

Analyseversion unverändert (12): Scan-Ergebnisse und die Bewertung einzelner
Dateien bleiben gleich, die Ergebnisablage muss nicht neu gerechnet werden.

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

### Geändert

- Die Störungssuche arbeitet streamend: zehn Minuten in 44,1 kHz brauchen
  31 MB statt 2,5 GB und sind siebenmal so schnell
- Das Residual rechnet blockweise: fünf Minuten 96 kHz Stereo brauchen 630 MB
  statt 3,1 GB. Die Länge ist wie dokumentiert auf `max_seconds` begrenzt,
  auch wenn eine längere `duration` angefragt wird

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
Fassungen zweier Quellen. CALIBRATION.md dokumentiert jede Zahl samt der
Fehlschlüsse, die dahinterstecken.

### Bekannte Grenzen

- Verlustbehaftete Quellen ohne Encoder-Tiefpass lassen sich am Spektrum nicht
  nachweisen. Über zwei Leitern wurden acht bzw. neun von zehn Fassungen
  erkannt. AAC 256 begrenzt bei 96,9 % der Nyquist-Frequenz und ist dort nicht
  vom Antialiasing-Filter eines Wandlers zu unterscheiden (CALIBRATION.md,
  Abschnitte 2 und 11)
- Die Schwellen sind an einer überschaubaren Zahl echter Aufnahmen kalibriert
