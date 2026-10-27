#!/usr/bin/env python3
r"""
validate_md.py — 双语翻译 / PDF 渲染前的结构性体检

用法：
    python3 validate_md.py <md_path> [<images_dir>]

退出码：
    0  全部通过
    1  发现问题（详情打印到 stdout）

检查项（按发现频次排序，命中即继续，不会短路）：
    1. 代码栅栏 ``` 平衡
    2. 表格列数对齐（含转义 `\|` 与 `||` 操作符的列计数）
    3. 图片引用文件存在
    4. 内部 anchor 链接 `](#xxx)` 都能解析到 `<span id="xxx">`
    5. 行内反引号 ` 平衡
    6. 粗体 ** 平衡
    7. KaTeX 风险：行内未转义的 `$` 数量为奇数（缓存名 WGP$/K$ 等会触发误渲染）
    8. 表 / 图标题双语化（Table N. / Figure N. 行需含中文）

每条检查独立打开/关闭可参考源码末尾的 main()。脚本无第三方依赖。
"""
from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple


def _split_code_aware(lines: List[str]):
    """生成 (line_index_1based, line_text, in_code_block: bool)。``` 自身归属代码段外。"""
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            yield i, line, False
            in_code = not in_code
            continue
        yield i, line, in_code


def check_code_fences(lines: List[str]) -> List[str]:
    in_code = False
    last_open = 0
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            if not in_code:
                last_open = i
            in_code = not in_code
    if in_code:
        return [f"UNBALANCED ``` — last open at L{last_open}"]
    return []


def check_table_columns(lines: List[str]) -> List[str]:
    issues: List[str] = []
    in_table = False
    header_cols = 0
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            in_table = False
            continue
        s = line.rstrip("\n")
        is_row = s.startswith("|") and s.endswith("|") and len(s) > 2
        if is_row and not in_table:
            nxt = lines[i].rstrip("\n") if i < len(lines) else ""
            if re.match(r"^\|[\s\-:|]+\|$", nxt):
                in_table = True
                header_cols = len(re.findall(r"(?<!\\)\|", s)) - 1
                continue
        if in_table:
            if not is_row:
                in_table = False
                continue
            cols = len(re.findall(r"(?<!\\)\|", s)) - 1
            if cols != header_cols:
                issues.append(
                    f"L{i}: table row has {cols} cols, expected {header_cols}: {s[:80]}"
                )
    return issues


def check_image_refs(text: str, img_dir: Optional[str]) -> List[str]:
    if not img_dir or not os.path.isdir(img_dir):
        return []
    all_imgs = set(os.listdir(img_dir))
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    issues = []
    for r in refs:
        leaf = r.rsplit("/", 1)[-1]
        if leaf and leaf not in all_imgs:
            issues.append(f"missing image: {r}")
    return issues


def check_anchors(text: str) -> List[str]:
    anchors = set(re.findall(r'<span id="([^"]+)"></span>', text))
    links = set(re.findall(r"\]\(#([^)]+)\)", text))
    return [f"dangling anchor: #{x}" for x in sorted(links - anchors)]


def check_backticks(lines: List[str]) -> List[str]:
    issues = []
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            continue
        s = line.rstrip("\n")
        if "```" in s:
            continue
        if s.count("`") % 2 != 0:
            issues.append(f"L{i}: odd backtick count: {s[:80]}")
    return issues


def check_bold(lines: List[str]) -> List[str]:
    issues = []
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            continue
        s = line.rstrip("\n")
        if s.count("**") % 2 != 0:
            issues.append(f"L{i}: odd '**' count: {s[:80]}")
    return issues


def check_dollar(lines: List[str]) -> List[str]:
    """缓存名 WGP$/K$ 等若未转义为 `\\$`，KaTeX 会把后续文字当作行内公式渲染。"""
    issues = []
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            continue
        s = line.rstrip("\n")
        text_only = re.sub(r"`[^`]*`", "", s)
        n = len(re.findall(r"(?<![\\$])\$(?!\$)", text_only))
        if n > 0 and n % 2 != 0:
            issues.append(f"L{i}: odd unescaped '$' (KaTeX risk): {s[:80]}")
    return issues


def check_caption_bilingual(lines: List[str]) -> List[str]:
    """Accept inline captions or adjacent numbered Chinese caption paragraphs."""
    issues = []
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            continue
        m = re.match(
            r"^[>\s]*#{0,4}\s*(?:\*\*)?(Table|Figure|Fig\.?)\s+"
            r"(\d+|[IVXLCDM]+)\s*[.:：]\s*(.+)$",
            line,
        )
        if not m:
            continue
        rest = m.group(3)
        if not any("\u4e00" <= c <= "\u9fff" for c in rest):
            prefix = "表" if m.group(1) == "Table" else "图"
            chinese_caption = rf"^(?:\*\*)?{prefix}\s*{re.escape(m.group(2))}\s*[.:：]"
            for following in lines[i:]:
                following = re.sub(r"^[>\s]+", "", following).strip()
                if not following:
                    continue
                if re.match(chinese_caption, following):
                    break
                issues.append(
                    f"L{i}: {m.group(1)} caption missing Chinese: {line.strip()[:100]}"
                )
                break
            else:
                issues.append(
                    f"L{i}: {m.group(1)} caption missing Chinese: {line.strip()[:100]}"
                )
    return issues


def check_pipe_ops_in_tables(lines: List[str]) -> List[str]:
    """表格单元里裸露的 `||`/`|=`（逻辑 OR）会被 markdown 解析为列分隔。"""
    issues = []
    in_table = False
    for i, line, in_code in _split_code_aware(lines):
        if in_code:
            in_table = False
            continue
        s = line.rstrip("\n")
        if not s.startswith("|"):
            in_table = False
            continue
        if re.match(r"^\|[\s\-:|]+\|$", s):
            in_table = True
            continue
        if not in_table:
            continue
        for m in re.finditer(r"`([^`]*)`", s):
            inside = m.group(1)
            if re.search(r"(?<!\\)\|\|", inside) or re.search(r"(?<!\\)\|=", inside):
                issues.append(f"L{i}: code in table cell has unescaped '||' / '|=': {inside}")
                break
    return issues


CHECKS: List[Tuple[str, callable]] = [
    ("code_fences", lambda lines, text, img: check_code_fences(lines)),
    ("table_columns", lambda lines, text, img: check_table_columns(lines)),
    ("image_refs", lambda lines, text, img: check_image_refs(text, img)),
    ("anchors", lambda lines, text, img: check_anchors(text)),
    ("backticks", lambda lines, text, img: check_backticks(lines)),
    ("bold", lambda lines, text, img: check_bold(lines)),
    ("dollar_katex", lambda lines, text, img: check_dollar(lines)),
    ("caption_bilingual", lambda lines, text, img: check_caption_bilingual(lines)),
    ("pipe_ops_in_tables", lambda lines, text, img: check_pipe_ops_in_tables(lines)),
]


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    md_path = argv[1]
    img_dir = argv[2] if len(argv) > 2 else None

    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    print(f"Validating: {md_path}")
    print(f"Lines: {len(lines):,}  Bytes: {len(text):,}")
    if img_dir:
        print(f"Image dir: {img_dir}")
    print("=" * 60)

    total = 0
    for name, fn in CHECKS:
        issues = fn(lines, text, img_dir)
        status = "PASS" if not issues else f"FAIL ({len(issues)})"
        print(f"{name:24s}  {status}")
        for x in issues[:5]:
            print(f"    {x}")
        if len(issues) > 5:
            print(f"    … and {len(issues) - 5} more")
        total += len(issues)

    print("=" * 60)
    print(f"TOTAL ISSUES: {total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
