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


def detect_device(requested: str = "auto") -> str:
    """Auto-detect best compute device. Returns 'cuda' or 'cpu'.

    - 'auto': use CUDA if available, else CPU
    - 'cpu':  force CPU
    - 'cuda': prefer CUDA, warn and fallback if unavailable
    """
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


def extract_images_pymupdf(pdf_path: str, output_dir: str) -> tuple[list[str], dict]:
    """Extract full-resolution images via PyMuPDF with position metadata.

    Returns (extracted_paths, page_map) where page_map is:
        {page_1indexed: [{"path": ..., "w": ..., "h": ..., "rect": (x0,y0,x1,y1)}, ...]}
    """
    import fitz

    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    extracted = []
    page_map: dict[int, list[dict]] = {}

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue

            filename = f"page{page_idx + 1}_img{img_idx + 1}.png"
            path = os.path.join(images_dir, filename)

            img_bytes = base["image"]
            ext = base.get("ext", "png")
            if ext != "png":
                from PIL import Image as _PILImage
                from io import BytesIO
                pil_img = _PILImage.open(BytesIO(img_bytes))
                buf = BytesIO()
                pil_img.save(buf, format="PNG")
                img_bytes = buf.getvalue()

            with open(path, "wb") as f:
                f.write(img_bytes)
            extracted.append(path)

            rects = page.get_image_rects(xref)
            rect = (rects[0].x0, rects[0].y0, rects[0].x1, rects[0].y1) if rects else None

            page_1idx = page_idx + 1
            page_map.setdefault(page_1idx, []).append({
                "path": path,
                "name": filename,
                "w": base["width"],
                "h": base["height"],
                "rect": rect,
            })

    doc.close()
    return extracted, page_map


def _upgrade_images(markdown_text: str, marker_images: dict, page_map: dict,
                    images_dir: str) -> tuple[str, dict]:
    """Replace Marker images with higher-quality PyMuPDF originals where possible.

    For pages where PyMuPDF extracted the raw embedded images, this creates
    a layout-preserving composite (or uses the single image directly) and
    updates the markdown references.
    """
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
    """Compose multiple images into a single image preserving their relative layout.

    Uses the PDF rect positions to determine side-by-side vs. stacked arrangement.
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


def _ocr_with_easyocr(image_paths: dict[str, str], threshold: int, gpu: bool) -> dict:
    """GPU-accelerated OCR via easyocr."""
    import easyocr

    reader = easyocr.Reader(["en", "ch_sim"], gpu=gpu)

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    report = {}

    for name, path in image_paths.items():
        if Path(path).suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            results = reader.readtext(path)
            text = " ".join(r[1] for r in results).strip()
        except Exception:
            continue
        word_count = len(text.split())
        if word_count >= threshold:
            report[name] = {"path": path, "word_count": word_count, "text": text}

    return report


def _ocr_with_tesseract(image_paths: dict[str, str], threshold: int) -> dict:
    """CPU-only OCR via Tesseract."""
    import pytesseract
    from PIL import Image

    IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".gif", ".webp"}
    report = {}

    for name, path in image_paths.items():
        if Path(path).suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            text = pytesseract.image_to_string(Image.open(path), lang="eng").strip()
        except Exception:
            continue
        word_count = len(text.split())
        if word_count >= threshold:
            report[name] = {"path": path, "word_count": word_count, "text": text}

    return report


def run_ocr(image_paths: dict[str, str], threshold: int = 20, device: str = "cpu") -> dict:
    """Run OCR on images. Prefers easyocr (GPU-capable) when available, falls back to tesseract."""
    use_gpu = device.startswith("cuda")

    # Try easyocr first (supports GPU acceleration)
    try:
        import easyocr  # noqa: F401

        backend = f"easyocr ({'GPU' if use_gpu else 'CPU'})"
        print(f"[OCR] Using {backend}", file=sys.stderr)
        return _ocr_with_easyocr(image_paths, threshold, gpu=use_gpu)
    except ImportError:
        pass

    # Fall back to tesseract (CPU only)
    try:
        import pytesseract  # noqa: F401

        print("[OCR] Using tesseract (CPU only)", file=sys.stderr)
        return _ocr_with_tesseract(image_paths, threshold)
    except ImportError:
        pass

    print("[OCR] No OCR backend available (install easyocr or pytesseract)", file=sys.stderr)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Extract PDF to Markdown + images")
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("output_dir", nargs="?", default=None, help="Output directory (default: {stem}_extracted/)")
    parser.add_argument("--ocr-threshold", type=int, default=20, help="Min words to flag image as text-heavy")
    parser.add_argument("--no-ocr", action="store_true", help="Skip OCR processing")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                        help="Compute device: auto (detect GPU), cpu (force CPU), cuda (prefer GPU)")
    args = parser.parse_args()

    pdf_path = os.path.abspath(args.pdf)
    if not os.path.exists(pdf_path):
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    pdf_parent = str(Path(pdf_path).parent)
    output_dir = args.output_dir or os.path.join(pdf_parent, f"{Path(pdf_path).stem}_extracted")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    device = detect_device(args.device)

    # Step 1: Marker extraction
    print(f"[1/3] Running Marker ({device.upper()}): {pdf_path}", file=sys.stderr)
    markdown_text, marker_images = extract_with_marker(pdf_path, output_dir, device)

    md_path = os.path.join(output_dir, "extracted.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    # Step 2: PyMuPDF supplementary image extraction + quality upgrade
    print("[2/3] Extracting images with PyMuPDF...", file=sys.stderr)
    pymupdf_images, page_map = extract_images_pymupdf(pdf_path, output_dir)

    images_dir = os.path.join(output_dir, "images")
    markdown_text, marker_images = _upgrade_images(
        markdown_text, marker_images, page_map, images_dir,
    )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(markdown_text)

    all_images = dict(marker_images)
    for p in pymupdf_images:
        name = os.path.basename(p)
        if name not in all_images:
            all_images[name] = p

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
