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
pip install markdown weasyprint Pygments matplotlib latex2mathml
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

多行数学环境（`cases` / `aligned` / `matrix` 等）在 WeasyPrint 自带的 MathML 渲染器下会被压成一行。为正确渲染这些公式，脚本优先调用 KaTeX 服务端渲染，输出 HTML + CSS 给 WeasyPrint。

需要：Node.js 16+（Cursor Server 自带的 v20 就够用，只要 `node` 在 PATH 里即可；不需要 `npm` 也不需要 `sudo`）。

```bash
~/.cursor/skills/md-to-pdf/install_katex.sh
```

脚本会：下载 KaTeX tarball → 瘦身（只留 `katex.min.js` + `katex.min.css` + woff2 字体）→ 把字体 base64 内联进单文件 CSS bundle → 做一条 `\begin{cases}` 的 smoke test。幂等：再次运行会跳过下载，直接重建 bundle。

如果不装 KaTeX，脚本仍能工作：多行数学环境会退化到 matplotlib mathtext 或 MathML（`cases` 会被压成一行），其余功能不受影响。

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
~/.cursor/skills/md-to-pdf/install_katex.sh   # 启用 KaTeX 数学公式
~/.cursor/skills/md-to-pdf/install_mermaid.sh # 启用 mermaid 图渲染
```

两个脚本都幂等，已装过会跳过；只需要哪一种就跑哪一种。

### Step 1: 确认输入输出

- 输入：用户提供的 Markdown 文件路径
- 输出：默认与输入同名但扩展名为 `.pdf`，用户也可指定输出路径

### Step 2: 运行转换脚本

```bash
python3 ~/.cursor/skills/md-to-pdf/convert.py "<MD文件路径>"
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

- **纸张**：A4 (210 × 297mm)，页边距 25/22/28/22mm（上/左/下/右）
- **目录**：如果文档没有自带目录，从标题自动生成并放在第一页；如果文档已有目录（标题含"目录"或"Contents"），则跳过自动生成
- **页码**：每页底部居中，目录页不编号
- **字体**：正文用衬线体（Noto Serif CJK），标题用无衬线体（Noto Sans CJK）
- **排版**：两端对齐，1.6 倍行距，10pt 正文字号
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
python3 ~/.cursor/skills/md-to-pdf/convert.py ~/docs/report.md
```

输出：`~/docs/report.pdf`

指定输出路径和标题：

```bash
python3 ~/.cursor/skills/md-to-pdf/convert.py report.md -o output/report.pdf --title "季度报告"
```

### 实际案例：CuTe Layout 论文

输入 Markdown：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（2299 行，含 9 张图片和大量 LaTeX 公式的中英双语学术论文）

```bash
python3 ~/.cursor/skills/md-to-pdf/convert.py inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md
```

输出：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.pdf`

该案例覆盖了主要排版特性：自动检测已有目录（不重复生成）、LaTeX 数学公式渲染（KaTeX 首选、mathtext/MathML 兜底）、图表不跨页、PNG 无损图片、参考文献逐行显示。尤其：第 495 行的 `\begin{cases}` 公式在 PDF 里正确显示为两行、带可见左花括号，和浏览器 Markdown 预览一致。

## 故障排除

| 问题 | 解决 |
|------|------|
| `weasyprint` 导入失败 | 安装系统依赖：`sudo apt-get install libpango1.0-dev libcairo2-dev` |
| 中文显示为方框 | 安装字体：`sudo apt-get install fonts-noto-cjk` |
| 图片未显示 | 确认图片路径是相对于 Markdown 文件的相对路径 |
| 代码无语法高亮 | 安装 Pygments：`pip install Pygments` |
| 公式中中文显示为方块 | 含中文的公式会经 `\text{}` 回退到正文字体；确认已装 `fonts-noto-cjk` |
| 多行公式（`cases`/`aligned`/`matrix`）被压成一行 | 运行 `~/.cursor/skills/md-to-pdf/install_katex.sh` 启用 KaTeX 管线 |
| `install_katex.sh` 报 `node not found` | 安装 Node.js 16+；可用 fnm/nvm，不需 sudo |
| `install_katex.sh` 可下载但 smoke test 失败 | 删除 `~/.cursor/skills/md-to-pdf/vendor/katex` 后重跑；确认 Node 版本 ≥ 16 |
| Mermaid 图显示为红色 `[Mermaid 渲染失败]` 占位 | 运行 `~/.cursor/skills/md-to-pdf/install_mermaid.sh`；如未装 chromium，先 `sudo apt-get install chromium-browser` 或 `sudo snap install chromium` |
| `install_mermaid.sh` 提示 "chromium can't read $SKILL_DIR" | 你在用 snap 版 chromium，且 skill 真实路径在 `~/.cursor/` 等隐藏目录下。把代码移到非隐藏路径（如 `~/projects/md-to-pdf/`），再 `ln -s ~/projects/md-to-pdf ~/.cursor/skills/md-to-pdf` |
| Mermaid 图渲染但中文乱码 | 确认已装 `fonts-noto-cjk` |
