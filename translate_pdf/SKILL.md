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

### Step 1.5: 公式质量优化

Marker 从 PDF 提取公式时存在局限性：复杂的多行 LaTeX 环境可能截断或丢失内容，符号识别也可能出错。此步骤采用三级策略，在翻译前确保公式的完整性和准确性。

#### 第一级：arXiv LaTeX 源码（权威来源，优先使用）

检查 PDF 文件名是否包含 arXiv 编号（匹配正则 `\d{4}\.\d{4,5}(v\d+)?`），如果是：

1. 从文件名提取 arXiv ID（如 `2603.02298v1`），下载并解压源码包：
   ```bash
   wget -q "https://arxiv.org/e-print/{arXiv_ID}" -O "{输出目录}/arxiv_src.tar.gz"
   mkdir -p "{输出目录}/arxiv_src"
   tar xzf "{输出目录}/arxiv_src.tar.gz" -C "{输出目录}/arxiv_src/" 2>/dev/null \
     || cp "{输出目录}/arxiv_src.tar.gz" "{输出目录}/arxiv_src/main.tex"
   ```
2. 读取 `.tex` 文件（如有多个，选包含 `\begin{document}` 的主文件）
3. **预处理 .tex 源码**——扫描 preamble 中的 `\newcommand`/`\def` 宏定义，构建宏映射表。后续提取公式时需将自定义宏展开为标准 LaTeX（如 `\v{A}` → `\mathbf{A}`），否则 Markdown 无法渲染
4. **全面比对并替换公式**——将 `.tex` 中的公式与 `extracted.md` 中 Marker 提取的公式逐一比对（利用公式前后段落文本作为上下文定位）：
   - **空/截断公式**：`\begin{array}{ccc...` 无 `\end`、`$$` 内无实际内容等——直接用 `.tex` 原始公式替换
   - **可疑公式**：Marker 提取结果与 `.tex` 原始公式差异较大（如符号缺失、结构错乱）——用 `.tex` 版本替换
   - **正常公式**：Marker 提取结果与 `.tex` 一致或仅有细微格式差异——保留 Marker 版本（已适配 Markdown）
5. **适配 Markdown**——从 `.tex` 提取的公式需要做以下清理后再写入 `extracted.md`：
   - 去除 `\textcolor{...}{内容}` → 保留`内容`
   - 去除 `\label{...}`
   - 展开自定义宏（按步骤 3 的宏映射表）
   - `\begin{equation}...\end{equation}` → `$$...$$`
   - `\begin{align}...\end{align}` → 拆分为多个 `$$...$$` 或保留为 `\begin{aligned}`
   - 应用数学公式的 GitHub 兼容规则（`\lvert`/`\rvert`、`^{\ast}` 等，见 Step 3 的数学公式规则）
6. 清理源码文件：
   ```bash
   rm -rf "{输出目录}/arxiv_src" "{输出目录}/arxiv_src.tar.gz"
   ```

#### 第二级：Marker 提取结果（默认）

当第一级不可用时（非 arXiv 论文、下载失败），使用 `extract_pdf.py` Marker 提取的公式。此时扫描 `extracted.md` 检测空/截断公式：
- `$$\begin{array}{...$$` 或 `$$\begin{aligned}...$$`：`\begin` 后无对应 `\end`，直接以 `$$` 结尾
- `$$` 块内只有环境声明和列说明符（如连续的 `c`、`l`、`r`），无实际数学内容

没有检测到问题则跳过。检测到问题的公式进入第三级。

#### 第三级：PDF 截图（兜底）

对经过第一级或第二级后仍未解决的空/截断公式：

1. 根据空公式在 `extracted.md` 中的位置（附近的 `<span id="page-N">` 标记）确定其所在 PDF 页码
2. 用 PyMuPDF 打开 PDF，在该页面上定位公式区域（利用前后文本块的位置夹逼）
3. 渲染该区域为 PNG 图片：
   ```python
   import fitz
   doc = fitz.open("<PDF路径>")
   page = doc[page_idx]
   pix = page.get_pixmap(dpi=200, clip=formula_rect)
   pix.save("{输出目录}/images/formula_p{page}_n{idx}.png")
   ```
4. 将 `extracted.md` 中的空公式块替换为图片引用：`![](formula_p{page}_n{idx}.png)`

#### 报告

向用户报告公式优化结果：使用了哪一级策略、校准/替换了多少处公式、是否有未能修复的公式。

### Step 2: 读取提取内容

1. 读取 `{输出目录}/extracted.md`
2. 如果存在 `{输出目录}/ocr_report.json`，也读取它（包含文字密集图片的 OCR 文本）
3. 评估文档大小：如果超过 500 行，按章节分块处理（见下方"分块策略"）

### Step 2.5: 论文背景分析与术语表

翻译前先读取 extracted.md 全文（或至少读取标题、摘要、引言、目录），完成以下两项工作：

#### A. 自动总结论文背景

生成一段 3-5 句话的背景摘要，涵盖：
- **所属领域**：如"GPU 编程 + 抽象代数"、"计算机视觉 + 自监督学习"
- **核心研究对象**：如"张量布局的数学表示与运算体系"
- **目标读者画像**：如"CUDA 内核开发者、高性能计算研究者"
- **关键上下文**：论文依赖的前置知识、所属项目/库（如 CUTLASS、Triton）

示例输出：

> **论文背景**：本文是 NVIDIA 关于 CuTe（CUDA Tensors）的数学规范论文，属于 GPU 编程与抽象代数的交叉领域。核心研究对象是张量布局（layout）的层次化表示及其上的代数运算（复合、补、求逆等）。目标读者为 CUDA 内核开发者和高性能线性代数库（如 CUTLASS）的使用者。论文大量使用集合论、函数映射的数学语言来描述 GPU 硬件的数据排布。

将背景摘要向用户展示，并询问：
- 背景是否准确？
- 是否有需要补充或修正的信息？（如特定术语偏好、领域惯例等）

如果用户提供了补充，将其合并到背景摘要中。如果用户确认无误或无额外补充，继续下一步。

#### B. 构建术语表

在背景摘要的基础上，扫描全文提取高频技术术语（出现 2 次以上的英文专业词汇），建立术语对照表。背景信息用于术语消歧——同一英文词在不同领域有不同译法时，以论文实际领域为准。

格式示例：

```
| English | 中文 |
|---------|------|
| layout | 布局 |
| stride | 步长 |
| coalesce | 合并 |
| integral coordinate | 整数坐标 |
| thread-value partitioning | 线程–值划分 |
```

规则：
- 术语表控制在 20-50 条，只收专业术语，不收常见词
- 同一概念只用一种中文译法，全文保持一致
- 后续每个分块翻译时，将**背景摘要 + 术语表**作为上下文附带，确保翻译一致

### Step 3: 翻译并生成双语文档

逐段处理 extracted.md 的内容，生成双语 Markdown。翻译每个分块时，始终附带 Step 2.5 的**背景摘要 + 术语表**作为参考。

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

### Step 6: 审校

翻译和图片处理完成后，对 `_zh.md` 进行一轮自审校。逐章节重新读取译文，检查以下问题：

1. **漏翻**：中文句子中是否夹杂未翻译的英文普通词汇（专有名词除外）
2. **术语一致性**：核对 Step 2.5 的背景摘要和术语表，同一术语全文是否用了同一译法
3. **信息完整性**：中文段落是否完整传达了对应英文段落的所有信息，有无省略或压缩
4. **图片完整性**：所有原文图片引用是否都保留在译文中，路径是否正确指向 `{PDF文件名}_images/`
5. **公式渲染**：LaTeX 公式是否遵守 GitHub 兼容规则（`\lvert`/`\rvert`、`^{\ast}` 等）
6. **公式质量验证**：Step 1.5 优化的公式是否正确——来自 `.tex` 源码的公式宏是否已展开、语法是否完整可渲染；Marker 提取的公式是否有遗漏的符号；截图替代的图片是否清晰、区域是否准确

发现问题后用 StrReplace 直接修正。审校完成后向用户报告修正数量和类型。

## 翻译规则

### 基本规则

- 技术术语、缩写、专有名词保留英文原文，或使用公认的中文翻译（如 "attention mechanism" → "注意力机制"）
- 首次出现的重要术语可以用括号标注英文：注意力机制（Attention Mechanism）
- 同一术语全文必须使用同一种中文译法，参照 Step 2.5 的术语表
- 保留 Markdown 格式（粗体、斜体、链接、代码块）不变
- 保留 LaTeX 数学公式不变
- 不翻译代码片段
- 翻译要自然流畅，符合中文技术文档的阅读习惯
- 不要逐字直译，要意译

### 禁止事项

- **禁止漏翻**：中文句子中不得夹杂未翻译的英文普通词汇。专有名词（如 CUTE、CUTLASS、Triton）和术语表中约定保留英文的除外。错误示例：~~"张量布局也随之更加 intricate"~~，应译为"张量布局也随之更加复杂"
- **禁止过度压缩**：中文翻译必须完整传达原文信息，不得省略句子或细节。翻译后的中文段落信息量应与原文匹配。如原文有 3 句话，中文不应压缩为 1 句
- **禁止术语不一致**：同一英文术语在全文中必须对应同一中文翻译，不得在不同章节使用不同译法

### 易错术语提示

以下术语容易误译，翻译时注意：

| 英文 | 正确翻译 | 常见误译 |
|------|----------|----------|
| integral coordinate | 整数坐标 | ~~积分坐标~~ |
| complement | 补（布局代数语境） | ~~补充、互补~~ |
| coarsen / refine | 粗化 / 细化 | ~~粗糙化 / 精炼~~ |
| compose / composition | 复合 | ~~组合、组成~~ |
| stride | 步长 | ~~跨度~~ |
| rank (of a tuple) | 秩 | ~~排名~~ |

## 分块策略（大文档）

如果 extracted.md 超过 500 行：

1. 按一级或二级标题（`#` 或 `##`）切分章节
2. 每次读取和处理一个章节（约 100-300 行）
3. **重叠上下文**：翻译每个分块时，除本块内容外还需附带以下上下文：
   - Step 2.5 的**背景摘要 + 术语表**（保持领域理解和术语一致）
   - 前一块**末尾 20-30 行**的原文和译文（保持行文连贯）
   - 上下文仅供参考，不要重复输出到译文中
4. 翻译该章节后追加到输出文件
5. 处理下一个章节，直到全部完成
6. 每处理完一个章节，向用户简要报告进度

如果单个章节超过 300 行，可以进一步按段落分批处理，同样遵守重叠上下文规则。

## 示例用法

用户说："翻译这个 PDF ~/papers/attention.pdf"

1. 运行：`python3 ~/.cursor/skills/translate-pdf/extract_pdf.py ~/papers/attention.pdf`
2. 公式质量优化（三级策略）：arXiv 论文优先下载 `.tex` 源码全面校准公式；非 arXiv 论文使用 Marker 提取结果并检测空公式；无法修复的用 PDF 截图兜底
3. 读取 `~/papers/attention_extracted/extracted.md`（中间文件在子目录）
4. 自动总结论文背景（领域、研究对象、目标读者），向用户确认；构建术语表（20-50 条）
5. 逐段翻译，写入 `~/papers/attention_zh.md`（与 PDF 同目录），每块附带背景摘要、术语表和前一块末尾上下文
6. 搬迁图片：`mv ~/papers/attention_extracted/images ~/papers/attention_images`
7. 修正 `attention_zh.md` 中的图片路径：`![](xxx.png)` → `![](attention_images/xxx.png)`
8. 删除中间目录：`rm -rf ~/papers/attention_extracted/`
9. 审校：逐章节检查漏翻、术语一致性、信息完整性、公式质量验证，修正问题
10. 告诉用户：翻译完成，输出文件在 `~/papers/attention_zh.md`

### 实际案例：CuTe Layout 论文

输入 PDF：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra.pdf`（NVIDIA 的 CuTe 布局代数论文，33 页）

产出文件：
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（2299 行双语 Markdown）
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_images/`（9 张 PNG 图片）

该论文包含大量 LaTeX 数学公式和技术图表，翻译时公式原样保留（遵守 GitHub 兼容规则：`\lvert`/`\rvert`、`^{\ast}` 等），图表配中文标题说明。
