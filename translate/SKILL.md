---
name: translate
description: >-
  Translate English technical documents from local PDFs, online papers
  (including arXiv), and blog posts into bilingual English-Chinese Markdown
  with paragraph-by-paragraph comparison. Use when the user wants a Chinese
  translation or bilingual edition of a PDF, paper URL, arXiv ID, or blog post.
---

# 技术文档双语翻译

将英文技术文档翻译为逐段中英对照 Markdown，来源包括本地 PDF、网络论文和博客。arXiv 是当前已知的常见论文来源；其他站点的专用获取方式在实际使用时再补充。

## 前置条件

仅 PDF 提取分支需要以下依赖；获取 HTML 正文时不要求安装 PDF/OCR 工具。

Python 环境需要安装：

```bash
pip install -r ~/.cursor/skills/translate/requirements.txt
```

系统需要 Tesseract（OCR 功能）：`sudo apt-get install tesseract-ocr`

## 工作流程

先识别来源并取得完整正文，再执行适用的翻译、分块和审校步骤。PDF 专用步骤不适用于已取得完整 HTML 正文的来源。

### Step 0: 识别来源并统一输入输出

- **本地 PDF**：使用用户提供的文件，进入 Step 1。
- **网络论文**：从用户给出的论文链接获取全文；arXiv 链接或编号按 [arXiv 来源说明](references/arxiv.md) 处理。其他来源先使用可访问的完整 HTML 正文或下载 PDF，不预设站点专用规则。
- **博客**：提取文章正文，保留标题层级、段落、列表、表格、代码、公式、插图、图注和正文链接，排除导航、广告、推荐列表和评论。只有作者提供 PDF 或 HTML 无法完整获取时才考虑 PDF 分支。
- 全文不可访问或只能读到摘要/节选时，说明缺失范围；需要用户补充全文才能完整翻译，不把摘要或搜索片段当作全文。

统一约定：

- `{文档名}`：本地 PDF 的文件名（不含扩展名）；网络来源使用稳定、适合文件系统的标题或论文编号，arXiv 应包含实际使用的版本号。
- `{交付目录}`：用户指定的目录优先；未指定时，本地 PDF 使用原 PDF 所在目录，网络来源使用当前工作区的 `inout/{文档名}/`。
- `{输出目录}`：中间工作目录，默认 `{交付目录}/{文档名}_extracted/`；不要与最终交付目录混用。
- 最终译文统一为 `{交付目录}/{文档名}_zh.md`，正文图片（如有）为同级的 `{文档名}_images/`。
- 在最终译文开头保留来源说明：原始路径或 URL，以及可获取的标题、作者、发布日期；网络来源另记录访问日期，arXiv 记录实际论文编号和版本。此说明不受后文“丢弃文档元数据行”的规则影响。
- 临时分块草稿统一放在当前工作区的 `.cursor/tmp/translate/`，使用前先创建该目录。

**完整 HTML 正文分支**：将正文整理到 `{输出目录}/extracted.md`，下载正文图片到 `{输出目录}/images/` 并改为本地引用；将正文中的相对链接解析为来源页面对应的绝对 URL，保留内部锚点。无法下载的图片保留原始绝对 URL 并在交付时说明，不声称已完整离线保存。保留可用的原始 LaTeX 公式，避免只留下渲染后的空标签或占位符。原始正文快照及来源信息在审校完成前保留，以供完整性核对。无需生成 `ocr_report.json`。

整理后进入 Step 2，复用背景分析、术语表、逐段翻译、断点恢复和审校。无需把网页先转为 PDF，也不运行 Marker 或 PDF 专用标题规整脚本。网页图片保持原格式；PDF 分支的 PNG 无损约定不强加到网页资源。

### Step 1: 提取 PDF（仅 PDF 来源）

用 Shell 工具运行提取脚本：

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/extract_pdf.py "<PDF路径>" "<输出目录>"
```

- 如果用户没有指定输出目录，脚本默认在 PDF 所在目录下创建 `{文档名}_extracted/` 子目录存放中间文件
- 脚本会输出一个 JSON 摘要到 stdout，包含 `markdown_file`、`markdown_lines`、`total_images`、`text_heavy_images` 等信息（缓存命中时 `status: "cached"`）
- **幂等**：若 `extracted.md` 已存在且 mtime 不早于 PDF，脚本直接返回缓存摘要并跳过整个抽取（数百秒 → 不到 1 秒）。强制重抽用 `--force`
- 所有图片统一保存为 PNG 无损格式（避免 JPEG 压缩损失）
- 当 PyMuPDF 能提取到比 Marker 更高分辨率的原始嵌入图片时，会自动替换并更新 Markdown 引用
- **自动重建被 Marker 破坏的表格**：Marker 处理含 `<br>` 换行的表格单元时，常把表头切到多行并夹杂 `>` 块引用前缀，导致 Markdown 解析为 wall-of-text。`extract_pdf.py` 在写入 `extracted.md` 前调用 `_reconstruct_broken_tables()`：扫描每个 `|---|---|...` 分隔行，反向吸收破损的表头碎片（带 `<br`、`>` 前缀、列数不全的行），正向收集 body 行直到下一个分隔行（= 下一个表的边界），输出列数对齐的干净表格
- 向用户报告提取结果摘要

### Step 1.5: 公式质量优化（PDF 提取后）

Marker 从 PDF 提取公式时存在局限性：复杂的多行 LaTeX 环境可能截断或丢失内容，符号识别也可能出错。此步骤采用三级策略，在翻译前确保公式的完整性和准确性。

#### 第一级：arXiv LaTeX 源码（权威来源，优先使用）

优先使用 Step 0 已确认的 arXiv 编号与版本；本地 PDF 尚未识别来源时，再检查文件名（现代编号可匹配 `\d{4}\.\d{4,5}(v\d+)?`）或论文首页元信息。按 [arXiv 来源说明](references/arxiv.md) 确认身份与版本，不仅依赖文件名。源码可用时：

1. 使用已确认的 arXiv 编号和版本获取源码，按 [arXiv 来源说明](references/arxiv.md) 检查实际文件格式并展开到 `{输出目录}/arxiv_src/`。不要将归档解包失败直接当作单个 TeX 文件。
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
6. 保留源码直到 Step 6 完成公式审校，再随本次任务的中间文件一并清理。

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

### Step 2.5: 文档背景分析与术语表

翻译前先读取 extracted.md 全文（或至少读取标题、摘要、引言、目录），完成以下两项工作：

#### A. 自动总结文档背景

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

在背景摘要的基础上，扫描全文提取高频技术术语（出现 2 次以上的英文专业词汇），建立术语对照表。背景信息用于术语消歧——同一英文词在不同领域有不同译法时，以文档实际领域为准。

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

**大文档（≥ 1500 行）必须持久化**：将背景摘要写入 `_chunks/_context.md`、术语表写入 `_chunks/_glossary.md`，或用：

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-glossary "{输出目录}" .cursor/tmp/translate/glossary.md
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-context  "{输出目录}" .cursor/tmp/translate/context.md
```

这样下一轮 agent 进来（无论是否同一会话）都能直接读这两个文件锁住风格，无须从头分析。

### Step 3: 翻译并生成双语文档

逐段处理 extracted.md 的内容，生成双语 Markdown。翻译每个分块时，始终附带 Step 2.5 的**背景摘要 + 术语表**作为参考。

**最终的双语文档写入 Step 0 确定的 `{交付目录}/{文档名}_zh.md`**。本地 PDF 默认与输入文件同目录，例如输入 `~/papers/attention.pdf`，输出到 `~/papers/attention_zh.md`；网络来源不要求存在本地 PDF。

对每种内容类型的处理规则：

#### 标题

按最终页面的可用宽度选择布局，不强制英中文同行。短标题在一行内能清晰容纳时，可以使用斜杠连接：

```markdown
## Introduction / 引言
### Related Work / 相关工作
```

较长的文档标题、章节标题优先分为英文在上、中文在下的两个语言块，避免混排后由渲染器任意折行。Markdown 中仍使用**同一个标题节点**，用 `<br><br>` 留出段落间隔：

```markdown
## Roofline-Driven Optimization of ROCm Libraries <br><br> 基于 Roofline 模型的 ROCm 库优化
```

- 不要把英中文分别写成两个 `##` 标题，否则目录和 PDF 书签会出现两个章节。
- 不要只在 Markdown 源码中插入普通换行；渲染时可能被合并为空格。长标题允许各语言块内部自然折行，但两个语言块之间必须明确分开。
- **目录分行但不留空行**：长条目的英中文上下展示，共用一个目录项、同一缩进层级与跳转目标；短条目可以同行。目录内部使用正常行距，不复制正文标题的段间留白。`md-to-pdf` 会将标题中的连续 `<br>` 合并为目录里的单个 `<br>`；手写目录也在同一列表项内用单个 `<br>` 分隔。
- 渲染后抽查正文标题和目录，确认目录英中文之间没有空白行，间距与条目内自然折行一致；如同行版本发生混乱折行，改为分块布局后重新渲染，不缩小字体或删减标题来硬塞一行。

#### 段落

英文原文放在引用块中，中文翻译在下方，两者之间空一行：

```
> We propose a novel framework for neural machine translation that leverages
> cross-lingual representations to improve translation quality.

我们提出了一种新的神经机器翻译框架，利用跨语言表示来提高翻译质量。
```

#### 表格

保留原始英文表格。是否提供整张翻译版本由表格类型决定：

**A. 文字密集型表格（描述、解释、长句单元格）**：在下方添加 `**[翻译]**` 块，整张翻译。

```
| Method | Accuracy | Description |
|--------|----------|-------------|
| Ours   | 95.2%    | Uses attention |

**[翻译]**

| 方法 | 准确率 | 描述 |
|------|--------|------|
| 我们的 | 95.2% | 使用注意力机制 |
```

**B. 数字 / 短标签 / 多列对照型表格（如硬件特性矩阵、规格对比）**：**只翻译表头，不复制整张表**。原因：4 列以上的英文 `Yes`/`No`/数字常量在中文里展开为"是的"/"没有"会破坏对齐，且无信息增益。

```
| Feature             | GFX12 | MI430/MI450 | GFX13.0 Canis | GFX13.1 Arcadia |
|---------------------|-------|-------------|---------------|-----------------|
| Virtual Address Size| 48    | 48 / 57     | 57 / 48       | 48 / 57         |
| V_MUL_U64           | No    | Yes / Slow  | No            | Yes             |

**[表头翻译]**：功能 | GFX12 | MI430/MI450 | GFX13.0 Canis | GFX13.1 Arcadia
```

**通用强制约束**（无论 A 还是 B）：

1. **列数不变**：翻译表的 `|` 数量必须与原表头完全一致；分隔符行（`|---|---|...`）的列数也要对齐
2. **保留单元格内分隔符**：`/`、`,`、`+`、`-` 在数字串中（如 `48 / 57`、`16, 32`、`bs=1`）必须**原样保留**，不能替换为空格或拆到下一格
3. **代号、数字、缩写不译**：单元格里的 `Yes`/`No` 在 B 类表里不译，A 类表里译为"是"/"否"（不是"是的"/"没有"）；产品代号（Canis、AT2、Magnus、Arcadia 等）一律保留英文（详见下方"产品代号保留"规则）
4. **翻译完表格自检**：写完 `**[翻译]**` 块后，数一次原表头的 `|` 数和翻译表头的 `|` 数。如不一致，先修正再继续

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

PDF 分支的 `extract_pdf.py` 会自动为代码块添加语言标签（如 ` ```python `、` ```cpp `）；HTML 分支保留原有标签，可明确识别语言时补充。翻译时：

- **保留语言标签**不变，确保渲染时有语法高亮
- **不翻译代码内容**，代码块原样保留
- 如果代码块前后有解释性文字，翻译文字部分即可

#### 图片

图片引用路径需要指向 `{文档名}_images/` 子目录（见 Step 5 的图片搬迁步骤）。翻译时先保留原始引用路径不变，Step 5 中统一修正。

**重要原则**：
- 翻译文档必须包含原始文档正文中的**所有图片**，不得遗漏任何一张。
- 图片必须是文档中**完整、未翻译的原始图片**。不要裁剪或修改原始图片。
- `extract_pdf.py` 会自动检测并渲染 Marker 遗漏的矢量图（通过 `_add_missing_vector_figures()`），确保 `extracted.md` 中包含所有图片引用。翻译时保留这些引用即可。

如果有标题（caption），同时翻译图号和标题文字。较长图注使用两个独立段落，英文在上、中文在下，中间空一行；表格标题、子图标题和图片文字翻译也遵循相同原则。短标题可在能清晰容纳一行时同行展示。

```markdown
![]({文档名}_images/fig1.png)

> Figure 1: Architecture of the proposed system.

图 1：所提出系统的架构。
```

两段保留同一图表编号，并紧邻对应图片或表格；分页时尽量保持图片/表格与双语标题在一起。不要把整段英中文图注用斜杠拼成长段，也不要在图片 alt 中重复完整图注，避免导出时出现第二份标题。

**文字密集型图片**：仅当图片中包含**大量英文文字**（如段落描述、长标签、表格等）时，才在原始图片下方添加翻译版本。简单标签（坐标轴名称、变量名等）无需翻译。

如果 `ocr_report.json` 中显示该图片是文字密集型的，在图片下方添加 OCR 文字翻译：

```
![Figure 2]({文档名}_images/fig2.png)

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

最终输出文件路径：`{交付目录}/{文档名}_zh.md`（见 Step 0）。使用 `chunkctl.py assemble` 时，如果工作目录不在交付目录下，必须用 `--out` 显式指定最终路径。

**Write 工具实操约束**：
- 单次 Write 内容**≤ 8 KB**（约 200 行 Markdown）。超过则拆为多个文件后用 `cat` 拼接。
- 每次 Write 完调用一次 `wc -l` 确认行数符合预期，提早发现"empty Write"等异常。
- 大块内容若 Write 失败，fallback 用 shell heredoc：
  ```bash
  cat > .cursor/tmp/translate/chunk.md <<'EOF'
  …内容…
  EOF
  ```

**写入策略二选一**：

#### A. 小文档（< 1500 行 extracted.md）：直接追加

第一块用 Write 创建文件，后续块用 StrReplace 在文件末尾追加（用文件最后几行作为 old_string，追加新内容作为 new_string）。完成后报告输出路径。

#### B. 大文档（≥ 1500 行 extracted.md）：**断点恢复机制（强烈推荐）**

详见 [大文档断点恢复](#大文档断点恢复) 一节。核心：每个 chunk 一个独立文件，用 `_state.json` 跟踪进度，全部完成后 `chunkctl assemble` 一次性拼出 `_zh.md`。中断后重启可精确续翻，不重做。

### Step 5: 搬迁图片并清理中间文件

翻译完成后（大文档先用 `chunkctl.py assemble` 拼出 `_zh.md`），按以下顺序操作：

1. **搬迁图片**：存在 `{输出目录}/images/` 时，将其移动（`mv`）为与 `_zh.md` 同级的 `{文档名}_images/`；无图片时跳过。若目标目录已存在，先核对并合并资源，避免直接 `mv` 造成目录嵌套或覆盖。
   ```bash
   mv "{输出目录}/images" "{交付目录}/{文档名}_images"
   ```
2. **修正图片引用**：将 `_zh.md` 中本次已搬迁的本地图片引用路径从 `![](filename)` 更新为 `![]({文档名}_images/filename)`
   ```bash
   sed -i 's|!\[\(.*\)\](\([^/)]*\.\(jpeg\|jpg\|png\|gif\|webp\)\))|![\1]({文档名}_images/\2)|g' "{输出文件}"
   ```
   或使用 StrReplace 工具逐个替换。此正则只覆盖无目录前缀的常见位图路径；HTML 分支还需处理 `images/` 前缀、SVG、引用式图片和 HTML 图片标签，按实际引用更新，不改写未下载的远程图片 URL。
3. **清理剩余中间文件**：先完成 Step 6 审校并确认所有图片引用有效，再清理本次任务创建的 `{输出目录}/`；审校前保留原文和断点文件。网络来源下载的原文及来源说明按用户要求保留。
   ```bash
   rm -rf "{输出目录}/"
   ```

最终保留的文件：
- `{文档名}_zh.md`（翻译结果）
- `{文档名}_images/`（图片目录，被 markdown 引用）

### Step 6: 审校

翻译完成（含图片搬迁）后必须进行**自动 + 人工 + 迭代**三段式自审校，否则不要交付。

#### 6.1 自动结构性体检（强制，先行）

在做任何人工审阅前，先跑结构性验证脚本——它会捕获绝大多数会导致 PDF 渲染崩坏或对照错位的格式问题：

```bash
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/validate_md.py \
    "{交付目录}/{文档名}_zh.md" \
    "{交付目录}/{文档名}_images"
```

脚本输出 9 项 PASS/FAIL：代码栅栏平衡、表格列数对齐、图片引用存在、内部 anchor 链接解析、反引号平衡、`**` 平衡、`$` 转义（KaTeX 风险）、Table/Figure 标题双语、表格代码单元里的 `||`/`|=` 转义。任何 FAIL **都必须先修复**，再进入下一阶段。

常见命中与对策：

| 命中项 | 典型成因 | 修复 |
|---|---|---|
| `table_columns` | 单元格里有 `||` / `|=` 等逻辑 OR；或 PDF 提取时单元格被截行 | `dst |= src` → `dst \|= src`；多行单元改用 `<br>` |
| `dollar_katex` | 缓存名 `WGP$`、`K$`、`L1$`、`SE$` 未转义 | 全部改为 `WGP\$`/`K\$` 或反引号包裹 |
| `anchors` | PDF 内部页锚（如 `#page-79-1`）随章节移动而失效 | 用 grep 定位最近的有效 `<span id="...">`，替换或新增 anchor |
| `pipe_ops_in_tables` | 同 `table_columns`，但被发现于代码字段内 | 同上 |
| `caption_bilingual` | 图表编号或标题遗漏翻译 | 在英文图表标题之后紧接同编号的中文标题段落；短标题也可同行 |

**不要在没跑通脚本前手工逐章扫描**——会浪费时间在脚本能秒检的问题上。

#### 6.2 内容人工审校（按章节）

脚本通过后，逐章节重新读取译文，检查以下问题：

1. **漏翻**：中文句子中是否夹杂未翻译的英文普通词汇（专有名词除外）
2. **术语一致性**：核对 Step 2.5 的背景摘要和术语表，同一术语全文是否用了同一译法
3. **信息完整性**：中文段落是否完整传达了对应英文段落的所有信息，有无省略或压缩
4. **伪代码注释逻辑核对**：翻译伪代码中的英文注释时，**必须同时核对代码逻辑**——只译字面会出错。例如 `if (!inWG) { /* not in workgroup */ }` 不能译为「工作组：…」，应译为「**不在工作组内**」。代码里的真值条件优先于英文注释的字面表述
5. **表格行序与字段值对照**：PDF 提取时 2 列对照表常变成列优先（column-major）排列，导致 row 错位（如 opcode 245 的描述跑到 opcode 248 的格子里）。**任何"opcode/code 数列 + 描述"的表都要逐行核查"序号 ↔ 内容"是否一致**；类似地，bit 范围 `[127:96]` 行里出现 `[79:64]` 这种字段也是复制错误，需要修
6. **截断表 / 残缺行**：Marker 偶尔输出只有 1 行的 "table"——往往是上一表的续表被切断，需要回查 PDF 补齐
7. **重复图片插入**：Marker 把同一物理 PNG 多处引用，相邻 5 行内出现两次同名 `![](xxx.png)` 通常是冗余，删掉除第一处外的所有副本
8. **图片完整性**：所有原文图片引用是否都保留，路径是否正确指向 `{文档名}_images/`
9. **公式渲染**：LaTeX 公式是否遵守 GitHub 兼容规则（`\lvert`/`\rvert`、`^{\ast}` 等）
10. **公式质量验证**：Step 1.5 优化的公式是否正确——来自 `.tex` 源码的公式宏是否已展开、语法是否完整可渲染；Marker 提取的公式是否有遗漏的符号；截图替代的图片是否清晰、区域是否准确
11. **双语标题与目录排版**：长标题、长目录项及长图表标题是否按英文在上、中文在下分块；同一章节是否只占一个目录项和书签；是否存在混排折行、重复图注或图注脱离对应图片的问题

#### 6.3 大文档（≥ 10000 行 _zh.md）：并行 subagent 审校

单个 agent 顺序读 18K 行容易超时或丢上下文。改用并行 subagent 模式：

1. 按章节边界（`# `）切成 8–10 段，每段约 1500–2500 行
2. 用 Task 工具同一消息内**并行**派发若干 `subagent_type=generalPurpose`（或 `explore`，readonly）任务，每个 prompt 形如：

   ```
   审阅 <_zh.md> 第 L<start>–L<end> 行（共 X 行），按下面 6 个维度报告问题，每条注明行号：
   1) 漏翻：中文段中夹带未译英文普通词
   2) 术语不一致：相对术语表 _glossary.md 偏离
   3) 信息缺失：中文相对英文有遗漏 / 压缩
   4) 表格语法：列数失配、未转义的 ||、被截断的表
   5) 图片引用：dead 路径
   6) 格式异常：孤立 > 行、标题层级跳跃、重复图

   每条问题分类标注严重度 (CRITICAL / 轻微)，最后给一段总结。不要修复，只报告。
   ```

3. 各 subagent 返回结构化报告后，**主 agent 聚合所有结果**，按严重度排序后用 StrReplace / 脚本批量修复
4. 修复后**回到 6.1 重跑 validate_md.py**，确保结构性问题被引入的零修复也未引入新问题

#### 6.4 牧羊人法则迭代（直到收敛）

**PDF 提取分支在生成 PDF 前先规整标题层级**（多级技术规范尤其重要）：跑 `normalize_headings.py`（见上文「翻译时的格式陷阱 → #6 标题层级与目录（TOC）」），否则 Marker 打乱的层级会让 PDF 目录全错。

修复 → `validate_md.py` → 修复，循环直到：

- `validate_md.py` 9 项全 PASS
- 标题层级与原文一致；PDF 提取分支按需使用 `normalize_headings.py`，HTML 分支保留原文章节层级，不套用硬件规范的编号规则
- `md-to-pdf` 渲染 PDF 无 warning / error
- PDF 书签树层级正确嵌套（`fitz.open(...).get_toc()` 抽查：章 L1 / 节 L2 / 指令 L3）
- 人工抽查 5–10 章无新问题

每一轮的修复不应引入新 FAIL（"破壁修复"）。如果某次修复后某项从 PASS 变 FAIL，**回退该修改**重新设计。

最后向用户报告：自动检测命中 → 修复数 → 人工审校命中 → 修复数 → 最终通过的检查项数。

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

### 产品 / 架构代号保留

GPU、CPU、加速器规范类文档大量使用产品代号、架构代号、芯片代号。这类标识符**一律保留英文原文**，不译、不音译、不字面释义：

- **GPU 架构 / 系列代号**：RDNA、CDNA、GFX13、GFX13.0、GFX13.1、CDNA4、Navi、Vega、Arcturus、Aldebaran、Aqua Vanjaram
- **芯片 / 产品代号**：MI300、MI300X、MI350、MI355X、MI400、MI430、MI450、Canis、AT2、Magnus、Orion、Arcadia
- **NVIDIA 等竞品代号**：Hopper、Ada、Blackwell、Rubin、Ampere
- **指令集 / 微架构组件**：WGP、SIMD、SQC、TCP、SH、CU、XCD、SE、SA、SPI、SC（保留缩写，不展开译）

**错误示例**（来自实际错译）：
- `Canis` → ~~"犬"~~（字面译）→ 应保留 `Canis`
- `Magnus` → ~~"马格努斯"~~（音译）→ 应保留 `Magnus`
- `Arcadia` → ~~"阿卡迪亚"~~（音译）→ 应保留 `Arcadia`
- `AT2/Magnus` → ~~"AT2/马格努斯"~~ → 应保留 `AT2/Magnus`

**Step 2.5 术语表强制要求**：构建术语表时，先扫描全文找出所有"首字母大写但非常用英文词"的标识符，归入"保留原文"分类，与翻译型术语分开列出：

```
| 类型     | 原文          | 处理     |
|----------|---------------|----------|
| 代号     | Canis         | 保留原文 |
| 代号     | AT2           | 保留原文 |
| 代号     | Arcadia       | 保留原文 |
| 术语     | wavefront     | 波前     |
| 术语     | workgroup     | 工作组   |
```

### 禁止事项

- **禁止漏翻**：中文句子中不得夹杂未翻译的英文普通词汇。专有名词（如 CUTE、CUTLASS、Triton）和术语表中约定保留英文的除外。错误示例：~~"张量布局也随之更加 intricate"~~，应译为"张量布局也随之更加复杂"
- **禁止过度压缩**：中文翻译必须完整传达原文信息，不得省略句子或细节。翻译后的中文段落信息量应与原文匹配。如原文有 3 句话，中文不应压缩为 1 句
- **禁止术语不一致**：同一英文术语在全文中必须对应同一中文翻译，不得在不同章节使用不同译法
- **禁止代号字面译**：产品 / 架构 / 芯片代号一律保留英文原文，禁止字面翻译（`Canis` ≠ "犬"）或音译（`Magnus` ≠ "马格努斯"），详见上方"产品 / 架构代号保留"

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
| round-robin | 轮转 | ~~轮询~~（"轮询"对应 polling，是另一概念） |
| polling | 轮询 / 反复读 | — |
| context switching | 上下文切换 | 不要中英混排「context 切换」 |
| barrier ops | barrier 类（**所有**屏障）操作 | ~~只翻成具体某条 `S_BARRIER`~~（缩窄语义） |
| retry vs replay | retry = 重试；replay = **重放**（XNACK / faulting load 重新执行） | 二者全文必须明确区分；同一文档不能交替使用 |
| stall-on-fault | fault 下 stall（保留英文短语） | ~~故障停顿~~（语义流失） |
| Accrued Exception | 累积 / 已累计异常标志 | ~~精确异常~~（precise 是另一概念） |
| save-context / save context | 保存上下文 | 不要保留英文短语在中文段落里 |
| wait-idle | 等待 idle / 等待空闲 | ~~Wait-Idle~~ 留英文 |
| forward progress | 前进保证 | ~~前进进展~~ |
| co-issue / co-execute | 协同发射 / 协同执行 | ~~共发射~~（不准确） |

### 翻译时的格式陷阱（PDF 渲染相关）

以下规则与 KaTeX/Markdown/Weasyprint 的解析约定有关——违反将导致 PDF 渲染崩坏或文本被误判为公式/表格分隔。**必须在翻译过程中就注意，不要等到 PDF 渲染失败再修。**

#### 1. `$` 必须转义（缓存名是高发点）

KaTeX 把 `$...$` 视为行内公式定界符。文档里出现的 `WGP$`、`K$`、`L1$`、`SE$`、`Inst$` 这类**缓存简写**若不转义，KaTeX 会从一个 `$` 一路吃到下一个 `$` 之间的所有正文，把它整段当成公式渲染——视觉效果是大段文字突然变成歪斜的 mathit 字体。

**做法**：

- 在中文段落 / `>` 引用块 / 表格单元 / 标题里出现 `<NAME>$` 时，一律改为 `<NAME>\$`（如 `WGP\$`）
- 反引号包裹（如 `` `WGP$` ``）也安全，但中文段中读起来不自然，优先用 `\$`
- `validate_md.py` 的 `dollar_katex` 检查会捕获漏转义

#### 2. 表格单元里的 `||` / `|=` 必须转义

Markdown 表格用 `|` 分列。代码片段里的 `dst |= src`（位运算 OR 赋值）或 `a || b`（逻辑或）如果在表格单元中，**就算被反引号包裹**，部分渲染器仍按字面 `|` 切列——结果是该行变成多列，破坏整张表的列数约束。

**做法**：

- 表格单元内的代码片段中所有 `|` 字符（无论是否被反引号包裹）都改用 `\|`：
  - `` `dst |= src` `` → `` `dst \|= src` ``
  - `` `a || b` `` → `` `a \|\| b` ``
- 多行内容用 `<br>` 不要用真实换行（真实换行也会被表格解析终止）
- `validate_md.py` 的 `pipe_ops_in_tables` 与 `table_columns` 都会捕获

#### 3. 表格列数对齐（极常见 PDF 提取后遗症）

Marker 提取 PDF 大表时，偶尔会把：

- 多行表头切成两行（第二行混入 `<br` / `>` 等碎片）
- 把"续表"切到下一页时只保留 1 行 body（残缺表）
- 把列优先（column-major）的 opcode 表打乱行序

`validate_md.py` 的 `table_columns` 会捕获列数失配。但**残缺表**与**乱序表**需要人工核对 PDF 后修复（后者尤其常见于 2 列 opcode 编号 + 名字的表，序号会混杂）。

#### 4. 图表标题双语化与分段

图表标题的编号和文字都要翻译。长标题分成相邻的英中文两个段落，不能用斜杠强制拼接；两段保留相同编号，罗马数字编号同样保留。短标题在最终页面能清晰容纳一行时，可使用同行布局。

```markdown
Table 90. Summary of Microcode Formats

表 90：微码格式概览

> Figure 2. Shared Memory Hierarchy

图 2：共享内存层级
```

`validate_md.py` 的 `caption_bilingual` 接受同行双语标题，或紧接英文标题的同编号中文段落；不能用远处正文里的中文提及充当标题翻译。

#### 5. 内部 anchor 链接必须解析

`extracted.md` 里的 `[xxx](#page-79-1)` 是 PDF 提取的页锚——翻译过程中删除/合并章节后这些锚点可能失效。`validate_md.py` 的 `anchors` 会列出 dangling 链接；修复时用 `grep -nP '<span id="[^"]+">'` 找到最近的有效 anchor 替换。

#### 6. 标题层级与目录（TOC）——生成 PDF 前必修

**症状**：`md-to-pdf` 生成的 PDF 目录层级全错/扁平（章、节、指令挤在同一级，或指令跑到 H1）。

**根因**：Marker 提取时**不按章节号给标题分级**，而是凭视觉字号乱标。典型表现（以 AMD SP3 指令集为例，1430 页）：

1. 章（`N ...`）和节（`N.M ...`）**全被标成 `#`(H1)**，opcode（`N.M.K ...`）被标成 `####`(H4)——层级完全扁平
2. 个别**章号丢失**（如 `Encoding ENC_SOP1` 没编号，本应是第 9 章）
3. 整段指令签名被**并进标题行**：`# **2.5.13 DS_APPEND ds_append vgpr...**`
4. 无编号 opcode 标题把签名当标题：`#### flat_load_dword v_dst 32 , v_addr 64 FLAT`
5. Marker 误判碎片当标题：`Examples:`、`mul:{1,2,4}`、`0.5ULP accuracy...`（`0.5ULP` 还会被误解析成「第 0 章」顶进 H1）
6. 提取出的旧「Contents/目录」块**页码是原始 PDF 的**（已失效）、行残缺，还会触发 `md-to-pdf` 的 `_has_manual_toc` → **跳过自动生成正确目录**

**正确规则**：标题级别应由**章节号层数**决定——`N`→H1、`N.M`→H2、`N.M.K…`→H3。`md-to-pdf` 的目录深度是 **`toc_depth: 1-4`**，所以：

- 想进目录的（章/节/指令）用 H1–H3
- **不想进目录**的（续表头 `... (continued)`、`Global.`/`Scratch.` 之类小标签、Marker 碎片）降到 **H5**（低于 1-4，自动不进目录）
- **删掉失效的旧「Contents/目录」块**，让 `md-to-pdf` 依据修好的层级**自动生成**正确目录（自动目录是可点击的嵌套列表）

**适用范围**：以下脚本用于 PDF 提取的编号规范类文档，不对普通博客或 HTML 论文强制运行。

**做法**：跑规整脚本（默认 dry-run，`--apply` 写回）：

```bash
# 先预览（会报告：删除的失效目录行数、级别修正数、签名拆分数、层级分布、疑似丢章号的警告）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/normalize_headings.py "{文档名}_zh.md"
# 确认无误后写回
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/normalize_headings.py "{文档名}_zh.md" --apply
```

脚本会：按编号层数重排级别、拆分「标题里并进的签名」、删除失效旧目录、把碎片降到 H5。若脚本报告 **⚠ 疑似丢章号**（无编号的 `Encoding ...` 章标题），需**人工按顺序补回章号**（脚本不猜数字，避免错编号）。修完后回到 6.1 重跑 `validate_md.py`，再重新生成 PDF。

**验证**：用 PyMuPDF 检查生成 PDF 的书签树层级是否正确嵌套：

```python
import fitz
for lv, title, pg in fitz.open("xxx_zh.pdf").get_toc():
    print("  " * (lv - 1) + f"[L{lv}] {title[:50]} (p{pg})")
# 期望：L1=章/前置/附录，L2=节，L3=指令；不应出现「第 0 章」或签名串当标题
```

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

## 大文档断点恢复

**触发条件**：`extracted.md` ≥ 1500 行（约 17+ 个 chunk）。这类任务一次会话内常因网络波动 / 模型超时 / 工具流截断中断；不上断点机制每次重启都会浪费已翻译的内容。

**核心思路**：把翻译进度持久化到磁盘（`_chunks/` 目录 + `_state.json`），每个 chunk 是一个独立 `.md` 文件，最后一次性拼接为 `_zh.md`。重启的 agent 只需读 `_state.json` 就能精确续翻。

### 目录结构

```
inout/MyDoc_extracted/
├── extracted.md            # 原文（只读）
├── images/                 # Marker 提取的图片
├── ocr_report.json
└── _chunks/
    ├── _state.json         # {chunks: [{id, title, start_line, end_line, status}], …}
    ├── _glossary.md        # 持久化的术语表（Step 2.5 产物）
    ├── _context.md         # 持久化的背景摘要（Step 2.5 产物）
    ├── _prev_tail.md       # 最近一次完成 chunk 的末尾 30 行（重叠上下文）
    ├── 00_frontmatter.md   # 各 chunk 的双语输出
    ├── 01_ch1_intro.md
    └── …
```

### 工作流（用 `chunkctl.py` 控制）

`chunkctl.py` 路径：`~/.cursor/skills/translate/chunkctl.py`。所有命令对 `_state.json` 的读写都是原子的；可在任何 agent 实例之间无缝接力。

```bash
# 1) 自动切片并初始化状态（首次进入大文档翻译时执行一次）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py init "{输出目录}"

# 2) 持久化术语表与背景（来自 Step 2.5）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-glossary "{输出目录}" .cursor/tmp/translate/glossary.md
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-context  "{输出目录}" .cursor/tmp/translate/context.md

# 3) 查看进度
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py list "{输出目录}"

# 4) 取下一个待翻 chunk（返回 JSON：id / title / start_line / end_line / 上下文文件路径）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py next "{输出目录}"
#   → agent 读对应行段、读 _glossary.md / _context.md / _prev_tail.md，写翻译到 .cursor/tmp/translate/<id>.md

# 5) 完成后登记
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py mark "{输出目录}" <chunk_id> done --file .cursor/tmp/translate/<id>.md
#   → 自动把文件搬到 _chunks/<id>.md 并刷新 _prev_tail.md

# 6) 全部完成后拼接生成最终 _zh.md
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py assemble "{输出目录}"
#   → 输出到 <pdf_parent>/<stem>_zh.md（可用 --out 指定）
```

### 关键约束

- **chunk 大小目标 80–280 行原文**：`init` 自动切片，必要时可用 `chunkctl plan ...` 输出 JSON 后手工调整再 `init --plan plan.json --replace` 注入
- **每翻完一个 chunk 立即 `mark done`**：不要攒一批再批量 mark；状态文件即"checkpoint"
- **chunk 之间禁止互相依赖**：所有跨 chunk 上下文都来自 `_glossary.md`、`_context.md`、`_prev_tail.md` 这 3 个文件
- **每条 Write 调用 ≤ 8 KB**：超长 chunk 拆成多份 `.cursor/tmp/translate/<id>.part1.md`、`.cursor/tmp/translate/<id>.part2.md`，`cat` 后再 `mark`
- **Write 后必做 `wc -l` 校验**：对抗偶发的 empty Write
- **断电恢复检查清单**（新 agent 启动时执行一次）：
  1. `ls "{输出目录}/_chunks/_state.json"` 是否存在 — 存在就走断点流程
  2. `chunkctl list "{输出目录}"` 看到了几个 done / 几个 pending
  3. `cat "{输出目录}/_chunks/_glossary.md" "{输出目录}/_chunks/_context.md" "{输出目录}/_chunks/_prev_tail.md"` 加载上下文
  4. `chunkctl next "{输出目录}"` 取下一块继续

### 与前述步骤的衔接

- Step 1（提取）幂等：`extract_pdf.py` 不带 `--force` 已默认跳过缓存
- Step 2.5（背景 + 术语）：把生成的两段 Markdown 用 `chunkctl set-glossary/set-context` 持久化
- Step 3（翻译）：循环 `chunkctl next` → 翻译 → `chunkctl mark done`
- Step 4（写入）：替换为 `chunkctl assemble`
- Step 5（图片搬迁）：在 assemble 之后照常进行，路径修正与原方案一致
- Step 6（自审校）：在拼接好的 `_zh.md` 上跑（一次性，不必逐 chunk）

## 示例用法

用户说："翻译这个 PDF ~/papers/attention.pdf"

1. 运行：`/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/extract_pdf.py ~/papers/attention.pdf`
2. 公式质量优化（三级策略）：arXiv 论文优先下载 `.tex` 源码全面校准公式；非 arXiv 论文使用 Marker 提取结果并检测空公式；无法修复的用 PDF 截图兜底
3. 读取 `~/papers/attention_extracted/extracted.md`（中间文件在子目录）
4. 自动总结论文背景（领域、研究对象、目标读者），向用户确认；构建术语表（20-50 条）
5. 逐段翻译，写入 `~/papers/attention_zh.md`（与 PDF 同目录），每块附带背景摘要、术语表和前一块末尾上下文
6. 搬迁图片：`mv ~/papers/attention_extracted/images ~/papers/attention_images`
7. 修正 `attention_zh.md` 中的图片路径：`![](xxx.png)` → `![](attention_images/xxx.png)`
8. 审校：运行结构验证并逐章节检查漏翻、术语一致性、信息完整性、公式质量，修正问题
9. 审校通过后清理中间目录：`rm -rf ~/papers/attention_extracted/`
10. 告诉用户：翻译完成，输出文件在 `~/papers/attention_zh.md`

### 实际案例：CuTe Layout 论文

输入 PDF：`inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra.pdf`（NVIDIA 的 CuTe 布局代数论文，33 页）

产出文件：
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_zh.md`（2299 行双语 Markdown）
- `inout/2603.02298v1_CuTeLayoutRepresentationAndAlgebra_images/`（9 张 PNG 图片）

该论文包含大量 LaTeX 数学公式和技术图表，翻译时公式原样保留（遵守 GitHub 兼容规则：`\lvert`/`\rvert`、`^{\ast}` 等），图表配中文标题说明。

### 实际案例：MI400 Shader Programming Guide（断点恢复）

输入 PDF：`inout/MI400_Shader_Programming.pdf`（AMD 内部硬件规范，347 页 / 13,746 行 extracted.md / 536 张图）

由于规模超 `1500` 行阈值，使用断点恢复机制：

```bash
# 一次性建立状态
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py init inout/MI400_Shader_Programming_extracted/

# 持久化 Step 2.5 产物
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-glossary inout/MI400_Shader_Programming_extracted/ .cursor/tmp/translate/glossary.md
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py set-context  inout/MI400_Shader_Programming_extracted/ .cursor/tmp/translate/context.md

# 主循环（每个 chunk）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py next inout/MI400_Shader_Programming_extracted/
# … agent 读对应行段并翻译，写到 .cursor/tmp/translate/03_xxx.md（必要时分多个 Write）
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py mark inout/MI400_Shader_Programming_extracted/ 03_xxx done --file .cursor/tmp/translate/03_xxx.md

# 全部完成后
/workspace/ai_tools/.venv/bin/python ~/.cursor/skills/translate/chunkctl.py assemble inout/MI400_Shader_Programming_extracted/
mv inout/MI400_Shader_Programming_extracted/images inout/MI400_Shader_Programming_images
# … 修正图片路径，自审校；通过后再删除 _extracted/
```

模板了 89 个 chunk；任何中断只需重启 agent 后 `chunkctl list` 看进度、`chunkctl next` 续翻。

### 实际案例：SP3 MI350 指令集（标题层级 / TOC 修复）

输入 PDF：`inout/gfx9/sp3_mi350_instructions.pdf`（AMD SP3 MI350 指令集参考，1430 页），产出 793 页双语 PDF。

翻译、审校通过后交付，用户反馈**「PDF 目录层级不对」**。排查发现是 Marker 提取时把标题层级打乱了（章/节全 H1、opcode 全 H4、3 个章号丢失、93 处签名并进标题、旧目录页码失效并触发 `_has_manual_toc`）。用 `normalize_headings.py` 一次性规整（825 处级别修正 + 93 处签名拆分 + 删 128 行失效目录 + 碎片降 H5），人工补回 3 个丢失章号（ENC_SOP1=9、ENC_VOP1=14、ENC_VOPC=19），重跑 `validate_md.py`（9/9 PASS）并重新生成 PDF。最终书签树正确嵌套为 章(L1)→节(L2)→指令(L3)。

**教训固化**：见「翻译时的格式陷阱 → #6 标题层级与目录（TOC）」。多级技术规范（指令集、硬件手册）**生成 PDF 前必须先跑 `normalize_headings.py`**，不能只信任 Marker 的标题级别。

### 网络来源示例

- “翻译这篇 arXiv 论文，编号 2603.02298v1”：按 [arXiv 来源说明](references/arxiv.md) 获取对应版本全文，整理为 `extracted.md` 后复用双语翻译流程，记录来源与版本。
- “把这个博客链接翻译成中文对照文档”：获取完整文章正文并本地化正文图片，保留代码与链接，按 Step 0 的网络来源输出约定交付。站点特有的加载或解析问题在实际使用时再细化，不提前添加通用爬虫或站点适配器。
