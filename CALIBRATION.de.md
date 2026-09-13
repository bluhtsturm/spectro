# Kalibrierung

*[English version](CALIBRATION.md)*

Dieses Dokument hält fest, **warum** die Schwellen in `app/core.py` so stehen,
wie sie stehen, und welche Fehlschlüsse dahinter stecken. Wer eine Zahl ändern
will, findet hier die Messungen, die zu ihr geführt haben — und in `tests/` die
Fälle, die dabei nicht kaputtgehen dürfen.

Alle Werte stammen aus Messungen an echten Aufnahmen: Rips von Schallplatte und
Tonband (44,1/48/96 kHz, 16 und 24 bit), Leerlaufmitschnitten der Aufnahmekette
und einer nachweislich aus MP3 erzeugten FLAC-Datei. Die Aufnahmen selbst
liegen aus urheberrechtlichen Gründen nicht im Repository; die Testsuite
erzeugt sich ihre Prüfsignale mit ffmpeg selbst.

---

## 1. Bandkante: Steilheit statt Pegelabfall

**Die Regel.** Eine Bandbegrenzung wird nur gemeldet, wenn das Spektrum um
mindestens 15 dB abfällt **und** dieser Abfall steiler als 10 dB/kHz ist
(`spectral_edge`, `min_drop`, `min_steepness`).

**Warum.** Der erste Ansatz suchte den Punkt, an dem die Energie um 50 dB unter
das Maximum gefallen ist. Das misst den Höhenabfall der Aufnahme, nicht die
Bandgrenze der Kette — und lag an echtem Material in jedem einzelnen Fall
falsch: Tonbandaufnahmen wurden als „möglicher Transcode" gemeldet, während
eine tatsächlich aus MP3 erzeugte Datei als „Vollband, konsistent mit
verlustfrei" durchging.

Gemessene Steilheiten am Fundort der Kante:

| Material | dB/kHz |
|---|---|
| Encoder-Tiefpass (MP3 128k, AAC 96k) | 45–80 |
| Resampler- und Wandlerfilter | 11–18 |
| Höhenabfall von Schallplatte und Tonband | 3–6 |

Die Schwelle von 10 dB/kHz trennt die oberen beiden Gruppen von der unteren.
Eine Encoder-Leiter (Abschnitt 11) bestätigte das später an zehn Fassungen aus
einer Quelle: 36 bis 60 dB/kHz.
Nach ihrer Einführung blieb über 13 echte Dateien hinweg kein Fehlalarm übrig.

**Fallstricke.**

- *Eine leise Rillenstelle sieht aus wie eine Kante.* In ruhigen Abschnitten
  einer Auslaufrille sinkt der Hochtonanteil des Rillenrauschens so weit, dass
  der reine Pegelvergleich einen Abfall von über 15 dB findet. Nur die
  Steilheit unterscheidet das vom Filter.
- *Eine ideale Steilkante wird zu tief lokalisiert.* Die Suche nach dem größten
  Abstand zwischen „knapp darunter" und „darüber" trifft bei sehr steilem
  Abfall bis zu 2 kHz zu tief, weil das obere Vergleichsfenster schon davor
  ganz im Sperrbereich liegt. Die Steilheit würde dann an einer noch flachen
  Stelle gemessen und die Kante fiele durch die eigene Prüfung. Deshalb folgt
  auf die Grobsuche eine Feinbestimmung am stärksten Gefälle
  (`test_steilabfall_wird_erkannt`).

---

## 2. Die wandernde Bandkante ist **kein** Nachweis

**Die Regel.** Wechselt die Kante zwischen den Zeitabschnitten, wird das
berichtet, aber nicht als Befund gewertet (`pattern = "vereinzelt"`, Stufe
`ok`).

**Warum.** Zwischenzeitlich galt eine in einigen Abschnitten auftretende Kante
als Fingerabdruck eines Encoders, der in leisen Passagen die Höhen wegwirft.
Die Zahlen widerlegen das:

| Datei | Abschnitte mit Kante (nfft 8192) |
|---|---|
| nachweislich aus MP3 | 3 von 16 |
| Auslaufrille, echte Platte | 6 von 16 |
| Einlaufrille, echte Platte | 9 von 16 |

Die echte Platte schnitt „verdächtiger" ab als der echte Transcode. Die frühere
Erkennung beruhte allein darauf, wo die Schwelle lag — sie hätte auf einer
Sammlung von Analogrips reihenweise Fehlalarme erzeugt.

**Was ebenfalls nicht funktioniert hat.** MP3 arbeitet in Granulen von 1152
Samples, was bei 44,1 kHz einer Modulation von 38,28 Hz entspräche. Im
spektralen Fluss zeigte sich davon nichts: die Spitzen lagen bei allen Dateien
zwischen 5 und 10 dB über dem Umfeld, auch bei unbehandeltem FLAC.

**Konsequenz für die Aussage.** Fehlt eine Kante, ist eine Datei **nicht** als
verlustfrei bewiesen. Encoder mit hoher Bitrate und ohne Tiefpass hinterlassen
keine spektrale Spur. Der Bewertungstext sagt das ausdrücklich.

---

## 3. Hochgesampelte Dateien: der Stoppbandbeginn zählt

**Die Regel.** Die Quellrate wird nicht aus der Kante abgeleitet, sondern aus
dem Punkt, an dem das Spektrum 40 dB unter den Pegel an der Kante gefallen ist.
Dieser Punkt wird gegen 22,05 / 24 / 44,1 kHz verglichen (± 1,8 kHz).

**Warum.** Die Kante liegt im Übergangsbereich des Filters, also deutlich
unterhalb der Nyquist-Frequenz der Quelle. Bei 96-kHz-Dateien mit 48-kHz-Quelle
sitzt sie bei 22,2–22,8 kHz und wurde deshalb fälschlich als 44,1-kHz-Quelle
(Nyquist 22,05 kHz) ausgewiesen.

Vergleich verschiedener Definitionen an vier echten 96-kHz-Dateien mit
bekannter 48-kHz-Quelle (wahre Grenze also 24,0 kHz):

| Definition | gemessene Werte |
|---|---|
| Rauschboden + 6 dB | 23,20 / 23,45 / 24,46 / 24,70 kHz |
| Rauschboden + 20 dB | 22,36 / 22,73 / 23,96 / 24,30 kHz |
| **40 dB unter dem Kantenpegel** | **24,07 / 24,21 / 24,29 / 24,35 kHz** |

Nur die letzte Definition trifft die wahre Grenze auf ±0,4 kHz. Die beiden
anderen streuen um mehr als ein Kilohertz und hängen davon ab, wie tief der
Rauschboden der Datei liegt.

**Fallstrick.** Die Prüfung läuft auf dem Gesamtspektrum, nicht abschnittsweise.
In leisen Passagen erreicht der Abfall die Schwelle nicht — von zwei Aufnahmen
derselben Kette bekam sonst die eine eine Warnung und die andere nicht.

---

## 4. Bittiefe: der zweite Wert, nicht der erste

**Die Regel.** `astats` meldet „Bit depth: A/B". Ausgewertet wird **B** (Bits
ohne konstant genullte unterste Stellen), verglichen mit der vom Container
deklarierten Tiefe. Ein Unterschied ab 2 bit gilt als hochgerechnet.

**Warum.** A hängt von der Aussteuerung ab. Gemessen:

| Datei | A/B | ffprobe | Befund |
|---|---|---|---|
| echte 16-bit-Datei | 12/16 | 16 | in Ordnung |
| 16-bit-Inhalt in 24-bit-Hülle | 12/16 | 24 | hochgerechnet |
| laute echte 24-bit-Aufnahme | 23/24 | 24 | in Ordnung |
| **leise echte 24-bit-Aufnahme** | **16/24** | 24 | **in Ordnung** |

Die erste Fassung wertete A aus und hätte jede leise 24-bit-Aufnahme als
hochgerechnet gemeldet.

**Zwei weitere Fallstricke.**

- *Die Filterkette verfälscht die Messung.* `ebur128` rechnet intern in
  doppelter Genauigkeit. Steht `astats` in derselben Kette dahinter, misst es
  die konvertierten Samples und meldet Unsinn — beobachtet wurden „40 von
  44 bit" statt der korrekten 20 von 24. Ein `asplit` trennt die Zweige.
- *Bei verlustbehafteten Quellen ist der Wert bedeutungslos*, weil der Decoder
  Fließkomma liefert. Er wird dort nicht ausgewiesen.

---

## 5. Störungssuche: die Bassgegenprobe

**Die Regel.** Ein Ereignis zählt, wenn die Hochtonhüllkurve (ab 6 kHz) den
lokalen Untergrund um 14 dB übersteigt, höchstens 6 ms dauert **und** der Bass
um mindestens 6 dB weniger mitgeht.

**Warum die Gegenprobe.** Ohne sie zählt jeder Schlagzeugeinsatz als Knackser.
Gemessene Ereignisraten je Minute:

| Material | ohne Gegenprobe | mit Gegenprobe |
|---|---|---|
| Einlaufrille, Schallplatte | 132,6 | 124,3 |
| Knackser-Stelle, Schallplatte | 115,8 | 112,4 |
| Tonbandaufnahme | 12,6 | 10,6 |
| digitale Musik (Referenz für Fehltreffer) | 1,2 | 1,0 |

Die Erkennung verliert an echtem Material rund 3 % und drückt die Fehltreffer
auf etwa einen je Minute.

**Untergrund als Blockmedian.** Der lokale Untergrund wird über Blöcke von
0,5 Sekunden gebildet und linear verbunden. Ein gleitender Median wäre
sauberer, kostete aber ein Vielfaches an Rechenzeit; die Blockvariante
verarbeitet eine Fünf-Minuten-Aufnahme in gut zwei Sekunden.

**Grenze.** Was die Suche findet, ist ein Vorschlag zum Nachhören. Die
Zeitmarken lassen sich in der Oberfläche anklicken; sie zoomen das Spektrogramm
auf die Stelle.

---

## 6. Tiefton: Absolutpegel neben dem Verhältnis

**Die Regel.** Eine Rumpelwarnung braucht beides: Anteil unter 20 Hz weniger
als 12 dB unter dem Gesamtpegel **und** absolut über −55 dBFS. Brummspitzen
werden erst ab −95 dBFS überhaupt betrachtet.

**Warum.** In einer stillen Aufnahme liegt der Tiefstton zwangsläufig nahe am
Gesamtpegel, weil beides der Rauschboden ist. Ohne die Absolutschwelle meldete
ein Leerlaufmitschnitt bei −82 dBFS eine Rumpelwarnung. Ebenso stand in einer
stillen Aufnahme ein −110-dBFS-Artefakt als „Netzbrumm" im Bericht.

**Eigene Auflösung.** Die Analyse tastet auf 4 kHz herunter und rechnet mit
16k-Fenstern, also 0,24 Hz je Bin. Mit der Auflösung der Bildanalyse (23 Hz bei
48 kHz) ließen sich 50 Hz und 60 Hz nicht unterscheiden.

**Fallstrick aus der Praxis.** Eine erste Messung ergab 30 dB Rumpeln bei
laufendem Plattenspieler. Nachgeprüft stammte das aus **einem** Impuls (Nadel
absetzen); der Median lag bei −75 dBFS. Deshalb rechnet die Auswertung
durchgehend mit Medianen über Zeitfenster, nicht mit Mittelwerten.

---

## 7. Dauertöne: drei Bedingungen gleichzeitig

**Die Regel.** Ein Ton gilt als Einstreuung, wenn er schmal ist (höchstens
60 Hz bei −6 dB), leise gegenüber dem Programm (mindestens 30 dB unter dem
Maximum), lauter als −95 dB (darunter sind es Quantisierungsartefakte) und in
mindestens 80 % der Zeitabschnitte an derselben Stelle steht.

**Warum alle vier.** Mit nur zwei Bedingungen meldete die Prüfung gehaltene
Musiknoten bei 1 kHz. Mit der Untergrenze von −95 dB fielen zusätzlich
Artefakte oberhalb der Bandgrenze verlustbehafteter Dateien weg, die bei −108
bis −125 dB lagen.

**Wozu es gut ist.** An einer echten Kette fand die Prüfung einen Ton bei
19,37 kHz, der in Aufnahmen von Plattenspieler *und* Tonbandgerät auftrat, aber
nicht im Leerlauf ohne laufende Geräte — also eine Einstreuung der
Aufnahmeumgebung, nicht des Tonträgers.

---

## 8. Residual: Crest allein genügt nicht

**Die Regel.** Die Differenz zweier Fassungen wird nach Ausrichtung und
Pegelabgleich gebildet und über vier Kennzahlen beurteilt: Crest gegenüber dem
Original, Anteil in leisen und in lauten Abschnitten, und die Korrelation der
spektralen Form mit dem Programm.

**Warum nicht nur Crest.** Gemessen an Restaurationen:

| Bearbeitung | Crest des Residuals | Crest der Quelle |
|---|---|---|
| nur Entknacksen | 48 dB | 20 dB |
| Rauschunterdrückung | 38 dB | 20 dB |

Der Abstand trennt die beiden Fälle, sagt aber nichts darüber, *was* eine
Rauschunterdrückung entfernt hat. Dafür braucht es die Form: folgt das
spektrale Profil des Entfernten dem des Programms (r > 0,8), verschwindet nicht
nur ein Rauschteppich. An einer echten Restaurationskette wurden r = 0,93 bis
0,98 gemessen, bei einem Restsignal von 8 bis 12 dB unter dem Original in den
Musikpassagen.

**Was der Abgleich leisten kann und was nicht.** Ein konstanter Pegelunterschied
wird vollständig herausgerechnet. Darüber hinaus wurde geprüft, wie viel ein
optimaler linearer Filter, ein Pegelabgleich je Zeitfenster und ein Abgleich je
Band und Zeitfenster zusätzlich erklären:

| Abgleich | Restsignal |
|---|---|
| konstanter Pegel | −10,4 dB |
| optimaler linearer Filter | −12,8 dB |
| Pegel je Zeitfenster | −11,1 dB |
| Filter je Band und Zeitfenster | −11,2 dB |

Der Unterschied war also weder Entzerrung noch Dynamik. Zum Vergleich: reines
Entknacksen derselben Aufnahme ergibt −29 dB. Die aufwendigeren Abgleiche
stehen nicht im Programm, weil sie in dieser Messung kaum etwas beitrugen.

---

## 9. Ausrichtung zweier Aufnahmen

**Die Regel.** Grob-zu-fein-Suche direkt am spektralen Abstand, gedeckelt auf
ein Viertel der kürzeren Aufnahme, mit mindestens 70 % Überlappung und einer
leichten Bevorzugung kleiner Versätze.

**Warum nicht Kreuzkorrelation der Hüllkurve.** Bei gleichförmigem Material
(Rauschen, Dauertöne, Rillengeräusch) liegt sie daneben: In einem Test mit
einem künstlichen Versatz von 430 ms lieferte sie 4,3 Sekunden — schlechter als
gar keine Ausrichtung. Die Grob-zu-fein-Suche fand den Versatz exakt und
senkte das Restsignal von 15,7 auf 0,6 dB.

**Warum die Deckelung.** Ohne sie verschob die Suche bei periodischem Material
(Loops, Tremolo) um mehrere Sekunden, weil dort auch ein völlig falscher
Versatz gut passt.

---

## 10. Vergleich unterschiedlich langer Dateien

Das Spalten-Pooling arbeitet in Zweierpotenzen. Unterschiedlich lange Dateien
bekommen dadurch verschiedene Zeitraster — gemessen wurden 10,67 ms gegen
42,67 ms je Spalte. Ohne Angleichung verglich das Differenzbild verschiedene
Zeitpunkte miteinander. Die feinere Seite wird deshalb auf das gröbere Raster
gebracht.

---

## 11. Encoder-Leiter: was eine Bandgrenze verrät – und was nicht

Alle Fassungen stammen aus **einer** verlustfreien Quelle, in einem Durchgang
erzeugt. Gemessen wurde die Kante im Gesamtspektrum:

| Fassung | Kante | % Nyquist | Steilheit | erkannt |
|---|---|---|---|---|
| MP3 128 | 15,95 kHz | 72 % | 55 dB/kHz | ja |
| MP3 192 | 16,00 kHz | 73 % | 36 dB/kHz | ja |
| MP3 256 | 19,11 kHz | 87 % | 37 dB/kHz | ja |
| MP3 320 | 20,14 kHz | 91 % | 59 dB/kHz | ja |
| MP3 V0 | – | – | – | **nein** |
| AAC 128 | 19,93 kHz | 90 % | 59 dB/kHz | ja |
| AAC 256 | – | – | – | **nein** |
| Opus 96 | 20,48 kHz | 85 % | 59 dB/kHz | ja |
| Opus 192 | 20,46 kHz | 85 % | 60 dB/kHz | ja |
| Vorbis q6 | 19,94 kHz | 90 % | 45 dB/kHz | ja |
| Quelle (FLAC) | – | – | – | – (richtig) |

**Erste Folgerung: die Frequenz benennt keine Bitrate.** 128 und 192 kbit/s
liegen 50 Hz auseinander; im Bereich um 20 kHz treffen sich MP3 320, AAC 128,
Vorbis und Opus. Die frühere Zuordnungstabelle stammte aus Literaturwerten und
hätte MP3 128 als „um 160 kbit/s" ausgewiesen. Sie wurde durch drei grobe
Bereiche ersetzt, die nur noch niedrige, mittlere und hohe Bitrate
unterscheiden und ausdrücklich sagen, dass Format und Rate offen bleiben.

**Zweite Folgerung: die Schwelle „nahe Nyquist" lag zu tief.** Sie stand bei
90 % und schnitt damit MP3 320 (91 %), AAC 128 (90 %) und Vorbis (90 %) ab.
Gemessen liegt das Antialiasing-Filter eines 48-kHz-Wandlers dagegen bei 97 %.
Die Schwelle steht jetzt bei **94 %**, mit rund drei Prozentpunkten Abstand
nach beiden Seiten. Erkennungsrate der Leiter dadurch von fünf auf acht von
zehn gestiegen, ohne dass eine Analogaufnahme neu anschlägt.

**Dritte Folgerung: die Ganzdatei entscheidet.** MP3 320 zeigte die Kante in
nur 2 von 16 Abschnitten, AAC 128 in keinem einzigen – im Gesamtspektrum stand
sie bei beiden unübersehbar. Die abschnittsweise Auswertung dient jetzt nur
noch als Zusatzinformation.

**Die verbleibende Lücke ist gemessen, nicht vermutet.** MP3 V0 und AAC 256
haben keine Bandgrenze: ihr Spektrum folgt der Quelle bis 22 kHz. Bei diesem
Material konnte die Quelle oberhalb von 19 kHz ohnehin wenig bieten (dort schon
60 dB unter dem Maximum), sodass die Encoder nichts abschneiden mussten. Solche
Dateien sind am Spektrum nicht als verlustbehaftet erkennbar – die Bewertung
sagt das ausdrücklich.

### Gegenprobe mit einer zweiten Leiter

Dieselben zehn Fassungen, erzeugt aus einer **anderen** Quelle:

| Fassung | Leiter 1 | Leiter 2 |
|---|---|---|
| MP3 128 | 15,95 kHz | 15,97 kHz |
| MP3 192 | 16,00 kHz | **18,11 kHz** |
| MP3 256 | 19,11 kHz | 19,40 kHz |
| MP3 320 | 20,14 kHz | 20,07 kHz |
| MP3 V0 | **keine** | **20,19 kHz** |
| AAC 128 | 19,93 kHz | 19,91 kHz |
| AAC 256 | keine | keine |
| Opus 96 | 20,48 kHz | 20,38 kHz |
| Opus 192 | 20,46 kHz | 19,97 kHz |
| Vorbis q6 | 19,94 kHz | 18,97 kHz |
| erkannt | 8 von 10 | 9 von 10 |

**MP3 192 liegt bei gleicher Einstellung 2,1 kHz auseinander** – damit ist die
Aussage aus Abschnitt 11 nicht nur belegt, sondern verschärft: die Bandgrenze
hängt ebenso vom Material ab wie von der Bitrate. Ein Encoder senkt sie, wenn
das Programm oben nichts hergibt.

**MP3 V0 wurde in Leiter 2 erkannt, in Leiter 1 nicht.** Die Blindstelle liegt
also nicht am Encoder, sondern an der Quelle: hatte diese oberhalb von 19 kHz
schon kaum Inhalt, muss der Encoder nichts abschneiden, und es bleibt keine
Kante zu finden.

**AAC 256 blieb in beiden Leitern unerkannt.** In Leiter 2 zeigt es eine Kante
bei 21,4 kHz, also 96,9 % der Nyquist-Frequenz – genau dort, wo auch das
Antialiasing-Filter eines Wandlers sitzt (gemessen 96,6 %). Die beiden sind an
dieser Stelle nicht unterscheidbar; eine höhere Schwelle würde jede native
Aufnahme als Transcode melden. Das ist eine prinzipielle Grenze, keine
Einstellungsfrage.

### Die Auflösung darf das Urteil nicht bestimmen

Bei der Gegenprobe fiel auf, dass dieselbe Datei je nach FFT-Größe verschieden
bewertet wurde:

| Datei | nfft 1024 | 2048 | 4096 | 8192 | 16384 |
|---|---|---|---|---|---|
| MP3 V0 (Leiter 2) | 20,16 k | 20,16 k | 20,19 k | 20,80 k | 21,50 k |
| Vorbis q6 (Leiter 2) | 18,78 k | 18,76 k | 18,97 k | 20,69 k | 21,21 k |

Beide kippten bei 8192 oder 16384 von „konstante Bandkante" auf „kein
Steilabfall", weil die Kante über die 94-Prozent-Schwelle wanderte. Ursache ist
die Messung selbst: bei langem Fenster liegt der Rauschboden tiefer, der
Übergang zieht sich weiter, und die steilste Stelle liegt höher. Weder eine
pegelbasierte Kantendefinition noch das Mitteln der Bins auf eine gröbere
Auflösung glich das aus – die Unterschiede sind physikalisch, nicht numerisch.

Deshalb urteilt die Bandanalyse jetzt immer bei **nfft 4096**, unabhängig
davon, welche Größe für die Darstellung gewählt wurde. Passt die Einstellung,
wird das vorhandene Spektrum genutzt; sonst wird eigens dafür noch einmal
analysiert. Das kostet auf eine Fünf-Minuten-Datei 0,8 Sekunden und macht das
Urteil reproduzierbar.

### Verlustfreie Exoten

Dasselbe Material als WAV, ALAC, WavPack und Monkey's Audio – die dekodierten
Spuren haben identische Prüfsummen. Alle vier Berichte stimmen in jedem Feld
überein, die Nullprobe gegen die WAV-Referenz ergibt −221,69 dB. Der
Dekodierpfad und die Auswertung der Containerangaben behandeln die Formate
also gleich.

Dabei fiel auf, dass das Muster **„vereinzelte Kante" nie etwas aussagte.**
Seit die Ganzdatei über die Bandbegrenzung entscheidet (Abschnitt 11), trat es
nur noch dort auf, wo im Gesamtspektrum gar keine Kante steht – an 41 geprüften
Dateien ausschließlich bei diesem sauberen verlustfreien Sample, in 4 von 16
Abschnitten bei 12,8 kHz. Einzelne Abschnitte einer Aufnahme erfüllen die
Kantenbedingung rein zufällig. Die Einstufung entfiel deshalb; die
Abschnittszahlen bleiben als Kennzahl im Bericht.

### Netzbrumm: die Empfindlichkeit hängt am Programm, nicht an einem Festwert

Geprüft mit einem Sägezahn – dieselbe Wellenform wie echter Netzbrumm, also
mit allen Harmonischen –, unter brummfreies Programm gemischt:

| Beimischung | Pegel der Spitze | erkannt |
|---|---|---|
| −30 dB | −40 dBFS | ja, Netzfrequenz richtig bestimmt |
| −45 dB | −53 dBFS | nein |
| −60 dB und leiser | – | nein |

Das wirkt streng, ist aber richtig: im Programm liegt der Bereich um 50 bis
60 Hz ohnehin bei −57 dBFS, ein Brumm bei −53 dBFS steht also gerade einmal auf
dem Niveau seiner Umgebung (Prominenz 0 dB) und ist weder messbar noch hörbar.
Zum Vergleich eine echte Einlaufrille: dort liegt der Brumm bei −71 dBFS, das
Rillenrauschen daneben aber bei −93 dBFS – Prominenz 21 dB, mühelos zu finden.

**Maßgeblich ist also der Abstand zum lokalen Untergrund, nicht der
Absolutpegel.** Die Schwelle von 8 dB Prominenz gilt unverändert; leiser Brumm
unter kräftigem Bass bleibt unentdeckt, weil er dort tatsächlich verschwindet.

Bei der Gelegenheit fiel auf, dass `mains_hz` auch dann eine Frequenz nannte,
wenn überhaupt keine Spitze gefunden wurde – der Wert war dann geraten. Er ist
jetzt leer, solange nichts gefunden wurde.

### Übersteuerung: Flat factor und Spitzenrate, nicht der True Peak

Gemessen an einem Master aus der Lautheitskrieg-Ära gegen elf andere
Aufnahmen:

| Aufnahme | LUFS | True Peak | Flat factor | Spitzen je Minute |
|---|---|---|---|---|
| Lautheitskrieg-Master | −7,4 | +0,4 dBTP | **0,99** | **151** |
| lautes Quellmaterial 1 | −4,6 | +1,9 dBTP | 0,0 | 1,5 |
| lautes Quellmaterial 2 | −7,7 | +0,1 dBTP | 0,0 | 8,5 |
| MP3 320 derselben Quelle | −4,6 | +2,0 dBTP | 0,0 | 0,4 |
| Tonband | −14,7 | −1,2 dBTP | 0,0 | 0,2 |
| Einlaufrille | −40,8 | −9,8 dBTP | 0,0 | 0,4 |

**Der True Peak allein taugt nicht als Kriterium.** Er lag bei fünf von zwölf
Aufnahmen über der Vollaussteuerung, darunter bei sauberen, nur eben lauten
Fassungen – bei einer sogar bei +2,0 dBTP, ohne dass das Master abgeflacht
wäre. Er wird deshalb nur noch als milderer Hinweis gemeldet.

**Flat factor und Spitzenrate trennen dagegen sauber:** null gegen 0,99 und
0,4 bis 8,5 gegen 151 je Minute. Beides zusammen führt zur Warnung.

Gezählt wird die Rate je Minute, nicht die absolute Zahl – eine lange Aufnahme
sammelt sonst zwangsläufig mehr Spitzen an.

**Eine Verankerung am Pegel ist nötig.** In digitaler Stille liegt jedes Sample
auf dem Extremwert des Signals, `astats` zählt dort also jedes einzelne als
Spitze: 2,6 Millionen je Minute für eine leere Datei. Die Beurteilung verlangt
deshalb zusätzlich einen Spitzenpegel oberhalb von −1 dBFS.

Nebenbei zeigte sich ein bekannter Effekt an echtem Material: dieselbe Quelle
stieg durch die MP3-Kodierung von +1,9 auf +2,0 dBTP.

### Netzbrumm gegen Musikbass: die Prominenzschwelle lag zu tief

Ein kommerzielles Master aus der Lautheitskrieg-Ära brachte die Prüfung zum
Fehlurteil: gemeldet wurde „Netzbrumm bei 60 Hz und Vielfachen, am stärksten
180 Hz". Tatsächlich war das ein Bassanteil der Musik. Die Gegenüberstellung
über elf Aufnahmen:

| Aufnahme | Kandidat | Prominenz |
|---|---|---|
| Plattenspieler im Leerlauf (Brumm nachgewiesen) | 50 Hz | 39,5 dB |
| Einlaufrille (Brumm nachgewiesen) | 50 Hz | 23,7 dB |
| Vinylrip mit Musik (Brumm nachgewiesen) | 50 Hz | 15,9 dB |
| **Popmaster** | 180 Hz | **9,9 dB** |
| **lautes Quellmaterial** | 60 Hz | **10,1 dB** |
| **CD-Sample** | 240 Hz | **9,7 dB** |
| Tapedeck im Leerlauf | 150 Hz | 9,8 dB |

Die Gruppen trennen sich sauber zwischen 10,1 und 15,9 dB. Die Schwelle steht
jetzt bei **14 dB** statt bei 8. Zeitbeständigkeit taugte dafür nicht: der
180-Hz-Anteil des Masters stand in allen acht Zeitabschnitten, genau wie echter
Brumm.

Der Preis ist eine geringere Empfindlichkeit. In der Mischprobe aus dem
vorigen Abschnitt hatte ein beigemischter Brumm bei −40 dBFS eine Prominenz von
10,3 dB – der würde jetzt nicht mehr gemeldet. Das ist die richtige
Entscheidung: bei 10 dB Prominenz ist Brumm von Musik nicht zu unterscheiden,
und eine Warnung auf jedem Popmaster wäre wertlos.

### Limitiert ist nicht übersteuert

Ein zweites Beispiel aus der Lautheitskrieg-Ära lag mit −4,9 LUFS und einem
Crest-Faktor von 8,6 dB noch weiter oben als das erste – zeigte aber Flat
factor 0,0 und ein einziges Sample an der Vollaussteuerung. Das Master ist also
hart limitiert, nicht übersteuert; die Übersteuerungsprüfung schwieg zu Recht.

Damit sagte das Programm über ein offensichtlich zusammengedrücktes Master
allerdings gar nichts. Die Gegenüberstellung von zehn Aufnahmen liefert eine
saubere Trennung:

| Gruppe | Crest-Faktor | Lautheit |
|---|---|---|
| laute Masters | 7,6 – 12,2 dB | −4,6 bis −9,2 LUFS |
| Rips von Platte und Band | 15,7 – 27,3 dB | −14,7 bis −40,8 LUFS |

Seit der Änderung stellt der Bericht bei einem Crest-Faktor unter 12,5 dB und
einer Lautheit über −12 LUFS fest, dass das Master stark zusammengedrückt ist –
ohne Warnstufe, denn das ist eine Produktionsentscheidung und kein Defekt.

### Gleichlauf: an bekannter Schwankung geeicht

Die Messung entnimmt die Momentanfrequenz eines Messtons der Hilbert-
Transformierten des schmalbandig gefilterten Signals; ihr Modulationsspektrum
trennt Wow (0,2–6 Hz) von Flutter (6–100 Hz). Geprüft wurde gegen künstlich
erzeugte Töne mit genau vorgegebenem Effektivwert:

| Vorgabe | gemessen | Modulationsfrequenz |
|---|---|---|
| 0,00 % (unmoduliert) | 0,000 % | – |
| 0,10 % bei 0,55 Hz | 0,098 % | 0,49 Hz |
| 0,30 % bei 0,55 Hz | 0,295 % | 0,49 Hz |
| 0,50 % bei 3,0 Hz | 0,500 % | 2,93 Hz |

Die Abweichung bleibt unter zwei Prozent des Messwerts, ein unmodulierter Ton
ergibt exakt null. Die Auflösung des Modulationsspektrums beträgt 0,24 Hz,
weshalb 0,55 Hz als 0,49 Hz erscheint.

**Voraussetzung ist ein Dauerton.** Als Kriterium dient der Anteil der
Spektralspitze an der Gesamtenergie: reines Rauschen 0,003, Musik 0,05, ein
Messton 0,48 bis 1,00. Die Schwelle liegt bei 0,20.

**An einer echten Messschallplatte** (315 Hz nach DIN, über einen
Plattenspieler aufgenommen): Trägerfrequenz 312,0 Hz, also 0,95 % zu langsam;
Wow 0,148 %, Flutter 0,076 %. Die stärkste Schwankung lag bei 0,49 Hz und
damit im Takt einer Umdrehung bei 33 min⁻¹ – ein Hinweis auf eine außermittige
Pressung oder einen Rundlauffehler, den der Bericht seitdem ausdrücklich nennt.

Ohne scipy umgesetzt: analytisches Signal, Bandpass und gemitteltes
Leistungsdichtespektrum sind mit numpy wenige Zeilen, und die Ergebnisse
stimmen mit der scipy-Fassung auf drei Nachkommastellen überein.

### Aufbau des Analysekerns

`app/core.py` ist nur noch eine Fassade: sie führt die Module zusammen und
bleibt die Schnittstelle für CLI, Web-Schicht und Tests. Der Code liegt nach
Zuständigkeiten getrennt daneben.

| Modul | Zeilen | Inhalt |
|---|---|---|
| `params.py` | 160 | Parameter, Konstanten, Fehlerklasse |
| `audio.py` | 223 | Dekodierung und Messwerte über ffmpeg |
| `stft.py` | 152 | Kurzzeit-Fouriertransformation |
| `band.py` | 351 | Bandkante, Bandbreite, Dauertöne |
| `render.py` | 197 | Frequenzachsen und Spektrogramme |
| `compare.py` | 460 | Ausrichtung, Differenz, Nullprobe, Residual |
| `measure.py` | 587 | Tiefton, Gleichlauf, Frequenzgang, Impulse, Pegel |
| `report.py` | 83 | zusammengesetzte Berichte |
| `core.py` | 98 | Fassade |

Vorher lag all das in einer Datei mit 2123 Zeilen und 48 Funktionen. Beim
Entfernen eines einzelnen Musters hatte ich dort einmal versehentlich sieben
Funktionen mitgelöscht – genau der Fehler, den eine solche Datei begünstigt.

Die Zerlegung ändert kein Verhalten. Belegt ist das doppelt: alle Tests laufen
unverändert durch, und ein Bericht über drei Dateien ergibt vor und nach der
Zerlegung dieselbe Prüfsumme.

### Die Ergebnisablage muss beschreibbar sein, nicht bloß vorhanden

Ein CI-Lauf meldete einen Fehlschlag, der lokal nie auftrat: nach einem zweiten
Scan kam kein einziges Ergebnis aus der Ablage. Ursache war nicht die Ablage
selbst, sondern der Vorgabepfad `/data/index`. Lokal lief die Suite als root und
konnte ihn anlegen, auf dem Läufer nicht – die Ablage schaltete sich still ab.

Zwei Dinge waren daran falsch. Erstens prüfte `SidecarStore` nur, ob sich der
Ordner anlegen lässt. Ein bestehender, aber schreibgeschützter Ordner galt
damit als nutzbar: die Ablage meldete sich als aktiv, verwarf aber jeden
Eintrag, und jeder Scan rechnete alles neu, ohne dass es auffiel. Jetzt wird
beim Start eine Datei geschrieben und wieder entfernt.

Zweitens schaltete sich die Ablage bei einem unbrauchbaren Pfad ganz ab. Sie
weicht nun auf `~/.cache/spectro/index` aus und schreibt eine Warnung ins
Protokoll. Im Container ändert sich nichts, außerhalb funktioniert der Scan
damit auch ohne gesetztes `SIDECAR_DIR`.

Die Testumgebung setzt den Pfad jetzt selbst, und der Test prüft zusätzlich,
dass die Ablage überhaupt aktiv ist – sonst steht die Ursache wieder nirgends.
