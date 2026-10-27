#!/usr/bin/env python3
"""
normalize_headings.py —— 修复 Marker 提取导致的标题层级错乱 / TOC 层级错误。

背景（lesson learned，见 SKILL.md「标题层级与目录(TOC)」）：
Marker 从 PDF 提取时经常丢失或打乱标题层级。典型症状（在 md-to-pdf 生成的
PDF 目录里表现为「层级全错/扁平」）：
  1. 章(`N ...`) 和节(`N.M ...`) 全被标成 `#`(H1)，opcode(`N.M.K ...`)
     被标成 `####`(H4) —— 层级完全扁平。
  2. 个别章号在提取时丢失（如 `Encoding ENC_SOP1` 没有编号）。
  3. 整段指令签名被并进标题行（`# **2.5.13 DS_APPEND ds_append vgpr...**`）。
  4. 无编号 opcode 标题把签名当成标题（`#### flat_load_dword v_dst 32...`）。
  5. Marker 误识别的碎片（`Examples:`、`mul:{1,2,4}`、`0.5ULP accuracy...`）
     被当成标题，污染目录；`0.5ULP` 还会被误解析成「第 0 章」顶进 H1。
  6. 提取出的旧「Contents/目录」页页码是原始 PDF 的（已失效）、且行残缺，
     还会触发 md-to-pdf 的 `_has_manual_toc` → 跳过自动生成正确目录。

本脚本按「章节号层数」重建层级（`N`→H1、`N.M`→H2、`N.M.K…`→H3），拆分
被并进标题的签名，删除失效的旧目录块，并把误判碎片降到 H5（低于 md-to-pdf
的 toc_depth=1-4，从而不进目录）。

默认 dry-run 只报告；加 --apply 才写回。写回前请自行备份 / 用 git。
用法：
    python normalize_headings.py <bilingual_zh.md>            # 预览
    python normalize_headings.py <bilingual_zh.md> --apply    # 写回
"""
import re
import sys

# 会被识别为 opcode 签名（而非「/ 中文」翻译）的标志串
SIG_RE = re.compile(
    r"<sup>|POS \(INSTFIELD\)|Flags:|NAME TYPE|(?<![A-Za-z])[a-z][a-z0-9]*\\?_[a-z0-9\\_]+"
)
# 单独成行的全大写标识符（如 OPF_*, ASIC_*）—— 视为「术语定义」小节，进目录用 H3
ALLCAPS_ID = re.compile(r"^\*{0,2}(?:OPF|ASIC|SEN|SP|ENC)\\?_[A-Z0-9\\_]+\*{0,2}\s*$")
# opcode 签名标题：`<span?>**mnemonic** <operands...>`
SIG_HEAD = re.compile(r"^(<span[^>]*></span>\s*)?\*\*([^*]+?)\*\*\s*(.*)$")


def strip_span(s):
    return re.sub(r"<span[^>]*></span>\s*", "", s)


def disp(body):
    return strip_span(body).strip().replace("**", "").strip()


def en_part(d):
    return d.split(" / ")[0].strip()


def numbered(body):
    """返回章节号（如 '2.5.13'）或 None。

    只认「数字后紧跟空格/点/星号/行尾」的编号；`0.5ULP`（数字紧贴字母）
    不算编号，避免被误解析成章号。
    """
    c = strip_span(body).strip()
    m = re.match(r"\*{0,2}\s*(\d+(?:\.\d+)*)(?=[\s.\*]|$)", c)
    if not m:
        return None
    # 排除「0」这种（`0.5ULP` 退化匹配）以及数字紧贴字母的伪编号
    num = m.group(1)
    tail = c[m.end():]
    if num == "0" or re.match(r"[A-Za-z]", tail):
        return None
    return num


def classify(body, before_first_numbered):
    """返回 (level:int, new_body_or_None, split:(heading, remainder)_or_None)。"""
    num = numbered(body)
    if num:
        level = min(num.count(".") + 1, 3)
        # 拆分「编号 opcode 标题里并进了签名」的情况（仅 level-3）
        core = strip_span(body).strip()
        m = re.match(r"^\*\*(\d+(?:\.\d+)*\s+[A-Z][A-Z0-9_\\]+)([^*]*)\*\*(.*)$", core)
        if level == 3 and m:
            rest = (m.group(2).strip() + " " + m.group(3).strip()).strip()
            if rest and SIG_RE.search(rest):
                lead = body[: body.index("**")] if "**" in body else ""
                return level, None, ((lead + "**" + m.group(1).strip() + "**").strip(), rest)
        return level, None, None

    d = disp(body)
    de = en_part(d)
    core = strip_span(body).strip()

    # 第一个编号标题之前的无编号标题 = 前置内容（标题页 / 声明 / 目录）→ H1
    if before_first_numbered:
        return 1, None, None
    # 附录：单个大写字母 + 空格 + 标题词（如 "A Operand Types"）→ H1
    if re.match(r"^\*{0,2}[A-Z]\s+[A-Z][a-z]", core):
        return 1, None, None
    # 无编号的「章」标题（如 Marker 丢了章号的 Encoding ENC_XXX）→ H1，但发出警告
    if re.match(r"^\*{0,2}Encoding\b", core):
        return 1, None, ("__WARN_CHAPTER_NO_NUMBER__", None)
    # 无编号 opcode 签名标题 → 拆分为「mnemonic 标题 + 签名正文」，H3
    if SIG_RE.search(body):
        hm = SIG_HEAD.match(core)
        if hm and hm.group(3).strip():
            span = hm.group(1) or ""
            return 3, None, ("### " + span + "**" + hm.group(2).strip() + "**",
                             "__SIGSPLIT__" + hm.group(3).strip())
        return 3, None, None
    # 全大写标识符（flag/术语定义）→ H3
    if ALLCAPS_ID.match(core):
        return 3, None, None
    if de.startswith("References"):
        return 3, None, None
    # 其余（续表头 `... (continued)`、`Global.`、Marker 碎片）→ H5，移出目录(1-4)
    return 5, None, None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply = "--apply" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)
    path = args[0]
    raw = open(path, encoding="utf-8").read().split("\n")

    # 1) 删除失效的旧「Contents/目录」块：从该标题到下一个编号为 "1" 的标题之前
    ci = ii = None
    for i, l in enumerate(raw):
        m = re.match(r"^#{1,6}\s+(.*)$", l)
        if not m:
            continue
        if ci is None and en_part(disp(m.group(1))) in ("Contents", "目录"):
            ci = i
        elif ci is not None and numbered(m.group(1)) == "1":
            ii = i
            break
    dropped = 0
    if ci is not None and ii is not None:
        dropped = ii - ci
        raw = raw[:ci] + raw[ii:]

    # 2) 逐标题规整层级
    seen_numbered = False
    out = []
    changes = splits = warn = 0
    warn_lines = []
    lvl = {}
    for l in raw:
        m = re.match(r"^(#{1,6})\s+(.*)$", l)
        if not m:
            out.append(l)
            continue
        cur = len(m.group(1))
        body = m.group(2)
        before_first_numbered = not seen_numbered
        if numbered(body):
            seen_numbered = True
        level, newbody, split = classify(body, before_first_numbered)
        lvl[level] = lvl.get(level, 0) + 1

        if split and split[0] == "__WARN_CHAPTER_NO_NUMBER__":
            warn += 1
            warn_lines.append(disp(body)[:60])
            out.append("#" * level + " " + body)
            if cur != level:
                changes += 1
            continue
        if split and split[0].startswith("###") and split[1].startswith("__SIGSPLIT__"):
            out.append(split[0])
            out.append("")
            out.append(split[1][len("__SIGSPLIT__"):])
            splits += 1
            continue
        if split:  # 编号 opcode 的签名拆分
            nh, rem = split
            out.append("#" * level + " " + nh)
            out.append("")
            out.append(rem)
            splits += 1
            continue

        b = newbody if newbody is not None else body
        out.append("#" * level + " " + b)
        if cur != level:
            changes += 1

    print(f"删除失效目录行数: {dropped}")
    print(f"标题级别修正: {changes}, 签名拆分: {splits}")
    print(f"层级分布: {dict(sorted(lvl.items()))}")
    if warn:
        print(f"\n⚠  发现 {warn} 个疑似「丢了章号」的章标题（已置 H1，请人工补章号）:")
        for w in warn_lines:
            print("   -", w)
    print("\n提示：目录只显示 H1-H4；被降到 H5 的是续表头/Marker 碎片（不进目录）。")

    if apply:
        open(path, "w", encoding="utf-8").write("\n".join(out))
        print("\nAPPLIED ->", path)
    else:
        print("\n(dry-run，未写回；加 --apply 生效)")


if __name__ == "__main__":
    main()
