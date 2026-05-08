#!/usr/bin/env python3
"""md2pdf - Convert Markdown to A4 PDF with academic formatting.

Features:
  - A4 paper with proper margins and page numbers
  - Auto-generated table of contents on a separate first page
  - Figures, tables, and code blocks never split across pages
  - Academic paper typography (serif body, sans headings, justified text)
"""

import argparse
import json
import re
import shutil
import subprocess
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
    from pygments.formatters import HtmlFormatter as _HtmlFormatter
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

/* ===== Mermaid diagrams ===== */
figure.mermaid-figure {
    margin: 1.2em auto;
    text-align: center;
    page-break-inside: avoid;
    break-inside: avoid;
}
figure.mermaid-figure svg {
    max-width: 100%;
    max-height: 220mm;
    height: auto;
    display: block;
    margin: 0 auto;
}
.mermaid-error {
    border: 1pt solid #d99;
    background: #fff6f6;
    padding: 0.6em 0.8em;
    margin: 1em 0;
    color: #722;
    font-size: 9pt;
    page-break-inside: avoid;
}
.mermaid-error details {
    margin-top: 0.4em;
    color: #444;
}
.mermaid-error pre {
    background: #fff;
    border: 0.5pt solid #ddd;
    margin: 0.3em 0 0;
    font-size: 8.5pt;
}
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


_MERMAID_FENCE_RE = re.compile(
    r"^([ \t]*)```[ \t]*mermaid[ \t]*\n(.*?)\n[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

# Placeholders use a token that mermaid's SSR is guaranteed not to reuse
# inside its generated SVG element ids (mermaid prefixes its ids with the
# render id but only with [-a-zA-Z0-9_]; lowercase keeps it stable).
_MERMAID_PH_PREFIX = "mmdsentinelph"


def _protect_mermaid(md_text):
    """Extract ```mermaid fenced blocks BEFORE markdown conversion.

    Returns (cleaned_text, mermaid_store). Each placeholder is a paragraph
    on its own so the markdown parser leaves it untouched.
    """
    store = {}
    counter = [0]

    def _repl(m):
        indent = m.group(1)
        src = m.group(2)
        # Only consume fences sitting at column 0 (or with no leading
        # indentation that would make them part of a list item / blockquote).
        # Indented fences are still passed through as code blocks.
        if indent:
            return m.group(0)
        key = f"{_MERMAID_PH_PREFIX}{counter[0]:04d}"
        counter[0] += 1
        store[key] = src
        return f"\n\n{key}\n\n"

    cleaned = _MERMAID_FENCE_RE.sub(_repl, md_text)
    return cleaned, store


def _restore_mermaid(html, mermaid_store):
    """Replace mermaid placeholders with rendered SVG figures.

    Successful renders become <figure class="mermaid"> with an inline SVG.
    Failures (chromium missing, render error, etc.) become an error notice
    box followed by a collapsed <details> with the original source.

    Returns ``(html, extra_css)``: ``extra_css`` should be appended to the
    document's <style> so mermaid's ID-scoped CSS rules are honored.
    """
    if not mermaid_store:
        return html, ""

    items = [{"id": k, "src": v} for k, v in mermaid_store.items()]
    rendered, extra_css = _render_mermaid_batch(items)

    chromium_present = _find_chromium() is not None
    bundle_present = _MERMAID_JS.exists()

    for key, src in mermaid_store.items():
        svg = rendered.get(key)
        if svg:
            replacement = (
                '<figure class="mermaid-figure">'
                f"{svg}"
                "</figure>"
            )
        else:
            if not chromium_present:
                reason = (
                    "未检测到 chromium-browser；mermaid 图未渲染。"
                    "运行 ~/.cursor/skills/md-to-pdf/install_mermaid.sh 之前请先装 chromium。"
                )
            elif not bundle_present:
                reason = (
                    "vendor/mermaid/mermaid.min.js 缺失。"
                    "运行 ~/.cursor/skills/md-to-pdf/install_mermaid.sh。"
                )
            else:
                reason = "mermaid 渲染失败（参见 stderr 中的具体错误）。"
            esc_src = (
                src.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            replacement = (
                '<div class="mermaid-error">'
                f'<strong>[Mermaid 渲染失败]</strong> {reason}'
                '<details><summary>原始 mermaid 源码</summary>'
                f'<pre><code>{esc_src}</code></pre>'
                '</details></div>'
            )
        # Placeholders show up wrapped in <p>...</p> after markdown processing.
        html = html.replace(f"<p>{key}</p>", replacement)
        html = html.replace(key, replacement)

    return html, extra_css


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
    (r"\lvert", r"\vert"),
    (r"\rvert", r"\vert"),
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
    fig = _plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${latex}$", fontsize=fontsize, math_fontfamily="cm")
    buf = _BytesIO()
    fig.savefig(buf, format="svg", bbox_inches="tight",
                transparent=True, pad_inches=0.03)
    _plt.close(fig)
    b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


_SKILL_DIR = Path(__file__).resolve().parent
_KATEX_BUNDLE_CSS = _SKILL_DIR / "vendor" / "katex_bundle.css"
_KATEX_RENDER_JS = _SKILL_DIR / "vendor" / "render_katex.js"
_MERMAID_DIR = _SKILL_DIR / "vendor" / "mermaid"
_MERMAID_JS = _MERMAID_DIR / "mermaid.min.js"
_MERMAID_RENDER_CACHE = _MERMAID_DIR / "render-cache"


_CHROMIUM_CANDIDATES = (
    "chromium-browser",
    "chromium",
    "google-chrome",
    "chrome",
)


def _find_chromium():
    """Return path to chromium-like binary, or None."""
    for name in _CHROMIUM_CANDIDATES:
        p = shutil.which(name)
        if p:
            return p
    return None


def _mermaid_available():
    """True if chromium and the mermaid bundle are both present."""
    return _MERMAID_JS.exists() and _find_chromium() is not None


def _render_mermaid_batch(items):
    """Render a batch of mermaid sources via chromium headless.

    Args:
        items: list of {"id": str, "src": str}.

    Returns:
        (svgs, extra_css) where ``svgs`` is dict[id] -> svg-without-<style>,
        and ``extra_css`` is the concatenation of every diagram's inline
        <style> block (each scoped via #mmd-<id> IDs that mermaid already
        emits, so they stay non-conflicting). Missing keys indicate failure.
    """
    if not items or not _mermaid_available():
        return {}, ""

    chromium = _find_chromium()
    _MERMAID_RENDER_CACHE.mkdir(parents=True, exist_ok=True)
    html_path = _MERMAID_RENDER_CACHE / "render.html"

    # Build (placeholder_id, render_slot, src) triples. We render mermaid
    # under a generic, short slot id ("mmdR0", "mmdR1", ...) so that the
    # SVG element ids it emits don't share a substring with our HTML
    # placeholder (which would later be eaten by the placeholder->figure
    # html.replace, recursively corrupting the SVG).
    targets = []
    for i, it in enumerate(items):
        ph = it.get("id")
        src = it.get("src")
        if not ph or not isinstance(src, str):
            continue
        targets.append({
            "ph": str(ph),
            "slot": f"mmdR{i:04d}",
            "src": src,
        })
    if not targets:
        return {}, ""

    divs = "\n".join(f'<div id="{t["slot"]}"></div>' for t in targets)
    payload_js = json.dumps(
        [{"id": t["slot"], "src": t["src"]} for t in targets],
        ensure_ascii=False,
    )

    html = (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        '<title>PEND</title></head><body>\n'
        f'{divs}\n'
        '<script src="../mermaid.min.js"></script>\n'
        '<script>\n'
        '(async () => {\n'
        '  try {\n'
        '    mermaid.initialize({ startOnLoad: false, theme: "default", '
        'securityLevel: "loose", flowchart: { htmlLabels: true } });\n'
        f'    const items = {payload_js};\n'
        '    for (const it of items) {\n'
        '      try {\n'
        '        const r = await mermaid.render("mmd-" + it.id, it.src);\n'
        '        document.getElementById(it.id).innerHTML = r.svg;\n'
        '        document.getElementById(it.id).setAttribute("data-mmd-ok", "1");\n'
        '      } catch (e) {\n'
        '        const el = document.getElementById(it.id);\n'
        '        if (el) {\n'
        '          el.setAttribute("data-mmd-ok", "0");\n'
        '          el.setAttribute("data-mmd-err", String(e && e.message || e).slice(0, 500));\n'
        '        }\n'
        '      }\n'
        '    }\n'
        '    document.title = "MMD_DONE";\n'
        '  } catch (e) {\n'
        '    document.title = "MMD_FATAL_" + String(e && e.message || e).slice(0, 80);\n'
        '  }\n'
        '})();\n'
        '</script>\n'
        '</body></html>\n'
    )
    html_path.write_text(html, encoding="utf-8")

    args = [
        chromium,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--virtual-time-budget=30000",
        "--run-all-compositor-stages-before-draw",
        "--dump-dom",
        f"file://{html_path}",
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True,
            timeout=90, check=False,
        )
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Warning: chromium failed for mermaid render: {e}", file=sys.stderr)
        return {}, ""

    dump = proc.stdout or ""
    if "<title>MMD_DONE</title>" not in dump:
        m = re.search(r'<title>(MMD_FATAL_[^<]*)</title>', dump)
        msg = m.group(1) if m else "title not MMD_DONE; chromium may have errored"
        print(f"Warning: mermaid batch render incomplete ({msg})", file=sys.stderr)

    results = {}
    style_blocks = []
    for t in targets:
        slot = t["slot"]
        ph = t["ph"]
        # Find <div id="<slot>" ...>...</div> capturing inner content. The DOM
        # is dumped on a single (very long) line by chromium, so a non-greedy
        # match against the next </div> at the same nesting level works for
        # our flat structure.
        # We use a hand-rolled scanner because the SVG inside contains <div>s
        # via foreignObject, which would confuse a naive regex.
        idx = dump.find(f'id="{slot}"')
        if idx < 0:
            continue
        # Walk back to the opening '<div'.
        open_start = dump.rfind("<div", 0, idx)
        if open_start < 0:
            continue
        open_end = dump.find(">", idx)
        if open_end < 0:
            continue
        # Walk forward, balancing <div> / </div> nesting.
        depth = 1
        cursor = open_end + 1
        while depth > 0 and cursor < len(dump):
            next_open = dump.find("<div", cursor)
            next_close = dump.find("</div>", cursor)
            if next_close < 0:
                break
            if 0 <= next_open < next_close:
                depth += 1
                cursor = next_open + 4
            else:
                depth -= 1
                cursor = next_close + 6
        inner_end = cursor - 6  # back up past "</div>"
        inner = dump[open_end + 1:inner_end]

        # Read attributes off the opening tag.
        open_tag = dump[open_start:open_end + 1]
        ok = re.search(r'data-mmd-ok="1"', open_tag) is not None
        if not ok:
            err_m = re.search(r'data-mmd-err="([^"]*)"', open_tag)
            if err_m:
                print(f"Warning: mermaid render failed for {ph}: "
                      f"{err_m.group(1)}", file=sys.stderr)
            continue

        svg_m = re.search(r"<svg[\s\S]*?</svg>", inner)
        if not svg_m:
            continue
        svg = svg_m.group(0)
        svg = _scrub_svg_for_weasyprint(svg, style_blocks)
        results[ph] = svg

    extra_css = "\n".join(style_blocks)
    return results, extra_css


_DEF_LIKE_TAGS = ("marker", "linearGradient", "radialGradient", "pattern",
                  "filter", "clipPath", "mask", "symbol")


def _scrub_svg_for_weasyprint(svg, style_blocks):
    """Make a mermaid SVG render correctly under WeasyPrint.

    WeasyPrint's SVG renderer has known issues with mermaid's output:
      1. <style>...</style> inside the SVG has its CSS rules applied (yay)
         but its textual body is *also* rendered as visible text below the
         diagram. Mitigation: inline every CSS rule as a ``style=""``
         attribute on the matching SVG elements, then drop the <style>.
      2. Top-level <marker>/<linearGradient>/<filter>/... etc. aren't
         recognized as paint servers and their attributes dump as text.
         Mitigation: move them inside <defs>, which is never rendered as
         visible content but still resolvable via url(#...).
    The raw CSS is also surfaced via ``style_blocks`` so the caller can
    mirror it to the document <head> as defense-in-depth.
    """
    captured_styles = []

    def _capture_style(m):
        captured_styles.append(m.group(1))
        style_blocks.append(m.group(1))
        return ""

    svg = re.sub(r"<style[^>]*>([\s\S]*?)</style>", _capture_style, svg)

    if captured_styles:
        svg = _inline_css_into_svg(svg, "\n".join(captured_styles))

    def_tags_alt = "|".join(_DEF_LIKE_TAGS)
    def_pattern = re.compile(
        rf"<({def_tags_alt})\b[\s\S]*?</\1\s*>",
        re.IGNORECASE,
    )
    captured_defs = []

    def _capture_def(m):
        captured_defs.append(m.group(0))
        return ""

    svg = def_pattern.sub(_capture_def, svg)

    if captured_defs:
        svg = re.sub(
            r"(<svg\b[^>]*>)",
            r"\1<defs>" + "".join(captured_defs) + "</defs>",
            svg,
            count=1,
        )

    return svg


# --- Tiny CSS-to-inline-style applier scoped to a single mermaid SVG ----------
#
# Mermaid emits rules like
#     #mmd-id .node rect, #mmd-id .label text { fill:#333; ... }
# We don't actually care about the #mmd-id prefix because we only apply each
# rule to the SVG that contained it. The supported selector grammar is
# intentionally tiny (it covers everything mermaid actually emits):
#
#     selector := simpleSelector ( whitespace simpleSelector )*
#     simpleSelector := ('#' id | '.' className | tagName)+
#
# For each rule we walk the SVG element-by-element, test each opening tag
# against every selector in the rule's selector list, and merge the rule's
# declaration block into the element's existing ``style`` attribute. New
# declarations win over the existing inline style only when the existing one
# does not already declare the same property (existing inline wins).

_OPEN_TAG_RE = re.compile(r"<([a-zA-Z][\w:-]*)\b([^>]*)>")
_ATTR_RE = re.compile(r'(\w[\w:-]*)\s*=\s*"([^"]*)"')


def _split_top_level(s, sep):
    """Split ``s`` on ``sep`` while ignoring ``sep`` inside parentheses or
    matched braces (used for selector lists and declaration lists)."""
    parts, buf, depth_p, depth_b = [], [], 0, 0
    for ch in s:
        if ch == "(":
            depth_p += 1
        elif ch == ")":
            depth_p -= 1
        elif ch == "{":
            depth_b += 1
        elif ch == "}":
            depth_b -= 1
        if ch == sep and depth_p == 0 and depth_b == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _parse_simple_selector(token):
    """Parse a simple selector like 'g.foo.bar#baz' into a matcher dict."""
    tag = None
    classes = []
    ids = []
    i = 0
    if i < len(token) and token[i] not in ".#":
        m = re.match(r"[a-zA-Z][\w:-]*|\*", token[i:])
        if m:
            tag = m.group(0)
            i += len(tag)
            if tag == "*":
                tag = None
    while i < len(token):
        if token[i] == ".":
            j = i + 1
            while j < len(token) and (token[j].isalnum() or token[j] in "_-"):
                j += 1
            classes.append(token[i + 1:j])
            i = j
        elif token[i] == "#":
            j = i + 1
            while j < len(token) and (token[j].isalnum() or token[j] in "_-"):
                j += 1
            ids.append(token[i + 1:j])
            i = j
        else:
            return None
    return {"tag": tag, "classes": classes, "ids": ids}


def _parse_compound_selector(sel):
    """Parse ``#a .b c`` or ``#a > .b > c`` into a list of simple-selector
    matchers. ``>`` (child combinator) is treated the same as plain
    descendant since mermaid's SVG nesting is shallow enough that the
    distinction doesn't matter for our purpose.
    """
    sel = sel.replace(">", " ")
    parts = []
    for tok in sel.split():
        m = _parse_simple_selector(tok)
        if m is None:
            return None
        parts.append(m)
    return parts or None


def _matches_simple(simple, tag, classes, eid):
    if simple["tag"] and simple["tag"].lower() != tag.lower():
        return False
    if simple["classes"] and not all(c in classes for c in simple["classes"]):
        return False
    if simple["ids"] and not all(i == eid for i in simple["ids"]):
        return False
    return True


def _inline_css_into_svg(svg, css_text):
    # Strip /* comments */
    css_text = re.sub(r"/\*[\s\S]*?\*/", "", css_text)

    rules = []
    pos = 0
    while pos < len(css_text):
        brace = css_text.find("{", pos)
        if brace < 0:
            break
        end = css_text.find("}", brace + 1)
        if end < 0:
            break
        sel_text = css_text[pos:brace].strip()
        decl_text = css_text[brace + 1:end].strip()
        pos = end + 1
        if not sel_text or sel_text.startswith("@"):
            continue
        selectors = []
        for sel in _split_top_level(sel_text, ","):
            sel = sel.strip()
            if not sel or any(ch in sel for ch in "~+:["):
                # We don't support sibling combinators or pseudo-classes.
                continue
            parsed = _parse_compound_selector(sel)
            if parsed:
                selectors.append(parsed)
        if not selectors:
            continue
        decls = {}
        for d in _split_top_level(decl_text, ";"):
            d = d.strip()
            if not d or ":" not in d:
                continue
            prop, _, val = d.partition(":")
            decls[prop.strip().lower()] = val.strip()
        if decls:
            rules.append((selectors, decls))

    if not rules:
        return svg

    # Walk the SVG element-by-element, tracking an ancestor stack so that
    # descendant selectors can be applied.
    out = []
    stack = []  # list of dicts: {tag, classes, id}
    cursor = 0
    for m in re.finditer(r"<(/?)([a-zA-Z][\w:-]*)\b([^>]*)(/?)>", svg):
        out.append(svg[cursor:m.start()])
        cursor = m.end()
        closing = m.group(1) == "/"
        tag = m.group(2)
        attrs_text = m.group(3)
        self_close = m.group(4) == "/" or tag.lower() in (
            "br", "img", "hr", "meta", "link", "input", "use", "stop"
        ) or attrs_text.rstrip().endswith("/")

        if closing:
            if stack and stack[-1]["tag"].lower() == tag.lower():
                stack.pop()
            out.append(m.group(0))
            continue

        attrs = dict(_ATTR_RE.findall(attrs_text))
        classes = (attrs.get("class") or "").split()
        eid = attrs.get("id")
        node = {"tag": tag, "classes": classes, "id": eid}

        # Build an ancestor view for descendant matching.
        ancestor_chain = stack + [node]
        new_decls = {}
        for selectors, decls in rules:
            for compound in selectors:
                # Match if compound's last simple matches `node` and each
                # earlier simple matches some ancestor in order.
                if not _matches_simple(compound[-1], tag, classes, eid):
                    continue
                ai = len(ancestor_chain) - 2
                ok = True
                for simple in reversed(compound[:-1]):
                    while ai >= 0:
                        a = ancestor_chain[ai]
                        ai -= 1
                        if _matches_simple(simple, a["tag"], a["classes"], a["id"]):
                            break
                    else:
                        ok = False
                        break
                if ok:
                    for k, v in decls.items():
                        new_decls[k] = v
                    break  # one selector match per rule is enough

        if new_decls:
            existing = attrs.get("style", "")
            existing_props = {}
            for d in _split_top_level(existing, ";"):
                d = d.strip()
                if ":" in d:
                    prop, _, val = d.partition(":")
                    existing_props[prop.strip().lower()] = val.strip()
            # Existing inline style wins over the mermaid stylesheet.
            for k, v in new_decls.items():
                existing_props.setdefault(k, v)
            merged = "; ".join(f"{k}: {v}" for k, v in existing_props.items())
            if "style=" in attrs_text:
                attrs_text = re.sub(
                    r'style\s*=\s*"[^"]*"',
                    f'style="{merged}"',
                    attrs_text,
                    count=1,
                )
            else:
                attrs_text = attrs_text.rstrip() + f' style="{merged}"'
            new_open = f"<{tag}{attrs_text}{'/' if self_close else ''}>"
            out.append(new_open)
        else:
            out.append(m.group(0))

        if not self_close:
            stack.append(node)

    out.append(svg[cursor:])
    return "".join(out)


def _katex_available():
    """True if Node is on PATH and the KaTeX vendored assets are present."""
    if shutil.which("node") is None:
        return False
    if not _KATEX_RENDER_JS.exists():
        return False
    katex_js = _SKILL_DIR / "vendor" / "katex" / "dist" / "katex.min.js"
    return katex_js.exists()


def _katex_render_batch(items):
    """Render a batch of LaTeX snippets via Node + KaTeX.

    Args:
        items: list of {"id": str, "tex": str, "display": bool}.

    Returns:
        dict[id] -> html for successful renders. Missing keys indicate
        failure and the caller should fall back to mathtext / MathML / code.
    """
    if not items or not _katex_available():
        return {}
    try:
        proc = subprocess.run(
            ["node", str(_KATEX_RENDER_JS)],
            input=json.dumps(items),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        out = json.loads(proc.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        print(f"Warning: KaTeX batch render failed: {e}", file=sys.stderr)
        return {}
    results = {}
    for r in out:
        if r.get("ok") and isinstance(r.get("html"), str):
            results[r["id"]] = r["html"]
    return results


def _load_katex_bundle_css():
    """Return contents of katex_bundle.css if available, else empty string."""
    if not _KATEX_BUNDLE_CSS.exists():
        return ""
    try:
        return _KATEX_BUNDLE_CSS.read_text(encoding="utf-8")
    except OSError:
        return ""


def _restore_math(html, math_store):
    """Replace placeholders with rendered math.

    Priority: KaTeX (HTML) > matplotlib mathtext (SVG) >
              latex2mathml (MathML) > raw <code>.
    """
    katex_items = [
        {"id": key, "tex": latex, "display": bool(display)}
        for key, (latex, display) in math_store.items()
    ]
    katex_results = _katex_render_batch(katex_items)

    for key, (latex, display) in math_store.items():
        replacement = katex_results.get(key)

        if replacement is None:
            fixed = _fixup_latex(latex)
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

        if replacement is None and _l2m is not None:
            try:
                mathml = _l2m.convert(latex)
                if display:
                    replacement = f'<div class="math-display">{mathml}</div>'
                else:
                    replacement = mathml
            except Exception:
                pass

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

    # Extract mermaid fences first so the source isn't mangled by
    # markdown's inline parser (e.g. underscores in identifiers).
    md_text, mermaid_store = _protect_mermaid(md_text)

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
    body, mermaid_css = _restore_mermaid(body, mermaid_store)

    toc_section = ""
    has_toc = _has_manual_toc(md_text)
    if not no_toc and not has_toc and getattr(md, "toc_tokens", None):
        toc_section = (
            '<div class="toc-page">'
            '<h1 class="toc-title">目 录</h1>'
            f'<div class="toc">{md.toc}</div>'
            "</div>"
        )

    katex_css = _load_katex_bundle_css() if _katex_available() else ""

    html_str = (
        "<!DOCTYPE html>"
        '<html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{doc_title}</title>"
        f"<style>{CSS}"
        f"{_HtmlFormatter(style='default').get_style_defs('.codehilite') if pygments else ''}"
        f"{katex_css}"
        f"{mermaid_css}"
        f"</style>"
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
