#!/usr/bin/env python3
"""Build vendor/katex_bundle.css: single-file CSS with woff2 fonts inlined.

Reads vendor/katex/dist/katex.min.css + vendor/katex/dist/fonts/*.woff2
and produces vendor/katex_bundle.css where:
  - Each @font-face rule keeps only the woff2 url,
    replaced with a base64 data URI.
  - Non-woff2 font references are dropped.
  - WeasyPrint-friendly overrides for CJK text and page-break safety
    are appended at the end.
"""

import argparse
import base64
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
KATEX_CSS = SKILL_DIR / "vendor" / "katex" / "dist" / "katex.min.css"
FONTS_DIR = SKILL_DIR / "vendor" / "katex" / "dist" / "fonts"
BUNDLE_CSS = SKILL_DIR / "vendor" / "katex_bundle.css"

OVERRIDES = """
/* === md-to-pdf overrides for WeasyPrint === */
/* Let \\text{} fall back to page body font for CJK glyphs. */
.katex .mord.text,
.katex .text { font-family: inherit; }
/* Display math should not break across pages. */
.katex-display {
    page-break-inside: avoid;
    break-inside: avoid;
    margin: 0.8em 0;
}
/* KaTeX default is ~1.21em; tone down slightly for academic body text. */
.katex { font-size: 1.05em; }
"""


_FONTFACE_RE = re.compile(r"@font-face\s*\{([^}]*)\}", re.DOTALL)
_URL_RE = re.compile(
    r"url\(\s*([^)\s]+?)\s*\)\s*format\(\s*['\"]([^'\"]+)['\"]\s*\)"
)


def _inline_font_face(block_with_braces: str, fonts_dir: Path) -> str | None:
    """Rewrite one @font-face block: keep only woff2 src, inline as base64.

    ``block_with_braces`` is the full ``@font-face { ... }`` literal.
    Returns the rewritten block, or None if this block has no woff2 src.
    """
    m = _FONTFACE_RE.match(block_with_braces)
    if not m:
        return None
    body = m.group(1)

    srcs = list(_URL_RE.finditer(body))
    woff2 = next((m for m in srcs if m.group(2) == "woff2"), None)
    if woff2 is None:
        return None

    url = woff2.group(1).strip().strip("'\"")
    filename = Path(url).name
    font_path = fonts_dir / filename
    if not font_path.exists():
        print(f"warning: font missing: {font_path}", file=sys.stderr)
        return None

    data = font_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    data_uri = f"url(data:font/woff2;base64,{b64}) format('woff2')"

    # Rebuild the src declaration with only the woff2 entry; keep other
    # declarations (font-family, font-style, font-weight, font-display, ...)
    # intact. We locate "src:" in the original body and rewrite just that
    # property by truncating at the last url()/format() pair it spans.
    # Property values are separated by ";" or bounded by the block's end.
    decls = [d.strip() for d in body.split(";") if d.strip()]
    rebuilt = []
    for d in decls:
        key, _, _ = d.partition(":")
        if key.strip().lower() == "src":
            rebuilt.append(f"src:{data_uri}")
        else:
            rebuilt.append(d)
    return "@font-face{" + ";".join(rebuilt) + "}"


def build(check: bool = False) -> int:
    if not KATEX_CSS.exists():
        print(
            f"error: {KATEX_CSS} not found. Run install_katex.sh first.",
            file=sys.stderr,
        )
        return 1
    if not FONTS_DIR.exists():
        print(f"error: fonts dir {FONTS_DIR} missing.", file=sys.stderr)
        return 1

    original = KATEX_CSS.read_text(encoding="utf-8")

    replaced = 0
    dropped = 0

    def _sub(m):
        nonlocal replaced, dropped
        new = _inline_font_face(m.group(0), FONTS_DIR)
        if new is None:
            dropped += 1
            return ""
        replaced += 1
        return new

    new_css = _FONTFACE_RE.sub(_sub, original)
    # Collapse runs of blank lines left behind by dropped @font-face blocks.
    new_css = re.sub(r"\n{3,}", "\n\n", new_css)
    new_css = new_css.rstrip() + "\n" + OVERRIDES

    print(
        f"inlined {replaced} @font-face blocks, dropped {dropped}",
        file=sys.stderr,
    )

    size_kb = len(new_css.encode("utf-8")) / 1024

    if check:
        if not BUNDLE_CSS.exists():
            print(
                f"check failed: {BUNDLE_CSS} missing (expected ~{size_kb:.0f} KB)",
                file=sys.stderr,
            )
            return 2
        current = BUNDLE_CSS.read_text(encoding="utf-8")
        if current != new_css:
            print(
                f"check failed: {BUNDLE_CSS} out of date",
                file=sys.stderr,
            )
            return 2
        print(f"check ok: {BUNDLE_CSS} ({size_kb:.0f} KB)")
        return 0

    BUNDLE_CSS.write_text(new_css, encoding="utf-8")
    print(f"wrote {BUNDLE_CSS} ({size_kb:.0f} KB)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Verify bundle is up to date without writing.",
    )
    args = ap.parse_args()
    sys.exit(build(check=args.check))


if __name__ == "__main__":
    main()
