# ai_tools

A collection of practical AI/LLM utilities built by an HPC developer who works daily with NVIDIA/AMD hardware and AI large models. The goal is to package everyday AI workflows into reusable, open-source tools for the community.

## Project Context

- **Author background**: HPC (High-Performance Computing) developer with deep focus on NVIDIA/AMD hardware & software ecosystems and AI large language models.
- **Purpose**: Consolidate frequently used AI tools into a single open-source library so the broader community can benefit.
- **Target audience**: Developers, researchers, and engineers who work with LLMs, GPU computing, or AI infrastructure.
- **License**: MIT — maximally permissive to encourage community adoption and reuse.

## Tech Stack

- **Language**: Python 3.10+
- **Package management**: `pyproject.toml` (PEP 621). Use `requirements.txt` per-tool when standalone scripts are simpler.
- **Formatting & linting**: Ruff (format + lint), following PEP 8.
- **Type hints**: Always use type annotations for function signatures and public APIs.
- **Async**: Prefer `asyncio` for I/O-bound tasks (API calls, file I/O). Use `aiohttp` or `httpx` for async HTTP.
- **CLI**: Use `click` for command-line interfaces.
- **Testing**: `pytest` with `pytest-asyncio` for async tests.

## Project Structure

Each tool is a self-contained directory at the project root. A tool directory contains its `SKILL.md` (Cursor Agent Skill definition), scripts, dependencies, and `__init__.py` — everything needed to run independently.

```
ai_tools/
├── claude.md                 # This file — project guide for AI agents
├── LICENSE                   # MIT License
├── README.md                 # Top-level project README
├── .gitignore                # Ignore inout/, __pycache__, etc.
│
├── translate_pdf/            # Tool: PDF bilingual translation (EN → ZH)
│   ├── SKILL.md              # Cursor Skill definition (workflow core)
│   ├── extract_pdf.py        # PDF → Markdown + images + OCR report
│   ├── requirements.txt      # Python dependencies
│   └── __init__.py
│
├── md_to_pdf/                # Tool: Markdown → PDF conversion
│   ├── SKILL.md              # Cursor Skill definition
│   ├── convert.py            # Markdown → A4 PDF with academic formatting
│   └── __init__.py
│
└── .cursor/rules/
    └── documentation.mdc     # Documentation writing conventions
```

### Cursor Skill Integration

Each tool's `SKILL.md` uses `~/.cursor/skills/<skill-name>/` paths for script references. Users symlink tool directories into `~/.cursor/skills/`:

```bash
ln -sfn /path/to/ai_tools/translate_pdf  ~/.cursor/skills/translate-pdf
ln -sfn /path/to/ai_tools/md_to_pdf      ~/.cursor/skills/md-to-pdf
```

The YAML `name` field in SKILL.md uses kebab-case (e.g., `translate-pdf`) matching the Cursor skill directory name, while repo directories use snake_case per project convention.

## Coding Conventions

### Naming

- **Files & directories**: `snake_case` (e.g., `translate_pdf/`, `config.py`)
- **Functions & variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`

### Module Structure

- Every Python package must have an `__init__.py` with a module-level docstring and `__version__`.
- Each tool directory should be a self-contained package that can run independently.
- Shared utilities go in a top-level `utils/` package (create when needed).

### Documentation

- All docstrings and code comments in **English** (for international open-source audience).
- Each tool directory should have its own `README.md` explaining usage, dependencies, and examples.
- Use Google-style docstrings:

```python
def translate(text: str, model: str = "gpt-4o") -> str:
    """Translate English text to Simplified Chinese.

    Args:
        text: The source English text.
        model: OpenAI model identifier.

    Returns:
        Translated Chinese text.

    Raises:
        ValueError: If text is empty.
    """
```

### Git

- Commit messages in **English**, following [Conventional Commits](https://www.conventionalcommits.org/):
  - `feat: add PDF table extraction`
  - `fix: handle empty OCR result`
  - `docs: update translate_pdf README`
- Keep commits atomic — one logical change per commit.

## Guidelines for Claude

### When Adding a New Tool

1. Create a new directory at the project root: `tool_name/`
2. Add `SKILL.md` with YAML frontmatter (`name`, `description`) and workflow steps
3. Add `__init__.py` with docstring and `__version__ = "0.1.0"`
4. Add scripts for the tool's functionality
5. Add tool-specific dependencies to a local `requirements.txt`
6. Update the top-level `README.md` tool table with a brief description
7. Provide symlink command: `ln -sfn "$(pwd)/tool_name" ~/.cursor/skills/tool-name`

### API Keys & Secrets

- **Never** hardcode API keys. Always read from environment variables.
- Use `os.environ.get("KEY_NAME", "")` pattern.
- Document required environment variables in the tool's README.

### HPC / GPU Considerations

- When code depends on GPU hardware (CUDA, ROCm, specific driver versions), clearly document:
  - Minimum CUDA / ROCm version
  - Required GPU architecture (e.g., sm_80+ for Ampere)
  - Any system-level dependencies (e.g., `nvidia-smi`, `rocm-smi`)
- Prefer graceful degradation: tools should still work (or fail with a clear message) when GPU is unavailable.

### LLM API Usage

- Default to OpenAI-compatible API format (works with OpenAI, Azure OpenAI, vLLM, Ollama, etc.).
- Always make model name configurable — never hardcode a specific model.
- Implement retry logic with exponential backoff for API calls.
- Support async calls for batch/concurrent workloads.
- Add cost-awareness: log token usage when feasible.

### Testing

- Place tests in a `tests/` directory at the project root, mirroring the source structure.
- Name test files `test_<module>.py`.
- Use `pytest` fixtures for shared setup (API mocks, sample data).
- Mock external API calls in tests — never make real API calls in CI.

### Error Handling

- Raise specific exceptions with descriptive messages.
- Use `logging` module, not `print()`, for operational output.
- Catch and wrap third-party library errors with context.
