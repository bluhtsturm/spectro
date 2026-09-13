"""Frequenzachsen und das Zeichnen der Spektrogramme.

Teil des Analysekerns von spectro; core.py führt alle Module
zusammen und bleibt die Schnittstelle nach außen.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from .i18n import t
from .params import THEMES, Params


def _mel(f):
    return 2595.0 * np.log10(1.0 + np.asarray(f, dtype=float) / 700.0)


def _imel(m):
    return 700.0 * (10.0 ** (np.asarray(m, dtype=float) / 2595.0) - 1.0)


def target_freqs(scale: str, fmin: float, fmax: float, rows: int) -> np.ndarray:
    if scale == "linear":
        return np.linspace(fmin, fmax, rows)
    if scale == "log":
        return np.geomspace(max(fmin, 20.0), fmax, rows)
    return _imel(np.linspace(_mel(max(fmin, 0.0)), _mel(fmax), rows))


def pick_ticks(scale: str, lo: float, hi: float) -> list:
    if scale == "linear":
        step = 20000
        for s in (100, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000):
            if (hi - lo) / s <= 12:
                step = s
                break
        first = np.ceil(lo / step) * step
        return list(np.arange(first, hi + step / 2, step))
    cands = ([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000, 20000,
              24000, 32000, 48000, 96000] if scale == "log" else
             [0, 100, 250, 500, 1000, 2000, 3000, 4000, 6000, 8000, 11000,
              14000, 18000, 22000, 32000, 48000, 96000])
    return [f for f in cands if lo <= f <= hi]


def remap(db: np.ndarray, sr: int, nfft: int, freqs: np.ndarray) -> np.ndarray:
    """Interpoliert FFT-Bins linear auf die Ziel-Frequenzachse."""
    df = sr / nfft
    idx = np.clip(freqs / df, 0, db.shape[0] - 1.000001)
    i0 = idx.astype(int)
    frac = (idx - i0)[:, None].astype(np.float32)
    return db[i0] * (1 - frac) + db[i0 + 1] * frac


def resample_cols(db: np.ndarray, n: int) -> np.ndarray:
    """Streckt/staucht die Zeitachse auf n Spalten (fuer Differenzbilder)."""
    if db.shape[1] == n:
        return db
    idx = np.clip(np.linspace(0, db.shape[1] - 1.000001, n), 0, db.shape[1] - 1.000001)
    i0 = idx.astype(int)
    frac = (idx - i0).astype(np.float32)
    return db[:, i0] * (1 - frac) + db[:, i0 + 1] * frac


# --------------------------------------------------------------------------


def render(panels: list, p: Params, out, title: str = "", subtitle: str = "") -> list:
    """Rendert die Panels als PNG in eine Datei oder einen Puffer.

    Rueckgabe: Geometrie der Plotflaechen (Bruchteile der Bildkante, Ursprung
    links oben) samt Achsenbereichen - die Web-Oberflaeche rechnet damit
    Mausposition in Zeit/Frequenz um (Zoom per Aufziehen, Abspielmarke).
    """
    p = p.validate()
    th = THEMES.get(p.theme, THEMES["dark"])
    sr = panels[0].sr
    fmax = min(p.fmax or sr / 2, sr / 2)
    rows = 800 if p.raw else max(320, int(p.height * p.dpi))
    freqs = target_freqs(p.scale, p.fmin, fmax, rows)

    n = len(panels)
    has_diff = any(pan.kind == "diff" for pan in panels)
    has_spec = any(pan.kind != "diff" for pan in panels)
    fig = Figure(figsize=(p.width, p.height * n + (0 if p.raw else 0.7)),
                 dpi=p.dpi, facecolor=th["bg"])
    FigureCanvasAgg(fig)
    axes = fig.subplots(n, 1, squeeze=False)[:, 0]

    # feste Raender: dadurch ist die Geometrie im fertigen Bild exakt bekannt
    fig_h = p.height * n + (0 if p.raw else 0.7)
    if p.raw:
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0, hspace=0)
    else:
        ncb = int(has_spec) + int(has_diff)
        left_in, right_in = 0.85, 0.30 + 0.95 * ncb
        top_in = (0.75 if title else 0.30) + (0.02 if n > 1 else 0)
        bottom_in = 0.55
        fig.subplots_adjust(
            left=min(0.35, left_in / p.width),
            right=max(0.6, 1 - right_in / p.width),
            top=1 - top_in / fig_h,
            bottom=bottom_in / fig_h,
            hspace=0.26)

    spec_img = diff_img = None
    for ax, pan in zip(axes, panels, strict=False):
        disp = remap(pan.db, pan.sr, p.nfft, freqs)
        t1 = max(pan.t1, pan.t0 + 1e-6)
        if pan.kind == "diff":
            diff_img = ax.imshow(disp, origin="lower", aspect="auto", cmap="RdBu_r",
                                 vmin=-p.diff_range, vmax=p.diff_range,
                                 interpolation="nearest",
                                 extent=(pan.t0, t1, 0, rows))
        else:
            spec_img = ax.imshow(disp, origin="lower", aspect="auto", cmap=p.cmap,
                                 vmin=p.db_top - p.db_range, vmax=p.db_top,
                                 interpolation="nearest",
                                 extent=(pan.t0, t1, 0, rows))
        ax.set_facecolor(th["bg"])
        if p.raw:
            ax.set_axis_off()
            continue

        ticks = pick_ticks(p.scale, freqs[0], freqs[-1])
        ax.set_yticks(np.interp(ticks, freqs, np.arange(rows)))
        ax.set_yticklabels([f"{t/1000:g}k" if t >= 1000 else f"{t:g}" for t in ticks])
        ax.set_ylabel(t("plot.freq", p.lang), color=th["fg"], fontsize=9)
        ax.tick_params(colors=th["fg"], labelsize=8)
        for sp in ax.spines.values():
            sp.set_color(th["fg"])
            sp.set_alpha(0.35)
        ax.grid(axis="y", color=th["grid"], alpha=0.12, lw=0.5)
        ax.text(0.006, 0.985, pan.label + (f"   ({pan.note})" if pan.note else ""),
                transform=ax.transAxes, ha="left", va="top", fontsize=8.5,
                color=th["fg"],
                bbox={"facecolor": th["bg"], "alpha": 0.6,
                      "edgecolor": "none", "pad": 2.5})
        span = t1 - pan.t0
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda v, _=None, sp=span: _fmt_time(v, sp)))

    if not p.raw:
        axes[-1].set_xlabel(t("plot.time", p.lang), color=th["fg"], fontsize=9)
        pos0 = axes[0].get_position()
        pos1 = axes[-1].get_position()
        cbx = pos0.x1 + 0.10 / p.width
        cbw = 0.16 / p.width
        if spec_img is not None:
            cax = fig.add_axes([cbx, pos1.y0, cbw, pos0.y1 - pos1.y0])
            cb = fig.colorbar(spec_img, cax=cax)
            cb.set_label(t("plot.level", p.lang), color=th["fg"], fontsize=8)
            cb.ax.tick_params(colors=th["fg"], labelsize=7)
            cb.outline.set_alpha(0.35)
            cbx += 0.95 / p.width
        if diff_img is not None:
            cax2 = fig.add_axes([cbx, pos1.y0, cbw, pos0.y1 - pos1.y0])
            cb2 = fig.colorbar(diff_img, cax=cax2)
            cb2.set_label(t("plot.diff", p.lang), color=th["fg"], fontsize=8)
            cb2.ax.tick_params(colors=th["fg"], labelsize=7)
            cb2.outline.set_alpha(0.35)
        if title:
            fig.suptitle(title + ("\n" + subtitle if subtitle else ""),
                         color=th["fg"], fontsize=10, y=1 - 0.08 / fig_h,
                         verticalalignment="top")

    fig.savefig(out, format="png", facecolor=th["bg"])

    boxes = []
    for ax, pan in zip(axes, panels, strict=False):
        pos = ax.get_position()
        boxes.append({
            "x0": round(pos.x0, 5), "x1": round(pos.x1, 5),
            "y0": round(1 - pos.y1, 5), "y1": round(1 - pos.y0, 5),
            "t0": round(pan.t0, 4), "t1": round(max(pan.t1, pan.t0 + 1e-6), 4),
            "fmin": p.fmin, "fmax": fmax, "scale": p.scale,
            "label": pan.label, "kind": pan.kind,
        })
    return boxes


def _fmt_time(v, span: float | None = None) -> str:
    """Zeitachse: bei kurzen Ausschnitten mit Nachkommastellen, sonst m:ss."""
    v = max(v, 0)
    if span is not None and span < 2:
        return f"{int(v)//60}:{v % 60:06.3f}"
    if span is not None and span < 20:
        return f"{int(v)//60}:{v % 60:04.1f}"
    if v >= 3600:
        return f"{int(v)//3600}:{(int(v)%3600)//60:02d}:{int(v)%60:02d}"
    return f"{int(v)//60}:{int(v)%60:02d}"


