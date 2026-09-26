"""Texte der Bewertungen in mehreren Sprachen.

Die Analyse liefert Kennzahlen; erst hier werden daraus Sätze. Jeder Text hat
einen Schlüssel und wird mit den gemessenen Werten formatiert. Eine neue
Sprache besteht deshalb aus einem weiteren Eintrag in MESSAGES - am Code der
Analyse ändert sich nichts.

Zahlen werden je Sprache passend gesetzt: im Deutschen mit Komma, im
Englischen mit Punkt.
"""

from __future__ import annotations

from contextvars import ContextVar

DEFAULT_LANG = "de"
LANGUAGES = ("de", "en")

MESSAGES: dict[str, dict[str, str]] = {
    "de": {
        # --- Bandkante ---------------------------------------------------
        "band.none": (
            "Keine harte Bandkante. Die Signalenergie reicht bis etwa {bw}"
            "{soft}. Das schließt eine verlustbehaftete Quelle nicht aus: "
            "Encoder mit hoher Bitrate und ohne Tiefpass hinterlassen keine "
            "sichtbare Kante."),
        "band.none_nobw": (
            "Keine harte Bandkante gefunden. Das schließt eine verlustbehaftete "
            "Quelle nicht aus: Encoder mit hoher Bitrate und ohne Tiefpass "
            "hinterlassen keine sichtbare Kante."),
        "band.soft": (
            " und fällt darüber weich ab, wie es Bandmaschinen, Schallplatten "
            "und leise Aufnahmen tun"),
        "band.upsampled_sharp": (
            "Das Spektrum bricht bei {stop} ab (Rauschboden {floor:.0f} dB)."),
        "band.upsampled_slope": (
            "Das Spektrum fällt ab {edge} ab und erreicht bei {stop} den "
            "Rauschboden ({floor:.0f} dB)."),
        "band.upsampled": (
            "{how} Das ist die Bandgrenze einer {rate}-Aufnahme – die {sr:g} kHz "
            "tragen keine zusätzliche Information."),
        "band.transcode": (
            "Konstante Bandbegrenzung bei {edge} in einem verlustfreien "
            "Container – möglicher Transcode{hint}."),
        "band.transcode_hint": " (die Grenze passt zu {what})",
        "band.limited": "Bandbegrenzung bei {edge}{hint}.",
        "band.limited_hint": ", typisch für {what}",
        "rate.44100": "44,1 kHz", "rate.48000": "48 kHz", "rate.88200": "88,2 kHz",
        "hint.low": ("eine verlustbehaftete Kodierung mit niedriger Bitrate " +
                     "(MP3 oder AAC um 128 bis 192 kbit/s)"),
        "hint.mid": ("eine verlustbehaftete Kodierung mittlerer Bitrate"),
        "hint.high": ("eine verlustbehaftete Kodierung mit hoher Bitrate " +
                      "(MP3 256 oder 320, AAC, Vorbis oder Opus) – die " +
                      "Frequenz allein benennt weder Format noch Bitrate"),

        # --- Tiefton -----------------------------------------------------
        "low.hum": (
            "Netzbrumm bei {mains} Hz und Vielfachen, am stärksten {hz:.0f} Hz "
            "mit {level:.0f} dBFS. Meist hilft die Masseverbindung des "
            "Plattenspielers oder ein größerer Abstand der Signalkabel zu "
            "Netzteilen."),
        "low.hum_weak": "Schwacher Netzbrumm bei {mains} Hz ({level:.0f} dBFS) – unkritisch.",
        "low.rumble": (
            "Kräftiger Tiefstton unter 20 Hz ({level:.0f} dBFS, nur {rel:.0f} dB "
            "unter dem Gesamtpegel) – Rumpeln oder eine wellige Platte. Ein "
            "Rumpelfilter bei 20 Hz entlastet Verstärker und Tieftöner."),
        "low.rumble_mild": (
            "Messbarer Anteil unter 20 Hz ({level:.0f} dBFS), aber {rel:.0f} dB "
            "unter dem Gesamtpegel – für einen Rip von Schallplatte üblich."),
        "dyn.compressed": ("Stark zusammengedrücktes Master: Crest-Faktor "
                           "{crest:.1f} dB bei {lufs:.1f} LUFS. Kein Mangel, "
                           "sondern eine Produktionsentscheidung – Rips von "
                           "Platte und Band liegen bei 16 bis 27 dB."),
        "clip.clipped": ("Das Master ist übersteuert: {n} Samples liegen an der "
                         "Vollaussteuerung ({rate:.0f} je Minute), die Signalspitzen "
                         "sind abgeflacht (Flat factor {flat:.2f})."),
        "clip.truepeak": ("True Peak bei {tp:+.1f} dBTP, also oberhalb der "
                          "Vollaussteuerung. Bei der Wandlung oder einer "
                          "verlustbehafteten Kodierung kann das hörbar verzerren."),
        "low.clean": (
            "Tieftonbereich unauffällig: kein nennenswertes Rumpeln, kein "
            "Netzbrumm."),

        # --- Impulsstoerungen --------------------------------------------
        "imp.none": "Praktisch keine Impulsstörungen gefunden.",
        "imp.few": (
            "Vereinzelte Impulsstörungen ({rate:.0f} pro Minute) – für einen Rip "
            "von Schallplatte oder Band normal."),
        "imp.many": "Deutliches Knistern ({rate:.0f} Ereignisse pro Minute).",
        "imp.constant": (
            "Durchgehendes Knistern ({rate:.0f} Ereignisse pro Minute) – die "
            "Störungen liegen flächig über dem Material, nicht nur an einzelnen "
            "Stellen."),
        "imp.strong": (
            " Davon {n} kräftige Knackser (bis {db:.0f} dB über dem Untergrund)."),

        # --- Nullprobe ---------------------------------------------------
        "null.unrelated": "kein gemeinsamer Ursprung erkennbar (Korrelation {corr:.2f})",
        "null.identical": "Restsignal unter -60 dB – bitgenau oder praktisch identisch",
        "null.lossy": (
            "Restsignal {depth:.1f} dB – gleiche Quelle. So viel trennt eine "
            "verlustbehaftete Kodierung oder eine Bearbeitung wie Entknacksen "
            "vom Original"),
        "null.mastering": (
            "Restsignal {depth:.1f} dB – gleiche Aufnahme, aber deutlich anderes "
            "Mastering oder starke Kompression"),
        "null.distant": "Restsignal {depth:.1f} dB – allenfalls entfernt verwandtes Material",

        # --- Residual ----------------------------------------------------
        "res.impulses": (
            "Das Residual besteht fast nur aus kurzen Impulsen – entfernt wurden "
            "Knackser."),
        "res.gate": (
            "In den leisen Abschnitten wird praktisch das ganze Signal entfernt – "
            "so verhält sich eine kräftige Rauschunterdrückung oder ein Gate. Bei "
            "Einlauf- und Auslaufrillen ist das gewollt, mitten im Stück nicht."),
        "res.loud": (
            "In den lauten Abschnitten liegt das Entfernte {db:.0f} dB unter dem "
            "Original."),
        "res.follows": (
            "Seine spektrale Form folgt dabei eng dem Programm (r = {r:.2f}) – es "
            "ist also nicht nur ein Rauschteppich, der verschwindet. Ein "
            "Kontrollhören lohnt sich."),
        "res.noise": (
            "Seine spektrale Form ist von der des Programms unabhängig – das "
            "spricht für Rauschen und Störungen."),
        "res.mixed": (
            "Das Residual enthält Impulse und kontinuierliches Signal in "
            "gemischtem Verhältnis."),

        # --- Fehlermeldungen ---------------------------------------------
        "wow.speed_ok": ("Drehzahl stimmt: {ist:.2f} Hz gegenüber {nominal:.0f} Hz "
                         "Sollfrequenz, das sind {dev:+.2f} %."),
        "wow.speed_off": ("Die Drehzahl weicht um {dev:+.2f} % ab: {ist:.2f} Hz "
                          "statt {nominal:.0f} Hz. Hörbar wird das erst im "
                          "direkten Vergleich, messbar ist es deutlich."),
        "wow.speed_far": ("Die Drehzahl weicht um {dev:+.2f} % ab: {ist:.2f} Hz "
                          "statt {nominal:.0f} Hz – das entspricht einer "
                          "merklichen Tonhöhenverschiebung."),
        "wow.good": ("Gleichlauf unauffällig: Wow {wow:.3f} %, Flutter "
                     "{flutter:.3f} % (Effektivwert, ungewichtet)."),
        "wow.fair": ("Gleichlauf im üblichen Rahmen: Wow {wow:.3f} %, Flutter "
                     "{flutter:.3f} % (Effektivwert, ungewichtet). Bei lang "
                     "gehaltenen Tönen kann das hörbar werden."),
        "wow.poor": ("Deutliche Gleichlaufschwankungen: Wow {wow:.3f} %, Flutter "
                     "{flutter:.3f} % (Effektivwert, ungewichtet)."),
        "wow.eccentric": ("Die stärkste Schwankung liegt bei {hz:.2f} Hz, also im "
                          "Takt einer Umdrehung bei {upm:.0f} min⁻¹ – das spricht "
                          "für eine außermittige Pressung oder einen "
                          "Rundlauffehler."),
        "sweep.response": ("Frequenzgang {kanal}: {spanne:.1f} dB Spanne zwischen "
                           "40 Hz und 10 kHz ({lo:+.1f} bis {hi:+.1f} dB gegenüber "
                           "dem Bezugston)."),
        "sweep.highs": ("Oberhalb von 10 kHz fällt {kanal} um bis zu {db:.1f} dB ab."),
        "sweep.sep_good": "Kanaltrennung {db:.0f} dB – für einen Tonabnehmer gut.",
        "sweep.sep_fair": "Kanaltrennung {db:.0f} dB – brauchbar, aber nicht üppig.",
        "sweep.sep_poor": ("Kanaltrennung nur {db:.0f} dB – das schmälert die "
                           "Stereoabbildung hörbar. Meist lohnt ein Blick auf "
                           "Azimut und Auflagekraft."),
        "sweep.none": "Zu wenige auswertbare Tonstufen gefunden.",
        "err.no_sweep": ("keine Tonfolge gefunden – für Frequenzgang und "
                         "Kanaltrennung werden gehaltene Messtöne gebraucht"),
        "err.too_short_wow": "zu wenig Audiomaterial für eine Gleichlaufmessung",
        "err.no_tone": ("kein ausreichend stabiler Dauerton gefunden – für die "
                        "Gleichlaufmessung wird ein Messton gebraucht"),
        "err.no_stream": "keine Audiospur gefunden",
        "err.no_samples": "keine Samples dekodiert (leere oder defekte Datei?)",
        "err.no_ffmpeg": "ffmpeg/ffprobe nicht gefunden (Paket 'ffmpeg' installieren)",
        "err.timeout": "Zeitüberschreitung bei der Analyse",
        "err.silent": ("mindestens eine der beiden Dateien ist (nahezu) still – "
                       "eine Nullprobe ergibt hier keinen Sinn"),
        "err.no_overlap": "kein ausreichender gemeinsamer Bereich gefunden",
        "err.too_short_null": "zu wenig Audiomaterial für eine Nullprobe",
        "err.too_short_imp": "zu wenig Audiomaterial für eine Störungssuche",
        "err.too_short_low": "zu wenig Audiomaterial für die Tieftonanalyse",
        "err.too_short_mod": "zu wenig Material für die Modulationsanalyse",
        "err.no_samples_from": "keine Samples aus {name}: {err}",
        "param.not_finite": "{name} muss eine endliche Zahl sein",
        "param.nfft": "nfft muss eine Zweierpotenz >= 32 sein",
        "param.overlap": "overlap muss zwischen 0 und 0.95 liegen",
        "param.window": "unbekanntes Fenster: {value}",
        "param.scale": "unbekannte Skala: {value}",
        "param.channels": "unbekannter Kanalmodus: {value}",
        "param.cmap_invalid": "ungültige Colormap",
        "param.cmap": "unbekannte Colormap: {value}",
        "param.theme": "unbekanntes Theme: {value}",
        "param.freq_close": "fmin und fmax liegen zu dicht beieinander",
        "param.sr": "sr muss zwischen 1000 und 768000 Hz liegen",

        # --- Kanalbezeichnungen -------------------------------------------
        "ch.mono_sum": "Mono-Summe", "ch.mono": "Mono",
        "ch.left": "Links", "ch.right": "Rechts",
        "ch.mid": "Mid (L+R)", "ch.side": "Side (L-R)",
        "ch.n": "Kanal {n}",

        # --- Bild ---------------------------------------------------------
        "plot.freq": "Frequenz [Hz]", "plot.time": "Zeit [min:s]",
        "plot.level": "Pegel [dB rel. Peak]", "plot.diff": "Differenz [dB]",
        "plot.difference": "Differenz A - B",
        "plot.diff_note": ("unterhalb {band}: Median {median:+.1f} dB, "
                           "90-Perzentil |Δ| {p90:.1f} dB"),

        # --- CLI ----------------------------------------------------------
        "cli.no_edge": "keine Bandkante",
        "cli.edge": "Kante {edge} ({n}/{total} Abschnitte)",
        "cli.signal_to": "Signal bis {bw}",
        "cli.sweep": "Frequenzgang {kanal}: {werte}",
        "cli.up_missing": "Upload-Ordner nicht gefunden: {path}",
        "cli.up_none": "Keine Uploads vorhanden.",
        "cli.up_unknown": "kein Upload mit diesem Namen: {name}",
        "cli.up_confirm": "{n} Upload(s) löschen ({namen})?",
        "cli.up_deleted": "{n} Upload(s) gelöscht, {mb:.1f} MB frei.",
        "cli.up_total": "{n} Upload(s), zusammen {mb:.1f} MB.",
        "cli.wow": ("Gleichlauf: Träger {hz:.2f} Hz, Wow {wow:.3f} %, Flutter "
                    "{flutter:.3f} %, stärkste Modulation {mod:.2f} Hz"),
        "cli.impulses": ("Impulsstörungen: {count} ({rate}/min), davon {strong} "
                         "kräftig"),
        "cli.low": "Tiefton: unter 20 Hz {sub:.0f} dBFS ({rel:+.0f} dB rel.), Netz {mains} Hz",
        "cli.low_nohum": "Tiefton: unter 20 Hz {sub:.0f} dBFS ({rel:+.0f} dB rel.), kein Brumm",
        "cli.null": ("Nullprobe: {depth:.2f} dB Restsignal, Korrelation {corr:.4f}, "
                     "Versatz {offset:+.2f} ms"),
        "cli.residual": ("Residual: {path}  ({depth:.1f} dB unter A, Crest {crest:.0f} dB "
                         "gegenüber {src:.0f} dB im Original)"),
        "cli.diff": ("Differenz: Median {median:+.2f} dB, 90-Perzentil |Δ| {p90:.2f} dB, "
                     "Versatz {offset:+.3f} s"),
        "cli.skipped": "übersprungen (nicht gefunden): {path}",
        "cli.error_at": "Fehler bei {path}: {msg}",
        "cli.scan_summary": ("{count} Dateien, {warn} auffällig, {computed} neu gerechnet, "
                             "{cached} aus der Ablage, {errors} Fehler"),
        "cli.csv_written": "CSV geschrieben: {path}",
        "cli.not_a_dir": "Fehler: {path} ist kein Verzeichnis",
        "cli.error": "Fehler: {msg}",
        "cli.compare_png": "vergleich.png",
        "cli.cmp_file": "{tag}: {name} · {codec} · {rate:g} kHz · Bandkante {edge}",
        "cli.null_error": "Nullprobe: {msg}",
        "cli.residual_error": "Residual: {msg}",
        "cli.yes_no": "[j/N]",
        "cli.prune": "Ergebnisablage: {checked} geprüft, {removed} entfernt, {kept} behalten.",
        "cli.index_needed": "Fehler: --prune braucht --index",
        "cli.index_unusable": "Fehler: Ergebnisablage nicht nutzbar: {msg}",
        "help.description": "Erzeugt Spektrogramme aus Audiodateien (Dekodierung über ffmpeg).",
        "help.meta_file": "DATEI",
        "help.meta_folder": "ORDNER",
        "help.g_compare": "Vergleich",
        "help.g_analysis": "Analyse",
        "help.g_uploads": "Uploads",
        "help.g_display": "Darstellung",
        "help.output": "Ziel-PNG (nur bei einer Datei oder einem Vergleich)",
        "help.outdir": "Zielverzeichnis bei mehreren Dateien",
        "help.compare": "zwei Dateien übereinander zeichnen",
        "help.no_diff": "Differenzbild weglassen",
        "help.no_align": "Zeitversatz nicht automatisch ausgleichen",
        "help.diff_range": "Skala des Differenzbildes [± dB]",
        "help.null": "zusätzlich eine sample-genaue Nullprobe rechnen",
        "help.residual": "Differenz A−B als hörbare FLAC-Datei schreiben",
        "help.residual_gain": "das Residual beim Schreiben anheben [dB]",
        "help.fft": "FFT-Größe (Zweierpotenz)",
        "help.overlap": "Fensterüberlappung 0..0,95",
        "help.window": "Fensterfunktion",
        "help.channels": "Kanäle",
        "help.sr": "Resampling-Rate (Standard: Originalrate)",
        "help.start": "Startzeit [s]",
        "help.duration": "Länge [s]",
        "help.scan": "Ordner rekursiv prüfen statt einzelne Dateien zeichnen",
        "help.index": "Ergebnisablage für --scan (nur Geändertes wird neu gerechnet)",
        "help.refresh": "Ablage ignorieren und alles neu messen",
        "help.prune": ("Ergebnisablage aufräumen: Einträge zu gelöschten oder "
                       "geänderten Dateien entfernen (mit --index)"),
        "help.jobs": "gleichzeitig geprüfte Dateien bei --scan",
        "help.csv": "Scan-Ergebnis als CSV schreiben",
        "help.seconds": "Ausschnitt je Datei bei --scan [s]",
        "help.lowfreq": "Tiefton, Rumpeln und Netzbrumm untersuchen",
        "help.wow": "Gleichlauf messen (braucht einen Dauerton)",
        "help.nominal": "Sollfrequenz des Messtons, sonst automatisch",
        "help.sweep": "Frequenzgang und Kanaltrennung aus einer Tonfolge",
        "help.clicks": "Impulsstörungen (Knackser) suchen und auflisten",
        "help.cutoff": "Bandbreite schätzen und bewerten (Lossy-Erkennung)",
        "help.json": "vollständigen Analysebericht als JSON ausgeben",
        "help.no_image": "kein PNG schreiben",
        "help.uploads": "Uploads auflisten (im Container: /data/uploads)",
        "help.upload_dir": "Ort der Uploads, sonst UPLOAD_DIR oder /data/uploads",
        "help.delete": "Upload löschen, mehrfach angebbar",
        "help.delete_all": "alle Uploads löschen",
        "help.yes": "Rückfrage beim Löschen übergehen",
        "help.scale": "Frequenzachse",
        "help.fmin": "untere Frequenzgrenze [Hz]",
        "help.fmax": "obere Frequenzgrenze [Hz]",
        "help.db_range": "Dynamikbereich [dB]",
        "help.db_top": "Pegel am oberen Ende der Farbskala [dB]",
        "help.cmap": "Farbskala (matplotlib)",
        "help.theme": "Farbschema",
        "help.width": "Bildbreite [Zoll]",
        "help.height": "Höhe je Bildfeld [Zoll]",
        "help.dpi": "Auflösung [dpi]",
        "help.max_cols": "höchste Spaltenzahl (längere Aufnahmen werden verdichtet)",
        "help.raw": "nur Grafik, ohne Achsen",
        "help.title": "Bildtitel (Standard: Dateiname)",
        "help.lang": "Sprache der Ausgaben (Standard: LANG_DEFAULT, sonst de)",
        "help.quiet": "nur Fehler ausgeben",
        "csv.file": "Datei", "csv.path": "Pfad", "csv.codec": "Codec",
        "csv.rate": "Samplerate", "csv.channels": "Kanäle", "csv.bitrate": "Bitrate",
        "csv.duration": "Dauer_s", "csv.edge": "Bandkante_Hz", "csv.pattern": "Muster",
        "csv.level": "Bewertung", "csv.note": "Hinweis",

        # --- HTTP ---------------------------------------------------------
        "http.unknown_root": "unbekannter Ordner: {root}",
        "http.not_found": "Datei nicht gefunden",
        "http.not_a_file": "kein regulaeres File",
        "http.not_a_dir": "kein Verzeichnis",
        "http.no_permission": "keine Leseberechtigung",
        "http.outside": "Pfad ausserhalb des freigegebenen Ordners",
        "http.bad_value": "ungueltiger Wert fuer {name}",
        "http.too_many_files": "hoechstens {n} Dateien je Upload",
        "http.too_large": "groesser als {mb:g} MB",
        "http.no_multipart": "erwartet wird ein Upload als multipart/form-data",
        "http.bad_upload": "Upload unvollständig oder fehlerhaft",
        "plot.offset": "Versatz {offset:+.3f} s",
        "plot.cutoff": "Bandkante ~{edge}",
        "plot.channels": "{n} Kanäle",
        "pattern.voll": "kein Steilabfall",
        "pattern.konstant": "konstante Bandkante",
        "pattern.hochgesampelt": "hochgesampelt",
    },

    "en": {
        "band.none": (
            "No hard band edge. Signal energy extends to about {bw}{soft}. This "
            "does not rule out a lossy source: encoders running at high bitrates "
            "without a lowpass leave no visible edge."),
        "band.none_nobw": (
            "No hard band edge found. This does not rule out a lossy source: "
            "encoders running at high bitrates without a lowpass leave no "
            "visible edge."),
        "band.soft": (
            " and rolls off gently above that, the way tape machines, records "
            "and quiet recordings do"),
        "band.upsampled_sharp": (
            "The spectrum stops dead at {stop} (noise floor {floor:.0f} dB)."),
        "band.upsampled_slope": (
            "The spectrum starts falling at {edge} and reaches the noise floor "
            "at {stop} ({floor:.0f} dB)."),
        "band.upsampled": (
            "{how} That is the band limit of a {rate} recording – the {sr:g} kHz "
            "carry no additional information."),
        "band.transcode": (
            "Constant band limit at {edge} inside a lossless container – "
            "possible transcode{hint}."),
        "band.transcode_hint": " (the limit matches {what})",
        "band.limited": "Band limit at {edge}{hint}.",
        "band.limited_hint": ", typical of {what}",
        "rate.44100": "44.1 kHz", "rate.48000": "48 kHz", "rate.88200": "88.2 kHz",
        "hint.low": ("a lossy encoding at a low bitrate (MP3 or AAC around 128 to 192 kbit/s)"),
        "hint.mid": ("a lossy encoding at a medium bitrate"),
        "hint.high": ("a lossy encoding at a high bitrate (MP3 256 or 320, " +
                      "AAC, Vorbis or Opus) – the frequency alone identifies " +
                      "neither format nor bitrate"),

        "low.hum": (
            "Mains hum at {mains} Hz and its harmonics, strongest at {hz:.0f} Hz "
            "with {level:.0f} dBFS. Usually the turntable's ground connection or "
            "more distance between signal cables and power supplies fixes it."),
        "low.hum_weak": "Faint mains hum at {mains} Hz ({level:.0f} dBFS) – harmless.",
        "low.rumble": (
            "Strong content below 20 Hz ({level:.0f} dBFS, only {rel:.0f} dB "
            "below the overall level) – rumble or a warped record. A subsonic "
            "filter at 20 Hz takes the load off amplifier and woofers."),
        "low.rumble_mild": (
            "Measurable content below 20 Hz ({level:.0f} dBFS), but {rel:.0f} dB "
            "below the overall level – normal for a vinyl rip."),
        "dyn.compressed": ("Heavily compressed master: crest factor {crest:.1f} dB "
                           "at {lufs:.1f} LUFS. Not a defect but a production "
                           "decision – rips from record and tape sit at 16 to "
                           "27 dB."),
        "clip.clipped": ("The master is clipped: {n} samples sit at full scale "
                         "({rate:.0f} per minute) and the peaks are flattened "
                         "(flat factor {flat:.2f})."),
        "clip.truepeak": ("True peak at {tp:+.1f} dBTP, above full scale. On "
                          "conversion or lossy encoding that can distort audibly."),
        "low.clean": "Low end unremarkable: no notable rumble, no mains hum.",

        "imp.none": "Practically no impulse noise found.",
        "imp.few": (
            "Occasional impulse noise ({rate:.0f} per minute) – normal for a rip "
            "from record or tape."),
        "imp.many": "Clearly audible crackle ({rate:.0f} events per minute).",
        "imp.constant": (
            "Continuous crackle ({rate:.0f} events per minute) – the noise covers "
            "the material throughout, not just in places."),
        "imp.strong": (
            " Among them {n} strong pops (up to {db:.0f} dB above the local "
            "background)."),

        "null.unrelated": "no common origin detectable (correlation {corr:.2f})",
        "null.identical": "Residual below -60 dB – bit-identical or effectively so",
        "null.lossy": (
            "Residual {depth:.1f} dB – same source. That is the distance a lossy "
            "encoding or an edit such as declicking puts between a file and its "
            "original"),
        "null.mastering": (
            "Residual {depth:.1f} dB – same recording, but clearly different "
            "mastering or heavy compression"),
        "null.distant": "Residual {depth:.1f} dB – at best distantly related material",

        "res.impulses": (
            "The residual consists almost entirely of short impulses – what was "
            "removed were clicks."),
        "res.gate": (
            "In the quiet sections practically the whole signal is removed – that "
            "is how a strong noise reduction or a gate behaves. In lead-in and "
            "run-out grooves this is intended, in the middle of a track it is "
            "not."),
        "res.loud": (
            "In the loud sections what was removed sits {db:.0f} dB below the "
            "original."),
        "res.follows": (
            "Its spectral shape closely follows the programme (r = {r:.2f}) – so "
            "it is not merely a noise floor disappearing. Worth listening to."),
        "res.noise": (
            "Its spectral shape is independent of the programme – that points to "
            "noise and disturbances."),
        "res.mixed": (
            "The residual contains impulses and continuous signal in mixed "
            "proportion."),

        "wow.speed_ok": ("Speed is correct: {ist:.2f} Hz against a nominal "
                         "{nominal:.0f} Hz, that is {dev:+.2f} %."),
        "wow.speed_off": ("Speed deviates by {dev:+.2f} %: {ist:.2f} Hz instead "
                          "of {nominal:.0f} Hz. Audible only in direct "
                          "comparison, but clearly measurable."),
        "wow.speed_far": ("Speed deviates by {dev:+.2f} %: {ist:.2f} Hz instead "
                          "of {nominal:.0f} Hz – that amounts to a noticeable "
                          "shift in pitch."),
        "wow.good": ("Speed stability unremarkable: wow {wow:.3f} %, flutter "
                     "{flutter:.3f} % (RMS, unweighted)."),
        "wow.fair": ("Speed stability within the usual range: wow {wow:.3f} %, "
                     "flutter {flutter:.3f} % (RMS, unweighted). On long held "
                     "notes this can become audible."),
        "wow.poor": ("Clear speed fluctuations: wow {wow:.3f} %, flutter "
                     "{flutter:.3f} % (RMS, unweighted)."),
        "wow.eccentric": ("The strongest fluctuation sits at {hz:.2f} Hz, in step "
                          "with one revolution at {upm:.0f} rpm – that points to "
                          "an off-centre pressing or a concentricity error."),
        "sweep.response": ("Frequency response {kanal}: {spanne:.1f} dB spread "
                           "between 40 Hz and 10 kHz ({lo:+.1f} to {hi:+.1f} dB "
                           "against the reference tone)."),
        "sweep.highs": ("Above 10 kHz {kanal} falls by up to {db:.1f} dB."),
        "sweep.sep_good": "Channel separation {db:.0f} dB – good for a cartridge.",
        "sweep.sep_fair": "Channel separation {db:.0f} dB – usable, not generous.",
        "sweep.sep_poor": ("Channel separation only {db:.0f} dB – that audibly "
                           "narrows the stereo image. Usually worth checking "
                           "azimuth and tracking force."),
        "sweep.none": "Too few usable tone steps found.",
        "err.no_sweep": ("no tone sequence found – frequency response and channel "
                         "separation require held test tones"),
        "err.too_short_wow": "not enough audio for a speed-stability measurement",
        "err.no_tone": ("no sufficiently steady tone found – a test tone is "
                        "required for the speed-stability measurement"),
        "err.no_stream": "no audio stream found",
        "err.no_samples": "no samples decoded (empty or damaged file?)",
        "err.no_ffmpeg": "ffmpeg/ffprobe not found (install the 'ffmpeg' package)",
        "err.timeout": "analysis timed out",
        "err.silent": ("at least one of the two files is (nearly) silent – a null "
                       "test makes no sense here"),
        "err.no_overlap": "no sufficient common section found",
        "err.too_short_null": "not enough audio for a null test",
        "err.too_short_imp": "not enough audio for an impulse scan",
        "err.too_short_low": "not enough audio for low-frequency analysis",
        "err.too_short_mod": "not enough material for the modulation analysis",
        "err.no_samples_from": "no samples from {name}: {err}",
        "param.not_finite": "{name} must be a finite number",
        "param.nfft": "nfft must be a power of two >= 32",
        "param.overlap": "overlap must lie between 0 and 0.95",
        "param.window": "unknown window: {value}",
        "param.scale": "unknown scale: {value}",
        "param.channels": "unknown channel mode: {value}",
        "param.cmap_invalid": "invalid colormap",
        "param.cmap": "unknown colormap: {value}",
        "param.theme": "unknown theme: {value}",
        "param.freq_close": "fmin and fmax are too close together",
        "param.sr": "sr must lie between 1000 and 768000 Hz",

        "ch.mono_sum": "Mono sum", "ch.mono": "Mono",
        "ch.left": "Left", "ch.right": "Right",
        "ch.mid": "Mid (L+R)", "ch.side": "Side (L-R)",
        "ch.n": "Channel {n}",

        "plot.freq": "Frequency [Hz]", "plot.time": "Time [min:s]",
        "plot.level": "Level [dB rel. peak]", "plot.diff": "Difference [dB]",
        "plot.difference": "Difference A - B",
        "plot.diff_note": ("below {band}: median {median:+.1f} dB, "
                           "90th percentile |Δ| {p90:.1f} dB"),

        # --- CLI ----------------------------------------------------------
        "cli.no_edge": "no band edge",
        "cli.edge": "edge {edge} ({n}/{total} sections)",
        "cli.signal_to": "signal up to {bw}",
        "cli.sweep": "response {kanal}: {werte}",
        "cli.up_missing": "upload folder not found: {path}",
        "cli.up_none": "No uploads present.",
        "cli.up_unknown": "no upload by that name: {name}",
        "cli.up_confirm": "Delete {n} upload(s) ({namen})?",
        "cli.up_deleted": "{n} upload(s) deleted, {mb:.1f} MB freed.",
        "cli.up_total": "{n} upload(s), {mb:.1f} MB in total.",
        "cli.wow": ("speed stability: carrier {hz:.2f} Hz, wow {wow:.3f} %, "
                    "flutter {flutter:.3f} %, strongest modulation {mod:.2f} Hz"),
        "cli.impulses": "impulse noise: {count} ({rate}/min), {strong} of them strong",
        "cli.low": "low end: below 20 Hz {sub:.0f} dBFS ({rel:+.0f} dB rel.), mains {mains} Hz",
        "cli.low_nohum": "low end: below 20 Hz {sub:.0f} dBFS ({rel:+.0f} dB rel.), no hum",
        "cli.null": ("null test: {depth:.2f} dB residual, correlation {corr:.4f}, "
                     "offset {offset:+.2f} ms"),
        "cli.residual": ("residual: {path}  ({depth:.1f} dB below A, crest {crest:.0f} dB "
                         "against {src:.0f} dB in the original)"),
        "cli.diff": ("difference: median {median:+.2f} dB, 90th percentile |Δ| {p90:.2f} dB, "
                     "offset {offset:+.3f} s"),
        "cli.skipped": "skipped (not found): {path}",
        "cli.error_at": "error on {path}: {msg}",
        "cli.scan_summary": ("{count} files, {warn} flagged, {computed} newly analysed, "
                             "{cached} from the index, {errors} errors"),
        "cli.csv_written": "CSV written: {path}",
        "cli.not_a_dir": "error: {path} is not a directory",
        "cli.error": "error: {msg}",
        "cli.compare_png": "comparison.png",
        "cli.cmp_file": "{tag}: {name} · {codec} · {rate:g} kHz · band edge {edge}",
        "cli.null_error": "null test: {msg}",
        "cli.residual_error": "residual: {msg}",
        "cli.yes_no": "[y/N]",
        "cli.prune": "result index: {checked} checked, {removed} removed, {kept} kept.",
        "cli.index_needed": "error: --prune needs --index",
        "cli.index_unusable": "error: result index unusable: {msg}",
        "help.description": "Draws spectrograms of audio files (decoding through ffmpeg).",
        "help.meta_file": "FILE",
        "help.meta_folder": "FOLDER",
        "help.g_compare": "comparison",
        "help.g_analysis": "analysis",
        "help.g_uploads": "uploads",
        "help.g_display": "display",
        "help.output": "target PNG (single file or comparison only)",
        "help.outdir": "target folder for several files",
        "help.compare": "draw two files one above the other",
        "help.no_diff": "omit the difference view",
        "help.no_align": "do not compensate the time offset",
        "help.diff_range": "scale of the difference view [± dB]",
        "help.null": "also run a sample-accurate null test",
        "help.residual": "write the difference A−B as an audible FLAC file",
        "help.residual_gain": "boost the residual when writing it [dB]",
        "help.fft": "FFT size (power of two)",
        "help.overlap": "window overlap 0..0.95",
        "help.window": "window function",
        "help.channels": "channels",
        "help.sr": "resampling rate (default: original rate)",
        "help.start": "start time [s]",
        "help.duration": "length [s]",
        "help.scan": "check a folder recursively instead of drawing single files",
        "help.index": "result index for --scan (only changed files are re-analysed)",
        "help.refresh": "ignore the index and measure everything again",
        "help.prune": ("clean up the result index: remove entries of deleted or "
                       "changed files (with --index)"),
        "help.jobs": "files checked in parallel during --scan",
        "help.csv": "write the scan result as CSV",
        "help.seconds": "excerpt per file during --scan [s]",
        "help.lowfreq": "examine low end, rumble and mains hum",
        "help.wow": "measure speed stability (needs a steady tone)",
        "help.nominal": "nominal frequency of the test tone, otherwise automatic",
        "help.sweep": "frequency response and channel separation from a tone sequence",
        "help.clicks": "find and list impulse noise (clicks)",
        "help.cutoff": "estimate and assess the bandwidth (lossy detection)",
        "help.json": "print the full analysis report as JSON",
        "help.no_image": "do not write a PNG",
        "help.uploads": "list uploads (in the container: /data/uploads)",
        "help.upload_dir": "location of the uploads, otherwise UPLOAD_DIR or /data/uploads",
        "help.delete": "delete an upload, may be repeated",
        "help.delete_all": "delete all uploads",
        "help.yes": "skip the confirmation when deleting",
        "help.scale": "frequency axis",
        "help.fmin": "lower frequency limit [Hz]",
        "help.fmax": "upper frequency limit [Hz]",
        "help.db_range": "dynamic range [dB]",
        "help.db_top": "level at the top of the colour scale [dB]",
        "help.cmap": "colour map (matplotlib)",
        "help.theme": "colour theme",
        "help.width": "image width [inches]",
        "help.height": "height per panel [inches]",
        "help.dpi": "resolution [dpi]",
        "help.max_cols": "maximum number of columns (longer recordings are condensed)",
        "help.raw": "image only, without axes",
        "help.title": "image title (default: file name)",
        "help.lang": "language of the output (default: LANG_DEFAULT, otherwise de)",
        "help.quiet": "print errors only",
        "csv.file": "file", "csv.path": "path", "csv.codec": "codec",
        "csv.rate": "sample_rate", "csv.channels": "channels", "csv.bitrate": "bitrate",
        "csv.duration": "duration_s", "csv.edge": "band_edge_hz", "csv.pattern": "pattern",
        "csv.level": "verdict", "csv.note": "note",

        # --- HTTP ---------------------------------------------------------
        "http.unknown_root": "unknown folder: {root}",
        "http.not_found": "file not found",
        "http.not_a_file": "not a regular file",
        "http.not_a_dir": "not a directory",
        "http.no_permission": "no read permission",
        "http.outside": "path outside the shared folder",
        "http.bad_value": "invalid value for {name}",
        "http.too_many_files": "at most {n} files per upload",
        "http.too_large": "larger than {mb:g} MB",
        "http.no_multipart": "expected an upload as multipart/form-data",
        "http.bad_upload": "upload incomplete or malformed",
        "plot.offset": "offset {offset:+.3f} s",
        "plot.cutoff": "band edge ~{edge}",
        "plot.channels": "{n} channels",
        "pattern.voll": "no steep drop",
        "pattern.konstant": "constant band edge",
        "pattern.hochgesampelt": "upsampled",
    },
}


# Sprache der laufenden Anfrage. Ein ContextVar statt einer globalen Variable:
# der Dienst bearbeitet mehrere Anfragen nebenlaeufig, und eine deutsche darf
# einer englischen nicht die Sprache unter den Fuessen wegziehen.
_current: ContextVar[str] = ContextVar("spectro_lang", default=DEFAULT_LANG)


def set_current(lang: str | None) -> str:
    """Setzt die Sprache fuer den laufenden Aufruf (Anfrage, Task, Thread)."""
    code = normalise(lang)
    _current.set(code)
    return code


def current() -> str:
    return _current.get()


def normalise(lang: str | None) -> str:
    """Nimmt auch 'de-DE' oder 'en_GB' entgegen."""
    if not lang:
        return DEFAULT_LANG
    code = str(lang).replace("_", "-").split("-")[0].lower()
    return code if code in LANGUAGES else DEFAULT_LANG


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Übersetzt und formatiert.

    Ohne ausdrückliche Sprache gilt die der laufenden Anfrage. Unbekannte
    Schlüssel fallen auf sich selbst zurück.
    """
    lang = normalise(lang if lang is not None else current())
    vorlage = MESSAGES.get(lang, {}).get(key)
    if vorlage is None:
        vorlage = MESSAGES[DEFAULT_LANG].get(key, key)
    try:
        return vorlage.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return vorlage


def number(value: float, digits: int = 1, lang: str | None = None) -> str:
    """Dezimaltrennzeichen der jeweiligen Sprache."""
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if normalise(lang or current()) == "de" else text


def khz(hz: float, lang: str | None = None) -> str:
    return f"{number(hz / 1000, 1, lang)} kHz"
