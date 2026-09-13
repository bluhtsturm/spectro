# Changelog

Alle nennenswerten Änderungen. Das Format folgt lose
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionierung
[SemVer](https://semver.org/lang/de/).

Die Analyseversion (`ANALYSIS_VERSION` in `app/core.py`) wird erhöht, sobald
sich Messung oder Bewertung ändern. Cache und Ergebnisablage werden dadurch
ungültig, damit nach einem Update keine alten Bewertungen ausgeliefert werden.

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
