# ai_tools

A collection of practical AI/LLM utilities built by an HPC developer who works daily with NVIDIA/AMD hardware and AI large models. Each tool is packaged as a self-contained [Cursor Agent Skill](https://docs.cursor.com/context/skills) with its own scripts, dependencies, and documentation.

## Tools

| Tool | Description |
|------|-------------|
| [`translate`](translate/) | Translate local PDFs, online papers (including arXiv), and blog posts into bilingual English-Chinese Markdown with paragraph-by-paragraph comparison. PDF extraction uses Marker, PyMuPDF, and Tesseract/EasyOCR. |
| [`md_to_pdf`](md_to_pdf/) | Convert Markdown files to professionally formatted A4 PDF documents with auto-generated table of contents, academic paper typography, and smart page breaks. |

## Project Structure

```
ai_tools/
├── README.md                 # This file
├── install.sh                # One-command installer
├── claude.md                 # AI agent project guide
├── LICENSE                   # MIT License
│
├── translate/            # Tool: document bilingual translation (EN → ZH)
│   ├── SKILL.md              # Cursor Skill definition
│   ├── extract_pdf.py        # PDF extraction script
│   ├── requirements.txt      # Python dependencies
│   └── __init__.py
│
└── md_to_pdf/                # Tool: Markdown → PDF conversion
    ├── SKILL.md              # Cursor Skill definition
    ├── convert.py            # Conversion script
    └── __init__.py
```

Each tool directory is **self-contained**: `SKILL.md` (workflow definition for Cursor Agent) + scripts + dependencies all live together.

## Installation

### Quick Install

```bash
git clone https://github.com/yourname/ai_tools.git
cd ai_tools
./install.sh            # symlink skills + install all dependencies
```

Options:

```bash
./install.sh --link-only   # only create symlinks, skip dependencies
./install.sh --deps-only   # only install dependencies, skip symlinks
```

### Manual Install

<details>
<summary>Click to expand manual steps</summary>

#### 1. Link skills into Cursor

```bash
ln -sfn "$(pwd)/translate" ~/.cursor/skills/translate
ln -sfn "$(pwd)/md_to_pdf"     ~/.cursor/skills/md-to-pdf
```

#### 2. Install dependencies

Both tools share the repository's `.venv`. The installer creates it when needed;
use `PYTHON_BIN` to select a compatible Python interpreter. For an AMD MI355X
machine with ROCm 10.1:

```bash
ROCM_DEVICE=gfx950 ./install.sh --deps-only --gpu amd
source .venv/bin/activate
```

Install the matching ROCm build of PyTorch before the remaining PDF dependencies;
see the [AMD PyTorch installation guide](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html).

**translate:**

```bash
python -m pip install -r translate/requirements.txt
sudo apt-get install tesseract-ocr          # optional, for OCR
```

**md_to_pdf:**

```bash
python -m pip install -r md_to_pdf/requirements.txt
sudo apt-get install libpango1.0-dev libcairo2-dev libgdk-pixbuf-2.0-dev libffi-dev shared-mime-info
sudo apt-get install fonts-noto-cjk         # Chinese font support
```

</details>

## Usage

### In Cursor (recommended)

Just tell the Cursor Agent what you need:

> "翻译这个 PDF：/path/to/paper.pdf"

> "把 report.md 转成 PDF"

The Agent will automatically invoke the corresponding Skill.

### Standalone

```bash
# PDF extraction (translation is done by the Cursor Agent)
python3 translate/extract_pdf.py input.pdf [output_dir] [--no-ocr]

# Markdown to PDF
python3 md_to_pdf/convert.py input.md [-o output.pdf] [--no-toc]
```

## Tips

For better document generation quality (especially with `translate` and `md_to_pdf`), consider adding a Cursor Rule to guide the Agent's writing style. Create `~/.cursor/rules/documentation.mdc` (global) or `<project>/.cursor/rules/documentation.mdc` (per-project) with your preferences — for example, preferred language, LaTeX math notation, Mermaid diagrams, etc. See [`.cursor/rules/documentation.mdc`](.cursor/rules/documentation.mdc) for a reference.

## Adding a New Tool

1. Create a new directory at the project root: `tool_name/`
2. Add `SKILL.md` with the Cursor Skill definition (YAML frontmatter + workflow)
3. Add scripts, `__init__.py`, and `requirements.txt`
4. Symlink into `~/.cursor/skills/`: `ln -sfn "$(pwd)/tool_name" ~/.cursor/skills/tool-name`
5. Update this README

## License

[MIT](LICENSE)
