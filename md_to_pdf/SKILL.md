---
name: md-to-pdf
description: >-
  Convert Markdown files to professionally formatted A4 PDF documents with
  auto-generated table of contents, academic paper typography, and smart page
  breaks that keep figures and tables on a single page. Use when the user wants
  to convert Markdown to PDF, generate a PDF document, or export Markdown as a
  printable file.
---

# Markdown 转 PDF

将 Markdown 文件转换为 A4 尺寸的 PDF 文档，采用学术论文排版风格。

## 前置条件

### Python 包

```bash
/workspace/ai_tools/.venv/bin/python -m pip install -r ~/.cursor/skills/md-to-pdf/requirements.txt
```

### WeasyPrint 的系统依赖（Ubuntu/Debian）

```bash
sudo apt-get install libpango1.0-dev libcairo2-dev libgdk-pixbuf-2.0-dev libffi-dev shared-mime-info
```

### 中文字体（如未安装）

```bash
sudo apt-get install fonts-noto-cjk
```

### KaTeX 服务端渲染（推荐，首次安装一次即可）

多行数学环境（`cases` / `aligned` / `matrix` 等）、`\underbrace` / `\overbrace` 等花括号标注，以及 `$$…$$` 块内跨物理行的公式，在没有 KaTeX 时都会渲染失败（见下方 mathtext 回退的坑）。为正确渲染这些公式，脚本优先调用 KaTeX 服务端渲染，输出 HTML + CSS 给 WeasyPrint。

需要：Node.js 16+。**`install_katex.sh` 现在会自动准备 node，无需手动装**：按 ① PATH 上已有的 node → ② 复用 Cursor Server 自带的 node（`~/.cursor-server/bin/*/node`，通常 v20+，零下载零 sudo）→ ③ `apt-get install nodejs`（Node 18 LTS，满足 16+；仅在 root 或有免密 sudo 时执行）的顺序尝试。想禁用第 ③ 步的 apt 安装，设 `NODE_NO_AUTOINSTALL=1`。

```bash
~/.cursor/skills/md-to-pdf/install_katex.sh
```

脚本会：**确保 node 可用（如上，必要时自动安装 Node 18）**→ 下载 KaTeX tarball → 瘦身（只留 `katex.min.js` + `katex.min.css` + woff2 字体）→ 把字体 base64 内联进单文件 CSS bundle → 做一条 `\begin{cases}` 的 smoke test。幂等：再次运行会跳过下载，直接重建 bundle。

如果不装 KaTeX，脚本仍能工作，但会退化到 matplotlib mathtext / MathML：`cases` 等被压成一行，`\underbrace` 之类不支持的宏会掉出豆腐块（□），`$$` 块内跨行的公式甚至整条以原始 LaTeX 文本出现。**强烈建议先跑 `install_katex.sh` 再生成任何含公式的文档。**

### Mermaid 图渲染（推荐，首次安装一次即可）

支持文档里的 ` ```mermaid ` 代码块（流程图、序列图、状态图、类图、ER 图、甘特图等）。脚本通过系统 chromium 离线渲染为 SVG 后嵌入 PDF。

需要：
- chromium-browser / chromium / google-chrome 任一在 PATH（snap 装的 chromium 也行）
- 不需要 npm、puppeteer 或 sudo

```bash
~/.cursor/skills/md-to-pdf/install_mermaid.sh
```

脚本会：检查 chromium 可访问性 → 下载 mermaid tarball（仅留 ~2.5MB 的 `mermaid.min.js`）→ 渲染 flowchart + sequence smoke test。幂等。

如果不装 mermaid，` ```mermaid ` 块会显示一个红框错误占位，并把原始源码折叠在 `<details>` 里，不会丢信息。

> **snap chromium 注意事项**：snap 包装的 chromium 默认无法访问 `~/.cursor/`、`~/.cache/` 等隐藏父目录。`install_mermaid.sh` 会做一次预检：如果 skill 真实路径仍位于隐藏目录下，脚本会直接退出并提示你把 skill 装到非隐藏路径（典型做法是把 skill 真实代码放在 `~/projects/` 或 `~/ws/` 下，再 `ln -s` 到 `~/.cursor/skills/md-to-pdf`）。

## 工作流程

### Step 0: 首次使用前

```bash
~/.cursor/skills/md-to-pdf/install_katex.sh   # 自动准备 node（必要时装 Node 18）+ 启用 KaTeX 数学公式
~/.cursor/skills/md-to-pdf/install_mermaid.sh # 启用 mermaid 图渲染
```

两个脚本都幂等，已装过会跳过；只需要哪一种就跑哪一种。

### Step 1: 确认输入输出

- 输入：用户提供的 Markdown 文件路径
- 输出：默认与输入同名但扩展名为 `.pdf`，用户也可指定输出路径

### Step 1.5: 渲染前预检（强烈推荐，特别是大文档）

`convert.py` 不会因为 Markdown 结构性问题（错位表格、未转义 `$` 触发 KaTeX、断链 anchor）而 fail 导致退出码非 0——它会**默默地**输出一个长得不对的 PDF。最常见的事故：

| 现象 | 实际成因 |
|---|---|
| 正文一段话突然变成歪斜的数学字体 | 缓存名 `WGP$`/`K$`/`L1$` 未转义为 `\$`，KaTeX 把后续正文当行内公式 |
| 整张表所有行错位、列对不上 | 表格单元里有未转义的 `\|=`/`\|\|`（代码用作位运算 OR）打破列数 |
| 表格只渲染了表头几行后突然中断 | Marker 提取出的"残缺表"——只有 1 行 body |
| 内部链接点击无反应 | PDF 页锚被翻译时删除，链接成 dangling |
| 表格行混乱排列、对不上 | 列优先（column-major）opcode 表被错误地按行读取 |

跑一遍 `translate` 自带的结构性体检脚本能秒级发现这 5 类问题：

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/validate_md.py "<MD路径>" "[图片目录]"
```

输出形如：

```
code_fences          PASS
table_columns        PASS
image_refs           PASS
anchors              PASS
backticks            PASS
bold                 PASS
dollar_katex         PASS
caption_bilingual    PASS
pipe_ops_in_tables   PASS
============================================================
TOTAL ISSUES: 0
```

任何一项 FAIL **都应在渲染前修复**。脚本无第三方依赖，独立可用，不限于 translate 翻译产物——任何技术 Markdown 都可以体检。

### Step 2: 运行转换脚本

双语文档按可读性选择标题布局：短标题可以同行；较长标题的英文和中文应上下分块，不强制用斜杠拼接。使用同一个 Markdown 标题与 `<br><br>` 保留段落间隔，例如：

```markdown
## Roofline-Driven Optimization of ROCm Libraries <br><br> 基于 Roofline 模型的 ROCm 库优化
```

自动目录保留英中文上下分行，但将连续 `<br>` 合并为单个 `<br>`，使用正常行距，不复制正文标题的段间留白。同一章节只有一个目录项和书签；手写目录也使用单个 `<br>` 分行。不要把两种语言拆成两个同级标题；不要依赖源码中的普通换行或缩小字体来处理过长标题。较长图表标题使用两个相邻段落，英文在上、中文在下，中间空一行，并保留相同图表编号。转换后抽查目录、长标题和图表标题的实际折行与分页，特别确认目录的英中文间没有额外空白行。

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/md-to-pdf/convert.py "<MD文件路径>"
```

常用选项：

| 参数 | 说明 |
|------|------|
| `-o <路径>` | 指定输出 PDF 路径 |
| `--no-toc` | 不生成目录页 |
| `--title <标题>` | 自定义文档标题（默认取第一个 H1） |

### Step 3: 报告结果

告诉用户 PDF 输出路径。如果转换失败，检查错误信息并修复。

## 排版特性

脚本自动处理以下排版需求：

- **纸张**：A4 (210 × 297mm)，页边距 18/20/22/20mm（上/左/下/右），紧凑学术论文风格
- **目录**：如果文档没有自带目录，从标题自动生成并放在第一页，保留显式分行，将连续 `<br>` 合并为一次换行以避免空白行；如果文档已有目录（标题含"目录"或"Contents"），则跳过自动生成
- **页码**：每页底部居中，目录页不编号
- **字体**：正文用衬线体（Noto Serif CJK），标题用无衬线体（Noto Sans CJK）
- **排版**：两端对齐，1.35 倍行距，9.5pt 正文字号；段落 / 图表 / 标题间距经过收紧调优，双语对照文档约 2× 原文页数
- **图表保护**：图片、表格、代码块设置 `page-break-inside: avoid`，不会被分割到两页
- **标题保护**：标题与后续内容不分离（`page-break-after: avoid`）
- **段落保护**：孤行/寡行控制（orphans/widows 各 3 行）
- **图片**：自动居中，限制最大高度不超过页面
- **数学公式**：`$...$` 和 `$$...$$` LaTeX 公式按优先级渲染：
  1. **KaTeX 服务端渲染**（首选）：输出 HTML + CSS，覆盖 `cases` / `aligned` / `align` / `matrix` / `pmatrix` / `bmatrix` / `array` 等多行环境，视觉效果与浏览器 Markdown 预览一致
  2. **matplotlib mathtext**（回退 1）：KaTeX 不可用或单条公式渲染失败时，逐条渲染为 SVG
  3. **latex2mathml MathML**（回退 2）：含中文或 mathtext 不支持的命令时触发
  4. **原始 LaTeX `<code>`**（回退 3）：以上全部失败时兜底
- **Mermaid 图**：` ```mermaid ` 围栏块通过系统 chromium 离线渲染为 SVG 后嵌入 PDF（flowchart / sequenceDiagram / stateDiagram / classDiagram / erDiagram / gantt / pie 等所有 mermaid 标准类型均支持）。整篇文档的所有 mermaid 图一次 chromium 启动批量渲染，开销近似常量。渲染失败的图（chromium 缺失 / 单条语法错）会显示带边框的红色错误占位框，并把原始源码折叠在 `<details>` 里
- **代码**：等宽字体，浅灰背景，自动折行；标注语言的代码块通过 Pygments 语法高亮显示（default 主题）
- **表格**：全宽带边框，表头灰底居中

## 示例

用户说："把 report.md 转成 PDF"

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/md-to-pdf/convert.py ~/docs/report.md
```

输出：`~/docs/report.pdf`

指定输出路径和标题：

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/md-to-pdf/convert.py report.md -o output/report.pdf --title "季度报告"
```

### 实际案例：CuTe Layout 论文

输入 Markdown：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（2299 行，含 9 张图片和大量 LaTeX 公式的中英双语学术论文）

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/md-to-pdf/convert.py inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md
```

输出：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.pdf`

该案例覆盖了主要排版特性：自动检测已有目录（不重复生成）、LaTeX 数学公式渲染（KaTeX 首选、mathtext/MathML 兜底）、图表不跨页、PNG 无损图片、参考文献逐行显示。尤其：第 495 行的 `\begin{cases}` 公式在 PDF 里正确显示为两行、带可见左花括号，和浏览器 Markdown 预览一致。

## 故障排除

### 安装 / 渲染环境类

| 问题 | 解决 |
|------|------|
| `weasyprint` 导入失败 | 安装系统依赖：`sudo apt-get install libpango1.0-dev libcairo2-dev` |
| 中文显示为方框 | 安装字体：`sudo apt-get install fonts-noto-cjk` |
| 图片未显示 | 确认图片路径是相对于 Markdown 文件的相对路径 |
| 代码无语法高亮 | 安装 Pygments：`pip install Pygments` |
| 公式中中文显示为方块 | 含中文的公式会经 `\text{}` 回退到正文字体；确认已装 `fonts-noto-cjk` |
| 多行公式（`cases`/`aligned`/`matrix`）被压成一行 | 运行 `~/.cursor/skills/md-to-pdf/install_katex.sh` 启用 KaTeX 管线 |
| `install_katex.sh` 报 `node not found and auto-install failed` | 自动准备 node 失败（无 apt、非 root 且无免密 sudo、又没有 Cursor Server 自带 node）。手动装 Node.js 16+：`sudo apt-get install -y nodejs`（Node 18），或用 fnm/nvm（不需 sudo）后重跑脚本 |
| `install_katex.sh` 可下载但 smoke test 失败 | 删除 `~/.cursor/skills/md-to-pdf/vendor/katex` 后重跑；确认 Node 版本 ≥ 16 |
| Mermaid 图显示为红色 `[Mermaid 渲染失败]` 占位 | 运行 `~/.cursor/skills/md-to-pdf/install_mermaid.sh`；如未装 chromium，先 `sudo apt-get install chromium-browser` 或 `sudo snap install chromium` |
| `install_mermaid.sh` 提示 "chromium can't read $SKILL_DIR" | 你在用 snap 版 chromium，且 skill 真实路径在 `~/.cursor/` 等隐藏目录下。把代码移到非隐藏路径（如 `~/projects/md-to-pdf/`），再 `ln -s ~/projects/md-to-pdf ~/.cursor/skills/md-to-pdf` |
| Mermaid 图渲染但中文乱码 | 确认已装 `fonts-noto-cjk` |

### Markdown 内容类（PDF 渲染异常）

这一类问题 `convert.py` 不会报错，PDF 体积也正常，但内容渲染走形。先跑 [Step 1.5](#step-15-渲染前预检强烈推荐特别是大文档) 的 `validate_md.py`，再对照下表。

| 现象 | 检查项 | 修复 |
|------|--------|------|
| 正文段落突然变成歪斜 mathit 字体 | `dollar_katex` | 缓存名 `WGP$`/`K$`/`L1$`/`SE$`/`Inst$` 等改为 `WGP\$`/`K\$`，或反引号包裹 |
| 表格列错位 / 行被切碎 | `table_columns`、`pipe_ops_in_tables` | 表格单元里 `\|=`、`\|\|` 转义；多行单元改用 `<br>` |
| 表格只渲染前若干行 | `table_columns` | 残缺表（PDF 提取丢行），回查源 PDF 补齐 |
| 表格行序明显错乱（如 opcode 245 描述跑到 248 行） | 人工 | 2 列对照表常被列优先（column-major）误解析，整列重排 |
| 内部链接（`[xxx](#anchor)`）点击无反应 | `anchors` | dangling anchor，用 grep 在文档里找最近的 `<span id="...">` 替换 |
| Table/Figure 标题只有英文 | `caption_bilingual` | 补充紧邻英文标题的同编号中文段落；短标题也可同行 |
| 某段粗体一直延续到段末 / 跨段 | `bold` | `**` 数量为奇数，找漏配的 `**` 补齐 |
| 某段反引号代码态延续到段末 | `backticks` | 反引号数量为奇数，找漏配的 `` ` `` 补齐 |
| PDF 中段内容缺失 | `code_fences` | 未闭合的 ```` ``` ````，找最后一个开放的代码栅栏补 ```` ``` ```` |
| 某条显示公式整条变成原始 LaTeX 文本（还带一个残留 `$`） | 人工 | **根因：没启用 KaTeX 时的 mathtext 回退无法解析公式体内的换行。** `$$…$$` 块的公式体不要跨物理行——即使 `convert.py` 的提取用了 `re.DOTALL` 能吃下多行，mathtext 渲染仍会失败并掉到原始 LaTeX 兜底。修复：把 display math 合并到单行；根治：`install_katex.sh` 启用 KaTeX（KaTeX 能正确渲染多行体） |
| 公式里出现豆腐块 □ / `⏟` 挤成一坨 / 花括号标注错位 | 人工 | 用了 mathtext **不支持**的宏（`\underbrace`/`\overbrace`/`\underset`/`cases`/`aligned`/`matrix` 等），回退到 latex2mathml 的 MathML 后缺字。根治：跑 `install_katex.sh` 启用 KaTeX（原生支持这些宏）；临时无 node 时，可把 `\underbrace{X}_{dim}` 降级写成下标 `X_{(dim)}` 等 mathtext 支持的等价写法 |
