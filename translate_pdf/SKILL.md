---
name: translate-pdf
description: >-
  Translate English technical PDF documents (papers, specs, slides) into
  bilingual English-Chinese Markdown with paragraph-by-paragraph comparison.
  Use when the user wants to translate a PDF, convert a paper to Chinese, or
  create bilingual documentation from PDF files.
---

# PDF 双语翻译

将英文技术 PDF（论文、规范、幻灯片）翻译为中英双语对照 Markdown 文档。

## 前置条件

Python 环境需要安装：

```bash
pip install -r ~/.cursor/skills/translate-pdf/requirements.txt
```

系统需要 Tesseract（OCR 功能）：`sudo apt-get install tesseract-ocr`

## 工作流程

按以下步骤执行，不要跳过。

### Step 1: 提取 PDF

用 Shell 工具运行提取脚本：

```bash
python3 ~/.cursor/skills/translate-pdf/extract_pdf.py "<PDF路径>" "<输出目录>"
```

- 如果用户没有指定输出目录，脚本默认在 PDF 所在目录下创建 `{PDF文件名}_extracted/` 子目录存放中间文件
- 脚本会输出一个 JSON 摘要到 stdout，包含 `markdown_file`、`markdown_lines`、`total_images`、`text_heavy_images` 等信息
- 所有图片统一保存为 PNG 无损格式（避免 JPEG 压缩损失）
- 当 PyMuPDF 能提取到比 Marker 更高分辨率的原始嵌入图片时，会自动替换并更新 Markdown 引用
- 向用户报告提取结果摘要

### Step 2: 读取提取内容

1. 读取 `{输出目录}/extracted.md`
2. 如果存在 `{输出目录}/ocr_report.json`，也读取它（包含文字密集图片的 OCR 文本）
3. 评估文档大小：如果超过 500 行，按章节分块处理（见下方"分块策略"）

### Step 3: 翻译并生成双语文档

逐段处理 extracted.md 的内容，生成双语 Markdown。

**重要：最终的双语文档写入到与输入 PDF 相同的目录**，文件名为 `{PDF文件名}_zh.md`。例如输入 `~/papers/attention.pdf`，输出到 `~/papers/attention_zh.md`。

对每种内容类型的处理规则：

#### 标题

英文标题后加斜杠和中文翻译：

```
## Introduction / 引言
### Related Work / 相关工作
```

#### 段落

英文原文放在引用块中，中文翻译在下方，两者之间空一行：

```
> We propose a novel framework for neural machine translation that leverages
> cross-lingual representations to improve translation quality.

我们提出了一种新的神经机器翻译框架，利用跨语言表示来提高翻译质量。
```

#### 表格

保留原始英文表格。如果表格包含大量文字内容，在下方添加翻译版本：

```
| Method | Accuracy | Description |
|--------|----------|-------------|
| Ours   | 95.2%    | Uses attention |

**[翻译]**

| 方法 | 准确率 | 描述 |
|------|--------|------|
| 我们的 | 95.2% | 使用注意力机制 |
```

如果表格只有数字和简短标签，可以只翻译表头，不翻译整个表格。

#### 数学公式

LaTeX 公式原样保留，不翻译。为确保 GitHub 正确渲染，遵守以下规则：

1. **绝对值/大小符号**：用 `\lvert` 和 `\rvert` 代替 `|`，避免被解析为表格分隔符。例如 `$\lvert S \rvert$` 而非 `$|S|$`。
2. **上标星号**：用 `^{\ast}` 代替 `^*`，避免被解析为 Markdown 强调。例如 `$\mathbf{L}^{\ast}$` 而非 `$\mathbf{L}^*$`。
3. **函数名中的下划线**：用 `\mathrm{func\_name}` 或 `\operatorname{func\_name}`，避免 `_` 被解析为斜体。
4. **整除符号**：用 `\,\vert\,` 代替 `\mid`，在内联公式中更安全。
5. **display math**：`$$` 公式独占一行，前后各留空行。

```
$$
\mathcal{L} = -\sum_{i=1}^{N} y_i \log(\hat{y}_i)
$$
```

如果公式前后有解释性文字，翻译文字部分即可。

#### 代码块

`extract_pdf.py` 会自动为代码块添加语言标签（如 ` ```python `、` ```cpp `）。翻译时：

- **保留语言标签**不变，确保渲染时有语法高亮
- **不翻译代码内容**，代码块原样保留
- 如果代码块前后有解释性文字，翻译文字部分即可

#### 图片

图片引用路径需要指向 `{PDF文件名}_images/` 子目录（见 Step 5 的图片搬迁步骤）。翻译时先保留原始引用路径不变，Step 5 中统一修正。

**重要原则**：
- 翻译文档必须包含原始论文中的**所有图片**，不得遗漏任何一张。
- 图片必须是论文中**完整、未翻译的原始图片**。不要裁剪或修改原始图片。
- `extract_pdf.py` 会自动检测并渲染 Marker 遗漏的矢量图（通过 `_add_missing_vector_figures()`），确保 `extracted.md` 中包含所有图片引用。翻译时保留这些引用即可。

如果有标题（caption），翻译标题：

```
![Figure 1]({PDF文件名}_images/fig1.png)

> Figure 1: Architecture of the proposed system.
>
> 图 1：所提出系统的架构。
```

**文字密集型图片**：仅当图片中包含**大量英文文字**（如段落描述、长标签、表格等）时，才在原始图片下方添加翻译版本。简单标签（坐标轴名称、变量名等）无需翻译。

如果 `ocr_report.json` 中显示该图片是文字密集型的，在图片下方添加 OCR 文字翻译：

```
![Figure 2]({PDF文件名}_images/fig2.png)

> **[图片文字]**: The processing pipeline consists of three stages...
>
> **[图片文字翻译]**: 处理管线由三个阶段组成...
```

#### 跳过的内容

以下内容不翻译，直接丢弃：
- 独立的页码（如孤立的 "3" 或 "Page 5"）
- 页眉页脚（版权声明、"Confidential" 等）
- 文档元数据行

### Step 4: 写入输出

- 输出文件路径：与输入 PDF 同目录，命名为 `{PDF文件名}_zh.md`
- 使用 Write 工具创建输出文件
- 如果文档很长需要分块处理，第一块用 Write 创建文件，后续块用 StrReplace 在文件末尾追加（用文件最后几行作为 old_string，追加新内容作为 new_string）
- 完成后向用户报告输出文件路径

### Step 5: 搬迁图片并清理中间文件

翻译完成后，按以下顺序操作：

1. **搬迁图片**：将 `{PDF文件名}_extracted/images/` 目录移动（`mv`）为与 `_zh.md` 同级的 `{PDF文件名}_images/`
   ```bash
   mv "{PDF文件名}_extracted/images" "{PDF所在目录}/{PDF文件名}_images"
   ```
2. **修正图片引用**：将 `_zh.md` 中所有图片引用路径从 `![](filename)` 更新为 `![]({PDF文件名}_images/filename)`
   ```bash
   sed -i 's|!\[\(.*\)\](\([^/)]*\.\(jpeg\|jpg\|png\|gif\|webp\)\))|![\1]({PDF文件名}_images/\2)|g' "{输出文件}"
   ```
   或使用 StrReplace 工具逐个替换。
3. **删除剩余中间文件**：删除 `{PDF文件名}_extracted/` 目录（此时只剩 `extracted.md`、`ocr_report.json` 等非图片文件）
   ```bash
   rm -rf "{PDF文件名}_extracted/"
   ```

最终保留的文件：
- `{PDF文件名}_zh.md`（翻译结果）
- `{PDF文件名}_images/`（图片目录，被 markdown 引用）

## 翻译规则

- 技术术语、缩写、专有名词保留英文原文，或使用公认的中文翻译（如 "attention mechanism" → "注意力机制"）
- 首次出现的重要术语可以用括号标注英文：注意力机制（Attention Mechanism）
- 保留 Markdown 格式（粗体、斜体、链接、代码块）不变
- 保留 LaTeX 数学公式不变
- 不翻译代码片段
- 翻译要自然流畅，符合中文技术文档的阅读习惯
- 不要逐字直译，要意译

## 分块策略（大文档）

如果 extracted.md 超过 500 行：

1. 按一级或二级标题（`#` 或 `##`）切分章节
2. 每次读取和处理一个章节（约 100-300 行）
3. 翻译该章节后追加到输出文件
4. 处理下一个章节，直到全部完成
5. 每处理完一个章节，向用户简要报告进度

如果单个章节超过 300 行，可以进一步按段落分批处理。

## 示例用法

用户说："翻译这个 PDF ~/papers/attention.pdf"

1. 运行：`python3 ~/.cursor/skills/translate-pdf/extract_pdf.py ~/papers/attention.pdf`
2. 读取 `~/papers/attention_extracted/extracted.md`（中间文件在子目录）
3. 逐段翻译，写入 `~/papers/attention_zh.md`（与 PDF 同目录）
4. 搬迁图片：`mv ~/papers/attention_extracted/images ~/papers/attention_images`
5. 修正 `attention_zh.md` 中的图片路径：`![](xxx.png)` → `![](attention_images/xxx.png)`
6. 删除中间目录：`rm -rf ~/papers/attention_extracted/`
7. 告诉用户：翻译完成，输出文件在 `~/papers/attention_zh.md`

### 实际案例：CuTe Layout 论文

输入 PDF：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra.pdf`（NVIDIA 的 CuTe 布局代数论文，33 页）

产出文件：
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（2299 行双语 Markdown）
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_images/`（9 张 PNG 图片）

该论文包含大量 LaTeX 数学公式和技术图表，翻译时公式原样保留（遵守 GitHub 兼容规则：`\lvert`/`\rvert`、`^{\ast}` 等），图表配中文标题说明。
