"""Compute metric-matched fallback @font-face overrides for the self-hosted type system.

Why this exists
---------------
Self-hosted web fonts swap in after first paint. If the fallback face has different
vertical metrics, every line box resizes when the real font arrives — cumulative
layout shift, and the "cheap template" tell of text jumping under the reader.

The fix (per CSS Fonts 4, and the technique web.dev documents for CLS): declare a
fallback @font-face whose src is a locally installed face, and override its metrics
so its line box matches the web font's:

  size-adjust        scales every glyph and metric of the fallback by a factor s
  ascent-override    replaces the fallback's ascent  (as % of font-size)
  descent-override   replaces the fallback's descent
  line-gap-override  replaces the fallback's line gap

Because size-adjust multiplies the overrides too, to land an effective ascent of
``wa`` (the web font's ascent as a fraction of em) we declare
``ascent-override: wa / s``. Same for descent and line gap.

Metrics used: OS/2 usWinAscent/usWinDescent for ascent/descent (the values browsers
use for line boxes on Windows, and the values this repo's primary demo venue runs),
hhea.lineGap for the line gap. macOS/Linux fallback faces differ slightly; the
residual shift there is sub-pixel for the sizes this product sets and is accepted
deliberately rather than shipping per-OS stylesheets.

Run:  python scripts/font_metrics.py
Prints the fallback @font-face blocks to paste into app/static/fonts.css.
"""

from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "app" / "static" / "fonts"

#: (web font file, local fallback file, local() face name, fallback family to declare)
PAIRS = [
    ("fraunces-latin-var.woff2", r"C:\Windows\Fonts\georgia.ttf", "Georgia", "Fraunces Fallback"),
    ("manrope-latin-var.woff2", r"C:\Windows\Fonts\arial.ttf", "Arial", "Manrope Fallback"),
    ("plexmono-latin-400.woff2", r"C:\Windows\Fonts\consola.ttf", "Consolas", "IBM Plex Mono Fallback"),
]


def metrics(path: Path) -> tuple[float, float, float, float]:
    """Return (ascent, descent, line_gap, units_per_em) as em fractions."""
    with TTFont(path, lazy=True) as font:
        upem = font["head"].unitsPerEm
        os2 = font["OS/2"]
        hhea = font["hhea"]
        return (
            os2.usWinAscent / upem,
            os2.usWinDescent / upem,
            hhea.lineGap / upem,
            float(upem),
        )


def main() -> None:
    for web_name, local_path, local_name, family in PAIRS:
        wa, wd, wg, _ = metrics(FONTS / web_name)
        fa, fd, fg, _ = metrics(Path(local_path))
        size_adjust = (wa + wd) / (fa + fd)
        print(f"/* {web_name} against {Path(local_path).name} */")
        print(f"@font-face {{")
        print(f'  font-family: "{family}";')
        print(f'  src: local("{local_name}");')
        print(f"  size-adjust: {size_adjust * 100:.2f}%;")
        print(f"  ascent-override: {wa / size_adjust * 100:.2f}%;")
        print(f"  descent-override: {wd / size_adjust * 100:.2f}%;")
        print(f"  line-gap-override: {wg / size_adjust * 100:.2f}%;")
        print("}")
        print()


if __name__ == "__main__":
    main()
