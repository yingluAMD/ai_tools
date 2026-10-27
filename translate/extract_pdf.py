#!/usr/bin/env python3
"""Extract PDF content to Markdown + images for bilingual translation.

Usage:
    python3 extract_pdf.py <input.pdf> [output_dir] [--ocr-threshold N] [--no-ocr] [--device auto|cpu|cuda]

Outputs:
    {output_dir}/extracted.md     -- Markdown from Marker
    {output_dir}/images/          -- Extracted images
    {output_dir}/ocr_report.json  -- OCR results for text-heavy images (if OCR enabled)

Prints a JSON summary to stdout for the calling agent.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared constants & helpers
# ---------------------------------------------------------------------------

_CAPTION_RE = re.compile(r"^(?:Figure|Fig\.?)\s*(\d+)\s*:", re.IGNORECASE)
_PAGE_MARKER_RE = re.compile(r"page-(\d+)-")
_RENDER_DPI = 200
_PAD_PT = 10
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}


def _block_text(block: dict) -> str:
    """Extract concatenated text from a PyMuPDF text block."""
    parts = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            parts.append(span.get("text", ""))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Code block language tagging
# ---------------------------------------------------------------------------

_BARE_FENCE_RE = re.compile(r"^``` *\n(.*?\n)``` *$", re.MULTILINE | re.DOTALL)
_OCR_SPACING_RE = re.compile(r"\b(\w ){2,}\w\b")

# Keywords whose letters get separated by spaces in PDF extraction.
# Sorted longest-first so "template" is replaced before "int" etc.
_SPACED_KEYWORDS = sorted([
    "template", "namespace", "typename", "continue", "unsigned", "volatile",
    "explicit", "operator", "override", "register", "noexcept",
    "virtual", "private", "typedef", "default", "nullptr", "mutable",
    "include", "defined", "finally", "protected",
    "struct", "static", "public", "extern", "return", "sizeof", "switch",
    "double", "signed", "delete", "import", "lambda", "global", "assert",
    "except",
    "const", "class", "while", "float", "short", "break", "throw", "catch",
    "using", "false", "yield", "raise", "async", "await", "super", "print",
    "void", "char", "long", "enum", "bool", "true", "auto", "else", "case",
    "this", "with", "elif", "pass", "from", "None", "True",
    "for", "int", "try", "def", "new", "not", "and",
], key=len, reverse=True)

_SPACED_KW_PATTERNS = [(re.compile(r"(?<!\w)" + r"\s+".join(kw) + r"(?!\w)"), kw)
                        for kw in _SPACED_KEYWORDS]


def _normalize_ocr(text: str) -> str:
    """Collapse all single-char spacing artifacts for language detection.

    Aggressive collapse — used only for analysis, never modifies actual content.
    """
    return _OCR_SPACING_RE.sub(lambda m: m.group().replace(" ", ""), text)


def _fix_letter_spacing(text: str) -> str:
    """Fix letter-spacing artifacts in code block content.

    Replaces only known programming keywords that appear with spaces between
    each letter (e.g. 't e m p l a t e' -> 'template'), preserving single-char
    variable names like 'm', 'i', 'k' intact.
    """
    for pat, kw in _SPACED_KW_PATTERNS:
        text = pat.sub(kw, text)
    return text


def _detect_code_language(code: str) -> str:
    """Detect programming language from code block content."""
    norm = _normalize_ocr(code)
    lines = [l for l in norm.splitlines() if l.strip()]
    if not lines:
        return ""

    if any(l.lstrip().startswith(">>>") for l in lines):
        return "python"

    if any(kw in norm for kw in ("__global__", "__device__", "__shared__", "<<<")):
        return "cuda"

    cpp_strong = ("template<", "template <", "namespace ", "std::",
                  "#include", "typename ", "const&", "const &")
    if any(kw in norm for kw in cpp_strong):
        return "cpp"

    py_score = 0
    py_kws = ("import ", "def ", "elif ", "yield ", "lambda ",
              "assert ", " in range(", "print(", "from ", " None")
    py_score += sum(1 for kw in py_kws if kw in norm)
    for l in lines:
        stripped = l.lstrip()
        if stripped.startswith("#") and not stripped.startswith("#include"):
            py_score += 1
            break
        if re.search(r"\S\s+#\s", l):
            py_score += 1
            break
    if re.search(r"\w\[.*:.*\]", norm):
        py_score += 1
    if any(l.rstrip().endswith(":") for l in lines):
        py_score += 1

    c_score = 0
    if any(l.rstrip().endswith(";") for l in lines):
        c_score += 2
    if "{" in norm or "}" in norm:
        c_score += 1
    c_score += sum(1 for kw in ("void ", "int ", "auto ", "return ") if kw in norm)
    if re.search(r"for\s*\(", norm):
        c_score += 2
    if "//" in norm:
        c_score += 1

    if py_score >= 2:
        return "python"
    if c_score >= 3:
        return "cpp"
    if py_score >= 1 and c_score == 0:
        return "python"

    if len(lines) <= 4 and c_score == 0 and py_score == 0:
        return "text"

    return ""


def _tag_code_blocks(markdown_text: str) -> str:
    """Add language tags to untagged code fences based on content analysis."""
    tagged = [0]

    def _replace(m):
        code = m.group(1)
        lang = _detect_code_language(code)
        fixed_code = _fix_letter_spacing(code)
        if lang:
            tagged[0] += 1
            return f"```{lang}\n{fixed_code}```"
        if fixed_code != code:
            tagged[0] += 1
            return f"```\n{fixed_code}```"
        return m.group(0)

    result = _BARE_FENCE_RE.sub(_replace, markdown_text)
    if tagged[0]:
        print(f"[Code] Tagged {tagged[0]} code block(s) with language identifiers",
              file=sys.stderr)
    return result


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------

def detect_device(requested: str = "auto") -> str:
    """Auto-detect best compute device. Returns 'cuda' or 'cpu'."""
    if requested == "cpu":
        print("[Device] Using CPU (forced)", file=sys.stderr)
        return "cpu"

    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"[Device] CUDA GPU detected: {name} ({mem_gb:.1f} GB)", file=sys.stderr)
            return "cuda"
        elif requested == "cuda":
            print("[Device] WARNING: --device cuda but CUDA not available, falling back to CPU", file=sys.stderr)
    except ImportError:
        if requested == "cuda":
            print("[Device] WARNING: PyTorch not installed with CUDA support", file=sys.stderr)

    print("[Device] Using CPU (no CUDA GPU detected)", file=sys.stderr)
    return "cpu"


# ---------------------------------------------------------------------------
# Step 1: Marker extraction
# ---------------------------------------------------------------------------

def extract_with_marker(pdf_path: str, output_dir: str, device: str) -> tuple[str, dict[str, str]]:
    """Convert PDF to Markdown using Marker on the specified device."""
    os.environ["TORCH_DEVICE"] = device

    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(pdf_path)
    text, _, images = text_from_rendered(rendered)

    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    saved = {}
    for name, img_data in images.items():
        png_name = str(Path(name).with_suffix(".png"))
        path = os.path.join(images_dir, png_name)
        img_data.save(path, format="PNG")
        saved[png_name] = path
        if name != png_name:
            text = text.replace(name, png_name)

    return text, saved


# ---------------------------------------------------------------------------
# Step 2: PyMuPDF image extraction & quality upgrade
# ---------------------------------------------------------------------------

_DECORATION_PAGE_RATIO = 0.30  # image appearing on >=30% of pages -> page header/footer
_TINY_IMG_DIM = 80              # images < 80x80 px -> bullet/icon decoration


def extract_images_pymupdf(pdf_path: str, output_dir: str) -> tuple[list[str], dict]:
    """Extract full-resolution images via PyMuPDF with position metadata.

    Applies two filters before writing files to disk:
    - Decoration filter: any image whose byte content (MD5) appears on
      >= 30% of all pages is treated as page header/footer (logo, watermark)
      and skipped entirely.
    - Tiny filter: images smaller than 80x80 px are dropped as bullets/icons.

    Identical raster bytes shared across multiple pages are written once and
    referenced by every page that contains them via page_map.

    Returns (extracted_paths, page_map) where page_map is:
        {page_1indexed: [{"path": ..., "name": ..., "w": ..., "h": ..., "rect": (x0,y0,x1,y1)}, ...]}
    """
    import fitz
    import hashlib

    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    decoration_threshold = max(3, int(total_pages * _DECORATION_PAGE_RATIO))

    occurrences: list[dict] = []
    for page_idx in range(total_pages):
        page = doc[page_idx]
        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue

            img_bytes = base["image"]
            ext = base.get("ext", "png")
            if ext != "png":
                from PIL import Image as _PILImage
                from io import BytesIO
                pil_img = _PILImage.open(BytesIO(img_bytes))
                buf = BytesIO()
                pil_img.save(buf, format="PNG")
                img_bytes = buf.getvalue()

            digest = hashlib.md5(img_bytes).hexdigest()[:12]
            rects = page.get_image_rects(xref)
            rect = (rects[0].x0, rects[0].y0, rects[0].x1, rects[0].y1) if rects else None

            occurrences.append({
                "page_idx": page_idx,
                "img_idx": img_idx,
                "bytes": img_bytes,
                "digest": digest,
                "w": base["width"],
                "h": base["height"],
                "rect": rect,
            })
    doc.close()

    pages_per_digest: dict[str, set[int]] = {}
    for o in occurrences:
        pages_per_digest.setdefault(o["digest"], set()).add(o["page_idx"])

    decoration_digests = {
        h for h, pages in pages_per_digest.items() if len(pages) >= decoration_threshold
    }

    written_paths: dict[str, tuple[str, str]] = {}
    extracted: list[str] = []
    page_map: dict[int, list[dict]] = {}
    dropped_decoration_occ = 0
    dropped_tiny_occ = 0
    deduped_occ = 0

    for o in occurrences:
        if o["digest"] in decoration_digests:
            dropped_decoration_occ += 1
            continue
        if o["w"] < _TINY_IMG_DIM and o["h"] < _TINY_IMG_DIM:
            dropped_tiny_occ += 1
            continue

        if o["digest"] in written_paths:
            deduped_occ += 1
        else:
            filename = f"page{o['page_idx'] + 1}_img{o['img_idx'] + 1}.png"
            path = os.path.join(images_dir, filename)
            with open(path, "wb") as f:
                f.write(o["bytes"])
            written_paths[o["digest"]] = (path, filename)
            extracted.append(path)

        path, filename = written_paths[o["digest"]]
        page_1idx = o["page_idx"] + 1
        page_map.setdefault(page_1idx, []).append({
            "path": path,
            "name": filename,
            "w": o["w"],
            "h": o["h"],
            "rect": o["rect"],
        })

    if dropped_decoration_occ:
        print(f"[Images] Filtered {dropped_decoration_occ} decoration occurrence(s) "
              f"({len(decoration_digests)} unique image(s) on >={decoration_threshold} pages)",
              file=sys.stderr)
    if dropped_tiny_occ:
        print(f"[Images] Filtered {dropped_tiny_occ} tiny (<{_TINY_IMG_DIM}x{_TINY_IMG_DIM} px) occurrence(s)",
              file=sys.stderr)
    if deduped_occ:
        print(f"[Images] Deduplicated {deduped_occ} identical raster occurrence(s) "
              f"(written once, referenced by every page)",
              file=sys.stderr)

    return extracted, page_map


def _upgrade_images(markdown_text: str, marker_images: dict, page_map: dict,
                    images_dir: str) -> tuple[str, dict]:
    """Replace Marker images with higher-quality PyMuPDF originals where possible."""
    if not page_map:
        return markdown_text, marker_images

    from PIL import Image as _PILImage

    updated_text = markdown_text
    updated_images = dict(marker_images)
    upgrades = 0

    for marker_name in list(marker_images):
        m = re.match(r"_page_(\d+)_", marker_name)
        if not m:
            continue
        page_0idx = int(m.group(1))
        page_1idx = page_0idx + 1

        if page_1idx not in page_map:
            continue

        entries = page_map[page_1idx]
        marker_path = marker_images[marker_name]
        marker_img = _PILImage.open(marker_path)
        marker_pixels = marker_img.size[0] * marker_img.size[1]
        total_orig_pixels = sum(e["w"] * e["h"] for e in entries)

        if total_orig_pixels <= marker_pixels:
            continue

        if len(entries) == 1:
            new_name = entries[0]["name"]
            updated_text = updated_text.replace(marker_name, new_name)
            updated_images.pop(marker_name, None)
            updated_images[new_name] = entries[0]["path"]
            upgrades += 1
        else:
            composite, composite_name = _compose_images(entries, page_1idx, images_dir)
            if composite is not None:
                composite_path = os.path.join(images_dir, composite_name)
                composite.save(composite_path, format="PNG")
                updated_text = updated_text.replace(marker_name, composite_name)
                updated_images.pop(marker_name, None)
                updated_images[composite_name] = composite_path
                upgrades += 1

    if upgrades:
        print(f"[Images] Upgraded {upgrades} image(s) with higher-quality PyMuPDF versions",
              file=sys.stderr)
    return updated_text, updated_images


def _compose_images(entries: list[dict], page_num: int,
                    images_dir: str) -> tuple:
    """Compose multiple images preserving their relative layout.

    Returns (PIL.Image, filename) or (None, None) on failure.
    """
    from PIL import Image as _PILImage

    rects = [e["rect"] for e in entries]
    if any(r is None for r in rects):
        return None, None

    y_coords = [e["rect"][1] for e in entries]
    y_span = max(y_coords) - min(y_coords)
    avg_height = sum(r[3] - r[1] for r in rects) / len(rects)
    is_horizontal = y_span < avg_height * 0.3

    if is_horizontal:
        sorted_entries = sorted(entries, key=lambda e: e["rect"][0])
    else:
        sorted_entries = sorted(entries, key=lambda e: e["rect"][1])

    GAP = 10
    pil_imgs = [_PILImage.open(e["path"]) for e in sorted_entries]

    if is_horizontal:
        total_w = sum(img.size[0] for img in pil_imgs) + GAP * (len(pil_imgs) - 1)
        max_h = max(img.size[1] for img in pil_imgs)
        composite = _PILImage.new("RGB", (total_w, max_h), (255, 255, 255))
        x = 0
        for img in pil_imgs:
            y_offset = (max_h - img.size[1]) // 2
            composite.paste(img, (x, y_offset))
            x += img.size[0] + GAP
    else:
        max_w = max(img.size[0] for img in pil_imgs)
        total_h = sum(img.size[1] for img in pil_imgs) + GAP * (len(pil_imgs) - 1)
        composite = _PILImage.new("RGB", (max_w, total_h), (255, 255, 255))
        y = 0
        for img in pil_imgs:
            x_offset = (max_w - img.size[0]) // 2
            composite.paste(img, (x_offset, y))
            y += img.size[1] + GAP

    filename = f"page{page_num}_composite.png"
    return composite, filename


# ---------------------------------------------------------------------------
# Vector figure detection & rendering
# ---------------------------------------------------------------------------

def _find_figure_clip(page, page_rect, target_fig_num: int | None = None):
    """Determine the clip rectangle for a vector figure on a PDF page.

    When target_fig_num is given, locates that specific figure caption and
    computes its region (handles pages with multiple figures).  Otherwise
    falls back to generic strategies.

    Strategies (in priority order):
    1. Caption-based: find "Figure N:" text, figure extends from previous
       body-text bottom to the caption bottom.
    2. Gap-based: largest vertical gap free of text blocks.
    3. Drawing-bbox: bounding box of all vector drawings.

    Returns a fitz.Rect or None.
    """
    import fitz

    text_dict = page.get_text("dict")
    text_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
    sorted_blocks = sorted(text_blocks, key=lambda b: b["bbox"][1])
    page_width = page_rect.x1 - page_rect.x0

    def _is_body_text(block):
        bw = block["bbox"][2] - block["bbox"][0]
        return bw > page_width * 0.5 and len(_block_text(block)) > 80

    # --- Strategy 1: caption-based ---
    # Find all captions on this page
    captions = []
    for tb in sorted_blocks:
        m = _CAPTION_RE.match(_block_text(tb))
        if m:
            captions.append((int(m.group(1)), tb))

    # Pick the target caption (or the first one if no target specified)
    target_caption = None
    if target_fig_num is not None:
        for fig_num, tb in captions:
            if fig_num == target_fig_num:
                target_caption = tb
                break
    elif captions:
        target_caption = captions[0][1]

    if target_caption is not None:
        caption_top = target_caption["bbox"][1]
        caption_bottom = target_caption["bbox"][3]

        figure_top = page_rect.y0
        for tb in sorted_blocks:
            if tb["bbox"][3] >= caption_top:
                break
            is_other_caption = _CAPTION_RE.match(_block_text(tb)) is not None
            if _is_body_text(tb) or is_other_caption:
                figure_top = tb["bbox"][3]

        clip = fitz.Rect(
            page_rect.x0,
            max(page_rect.y0, figure_top - _PAD_PT),
            page_rect.x1,
            min(page_rect.y1, caption_bottom + _PAD_PT),
        )
        if clip.height > 50:
            return clip

    # --- Strategy 2: gap-based ---
    if text_blocks:
        bboxes = sorted([b["bbox"] for b in text_blocks], key=lambda r: r[1])
        best_gap_top, best_gap_bot, best_gap_size = page_rect.y0, page_rect.y1, 0.0

        for i in range(len(bboxes) - 1):
            gap_top = bboxes[i][3]
            gap_bot = bboxes[i + 1][1]
            gap_size = gap_bot - gap_top
            if gap_size > best_gap_size:
                best_gap_size, best_gap_top, best_gap_bot = gap_size, gap_top, gap_bot

        top_gap = bboxes[0][1] - page_rect.y0
        if top_gap > best_gap_size:
            best_gap_size, best_gap_top, best_gap_bot = top_gap, page_rect.y0, bboxes[0][1]

        bot_gap = page_rect.y1 - bboxes[-1][3]
        if bot_gap > best_gap_size:
            best_gap_size, best_gap_top, best_gap_bot = bot_gap, bboxes[-1][3], page_rect.y1

        if best_gap_size >= 50:
            return fitz.Rect(
                page_rect.x0, max(page_rect.y0, best_gap_top - _PAD_PT),
                page_rect.x1, min(page_rect.y1, best_gap_bot + _PAD_PT),
            )

    # --- Strategy 3: drawing bounding box ---
    drawings = page.get_drawings()
    if drawings:
        rects = [d["rect"] for d in drawings if d.get("rect")]
        if rects:
            y0 = min(r.y0 for r in rects)
            y1 = max(r.y1 for r in rects)
            if y1 - y0 < page_rect.height * 0.85:
                return fitz.Rect(
                    page_rect.x0, max(page_rect.y0, y0 - _PAD_PT),
                    page_rect.x1, min(page_rect.y1, y1 + _PAD_PT),
                )

    return None


def _fix_vector_figures(markdown_text: str, marker_images: dict,
                        pdf_path: str, page_map: dict,
                        images_dir: str) -> tuple[str, dict]:
    """Fix incomplete and add missing vector-drawn figures.

    Two passes:
    1. Re-render existing Marker images that are suspiciously small (incomplete
       fragments of vector figures).
    2. Scan markdown for "Figure N:" captions with no nearby image reference,
       render the figure region from the PDF, and insert the image.
    """
    import fitz
    from PIL import Image as _PILImage

    doc = fitz.open(pdf_path)
    updated_text = markdown_text
    updated_images = dict(marker_images)

    # --- Pass 1: fix incomplete Marker images ---
    fixes = 0
    for marker_name in list(updated_images):
        m = re.match(r"_page_(\d+)_", marker_name)
        if not m:
            continue
        page_0idx = int(m.group(1))

        if (page_0idx + 1) in page_map:
            continue  # has embedded rasters — handled by _upgrade_images

        marker_path = updated_images[marker_name]
        if not os.path.exists(marker_path):
            continue

        file_size = os.path.getsize(marker_path)
        img = _PILImage.open(marker_path)
        w, h = img.size

        is_small_dims = w < 500 and h < 300
        is_tiny_file = file_size < 15 * 1024
        if not (is_small_dims or is_tiny_file):
            continue

        if page_0idx >= len(doc):
            continue
        page = doc[page_0idx]

        if len(page.get_drawings()) == 0:
            continue

        clip = _find_figure_clip(page, page.rect)
        if clip is None:
            continue

        pix = page.get_pixmap(dpi=_RENDER_DPI, clip=clip)
        new_name = f"_page_{page_0idx}_Figure_rendered.png"
        new_path = os.path.join(images_dir, new_name)
        pix.save(new_path)

        updated_text = updated_text.replace(marker_name, new_name)
        updated_images.pop(marker_name, None)
        updated_images[new_name] = new_path
        fixes += 1

    if fixes:
        print(f"[Images] Re-rendered {fixes} incomplete vector figure(s) from PDF",
              file=sys.stderr)

    # --- Pass 2: add completely missing figures ---
    SEARCH_WINDOW = 15
    lines = updated_text.split("\n")

    missing = []  # (line_idx, fig_num, pdf_page_0idx)
    for i, line in enumerate(lines):
        m = _CAPTION_RE.match(line.strip())
        if not m:
            continue
        fig_num = int(m.group(1))

        has_image = any("![" in lines[j] for j in range(max(0, i - SEARCH_WINDOW), i))
        if has_image:
            continue

        # Markers use 0-indexed page numbers (page-6 = PDF page 7).
        pdf_page_0idx = None
        for j in range(i, max(0, i - 60), -1):
            pm = _PAGE_MARKER_RE.search(lines[j])
            if pm:
                pdf_page_0idx = int(pm.group(1))
                break

        if pdf_page_0idx is not None:
            missing.append((i, fig_num, pdf_page_0idx))

    for line_idx, fig_num, page_0idx in reversed(missing):
        if page_0idx >= len(doc):
            continue
        page = doc[page_0idx]

        if len(page.get_drawings()) == 0:
            continue

        clip = _find_figure_clip(page, page.rect, target_fig_num=fig_num)
        if clip is None:
            continue

        img_name = f"_page_{page_0idx}_Figure_{fig_num}.png"
        img_path = os.path.join(images_dir, img_name)

        pix = page.get_pixmap(dpi=_RENDER_DPI, clip=clip)
        pix.save(img_path)

        updated_images[img_name] = img_path
        lines.insert(line_idx, f"![]({img_name})\n")

    doc.close()

    if missing:
        print(f"[Images] Added {len(missing)} missing vector figure(s) from PDF",
              file=sys.stderr)

    return "\n".join(lines), updated_images


# ---------------------------------------------------------------------------
# Step 2.5: Decoration cleanup pass (catches Marker leftovers)
# ---------------------------------------------------------------------------

def _strip_decoration_images(markdown_text: str, all_images: dict, images_dir: str,
                             total_pages: int) -> tuple[str, dict]:
    """Drop image references that look like page-header/footer decorations.

    Catches images that survived ``extract_images_pymupdf`` (e.g. Marker-only
    rasters such as ``_page_*_Picture_*.png``):

    - Same byte content (MD5) referenced on >= 30% of pages -> logo/watermark
    - Image dimensions smaller than 80x80 px -> bullet/icon
    """
    import hashlib
    from PIL import Image as _PILImage

    decoration_threshold = max(3, int(total_pages * _DECORATION_PAGE_RATIO))

    file_hash: dict[str, str] = {}
    file_dims: dict[str, tuple[int, int]] = {}
    for name, path in all_images.items():
        if not os.path.exists(path):
            continue
        try:
            with open(path, "rb") as f:
                file_hash[name] = hashlib.md5(f.read()).hexdigest()[:12]
        except OSError:
            continue
        try:
            file_dims[name] = _PILImage.open(path).size
        except Exception:
            file_dims[name] = (0, 0)

    ref_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    ref_counts: dict[str, int] = {}
    for m in ref_pattern.finditer(markdown_text):
        bname = os.path.basename(m.group(1))
        ref_counts[bname] = ref_counts.get(bname, 0) + 1

    refs_per_hash: dict[str, int] = {}
    for name, h in file_hash.items():
        refs_per_hash[h] = refs_per_hash.get(h, 0) + ref_counts.get(name, 0)

    decoration_files: set[str] = set()
    for h, count in refs_per_hash.items():
        if count >= decoration_threshold:
            for name, fh in file_hash.items():
                if fh == h:
                    decoration_files.add(name)
    for name, (w, hh) in file_dims.items():
        if 0 < w < _TINY_IMG_DIM and 0 < hh < _TINY_IMG_DIM:
            decoration_files.add(name)

    if not decoration_files:
        return markdown_text, all_images

    def _drop(m):
        bname = os.path.basename(m.group(1))
        return "" if bname in decoration_files else m.group(0)

    new_text = ref_pattern.sub(_drop, markdown_text)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)

    new_images = dict(all_images)
    for name in decoration_files:
        path = new_images.pop(name, None)
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    print(f"[Images] Dropped {len(decoration_files)} decoration image(s) "
          f"(hash repeats >={decoration_threshold} pages or <{_TINY_IMG_DIM}x{_TINY_IMG_DIM} px)",
          file=sys.stderr)
    return new_text, new_images


# ---------------------------------------------------------------------------
# Step 2.5: Table reconstruction
# ---------------------------------------------------------------------------

_SEP_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")


def _table_cells(line: str) -> list[str]:
    s = line.lstrip()
    if s.startswith(">"):
        s = s[1:].lstrip()
    if not s.startswith("|"):
        return []
    parts = s.split("|")
    if parts and parts[0] == "":
        parts = parts[1:]
    if parts and parts[-1].strip() == "":
        parts = parts[:-1]
    return [c.strip() for c in parts]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.match(c) for c in cells)


def _split_prose_pipe_tail(line: str) -> tuple[str, str] | None:
    """Detect ``prose | cell | cell ... <br?`` hybrid; return (prose, tail).

    Marker frequently emits a paragraph followed by the start of a table on
    the same line.  This split makes the table parse-able as its own block.
    """
    s = line.rstrip()
    pipes = [i for i, c in enumerate(s) if c == "|"]
    if len(pipes) < 3:
        return None
    starts_at = pipes[0]
    last = pipes[0]
    for p in pipes[1:]:
        if p - last > 40:
            starts_at = p
        last = p
    if starts_at == 0:
        return None
    prose = s[:starts_at].rstrip()
    tail = s[starts_at:].rstrip()
    if len(prose) < 5:
        return None
    return prose, tail


def _normalize_cells(cells: list[str], width: int) -> list[str]:
    if len(cells) == width:
        return cells
    if len(cells) > width:
        return cells[:width - 1] + [" ".join(cells[width - 1:])]
    return cells + [""] * (width - len(cells))


def _reconstruct_broken_tables(text: str) -> str:
    """Rebuild markdown tables that Marker emits with broken multi-line headers.

    Marker's PDF -> Markdown extraction inserts ``<br>`` tags into table cells
    that span multiple lines, but blank-line breaks and ``>`` blockquote
    prefixes around those tags often confuse downstream Markdown parsers.
    This function:

    1. Splits ``prose | cell | ...`` hybrid lines into separate prose + table
       blocks (Pass 1).
    2. For each separator row, walks BACKWARD absorbing only fragments that
       look broken (``>`` prefix, ``<br`` content, orphan trailing pieces, or
       cell counts smaller than the body width).  Walks FORWARD until a
       second separator row is found (= boundary to next table).  Emits a
       clean table with normalized columns (Pass 2).
    """
    from collections import Counter as _Counter

    lines = text.splitlines()

    pass1: list[str] = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith("|") or s.startswith(">"):
            pass1.append(ln)
            continue
        if not ln.strip():
            pass1.append(ln)
            continue
        result = _split_prose_pipe_tail(ln)
        if result is None:
            pass1.append(ln)
            continue
        prose, tail = result
        pass1.append(prose)
        pass1.append("")
        pass1.append(tail)
    lines = pass1

    n = len(lines)
    out: list[str] = []
    i = 0
    fixes = 0
    while i < n:
        ln = lines[i]
        c = _table_cells(ln)
        if not c or not _is_separator_row(c):
            out.append(ln)
            i += 1
            continue

        # Peek body widths below the separator.
        peek_widths: list[int] = []
        pj = i + 1
        peek_seen_sep = False
        while pj < n and len(peek_widths) < 4:
            pjc = _table_cells(lines[pj])
            if not pjc:
                break
            if _is_separator_row(pjc):
                if peek_seen_sep:
                    break
                peek_seen_sep = True
                pj += 1
                continue
            peek_widths.append(len(pjc))
            pj += 1
        peek_w = (_Counter(peek_widths).most_common(1)[0][0]
                  if peek_widths else 0)

        # Walk backward, absorbing only "broken" fragments.
        header_frags: list[str] = []
        consumed_back = 0
        back = i - 1
        crossed_blank = 0
        while back >= 0 and (i - back) < 12:
            bln = lines[back]
            if not bln.strip():
                crossed_blank += 1
                if crossed_blank > 3:
                    break
                consumed_back += 1
                back -= 1
                continue
            stripped = bln.lstrip()
            had_blockquote = stripped.startswith(">")
            if had_blockquote:
                stripped = stripped[1:].lstrip()
            if "|" not in stripped:
                break
            c2 = _table_cells(bln)
            if c2 and _is_separator_row(c2):
                consumed_back += 1
                back -= 1
                crossed_blank = 0
                continue
            has_br = "<br" in stripped
            no_lead_pipe = not stripped.startswith("|")
            cc = len(c2) if c2 else 0
            looks_broken = (
                had_blockquote
                or has_br
                or no_lead_pipe
                or (peek_w > 0 and 0 < cc < peek_w)
            )
            if not looks_broken:
                break
            header_frags.append(stripped)
            consumed_back += 1
            back -= 1
            crossed_blank = 0

        if not header_frags:
            out.append(ln)
            i += 1
            continue

        # Walk forward; stop on second separator (= next table boundary).
        body_rows: list[list[str]] = []
        j = i + 1
        consumed_forward = 0
        seen_inner_sep = False
        while j < n:
            jc = _table_cells(lines[j])
            if not jc:
                break
            if _is_separator_row(jc):
                if seen_inner_sep or body_rows:
                    break
                seen_inner_sep = True
                consumed_forward += 1
                j += 1
                continue
            body_rows.append(jc)
            consumed_forward += 1
            j += 1
        if len(body_rows) < 2:
            out.append(ln)
            i += 1
            continue
        target_w = _Counter(len(r) for r in body_rows).most_common(1)[0][0]
        if target_w < 2:
            out.append(ln)
            i += 1
            continue

        header_frags.reverse()
        joined = " ".join(f.rstrip() for f in header_frags)
        joined = re.sub(r"<br\s*/?>?\s*", " ", joined)
        joined = re.sub(r"\s+", " ", joined).strip()
        if not joined.startswith("|"):
            joined = "| " + joined.lstrip("|").strip()
        if not joined.endswith("|"):
            joined = joined.rstrip() + " |"
        header_cells = _table_cells(joined)
        if not header_cells:
            out.append(ln)
            i += 1
            continue
        header_cells = _normalize_cells(header_cells, target_w)

        if consumed_back > 0:
            out = out[:-consumed_back]
        while out and not out[-1].strip():
            out.pop()
        out.append("")

        out.append("| " + " | ".join(header_cells) + " |")
        out.append("|" + "|".join(["---"] * target_w) + "|")
        for r in body_rows:
            r = _normalize_cells(r, target_w)
            out.append("| " + " | ".join(r) + " |")

        i += consumed_forward + 1
        fixes += 1

    if fixes:
        print(f"[Tables] Reconstructed {fixes} broken table(s)", file=sys.stderr)

    new_text = "\n".join(out) + "\n" if out and out[-1] != "" else "\n".join(out)
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    return new_text


# ---------------------------------------------------------------------------
# Step 3: OCR
# ---------------------------------------------------------------------------

_OCR_SENT_SPLIT = re.compile(r"[.!?。！？\n]+")
_OCR_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _is_meaningful_ocr(text: str) -> bool:
    """Heuristic: filter out OCR output that is just a label cloud.

    Architecture diagrams, dataflow charts, etc. yield OCR text consisting of
    repeated short labels (``SIMD 0 SIMD 1 SIMD 2 ... VGPR VGPR ...``).  Such
    "text" pollutes the bilingual MD with garbage that LLMs can only translate
    word-by-word.  We drop OCR results where:

    - fewer than 5 tokens, OR
    - unique-token ratio < 0.4 (>60% of tokens are repeats), OR
    - average sentence length < 4 tokens (no real prose)
    """
    tokens = _OCR_TOKEN_RE.findall(text.lower())
    if len(tokens) < 5:
        return False
    if len(set(tokens)) / len(tokens) < 0.4:
        return False
    sentence_lens = [
        len(s.split()) for s in _OCR_SENT_SPLIT.split(text) if s.strip()
    ]
    if not sentence_lens:
        return False
    if sum(sentence_lens) / len(sentence_lens) < 4:
        return False
    return True


def _ocr_with_easyocr(image_paths: dict[str, str], threshold: int, gpu: bool) -> dict:
    """GPU-accelerated OCR via easyocr."""
    import easyocr

    reader = easyocr.Reader(["en", "ch_sim"], gpu=gpu)
    report = {}
    dropped_quality = 0

    for name, path in image_paths.items():
        if Path(path).suffix.lower() not in _IMAGE_EXTS:
            continue
        try:
            results = reader.readtext(path)
            text = " ".join(r[1] for r in results).strip()
        except Exception:
            continue
        word_count = len(text.split())
        if word_count < threshold:
            continue
        if not _is_meaningful_ocr(text):
            dropped_quality += 1
            continue
        report[name] = {"path": path, "word_count": word_count, "text": text}

    if dropped_quality:
        print(f"[OCR] Discarded {dropped_quality} label-cloud OCR result(s) "
              f"(repetitive / no prose)", file=sys.stderr)
    return report


def _ocr_with_tesseract(image_paths: dict[str, str], threshold: int) -> dict:
    """CPU-only OCR via Tesseract."""
    import pytesseract
    from PIL import Image

    report = {}
    dropped_quality = 0

    for name, path in image_paths.items():
        if Path(path).suffix.lower() not in _IMAGE_EXTS:
            continue
        try:
            text = pytesseract.image_to_string(Image.open(path), lang="eng").strip()
        except Exception:
            continue
        word_count = len(text.split())
        if word_count < threshold:
            continue
        if not _is_meaningful_ocr(text):
            dropped_quality += 1
            continue
        report[name] = {"path": path, "word_count": word_count, "text": text}

    if dropped_quality:
        print(f"[OCR] Discarded {dropped_quality} label-cloud OCR result(s) "
              f"(repetitive / no prose)", file=sys.stderr)
    return report


def run_ocr(image_paths: dict[str, str], threshold: int = 20, device: str = "cpu") -> dict:
    """Run OCR on images. Prefers easyocr (GPU-capable), falls back to tesseract."""
    use_gpu = device.startswith("cuda")

    try:
        import easyocr  # noqa: F401

        backend = f"easyocr ({'GPU' if use_gpu else 'CPU'})"
        print(f"[OCR] Using {backend}", file=sys.stderr)
        return _ocr_with_easyocr(image_paths, threshold, gpu=use_gpu)
    except ImportError:
        pass

    try:
        import pytesseract  # noqa: F401

        print("[OCR] Using tesseract (CPU only)", file=sys.stderr)
        return _ocr_with_tesseract(image_paths, threshold)
    except ImportError:
        pass

    print("[OCR] No OCR backend available (install easyocr or pytesseract)", file=sys.stderr)
    return {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Extract PDF to Markdown + images")
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("output_dir", nargs="?", default=None, help="Output directory (default: {stem}_extracted/)")
    parser.add_argument("--ocr-threshold", type=int, default=20, help="Min words to flag image as text-heavy")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR processing")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                        help="Compute device: auto (detect GPU), cpu (force CPU), cuda (prefer GPU)")
    parser.add_argument("--force", action="store_true",
                        help="Force re-extraction even if extracted.md is up-to-date")
    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf)
    if not os.path.exists(pdf_path):
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    pdf_parent = str(Path(pdf_path).parent)
    output_dir = args.output_dir or os.path.join(pdf_parent, f"{Path(pdf_path).stem}_extracted")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Idempotency: skip work if extracted.md is fresh.
    # Detection: extracted.md exists and is newer than the input PDF.
    md_path = os.path.join(output_dir, "extracted.md")
    if not args.force and os.path.exists(md_path):
        pdf_mtime = os.path.getmtime(pdf_path)
        md_mtime = os.path.getmtime(md_path)
        if md_mtime >= pdf_mtime:
            try:
                with open(md_path, "r", encoding="utf-8") as f:
                    md_lines = sum(1 for _ in f)
            except OSError:
                md_lines = 0
            images_dir = os.path.join(output_dir, "images")
            try:
                image_files = sorted(os.listdir(images_dir)) if os.path.isdir(images_dir) else []
            except OSError:
                image_files = []
            ocr_path = os.path.join(output_dir, "ocr_report.json")
            text_heavy = 0
            if os.path.exists(ocr_path):
                try:
                    with open(ocr_path, "r", encoding="utf-8") as f:
                        text_heavy = len(json.load(f) or {})
                except (OSError, json.JSONDecodeError):
                    text_heavy = 0
            summary = {
                "status": "cached",
                "pdf": pdf_path,
                "output_dir": output_dir,
                "markdown_file": md_path,
                "markdown_lines": md_lines,
                "total_images": len(image_files),
                "text_heavy_images": text_heavy,
                "image_files": image_files,
                "note": "Use --force to re-extract.",
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

    device = detect_device(args.device)

    # Step 1: Marker extraction
    print(f"[1/3] Running Marker ({device.upper()}): {pdf_path}", file=sys.stderr)
    markdown_text, marker_images = extract_with_marker(pdf_path, output_dir, device)
    markdown_text = _tag_code_blocks(markdown_text)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    # Step 2: PyMuPDF supplementary image extraction + quality upgrade
    print("[2/3] Extracting images with PyMuPDF...", file=sys.stderr)
    pymupdf_images, page_map = extract_images_pymupdf(pdf_path, output_dir)

    images_dir = os.path.join(output_dir, "images")
    markdown_text, marker_images = _upgrade_images(
        markdown_text, marker_images, page_map, images_dir,
    )

    all_images = dict(marker_images)
    for p in pymupdf_images:
        name = os.path.basename(p)
        if name not in all_images:
            all_images[name] = p

    # Fix incomplete + add missing vector figures (single PDF open)
    markdown_text, all_images = _fix_vector_figures(
        markdown_text, all_images, pdf_path, page_map, images_dir,
    )

    # Final decoration cleanup: catch Marker-only logos / icons that slipped past
    # PyMuPDF's hash-based filter (different hash but same visual function).
    import fitz as _fitz
    with _fitz.open(pdf_path) as _doc:
        _total_pages = len(_doc)
    markdown_text, all_images = _strip_decoration_images(
        markdown_text, all_images, images_dir, _total_pages,
    )

    # Reconstruct tables broken by Marker's `<br>` cell-content handling
    # before the LLM translation step sees them.
    markdown_text = _reconstruct_broken_tables(markdown_text)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    # Step 3: OCR (optional)
    ocr_report = {}
    if not args.no_ocr and all_images:
        print("[3/3] Running OCR on images...", file=sys.stderr)
        ocr_report = run_ocr(all_images, threshold=args.ocr_threshold, device=device)
        if ocr_report:
            report_path = os.path.join(output_dir, "ocr_report.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(ocr_report, f, ensure_ascii=False, indent=2)
    else:
        print("[3/3] OCR skipped", file=sys.stderr)

    md_lines = len(markdown_text.splitlines())

    summary = {
        "status": "success",
        "device": device,
        "pdf": pdf_path,
        "output_dir": output_dir,
        "markdown_file": md_path,
        "markdown_lines": md_lines,
        "total_images": len(all_images),
        "text_heavy_images": len(ocr_report),
        "image_files": list(all_images.keys()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
