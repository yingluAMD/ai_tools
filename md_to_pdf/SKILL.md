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

Python 包：

```bash
pip install markdown weasyprint Pygments matplotlib latex2mathml
```

WeasyPrint 的系统依赖（Ubuntu/Debian）：

```bash
sudo apt-get install libpango1.0-dev libcairo2-dev libgdk-pixbuf-2.0-dev libffi-dev shared-mime-info
```

中文字体（如未安装）：

```bash
sudo apt-get install fonts-noto-cjk
```

## 工作流程

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
- **数学公式**：`$...$` 和 `$$...$$` LaTeX 公式优先用 matplotlib mathtext 渲染为 SVG（真正的分数线、正确上下标），含中文的公式自动回退到 latex2mathml MathML
- **代码**：等宽字体，浅灰背景，自动折行
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

输入 Markdown：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（750 行，含 6 张图片和大量 LaTeX 公式的中英双语学术论文）

```bash
python3 ~/.cursor/skills/md-to-pdf/convert.py inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md
```

输出：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.pdf`（1.9 MB）

该案例覆盖了主要排版特性：自动检测已有目录（不重复生成）、LaTeX 数学公式渲染（matplotlib mathtext 为主，含中文的公式回退到 MathML）、图表不跨页、PNG 无损图片、参考文献逐行显示。

## 故障排除

| 问题 | 解决 |
|------|------|
| `weasyprint` 导入失败 | 安装系统依赖：`sudo apt-get install libpango1.0-dev libcairo2-dev` |
| 中文显示为方框 | 安装字体：`sudo apt-get install fonts-noto-cjk` |
| 图片未显示 | 确认图片路径是相对于 Markdown 文件的相对路径 |
| 代码无语法高亮 | 安装 Pygments：`pip install Pygments` |
| 公式中中文显示为方块 | 含中文的公式会自动回退到 MathML 渲染；若 latex2mathml 未安装则显示原始 LaTeX |
