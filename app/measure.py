"""Einzelmessungen: Tiefton, Gleichlauf, Frequenzgang, Impulsstörungen, Pegel.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import numpy as np

from .audio import _decode_mono, _decoder, _decoder_error, probe
from .band import _smooth
from .i18n import t
from .params import EPS, AudioError, Params


def lowfreq_scan(path: str, p: Params | None = None, max_seconds: float = 180.0) -> dict:
    """Untersucht den Tieftonbereich: Rumpeln, Plattenwelligkeit, Netzbrumm.

    Dafuer wird auf 4 kHz heruntergetastet - mit einem 16k-Fenster ergibt das
    0,24 Hz Aufloesung, fein genug, um 50 Hz von 60 Hz und von benachbarten
    Motorgeraeuschen zu trennen. Mit der ueblichen FFT-Groesse der Bildanalyse
    (23 Hz je Bin bei 48 kHz) waere das nicht moeglich.
    """
    p = (p or Params()).validate()
    sr = 4000
    x = _decode_mono(path, sr, p.start, p.duration, max_seconds=max_seconds)
    nfft = 16384
    if x.size < nfft:
        raise AudioError(t("err.too_short_low", p.lang))
    hop = nfft // 2
    n = 1 + (x.size - nfft) // hop
    V = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop][:n]
    w = np.hanning(nfft)
    P = (np.abs(np.fft.rfft(V * w, axis=1)) / (w.sum() / 2)) ** 2
    med = np.median(P, axis=0)                 # robust gegen einzelne Impulse
    df = sr / nfft

    def band(lo, hi):
        return float(10 * np.log10(med[int(lo / df):int(hi / df)].sum() + 1e-30))

    subsonic = band(1, 20)
    bass = band(20, 200)
    total = band(1, 2000)

    db = 10 * np.log10(med + 1e-30)
    kw = int(6 / df) | 1
    base = _smooth(db, kw)

    def harmonics(f0, count=6):
        out = []
        for k in range(1, count + 1):
            f = f0 * k
            i = int(round(f / df))
            if i >= db.size - 2:
                break
            j = int(np.argmax(db[max(0, i - 3):i + 4])) + max(0, i - 3)
            out.append({"hz": round(j * df, 2), "prominence_db": round(float(db[j] - base[j]), 1),
                        "level_db": round(float(db[j]), 1)})
        return out

    h50, h60 = harmonics(50.0), harmonics(60.0)
    def score(hs):
        return sum(max(0.0, e["prominence_db"]) for e in hs)

    mains, hs = (50, h50) if score(h50) >= score(h60) else (60, h60)
    # Zwei Bedingungen, beide an echtem Material gemessen:
    #   Prominenz: nachgewiesener Netzbrumm ragte 16 bis 40 dB aus seinem
    #   Umfeld, Bassanteile von Musik dagegen nur 9,5 bis 10,1 dB - darunter
    #   ein Popmaster, dessen 180-Hz-Anteil sonst als Brumm gemeldet wurde.
    #   Pegel: bei einer stillen Aufnahme stand sonst ein -110-dBFS-Artefakt
    #   als "Brumm" im Bericht.
    strong = [e for e in hs if e["prominence_db"] >= 14 and e["level_db"] > -95]

    out = {
        "subsonic_db": round(subsonic, 1),
        "bass_db": round(bass, 1),
        "total_db": round(total, 1),
        "subsonic_rel_db": round(subsonic - total, 1),
        # Ohne gefundene Spitzen gibt es keine Netzfrequenz zu melden. Vorher
        # stand hier immer ein Wert, auch wenn gar kein Brumm vorlag - und der
        # war dann schlicht geraten.
        "mains_hz": mains if strong else None,
        "hum": strong[:6],
        "analysed_seconds": round(x.size / sr, 1),
    }

    notes = []
    level = "ok"
    if strong:
        worst = max(strong, key=lambda e: e["level_db"])
        if worst["level_db"] > -70:
            level = "warn"
            notes.append(t("low.hum", p.lang, mains=mains, hz=worst["hz"],
                           level=worst["level_db"]))
        else:
            notes.append(t("low.hum_weak", p.lang, mains=mains,
                           level=worst["level_db"]))
    # Absolutpegel mitpruefen: in einer stillen Aufnahme liegt der Tiefstton
    # zwangslaeufig nah am Gesamtpegel, ohne dass etwas rumpelt
    if subsonic > -55 and subsonic - total > -12:
        level = "warn"
        notes.append(t("low.rumble", p.lang, level=subsonic, rel=total - subsonic))
    elif subsonic > -55 and subsonic - total > -25:
        notes.append(t("low.rumble_mild", p.lang, level=subsonic,
                       rel=total - subsonic))
    if not notes:
        notes.append(t("low.clean", p.lang))
    out["verdict"] = {"level": level, "text": " ".join(notes)}
    return out


# --------------------------------------------------------------------------


NOMINAL_TONES = (315.0, 1000.0, 3000.0, 3150.0, 400.0, 500.0, 100.0, 1200.0)


def _analytic(x: np.ndarray) -> np.ndarray:
    """Analytisches Signal ueber die FFT (entspricht scipy.signal.hilbert)."""
    n = x.size
    X = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1
    if n % 2 == 0:
        h[n // 2] = 1
        h[1:n // 2] = 2
    else:
        h[1:(n + 1) // 2] = 2
    return np.fft.ifft(X * h)


def _bandpass(x: np.ndarray, lo: float, hi: float, sr: int) -> np.ndarray:
    """Bandpass im Frequenzbereich - fuer einen Dauerton voellig ausreichend."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / sr)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, n=x.size)


def _welch(x: np.ndarray, fs: float, nperseg: int = 4096):
    """Gemitteltes Leistungsdichtespektrum (entspricht scipy.signal.welch)."""
    nperseg = min(nperseg, (x.size // 2) * 2)
    if nperseg < 16:
        raise AudioError("zu wenig Material fuer die Modulationsanalyse")
    w = np.hanning(nperseg)
    hop = nperseg // 2
    n = 1 + (x.size - nperseg) // hop
    V = np.lib.stride_tricks.sliding_window_view(x, nperseg)[::hop][:max(n, 1)]
    P = (np.abs(np.fft.rfft(V * w, axis=1)) ** 2).mean(axis=0)
    P /= fs * (w ** 2).sum()
    P[1:-1] *= 2
    return np.fft.rfftfreq(nperseg, 1 / fs), P


def wow_flutter(path: str, p: Params | None = None, nominal_hz: float | None = None,
                max_seconds: float = 30.0) -> dict:
    """Misst Drehzahlabweichung, Wow und Flutter an einem Dauerton.

    Braucht einen gehaltenen Messton - von einer Mess-Schallplatte, einem
    Messband oder notfalls einer sehr ruhigen Instrumentalstelle. Aus der
    Momentanfrequenz (Hilbert-Transformierte des schmalbandig gefilterten
    Tons) ergibt sich die Schwankung; ihr Modulationsspektrum trennt das
    langsame Wow von dem schnelleren Flutter.

    Gegen kuenstlich erzeugte Toene mit bekannter Schwankung geprueft: 0,10 %
    wurden als 0,098 % gemessen, 0,30 % als 0,295 %, und ein unmodulierter Ton
    ergab 0,000 %.
    """
    p = (p or Params()).validate()
    sr = 48000
    x = _decode_mono(path, sr, p.start, p.duration, max_seconds=max_seconds).astype(np.float64)
    if x.size < sr * 2:
        raise AudioError(t("err.too_short_wow", p.lang))

    # Traegerton suchen: staerkste Spitze oberhalb von 25 Hz
    w = np.hanning(x.size)
    F = np.abs(np.fft.rfft(x * w))
    f = np.fft.rfftfreq(x.size, 1 / sr)
    gueltig = f > 25
    idx = int(np.argmax(F[gueltig])) + int(np.searchsorted(f, 25))
    umfeld = slice(max(0, idx - 3), idx + 4)
    traeger = float((f[umfeld] * F[umfeld] ** 2).sum() / ((F[umfeld] ** 2).sum() + EPS))
    tonanteil = float((F[umfeld] ** 2).sum() / ((F ** 2).sum() + EPS))
    if tonanteil < 0.2 or traeger < 40:
        raise AudioError(t("err.no_tone", p.lang))

    y = _bandpass(x, traeger * 0.8, traeger * 1.25, sr)
    phase = np.unwrap(np.angle(_analytic(y)))
    inst = np.diff(phase) / (2 * np.pi) * sr

    rand = sr // 4                       # Einschwingen des Filters verwerfen
    inst = inst[rand:-rand] if inst.size > 2 * rand + sr else inst
    d = sr // 1000                       # auf 1 kHz heruntertasten
    inst = inst[:inst.size // d * d].reshape(-1, d).mean(axis=1)
    if inst.size < 1000:
        raise AudioError(t("err.too_short_wow", p.lang))

    mittel = float(np.mean(inst))
    abw = (inst - mittel) / mittel * 100.0
    fr, P = _welch(abw - abw.mean(), 1000.0)

    def band(lo, hi):
        sel = (fr >= lo) & (fr < hi)
        return float(np.sqrt(np.trapezoid(P[sel], fr[sel]))) if sel.any() else 0.0

    wow, flutter, gesamt = band(0.2, 6.0), band(6.0, 100.0), band(0.2, 100.0)
    spitze = float(fr[int(np.argmax(P))])

    soll = nominal_hz
    if soll is None:
        kandidaten = [(abs(mittel / n - 1), n) for n in NOMINAL_TONES]
        kandidaten.sort()
        soll = kandidaten[0][1] if kandidaten[0][0] < 0.06 else None
    drehzahl = (mittel / soll - 1) * 100 if soll else None

    out = {
        "carrier_hz": round(mittel, 3),
        "nominal_hz": soll,
        "speed_deviation_pct": round(drehzahl, 3) if drehzahl is not None else None,
        "wow_pct": round(wow, 4),
        "flutter_pct": round(flutter, 4),
        "combined_pct": round(gesamt, 4),
        "dominant_mod_hz": round(spitze, 2),
        "analysed_seconds": round(inst.size / 1000, 1),
    }

    teile = []
    if drehzahl is not None:
        schluessel = ("wow.speed_ok" if abs(drehzahl) < 0.3 else
                      "wow.speed_off" if abs(drehzahl) < 1.0 else "wow.speed_far")
        teile.append(t(schluessel, p.lang, dev=drehzahl, nominal=soll, ist=mittel))
    stufe = "ok"
    if gesamt < 0.1:
        teile.append(t("wow.good", p.lang, wow=wow, flutter=flutter))
    elif gesamt < 0.25:
        teile.append(t("wow.fair", p.lang, wow=wow, flutter=flutter))
    else:
        stufe = "warn"
        teile.append(t("wow.poor", p.lang, wow=wow, flutter=flutter))

    # Eine Modulation im Takt einer Umdrehung deutet auf Exzentrizitaet
    for upm, hz in ((33.3, 0.555), (45.0, 0.75), (78.0, 1.3)):
        if abs(spitze - hz) < 0.15 and wow > 0.03:
            teile.append(t("wow.eccentric", p.lang, hz=spitze, upm=upm))
            break
    out["verdict"] = {"level": stufe, "text": " ".join(teile)}
    return out


# --------------------------------------------------------------------------


def _tone_steps(x: np.ndarray, sr: int, block: float = 0.25,
                min_dauer: float = 1.2, min_tonanteil: float = 0.5) -> list:
    """Zerlegt eine Aufnahme in gehaltene Toene mit Pegel je Kanal."""
    n = int(sr * block)
    if n < 64 or x.shape[0] < n * 4:
        return []
    w = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    ab25 = int(np.searchsorted(freqs, 25))

    roh = []
    for i in range(x.shape[0] // n):
        blk = x[i * n:(i + 1) * n]
        mono = blk.mean(axis=1)
        F = np.abs(np.fft.rfft(mono * w))
        j = int(np.argmax(F[ab25:])) + ab25
        u = slice(max(0, j - 2), j + 3)
        energie = float((F ** 2).sum()) + EPS
        anteil = float((F[u] ** 2).sum()) / energie
        if anteil < min_tonanteil:
            roh.append(None)
            continue
        hz = float((freqs[u] * F[u] ** 2).sum() / ((F[u] ** 2).sum() + EPS))
        pegel = []
        for k in range(x.shape[1]):
            FK = np.abs(np.fft.rfft(blk[:, k] * w))
            pegel.append(20 * np.log10(float(np.sqrt((FK[u] ** 2).sum())) / n + EPS))
        roh.append((i * block, hz, pegel))

    stufen, akt = [], None
    for eintrag in roh + [None]:
        if eintrag is None:
            if akt and akt["ende"] - akt["start"] >= min_dauer:
                stufen.append(akt)
            akt = None
            continue
        t, hz, pegel = eintrag
        if akt and abs(hz - akt["hz"][-1]) / max(akt["hz"][-1], 1.0) < 0.03:
            akt["hz"].append(hz)
            akt["pegel"].append(pegel)
            akt["ende"] = t + block
        else:
            if akt and akt["ende"] - akt["start"] >= min_dauer:
                stufen.append(akt)
            akt = {"start": t, "ende": t + block, "hz": [hz], "pegel": [pegel]}

    fertig = []
    for s in stufen:
        pegel = np.array(s["pegel"])
        fertig.append({"start": round(s["start"], 2),
                       "seconds": round(s["ende"] - s["start"], 2),
                       "hz": round(float(np.median(s["hz"])), 1),
                       "levels_db": [round(float(np.median(pegel[:, k])), 1)
                                     for k in range(pegel.shape[1])]})
    return fertig


def tone_sweep(path: str, p: Params | None = None, reference_hz: float = 1000.0,
               max_seconds: float = 900.0) -> dict:
    """Frequenzgang und Kanaltrennung aus einer Folge gehaltener Toene.

    Gedacht fuer Mess-Schallplatten und Messbaender, die eine Tonleiter je
    Kanal enthalten. Je Ton wird der Pegel in beiden Kanaelen gemessen: die
    Differenz zwischen dem belegten und dem stillen Kanal ist die
    Kanaltrennung, der Verlauf des belegten Kanals gegenueber dem Bezugston
    der Frequenzgang.

    Was dabei herauskommt, ist immer die Kette als Ganzes - Tonabnehmer,
    Entzerrer, Wandler - nicht ein einzelnes Geraet.
    """
    p = (p or Params()).validate()
    sr = 48000
    info = probe(path)
    kanaele = max(1, min(int(info.get("channels") or 1), 2))
    proc = _decoder(path, sr, kanaele, p.start, p.duration or max_seconds)
    try:
        roh = proc.stdout.read()
    finally:
        proc.stdout.close()
        proc.wait()
        fehler = _decoder_error(proc)
    if not roh:
        raise AudioError(f"ffmpeg: {fehler[:200]}" if fehler
                         else t("err.no_samples", p.lang))
    x = np.frombuffer(roh, dtype=np.float32).reshape(-1, kanaele).astype(np.float64)

    stufen = _tone_steps(x, sr)
    if len(stufen) < 4:
        raise AudioError(t("err.no_sweep", p.lang))

    for s in stufen:
        pegel = s["levels_db"]
        if len(pegel) == 2:
            belegt = 0 if pegel[0] >= pegel[1] else 1
            s["channel"] = "L" if belegt == 0 else "R"
            s["level_db"] = pegel[belegt]
            s["crosstalk_db"] = round(pegel[belegt] - pegel[1 - belegt], 1)
        else:
            s["channel"] = "M"
            s["level_db"] = pegel[0]
            s["crosstalk_db"] = None

    out: dict = {"steps": stufen, "reference_hz": reference_hz,
                 "analysed_seconds": round(x.shape[0] / sr, 1)}
    teile = []
    stufe = "ok"

    # Frequenzgang je Kanal. Ausgewertet wird der laengste zusammenhaengende
    # Durchlauf mit monoton fallender oder steigender Frequenz: genau so sind
    # Messreihen aufgebaut. Einzelne Bezugstoene - etwa zwei Pegelmarken bei
    # 1 kHz - stehen ausserhalb dieses Durchlaufs und verfaelschen die Spanne
    # sonst um mehr als 10 dB.
    gang: dict = {}
    for kanal in ("L", "R", "M"):
        punkte = [s for s in stufen if s["channel"] == kanal]
        if len(punkte) < 4:
            continue
        # Aufeinanderfolgende Stufen fast gleicher Frequenz zusammenfassen -
        # sonst zerreisst eine wiederholte Messfrequenz den Durchlauf.
        vereint = []
        for schritt in punkte:
            if vereint and abs(schritt["hz"] - vereint[-1]["hz"]) / max(
                    vereint[-1]["hz"], 1.0) < 0.03:
                letzter = vereint[-1]
                letzter["level_db"] = round(
                    (letzter["level_db"] + schritt["level_db"]) / 2, 1)
                letzter["seconds"] = round(letzter["seconds"] + schritt["seconds"], 2)
                continue
            vereint.append(dict(schritt))

        beste, lauf = [], []
        for schritt in vereint:
            if not lauf:
                lauf = [schritt]
                continue
            vor = lauf[-1]["hz"]
            gleiche = abs(schritt["hz"] - vor) / max(vor, 1.0) < 0.03
            richtung_ok = (len(lauf) < 2 or
                           (schritt["hz"] - vor) * (lauf[-1]["hz"] - lauf[-2]["hz"]) > 0)
            if not gleiche and richtung_ok:
                lauf.append(schritt)
            else:
                if len(lauf) > len(beste):
                    beste = lauf
                lauf = [schritt]
        if len(lauf) > len(beste):
            beste = lauf
        if len(beste) < 4:
            continue

        bezug = min(beste, key=lambda s: abs(s["hz"] - reference_hz))
        if abs(bezug["hz"] - reference_hz) > reference_hz * 0.2:
            continue
        kurve = [{"hz": s["hz"], "db": round(s["level_db"] - bezug["level_db"], 1)}
                 for s in sorted(beste, key=lambda s: s["hz"])]
        gang[kanal] = kurve
        im_band = [k["db"] for k in kurve if 40 <= k["hz"] <= 10000]
        if im_band:
            spanne = max(im_band) - min(im_band)
            teile.append(t("sweep.response", p.lang, kanal=kanal, spanne=spanne,
                           lo=min(im_band), hi=max(im_band)))
            if spanne > 6:
                stufe = "warn"
        hoch = [k["db"] for k in kurve if k["hz"] > 10000]
        if hoch and min(hoch) < -6:
            teile.append(t("sweep.highs", p.lang, kanal=kanal, db=min(hoch)))
    out["response"] = gang

    trennung = [s["crosstalk_db"] for s in stufen
                if s.get("crosstalk_db") is not None and 200 <= s["hz"] <= 8000]
    if trennung:
        med = float(np.median(trennung))
        out["channel_separation_db"] = round(med, 1)
        out["channel_separation_min_db"] = round(float(min(trennung)), 1)
        schluessel = ("sweep.sep_good" if med >= 25 else
                      "sweep.sep_fair" if med >= 15 else "sweep.sep_poor")
        if med < 15:
            stufe = "warn"
        teile.append(t(schluessel, p.lang, db=med))

    out["verdict"] = {"level": stufe, "text": " ".join(teile) or t("sweep.none", p.lang)}
    return out


# --------------------------------------------------------------------------


def impulse_scan(path: str, p: Params | None = None, threshold_db: float = 14.0,
                 max_ms: float = 6.0, lf_margin: float = 6.0,
                 max_events: int = 300) -> dict:
    """Sucht kurze Impulsstoerungen - Knackser und Knistern von Schallplatten.

    Verglichen wird die Hochtonhuellkurve mit ihrem lokalen Untergrund: ein
    Knackser hebt die Hoehen fuer wenige Millisekunden weit darueber, ohne
    dass der Bass mitgeht. Genau daran lassen sich Musiktransienten (Snare,
    Becken) unterscheiden, die immer auch tiefe Anteile mitbringen.
    """
    p = (p or Params()).validate()
    info = probe(path)
    sr = int(p.sr or info["sample_rate"])
    x = _decode_mono(path, sr, p.start, p.duration, max_seconds=3600.0)
    nfft, hop = 256, 64
    if x.size < nfft * 16:
        raise AudioError(t("err.too_short_imp", p.lang))

    win = np.hanning(nfft).astype(np.float32)
    n = 1 + (x.size - nfft) // hop
    V = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop][:n]
    S = np.abs(np.fft.rfft(V * win, axis=1)).astype(np.float32) ** 2
    df = sr / nfft

    # Oberhalb der Bandkante steht bei hochgesampeltem Material nur Rauschen,
    # deshalb das Hochtonband bei 20 kHz bzw. der halben Nyquistrate kappen.
    hi0 = int(6000 / df)
    hi1 = int(min(0.45 * sr, 20000) / df) if sr > 50000 else S.shape[1]
    hi1 = max(hi0 + 2, hi1)
    hf = 10 * np.log10(S[:, hi0:hi1].sum(axis=1) + 1e-20)
    lf = 10 * np.log10(S[:, :max(2, int(1000 / df))].sum(axis=1) + 1e-20)

    # Untergrund als Blockmedian (0,5 s) mit linearer Verbindung - schnell
    # und unempfindlich gegen die Stoerungen selbst
    blk = max(8, int(0.5 * sr / hop))
    nb = max(1, hf.size // blk)
    centres = np.arange(nb) * blk + blk // 2
    base_h = np.interp(np.arange(hf.size), centres,
                       np.array([np.median(hf[i * blk:(i + 1) * blk]) for i in range(nb)]))
    base_l = np.interp(np.arange(lf.size), centres,
                       np.array([np.median(lf[i * blk:(i + 1) * blk]) for i in range(nb)]))
    over_h, over_l = hf - base_h, lf - base_l

    frame_ms = hop / sr * 1000
    max_frames = max(1, int(max_ms / frame_ms))
    t0 = float(p.start or 0.0)

    events = []
    i = 0
    while i < over_h.size:
        if over_h[i] < threshold_db:
            i += 1
            continue
        j = i
        while j < over_h.size and over_h[j] > threshold_db / 2:
            j += 1
        width = j - i
        peak = float(over_h[i:j].max())
        lf_peak = float(over_l[i:j].max())
        if width <= max_frames and peak - lf_peak >= lf_margin:
            events.append({"t": round(t0 + i * hop / sr, 3),
                           "db": round(peak, 1),
                           "ms": round(width * frame_ms, 2)})
        i = j + 1

    dur = x.size / sr
    per_min = len(events) / (dur / 60) if dur > 0 else 0.0
    strong = [e for e in events if e["db"] >= 25]

    if per_min < 2:
        level, text = "ok", t("imp.none", p.lang)
    elif per_min < 20:
        level, text = "ok", t("imp.few", p.lang, rate=per_min)
    elif per_min < 100:
        level, text = "warn", t("imp.many", p.lang, rate=per_min)
    else:
        level, text = "warn", t("imp.constant", p.lang, rate=per_min)
    if strong:
        text += t("imp.strong", p.lang, n=len(strong),
                  db=max(e["db"] for e in strong))

    return {
        "count": len(events),
        "per_minute": round(per_min, 1),
        "strong_count": len(strong),
        "analysed_seconds": round(dur, 2),
        "threshold_db": threshold_db,
        "events": sorted(events, key=lambda e: -e["db"])[:max_events],
        "verdict": {"level": level, "text": text},
    }


# --------------------------------------------------------------------------


def clipping_verdict(loud: dict, seconds: float, lang: str = "de") -> dict | None:
    """Beurteilt Uebersteuerung aus Pegelwerten.

    An echtem Material gemessen: der Flat Factor liegt bei zwoelf Aufnahmen
    ausnahmslos bei null, nur bei einem Master aus der Lautheitskrieg-Aera bei
    0,99. Die Zahl der Samples an der Vollaussteuerung trennt noch schaerfer -
    dort 151 je Minute gegen 0 bis 9 bei allen anderen, darunter zwei ebenfalls
    sehr laute Fassungen. Deshalb entscheiden diese beiden, nicht der True Peak
    allein: der liegt auch bei sauberen lauten Mastern ueber der Grenze.
    """
    if not loud:
        return None
    flach = loud.get("flat_factor") or 0.0
    spitzen = int(loud.get("abs_peak_count") or 0)
    tp = loud.get("true_peak_dbfs")
    peak = loud.get("peak_dbfs")
    rate = spitzen / (seconds / 60) if seconds and seconds > 0 else 0.0

    # Ohne Vollaussteuerung keine Uebersteuerung. Der Zaehler von astats meint
    # Samples auf dem Extremwert des Signals - in digitaler Stille ist das
    # jedes einzelne, was ohne diese Verankerung eine Warnung ausloest.
    ausgesteuert = peak is not None and peak > -1.0
    if ausgesteuert and (flach > 0 or rate >= 30):
        return {"level": "warn", "rate_per_min": round(rate, 1),
                "peak_samples": spitzen, "flat_factor": flach,
                "text": t("clip.clipped", lang, n=spitzen, rate=rate, flat=flach)}
    if tp is not None and tp > -0.1:
        return {"level": "warn", "rate_per_min": round(rate, 1),
                "peak_samples": spitzen, "flat_factor": flach,
                "text": t("clip.truepeak", lang, tp=tp)}
    return None


def dynamics_note(loud: dict, lang: str = "de") -> dict | None:
    """Stellt fest, wie stark ein Master zusammengedrueckt ist.

    Kein Mangel, sondern eine Produktionsentscheidung - deshalb ohne Warnung,
    nur als Feststellung. Die Grenzen stammen aus einer Gegenueberstellung von
    zehn Aufnahmen: laute Masters lagen bei einem Crest-Faktor von 7,6 bis
    12,2 dB und einer Lautheit ueber -10 LUFS, Rips von Platte und Band bei 16
    bis 27 dB und unter -14 LUFS.
    """
    if not loud:
        return None
    crest = loud.get("crest_db")
    lufs = loud.get("lufs_integrated")
    if crest is None or lufs is None:
        return None
    if crest < 12.5 and lufs > -12:
        return {"level": "ok", "crest_db": crest, "lufs": lufs,
                "text": t("dyn.compressed", lang, crest=crest, lufs=lufs)}
    return None
