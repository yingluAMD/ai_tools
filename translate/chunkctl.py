#!/usr/bin/env python3
"""Chunk-state controller for resilient bilingual translation.

Manages a `_chunks/` directory and `_state.json` so an interrupted translation
can be resumed by a fresh agent without re-translating completed sections.

Layout (one per PDF translation job):

    inout/MyDoc_extracted/
    ├── extracted.md                # original Marker output (read-only)
    ├── _chunks/
    │   ├── _state.json             # {schema, chunks: [{id,title,status,...}], glossary, context}
    │   ├── _glossary.md            # persisted terminology table
    │   ├── _context.md             # persisted background summary
    │   ├── _prev_tail.md           # last 30 lines of latest completed chunk (for overlap context)
    │   ├── 00_frontmatter.md       # bilingual chunk content
    │   ├── 01_ch1_intro.md
    │   └── ...

When all chunks are `done`, run `assemble` to produce the final `_zh.md`.

Subcommands
-----------
    init <extracted_dir> [--plan plan.json]
        Create skeleton: _chunks/, empty _state.json. If --plan is given, seed
        chunks list from a JSON list of {id,title,start_line,end_line}.

    plan <extracted_dir>
        Auto-derive a plan from extracted.md by splitting on `# ` (h1/h2)
        and section-numbered h3's. Print JSON. Pipe to `init --plan -`.

    list <extracted_dir>
        Show one-line status per chunk.

    next <extracted_dir>
        Print the JSON description of the next pending chunk (id, range, etc.),
        ready for the agent to pick up. Exit 1 if all done.

    mark <extracted_dir> <chunk_id> <status> [--file path]
        Update a chunk's status (pending/in_progress/done). If --file is given
        and status=done, the file content becomes that chunk's stored output
        and _prev_tail.md is refreshed.

    assemble <extracted_dir> [--out path]
        Concatenate all `done` chunks (in id order) to <out>. Default out:
        `<pdf_dir>/<stem>_zh.md`.

    set-glossary <extracted_dir> <file>
    set-context  <extracted_dir> <file>
        Load/replace persistent glossary/background files.

Idempotent: every command may be re-run safely.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1


def _chunks_dir(extracted_dir: Path) -> Path:
    d = extracted_dir / "_chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(extracted_dir: Path) -> Path:
    return _chunks_dir(extracted_dir) / "_state.json"


def _load_state(extracted_dir: Path) -> dict:
    p = _state_path(extracted_dir)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "schema": SCHEMA_VERSION,
        "extracted_dir": str(extracted_dir.resolve()),
        "chunks": [],
        "glossary_file": None,
        "context_file": None,
    }


def _save_state(extracted_dir: Path, state: dict) -> None:
    p = _state_path(extracted_dir)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _autoplan(extracted_md: Path) -> list[dict]:
    """Heuristic chapter/section splitter for English specs/papers."""
    lines = extracted_md.read_text(encoding="utf-8").splitlines()
    # Anchor lines: H1/H2 (`# `, `## `) and numbered H3 like "### 1.1.1.2."
    anchors: list[tuple[int, str]] = []
    h_re = re.compile(r"^# [^#]|^## [^#]")
    h3_num_re = re.compile(r"^### \*?\*?(\d+\.\d+(?:\.\d+){0,2})\.")
    for i, line in enumerate(lines):
        if h_re.match(line) or h3_num_re.match(line):
            title = line.lstrip("#").strip().strip("*").strip()
            anchors.append((i + 1, title))
    if not anchors:
        return [{"id": "00_all", "title": "all", "start_line": 1, "end_line": len(lines)}]
    plan: list[dict] = []
    # Front matter chunk: lines 1..first_anchor-1
    if anchors[0][0] > 1:
        plan.append({"id": "00_frontmatter", "title": "front matter",
                     "start_line": 1, "end_line": anchors[0][0] - 1})
    # Merge tiny adjacent sections; target chunk size 100..280 lines.
    MIN_SIZE = 80
    MAX_SIZE = 280
    cur_start = anchors[0][0]
    cur_title = anchors[0][1]
    next_idx = 1
    seq = len(plan)
    while next_idx < len(anchors):
        next_start = anchors[next_idx][0]
        next_title = anchors[next_idx][1]
        size = next_start - cur_start
        if size >= MIN_SIZE:
            plan.append({"id": f"{seq:02d}_{_slug(cur_title)}",
                         "title": cur_title, "start_line": cur_start,
                         "end_line": next_start - 1})
            seq += 1
            cur_start = next_start
            cur_title = next_title
        elif size + (anchors[next_idx + 1][0] if next_idx + 1 < len(anchors) else len(lines) + 1) - next_start <= MAX_SIZE:
            # merge by extending cur
            pass
        next_idx += 1
    plan.append({"id": f"{seq:02d}_{_slug(cur_title)}",
                 "title": cur_title, "start_line": cur_start, "end_line": len(lines)})
    # Split oversized chunks at the next anchor inside their range
    out: list[dict] = []
    for c in plan:
        s, e = c["start_line"], c["end_line"]
        if e - s + 1 <= MAX_SIZE:
            out.append(c)
            continue
        # split at internal anchors
        internals = [a for a in anchors if s < a[0] <= e]
        chunk_start = s
        for ai, (aline, atitle) in enumerate(internals):
            if aline - chunk_start >= MIN_SIZE:
                out.append({"id": f"{len(out):02d}_{_slug(atitle)}",
                            "title": atitle, "start_line": chunk_start,
                            "end_line": aline - 1})
                chunk_start = aline
        out.append({"id": f"{len(out):02d}_{_slug(c['title'])}_tail",
                    "title": f"{c['title']} (tail)",
                    "start_line": chunk_start, "end_line": e})
    # Re-id sequentially
    for i, c in enumerate(out):
        head = c["id"].split("_", 1)[1] if "_" in c["id"] else c["id"]
        c["id"] = f"{i:02d}_{head}"
        c.setdefault("status", "pending")
    return out


def _slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return (s[:32] or "section")


# ---- subcommands ----

def cmd_plan(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir)
    md = extracted / "extracted.md"
    if not md.exists():
        print(f"error: {md} not found", file=sys.stderr)
        return 2
    plan = _autoplan(md)
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir)
    state = _load_state(extracted)
    if args.plan == "-":
        plan = json.load(sys.stdin)
    elif args.plan:
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
    else:
        # auto
        md = extracted / "extracted.md"
        plan = _autoplan(md) if md.exists() else []
    if not state["chunks"] or args.replace:
        for c in plan:
            c.setdefault("status", "pending")
        state["chunks"] = plan
    _save_state(extracted, state)
    print(f"initialized {len(state['chunks'])} chunks under {_chunks_dir(extracted)}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.extracted_dir))
    for c in state["chunks"]:
        size = c["end_line"] - c["start_line"] + 1
        print(f"  {c['status']:11s}  {c['id']:32s}  L{c['start_line']:>5}-{c['end_line']:<5}  ({size} lines)  {c['title']}")
    done = sum(1 for c in state["chunks"] if c["status"] == "done")
    print(f"\n{done}/{len(state['chunks'])} chunks done")
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    state = _load_state(Path(args.extracted_dir))
    pending = [c for c in state["chunks"] if c["status"] != "done"]
    if not pending:
        print(json.dumps({"status": "all_done"}, ensure_ascii=False))
        return 1
    c = pending[0]
    out = dict(c)
    out["extracted_md"] = str(Path(args.extracted_dir) / "extracted.md")
    out["chunks_dir"] = str(_chunks_dir(Path(args.extracted_dir)))
    out["glossary_file"] = state.get("glossary_file")
    out["context_file"] = state.get("context_file")
    out["prev_tail_file"] = str(_chunks_dir(Path(args.extracted_dir)) / "_prev_tail.md")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir)
    state = _load_state(extracted)
    found = None
    for c in state["chunks"]:
        if c["id"] == args.chunk_id:
            found = c
            break
    if not found:
        print(f"error: chunk_id {args.chunk_id} not found", file=sys.stderr)
        return 2
    found["status"] = args.status
    if args.file:
        src = Path(args.file)
        if not src.exists():
            print(f"error: file {src} not found", file=sys.stderr)
            return 2
        dst = _chunks_dir(extracted) / f"{found['id']}.md"
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if args.status == "done":
            tail_lines = dst.read_text(encoding="utf-8").splitlines()[-30:]
            (_chunks_dir(extracted) / "_prev_tail.md").write_text(
                "\n".join(tail_lines) + "\n", encoding="utf-8"
            )
    _save_state(extracted, state)
    print(f"marked {args.chunk_id}: {args.status}")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir).resolve()
    state = _load_state(extracted)
    if args.out:
        out_path = Path(args.out)
    else:
        # Default: <pdf_parent>/<stem>_zh.md (stem = extracted_dir basename minus _extracted)
        stem = extracted.name
        if stem.endswith("_extracted"):
            stem = stem[: -len("_extracted")]
        if not stem:
            stem = "translation"
        out_path = extracted.parent / f"{stem}_zh.md"
    parts: list[str] = []
    for c in state["chunks"]:
        if c["status"] != "done":
            print(f"warning: chunk {c['id']} not done; skipping", file=sys.stderr)
            continue
        f = _chunks_dir(extracted) / f"{c['id']}.md"
        if f.exists():
            parts.append(f.read_text(encoding="utf-8").rstrip("\n"))
    out_path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {out_path} ({len(parts)} chunks)")
    return 0


def cmd_set_glossary(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir)
    state = _load_state(extracted)
    src = Path(args.file)
    dst = _chunks_dir(extracted) / "_glossary.md"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    state["glossary_file"] = str(dst.resolve())
    _save_state(extracted, state)
    print(f"glossary: {dst}")
    return 0


def cmd_set_context(args: argparse.Namespace) -> int:
    extracted = Path(args.extracted_dir)
    state = _load_state(extracted)
    src = Path(args.file)
    dst = _chunks_dir(extracted) / "_context.md"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    state["context_file"] = str(dst.resolve())
    _save_state(extracted, state)
    print(f"context: {dst}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan", help="auto-derive chunk plan from extracted.md (stdout JSON)")
    sp.add_argument("extracted_dir")
    sp.set_defaults(func=cmd_plan)

    si = sub.add_parser("init", help="create _chunks/_state.json from a plan")
    si.add_argument("extracted_dir")
    si.add_argument("--plan", default=None, help="path to plan JSON, or '-' for stdin; default = auto-plan")
    si.add_argument("--replace", action="store_true", help="replace existing chunk list")
    si.set_defaults(func=cmd_init)

    sl = sub.add_parser("list", help="show chunk status")
    sl.add_argument("extracted_dir")
    sl.set_defaults(func=cmd_list)

    sn = sub.add_parser("next", help="print next pending chunk descriptor (JSON)")
    sn.add_argument("extracted_dir")
    sn.set_defaults(func=cmd_next)

    sm = sub.add_parser("mark", help="update chunk status; optionally store file content")
    sm.add_argument("extracted_dir")
    sm.add_argument("chunk_id")
    sm.add_argument("status", choices=["pending", "in_progress", "done"])
    sm.add_argument("--file", default=None, help="path to file containing this chunk's bilingual output")
    sm.set_defaults(func=cmd_mark)

    sa = sub.add_parser("assemble", help="concatenate done chunks to final _zh.md")
    sa.add_argument("extracted_dir")
    sa.add_argument("--out", default=None, help="output path (default: <pdf_parent>/<stem>_zh.md)")
    sa.set_defaults(func=cmd_assemble)

    sg = sub.add_parser("set-glossary", help="store/replace persistent glossary file")
    sg.add_argument("extracted_dir")
    sg.add_argument("file")
    sg.set_defaults(func=cmd_set_glossary)

    sc = sub.add_parser("set-context", help="store/replace persistent background context file")
    sc.add_argument("extracted_dir")
    sc.add_argument("file")
    sc.set_defaults(func=cmd_set_context)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
