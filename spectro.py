#!/usr/bin/env python3
"""
spectro - Spektralanalyse von Audiodateien als Bild.

Beispiele:
    ./spectro.py album.flac
    ./spectro.py --cutoff --json *.flac
    ./spectro.py -s log --fft 4096 -c all aufnahme.wav
    ./spectro.py --compare original.flac encode.m4a -o vergleich.png
"""

from __future__ import annotations

import argparse
import contextvars
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import core
from app.core import AudioError, Params
from app.i18n import khz as _khz
from app.i18n import normalise, t
from app.sidecar import FREMD, SidecarStore


def cli_language(argv: list[str] | None = None) -> str:
    """Sprache schon vor dem eigentlichen Einlesen - die Hilfe braucht sie."""
    vorab = argparse.ArgumentParser(add_help=False)
    vorab.add_argument("--lang")
    ns, _ = vorab.parse_known_args(argv)
    return normalise(ns.lang or os.environ.get("LANG_DEFAULT") or "de")


def build_parser(lang: str = "de") -> argparse.ArgumentParser:
    def h(key: str) -> str:
        return t("help." + key, lang)

    datei, ordner = h("meta_file"), h("meta_folder")
    p = argparse.ArgumentParser(
        description=h("description"),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("files", nargs="*", metavar=datei)
    p.add_argument("-o", "--output", help=h("output"))
    p.add_argument("-d", "--outdir", default=".", help=h("outdir"))

    c = p.add_argument_group(h("g_compare"))
    c.add_argument("--compare", nargs=2, metavar=("A", "B"), help=h("compare"))
    c.add_argument("--no-diff", action="store_true", help=h("no_diff"))
    c.add_argument("--no-align", action="store_true", help=h("no_align"))
    c.add_argument("--diff-range", type=float, default=24.0, help=h("diff_range"))
    c.add_argument("--null", action="store_true", help=h("null"))
    c.add_argument("--residual", metavar=datei, help=h("residual"))
    c.add_argument("--residual-gain", type=float, default=0.0, metavar="DB",
                   help=h("residual_gain"))

    g = p.add_argument_group(h("g_analysis"))
    g.add_argument("-n", "--fft", dest="nfft", type=int, default=2048, help=h("fft"))
    g.add_argument("--overlap", type=float, default=0.75, help=h("overlap"))
    g.add_argument("-w", "--window", choices=sorted(core.WINDOWS), default="hann",
                   help=h("window"))
    g.add_argument("-c", "--channels",
                   choices=("mix", "left", "right", "mid", "side", "all"), default="mix",
                   help=h("channels"))
    g.add_argument("--sr", type=int, help=h("sr"))
    g.add_argument("--start", type=float, help=h("start"))
    g.add_argument("--duration", type=float, help=h("duration"))
    g.add_argument("--scan", metavar=ordner, help=h("scan"))
    g.add_argument("--index", metavar=ordner, default=None, help=h("index"))
    g.add_argument("--refresh", action="store_true", help=h("refresh"))
    g.add_argument("--prune", action="store_true", help=h("prune"))
    g.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                   help=h("jobs"))
    g.add_argument("--csv", metavar=datei, help=h("csv"))
    g.add_argument("--seconds", type=float, default=60.0, help=h("seconds"))
    g.add_argument("--lowfreq", action="store_true", help=h("lowfreq"))
    g.add_argument("--wow", action="store_true", help=h("wow"))
    g.add_argument("--nominal", type=float, metavar="HZ", help=h("nominal"))
    g.add_argument("--sweep", action="store_true", help=h("sweep"))
    g.add_argument("--clicks", action="store_true", help=h("clicks"))
    g.add_argument("--cutoff", action="store_true", help=h("cutoff"))
    g.add_argument("--json", action="store_true", help=h("json"))
    g.add_argument("--no-image", action="store_true", help=h("no_image"))

    u = p.add_argument_group(h("g_uploads"))
    u.add_argument("--uploads", action="store_true", help=h("uploads"))
    u.add_argument("--upload-dir", metavar=ordner, help=h("upload_dir"))
    u.add_argument("--delete", metavar="NAME", action="append", help=h("delete"))
    u.add_argument("--delete-all", action="store_true", help=h("delete_all"))
    u.add_argument("--yes", action="store_true", help=h("yes"))

    v = p.add_argument_group(h("g_display"))
    v.add_argument("-s", "--scale", choices=("linear", "log", "mel"), default="linear",
                   help=h("scale"))
    v.add_argument("--fmin", type=float, default=0.0, help=h("fmin"))
    v.add_argument("--fmax", type=float, help=h("fmax"))
    v.add_argument("--db-range", type=float, default=100.0, help=h("db_range"))
    v.add_argument("--db-top", type=float, default=0.0, help=h("db_top"))
    v.add_argument("--cmap", default="magma", help=h("cmap"))
    v.add_argument("--theme", choices=("dark", "light"), default="light", help=h("theme"))
    v.add_argument("--width", type=float, default=14.0, help=h("width"))
    v.add_argument("--height", type=float, default=5.0, help=h("height"))
    v.add_argument("--dpi", type=int, default=110, help=h("dpi"))
    v.add_argument("--max-cols", type=int, default=4000, help=h("max_cols"))
    v.add_argument("--raw", action="store_true", help=h("raw"))
    v.add_argument("--title", help=h("title"))
    v.add_argument("--lang", choices=("de", "en"), default=lang, help=h("lang"))
    v.add_argument("-q", "--quiet", action="store_true", help=h("quiet"))
    return p


def params_from(args) -> Params:
    return Params(
        nfft=args.nfft, overlap=args.overlap, window=args.window,
        channels=args.channels, scale=args.scale, fmin=args.fmin, fmax=args.fmax,
        db_range=args.db_range, db_top=args.db_top, cmap=args.cmap,
        width=args.width, height=args.height, dpi=args.dpi,
        max_cols=args.max_cols, start=args.start, duration=args.duration,
        sr=args.sr, raw=args.raw, theme=args.theme, diff_range=args.diff_range,
        lang=args.lang,
    ).validate()


def unique_out(outdir: str, path: str, written: set) -> str:
    base = os.path.basename(path)
    cand = os.path.join(outdir, os.path.splitext(base)[0] + ".png")
    return cand if cand not in written else os.path.join(outdir, base + ".png")


def open_index(args) -> SidecarStore:
    try:
        return SidecarStore(args.index)
    except OSError as e:
        sys.exit(t("cli.index_unusable", args.lang, msg=e))


def cli_quelle(root: str | None, rel: str):
    """Eintraege der Kommandozeile tragen den absoluten Scan-Ordner als Wurzel.

    Aeltere Fassungen schrieben fuer jeden Ordner "cli" - solche Eintraege
    lassen sich keiner Datei mehr zuordnen. Eintraege der Weboberflaeche
    (Ordnerschluessel wie "musik") bleiben unangetastet, falls sich beide
    eine Ablage teilen.
    """
    if root and os.path.isabs(root):
        return Path(root) / rel
    return None if root == "cli" else FREMD


def prune_index(args) -> int:
    if not args.index:
        sys.exit(t("cli.index_needed", args.lang))
    stand = open_index(args).prune(cli_quelle)
    if not args.quiet:
        print(t("cli.prune", args.lang, **stand))
    return 0


def scan_folder(args, p: Params) -> int:
    """Rekursive Ordnerpruefung mit optionaler Ergebnisablage."""
    root = os.path.abspath(args.scan)
    if not os.path.isdir(root):
        sys.exit(t("cli.not_a_dir", args.lang, path=args.scan))
    store = open_index(args)
    kind = f"quickcheck:{int(args.seconds)}:{args.lang}"

    dateien = []
    for pfad, unter, namen in os.walk(root):
        unter[:] = sorted(d for d in unter if not d.startswith("."))
        for n in sorted(namen):
            if n.startswith("."):
                continue
            if n.rsplit(".", 1)[-1].lower() in core.AUDIO_EXT:
                dateien.append(os.path.join(pfad, n))
    dateien.sort()

    def pruefen(f: str):
        """Eine Datei - laeuft in einem der Arbeits-Threads."""
        rel = os.path.relpath(f, root)
        if not args.refresh:
            res = store.load(root, rel, Path(f), kind)
            if res is not None:
                return rel, res, False, None
        try:
            res = core.quickcheck(f, args.seconds, lang=args.lang)
        except Exception as e:           # eine kaputte Datei beendet nicht den Scan
            meldung = str(e).replace(root + "/", "").replace(root, "")
            return rel, None, False, meldung or type(e).__name__
        store.save(root, rel, Path(f), kind, res)
        return rel, res, True, None

    zeilen, gerechnet, fehler = [], 0, 0
    # Mehrere Dateien zugleich; ausgegeben wird trotzdem in fester Reihenfolge.
    # Jede Aufgabe bekommt eine Kopie des Kontexts, damit auch Fehlermeldungen
    # aus dem Kern in der gewaehlten Sprache erscheinen.
    pool = ThreadPoolExecutor(max_workers=max(1, args.jobs))
    try:
        auftraege = [pool.submit(contextvars.copy_context().run, pruefen, f)
                     for f in dateien]
        for auftrag, f in zip(auftraege, dateien, strict=True):
            rel, res, neu, meldung = auftrag.result()
            if meldung is not None:
                fehler += 1
                # der Pfad steht schon in einer eigenen Spalte
                zeilen.append({"path": rel, "name": os.path.basename(f),
                               "error": meldung[:160]})
                if not args.quiet:
                    print(t("cli.error_at", args.lang, path=rel,
                            msg=meldung[:80]), file=sys.stderr)
                continue
            gerechnet += int(neu)
            res = {**res, "path": rel}
            zeilen.append(res)
            if not args.quiet and not args.json:
                v = res.get("verdict", {})
                kante = f"{res['cutoff_hz']/1000:.1f}k" if res.get("cutoff_hz") else "-"
                print(f"  [{v.get('level','?'):4s}] {kante:>7s}  {rel}")
                if v.get("level") == "warn":
                    print(f"          {v.get('text','')}")
    finally:
        # bei Strg+C nicht erst alle ausstehenden Dateien abarbeiten
        pool.shutdown(wait=True, cancel_futures=True)

    warn = sum(1 for z in zeilen if (z.get("verdict") or {}).get("level") == "warn")
    if args.json:
        print(json.dumps({"count": len(zeilen), "warnings": warn,
                          "computed": gerechnet, "files": zeilen},
                         indent=2, ensure_ascii=False))
    elif not args.quiet:
        print("\n" + t("cli.scan_summary", args.lang, count=len(zeilen), warn=warn,
                        computed=gerechnet,
                        cached=len(zeilen) - gerechnet - fehler, errors=fehler))

    if args.csv:
        import csv as _csv
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = _csv.writer(fh, delimiter=";")
            w.writerow([t(f"csv.{k}", args.lang) for k in
                        ("file", "path", "codec", "rate", "channels", "bitrate",
                         "duration", "edge", "pattern", "level", "note")])
            for z in zeilen:
                v = z.get("verdict") or {}
                w.writerow([z.get("name", ""), z.get("path", ""), z.get("codec", ""),
                            z.get("sample_rate", ""), z.get("channels", ""),
                            z.get("bit_rate", ""),
                            f"{z['duration']:.1f}" if z.get("duration") else "",
                            z.get("cutoff_hz", ""),
                            t("pattern." + z["pattern"], args.lang)
                            if z.get("pattern") else "",
                            v.get("level", "error" if z.get("error") else ""),
                            z.get("error") or v.get("text", "")])
        if not args.quiet:
            print(t("cli.csv_written", args.lang, path=args.csv))
    return 1 if fehler else 0


def upload_dir(args) -> Path:
    ort = args.upload_dir or os.environ.get("UPLOAD_DIR") or "/data/uploads"
    return Path(ort)


def manage_uploads(args) -> int:
    """Uploads auflisten und loeschen - dieselbe Ablage wie in der Oberflaeche."""
    ordner = upload_dir(args)
    if not ordner.is_dir():
        sys.exit(t("cli.up_missing", args.lang, path=ordner))

    dateien = sorted(f for f in ordner.iterdir()
                     if f.is_file() and not f.name.startswith("."))

    if args.delete or args.delete_all:
        if args.delete_all:
            ziele = dateien
        else:
            nach_name = {f.name: f for f in dateien}
            ziele, fehlend = [], []
            for name in args.delete:
                # Pfadangaben im Namen ignorieren, es wird nur im Ordner geloescht
                treffer = nach_name.get(os.path.basename(name))
                (ziele if treffer else fehlend).append(treffer or name)
            for name in fehlend:
                print(t("cli.up_unknown", args.lang, name=name), file=sys.stderr)
            if fehlend and not ziele:
                return 1
        if not ziele:
            print(t("cli.up_none", args.lang))
            return 0
        if not args.yes:
            namen = ", ".join(f.name for f in ziele[:5])
            if len(ziele) > 5:
                namen += " …"
            antwort = input(t("cli.up_confirm", args.lang, n=len(ziele), namen=namen)
                            + " " + t("cli.yes_no", args.lang) + " ")
            if antwort.strip().lower() not in ("j", "y", "ja", "yes"):
                return 0
        bytes_ = 0
        for f in ziele:
            try:
                bytes_ += f.stat().st_size
                f.unlink()
            except OSError as e:
                print(t("cli.error_at", args.lang, path=f.name, msg=e), file=sys.stderr)
        print(t("cli.up_deleted", args.lang, n=len(ziele), mb=bytes_ / 1e6))
        return 0

    if not dateien:
        print(t("cli.up_none", args.lang))
        return 0
    gesamt = 0
    for f in dateien:
        groesse = f.stat().st_size
        gesamt += groesse
        print(f"  {groesse/1e6:8.1f} MB  {f.name}")
    print(t("cli.up_total", args.lang, n=len(dateien), mb=gesamt / 1e6))
    return 0


def main() -> int:
    sprache = cli_language()
    core.set_language(sprache)
    args = build_parser(sprache).parse_args()
    core.set_language(args.lang)
    if args.uploads or args.delete or args.delete_all:
        return manage_uploads(args)
    if args.prune and not args.scan:
        return prune_index(args)
    if args.scan:
        try:
            rc = scan_folder(args, params_from(args))
        except ValueError as e:
            sys.exit(t("cli.error", args.lang, msg=e))
        if args.prune:
            prune_index(args)
        return rc
    if not args.files and not args.compare:
        build_parser(args.lang).print_help()
        return 2
    try:
        p = params_from(args)
    except ValueError as e:
        sys.exit(t("cli.error", args.lang, msg=e))

    if args.compare:
        a, b = args.compare
        panels, stats = core.compare(a, b, p, align=not args.no_align,
                                     show_diff=not args.no_diff)
        out = args.output or os.path.join(args.outdir, t("cli.compare_png", args.lang))
        core.render(panels, p, out,
                    title=f"{os.path.basename(a)}   ↔   {os.path.basename(b)}",
                    subtitle=f"FFT {p.nfft} · {p.window} · {p.scale} · "
                             + t("plot.offset", args.lang, offset=stats["offset_s"]))
        if args.null:
            try:
                stats["null"] = core.null_test(a, b, p)
            except AudioError as e:
                stats["null"] = {"error": str(e)}

        if args.residual:
            try:
                stats["residual"] = core.null_residual(
                    a, b, args.residual, p, gain_db=args.residual_gain)
            except AudioError as e:
                stats["residual"] = {"error": str(e)}

        if args.json:
            print(json.dumps(stats, indent=2, ensure_ascii=False))
        elif not args.quiet:
            for k in ("a", "b"):
                s = stats[k]
                co = _khz(s["cutoff"], args.lang) if s["cutoff"] else "–"
                print(t("cli.cmp_file", args.lang, tag=k.upper(), name=s["name"],
                        codec=s["codec"], rate=s["sample_rate"] / 1000, edge=co))
                print(f"   {s['verdict']['text']}")
            if "diff" in stats:
                d = stats["diff"]
                print(t("cli.diff", args.lang, median=d["median_db"],
                        p90=d["p90_abs_db"], offset=stats["offset_s"]))
            n = stats.get("null")
            if n and "error" not in n:
                print(t("cli.null", args.lang, depth=n["residual_db"],
                        corr=n["correlation"], offset=n["offset_ms"]))
                print(f"   {n['verdict']['text']}")
            elif n:
                print(t("cli.null_error", args.lang, msg=n["error"]))
            rs = stats.get("residual")
            if rs and "error" not in rs:
                print(t("cli.residual", args.lang, path=rs["path"],
                        depth=rs["residual_db"], crest=rs["crest_db"],
                        src=rs["source_crest_db"]))
                print(f"   {rs['verdict']['text']}")
            elif rs:
                print(t("cli.residual_error", args.lang, msg=rs["error"]))
            print(out)
        return 0

    rc = 0
    written: set = set()
    reports = []
    if not args.output and not args.no_image:
        os.makedirs(args.outdir, exist_ok=True)

    for path in args.files:
        if not os.path.isfile(path):
            print(t("cli.skipped", args.lang, path=path), file=sys.stderr)
            rc = 1
            continue
        try:
            if args.json:
                reports.append(core.summary(path, p))
                continue

            a = core.analyse(path, p)
            panels = core.build_panels(a, p)
            # Dasselbe Urteil wie in Oberflaeche und --json: bei der
            # Bezugsaufloesung, nicht bei der FFT-Groesse des Bildes
            band = (core.band_report(path, p, a.mags[0], a.sr, a.info["codec"])
                    if args.cutoff else None)
            cut = (band["edge_hz"] or band["signal_bandwidth_hz"]) if band else None
            sub = (f"{a.info['codec']} · {a.info['sample_rate']/1000:g} kHz · "
                   + t("plot.channels", args.lang, n=a.info["channels"])
                   + f" · FFT {p.nfft} · {p.window} · {p.scale}")
            if cut:
                sub += " · " + t("plot.cutoff", args.lang, edge=_khz(cut, args.lang))

            out = args.output or unique_out(args.outdir, path, written)
            if not args.no_image:
                written.add(out)
                core.render(panels, p, out,
                            title=args.title or os.path.basename(path), subtitle=sub)
            if not args.quiet:
                head = out if not args.no_image else os.path.basename(path)
                line = f"{head}  ({a.info['codec']}, {a.sr/1000:g} kHz, {a.duration:.1f}s)"
                if band:
                    v = band["verdict"]
                    kante = (t("cli.edge", args.lang,
                               edge=_khz(band["edge_hz"], args.lang),
                               n=band["blocks_with_edge"], total=band["blocks"])
                             if band["edge_hz"] else t("cli.no_edge", args.lang))
                    bw = (_khz(band["signal_bandwidth_hz"], args.lang)
                          if band["signal_bandwidth_hz"] else "n/a")
                    line += f"\n   {kante} · " + t("cli.signal_to", args.lang, bw=bw)
                    line += f"\n   [{v['level']}] {v['text']}"
                print(line)
            if args.lowfreq:
                lf = core.lowfreq_scan(path, p)
                schluessel = "cli.low" if lf["mains_hz"] else "cli.low_nohum"
                print("   " + t(schluessel, args.lang, sub=lf["subsonic_db"],
                                rel=lf["subsonic_rel_db"], mains=lf["mains_hz"]))
                print(f"   [{lf['verdict']['level']}] {lf['verdict']['text']}")
            if args.wow:
                try:
                    wf = core.wow_flutter(path, p, args.nominal)
                    print("   " + t("cli.wow", args.lang, hz=wf["carrier_hz"],
                                    wow=wf["wow_pct"], flutter=wf["flutter_pct"],
                                    mod=wf["dominant_mod_hz"]))
                    print(f"   [{wf['verdict']['level']}] {wf['verdict']['text']}")
                except AudioError as e:
                    print(f"   {e}")
            if args.sweep:
                try:
                    sw = core.tone_sweep(path, p)
                    for kanal, kurve in sw.get("response", {}).items():
                        werte = "  ".join(f"{k['hz']:.0f}:{k['db']:+.1f}" for k in kurve)
                        print(f"   {kanal}: {werte}")
                    print(f"   [{sw['verdict']['level']}] {sw['verdict']['text']}")
                except AudioError as e:
                    print(f"   {e}")
            if args.clicks:
                ev = core.impulse_scan(path, p)
                print("   " + t("cli.impulses", args.lang, count=ev["count"],
                                rate=ev["per_minute"], strong=ev["strong_count"]))
                for e in ev["events"][:10]:
                    print(f"      {int(e['t'])//60}:{e['t']%60:06.3f}  "
                          f"{e['db']:5.1f} dB  {e['ms']:.1f} ms")
        except AudioError as e:
            print(t("cli.error_at", args.lang, path=path, msg=e), file=sys.stderr)
            rc = 1

    if args.json:
        print(json.dumps(reports if len(reports) != 1 else reports[0],
                         indent=2, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except BrokenPipeError:          # z. B. Ausgabe in head/less
        try:
            sys.stdout.close()
        finally:
            os._exit(0)
    except AudioError as e:
        sys.exit(t("cli.error", None, msg=e))
