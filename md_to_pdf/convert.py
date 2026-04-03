#!/usr/bin/env python3
"""md2pdf - Convert Markdown to A4 PDF with academic formatting.

Features:
  - A4 paper with proper margins and page numbers
  - Auto-generated table of contents on a separate first page
  - Figures, tables, and code blocks never split across pages
  - Academic paper typography (serif body, sans headings, justified text)
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("Error: 'markdown' package not found. Run: pip install markdown")

try:
    from weasyprint import HTML as WeasyHTML
except ImportError:
    sys.exit("Error: 'weasyprint' package not found. Run: pip install weasyprint")

try:
    import pygments  # noqa: F401 – needed by codehilite
except ImportError:
    pygments = None

try:
    import latex2mathml.converter as _l2m
except ImportError:
    _l2m = None

try:
    import matplotlib as _mpl
    _mpl.use("Agg")
    import matplotlib.pyplot as _plt
    from io import BytesIO as _BytesIO
    import base64 as _b64
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False

# ---------------------------------------------------------------------------
# CSS – A4 academic paper styling
# ---------------------------------------------------------------------------
CSS = r"""
/* ===== Page setup ===== */
@page {
    size: A4;
    margin: 25mm 22mm 28mm 22mm;
    @bottom-center {
        content: counter(page);
        font-family: "Times New Roman", serif;
        font-size: 10pt;
        color: #555;
    }
}
@page toc {
    @bottom-center { content: none; }
}

/* ===== Body ===== */
body {
    font-family: "Noto Serif CJK SC", "Source Han Serif SC", "SimSun",
                 "Times New Roman", "Georgia", serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #222;
    text-align: justify;
    word-wrap: break-word;
}

/* ===== TOC page ===== */
.toc-page {
    page: toc;
    page-break-after: always;
}
.toc-title {
    text-align: center;
    font-size: 14pt;
    margin-top: 3em;
    margin-bottom: 1.5em;
    letter-spacing: 0.5em;
    font-family: "Noto Sans CJK SC", "Source Han Sans SC",
                 "Microsoft YaHei", sans-serif;
}
.toc ul        { list-style: none; padding-left: 0; }
.toc li        { margin: 0.25em 0; line-height: 1.6; }
.toc a         { color: #222; text-decoration: none; }
.toc ul ul     { padding-left: 1.5em; }

/* ===== Headings ===== */
h1, h2, h3, h4, h5, h6 {
    font-family: "Noto Sans CJK SC", "Source Han Sans SC",
                 "Microsoft YaHei", "Helvetica Neue", sans-serif;
    page-break-after: avoid;
    margin-top: 1.4em;
    margin-bottom: 0.4em;
}
.content > h1:first-child {
    text-align: center;
    font-size: 17pt;
    margin-top: 1.5em;
    margin-bottom: 0.8em;
}
h1 { font-size: 12pt; }
h2 { font-size: 10.5pt; border-bottom: 0.5pt solid #ccc; padding-bottom: 0.15em; }
h3 { font-size: 10pt; }
h4 { font-size: 10pt; }

/* ===== Page-break safety ===== */
table, figure, pre, .codehilite, blockquote, img {
    page-break-inside: avoid;
}
h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
}
p { orphans: 3; widows: 3; }

/* ===== Tables ===== */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 9pt;
}
th, td {
    border: 1px solid #777;
    padding: 4px 6px;
}
th {
    background: #f2f2f2;
    font-weight: bold;
    text-align: center;
}

/* ===== Images / figures ===== */
img {
    max-width: 100%;
    max-height: 230mm;
    height: auto;
    display: block;
    margin: 1em auto;
}
figure {
    margin: 1.2em auto;
    text-align: center;
}
figcaption {
    font-size: 8pt;
    color: #555;
    margin-top: 0.3em;
    page-break-before: avoid;
}

/* ===== Code ===== */
pre {
    background: #f7f7f7;
    border: 0.5pt solid #ddd;
    border-radius: 3px;
    padding: 10px 14px;
    font-size: 9pt;
    line-height: 1.4;
    overflow-wrap: break-word;
    white-space: pre-wrap;
}
code {
    font-family: "Consolas", "Source Code Pro", "Menlo", monospace;
    font-size: 9pt;
}
p code, li code {
    background: #f0f0f0;
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 9pt;
}

/* ===== Blockquote ===== */
blockquote {
    border-left: 3px solid #bbb;
    padding: 0.4em 1em;
    margin: 0.8em 0;
    color: #444;
    background: #fafafa;
}

/* ===== Misc ===== */
a        { color: #2a5db0; text-decoration: none; }
p        { margin: 0.6em 0; }
ul, ol   { padding-left: 2em; margin: 0.5em 0; }
li       { margin: 0.15em 0; }
hr       { border: none; border-top: 0.5pt solid #ccc; margin: 2em 0; }
.footnote    { font-size: 9pt; color: #555; }
.footnote hr { border-top: 0.5pt solid #ddd; margin: 1em 0 0.5em; }

/* ===== Pygments (codehilite) ===== */
.codehilite { margin: 1em 0; }

/* ===== Math ===== */
.math-display { text-align: center; margin: 0.8em 0; }
.math-display img { display: inline-block; max-width: 90%; }
img.math-inline { display: inline; height: auto; margin: 0; vertical-align: -0.4em; }
math { font-family: "STIX Two Math", "Cambria Math", "Latin Modern Math",
                     "Noto Serif CJK SC", serif; }
math[display="block"] { display: block; text-align: center; margin: 0.8em 0; }
"""


def _unicode_slugify(value, separator="-"):
    """Slugify preserving CJK characters."""
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"[\s]+", separator, value.strip().lower())


def _has_manual_toc(md_text):
    """Check if the markdown already contains a table of contents section."""
    return bool(re.search(
        r"^#{1,3}\s+.*(?:目录|[Cc]ontents|[Tt]able\s+[Oo]f\s+[Cc]ontents)",
        md_text, re.MULTILINE,
    ))


def _protect_math(md_text):
    """Extract LaTeX math from markdown BEFORE conversion to prevent _ and *
    being interpreted as emphasis.  Returns (cleaned_text, math_dict)."""
    math_store = {}
    counter = [0]

    def _placeholder(m, display):
        key = f"MATHPH{counter[0]:04d}"
        counter[0] += 1
        math_store[key] = (m.group(1).strip(), display)
        return f"\n\n{key}\n\n" if display else key

    # Split at fenced code blocks so we don't touch math inside ```...```
    parts = re.split(r"(```[\s\S]*?```)", md_text)
    for i in range(len(parts)):
        if parts[i].startswith("```"):
            continue
        parts[i] = re.sub(
            r"\$\$(.*?)\$\$",
            lambda m: _placeholder(m, True),
            parts[i], flags=re.DOTALL,
        )
        parts[i] = re.sub(
            r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
            lambda m: _placeholder(m, False),
            parts[i],
        )

    return "".join(parts), math_store


_MATHTEXT_FIXUPS = [
    (r"\bmod", r"\ \mathrm{mod}\ "),
    (r"\pmod", r"\ \mathrm{mod}\ "),
]


def _fixup_latex(latex):
    """Replace LaTeX commands unsupported by matplotlib mathtext."""
    for old, new in _MATHTEXT_FIXUPS:
        latex = latex.replace(old, new)
    return latex


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _latex_to_svg(latex, display=False):
    """Render a LaTeX string to an SVG data-URI via matplotlib mathtext."""
    if not _HAS_MPL:
        return None
    if _CJK_RE.search(latex):
        return None
    fontsize = 12 if display else 10
    prefix = r"\displaystyle " if display else ""
    fig = _plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${prefix}{latex}$", fontsize=fontsize,
             math_fontfamily="cm")
    buf = _BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight",
                transparent=True, pad_inches=0.03)
    _plt.close(fig)
    b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _restore_math(html, math_store):
    """Replace placeholders with rendered math.

    Priority: matplotlib mathtext (SVG) > latex2mathml (MathML) > raw <code>.
    """
    for key, (latex, display) in math_store.items():
        fixed = _fixup_latex(latex)
        replacement = None

        # 1) Try matplotlib mathtext
        try:
            src = _latex_to_svg(fixed, display=display)
            if src:
                if display:
                    replacement = (
                        f'<div class="math-display">'
                        f'<img src="{src}"></div>'
                    )
                else:
                    replacement = f'<img class="math-inline" src="{src}">'
        except Exception:
            pass

        # 2) Fallback: latex2mathml
        if replacement is None and _l2m is not None:
            try:
                mathml = _l2m.convert(latex)
                if display:
                    replacement = f'<div class="math-display">{mathml}</div>'
                else:
                    replacement = mathml
            except Exception:
                pass

        # 3) Fallback: raw LaTeX in <code>
        if replacement is None:
            if display:
                replacement = (
                    f'<div class="math-display"><code>{latex}</code></div>'
                )
            else:
                replacement = f"<code>{latex}</code>"

        html = html.replace(key, replacement)

    return html


def _wrap_images(html):
    """Wrap standalone <img> in <figure>; use alt text as caption."""

    def _repl(m):
        tag = m.group(0)
        alt = re.search(r'alt="([^"]*)"', tag)
        alt_text = alt.group(1).strip() if alt else ""
        cap = f"<figcaption>{alt_text}</figcaption>" if alt_text else ""
        return f"<figure>{tag}{cap}</figure>"

    return re.sub(r"<img\b[^>]*>", _repl, html)


def convert(input_path, output_path=None, no_toc=False, title=None):
    src = Path(input_path).resolve()
    if not src.exists():
        print(f"Error: {src} not found", file=sys.stderr)
        sys.exit(1)

    dst = Path(output_path).resolve() if output_path else src.with_suffix(".pdf")

    md_text = src.read_text(encoding="utf-8")
    md_text = re.sub(r"^\[TOC\]\s*$", "", md_text, flags=re.MULTILINE | re.IGNORECASE)

    # Separate consecutive lines starting with [number] (e.g. reference lists)
    # so Markdown treats each as its own paragraph instead of merging them.
    md_text = re.sub(
        r"(\n\[\d+\])",
        r"\n\1",
        md_text,
    )

    title_match = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    doc_title = title or (title_match.group(1).strip() if title_match else src.stem)

    # Extract math before markdown conversion to protect _ and * from
    # being interpreted as emphasis markers inside LaTeX formulas.
    md_text, math_store = _protect_math(md_text)

    extensions = [
        "tables",
        "fenced_code",
        "codehilite",
        "toc",
        "footnotes",
        "attr_list",
        "md_in_html",
        "sane_lists",
    ]
    ext_cfg = {
        "codehilite": {"css_class": "codehilite", "guess_lang": False},
        "toc": {
            "permalink": False,
            "slugify": _unicode_slugify,
            "toc_depth": "1-4",
        },
    }

    md = markdown.Markdown(extensions=extensions, extension_configs=ext_cfg)
    body = md.convert(md_text)
    body = _wrap_images(body)
    body = _restore_math(body, math_store)

    toc_section = ""
    has_toc = _has_manual_toc(md_text)
    if not no_toc and not has_toc and getattr(md, "toc_tokens", None):
        toc_section = (
            '<div class="toc-page">'
            '<h1 class="toc-title">目 录</h1>'
            f'<div class="toc">{md.toc}</div>'
            "</div>"
        )

    html_str = (
        "<!DOCTYPE html>"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{doc_title}</title>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f"{toc_section}"
        f'<div class="content">{body}</div>'
        "</body></html>"
    )

    WeasyHTML(string=html_str, base_url=f"{src.parent}/").write_pdf(str(dst))
    print(f"Output: {dst}")


def main():
    ap = argparse.ArgumentParser(
        description="Convert Markdown to A4 PDF with academic formatting"
    )
    ap.add_argument("input", help="Markdown file path")
    ap.add_argument(
        "-o", "--output", help="Output PDF path (default: <input>.pdf)"
    )
    ap.add_argument("--no-toc", action="store_true", help="Skip TOC page")
    ap.add_argument(
        "--title", help="Document title (default: first H1 or filename)"
    )
    args = ap.parse_args()
    convert(args.input, args.output, no_toc=args.no_toc, title=args.title)


if __name__ == "__main__":
    main()
