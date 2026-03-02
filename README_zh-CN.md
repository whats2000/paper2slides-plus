# paper2slides-plus

[English](README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md) | [日本語](README_ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1-412991.svg) ![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg) ![arXiv](https://img.shields.io/badge/arXiv-papers-b31b1b.svg)

本项目是基于原始 [paper2slides](https://github.com/takashiishida/paper2slides) 的进一步开发。我们非常感谢原作者 [takashiishida](https://github.com/takashiishida) 的贡献，但由于该项目已停止更新，因此我们创建了这个分支，以提供快速的更新与新功能。

## `paper2slides-plus` 的新功能

1. **全面支持将任何 PDF 转换为幻灯片**
2. **支持单页编辑**
3. **新增正确的 LaTeX 语法反馈与修正循环**
4. **博士级别的演讲者备注 (Speaker notes)**
5. **支持多篇论文的项目管理**
6. **编辑版本控制**
7. **支持自定义 LLM 供应商的 `BASE_URL` 覆盖**
8. **提供与其他应用程序集成的 API 版本**
9. **通过 Docker 轻松部署**

---

使用 LLM 将任何 arXiv 论文与 PDF 转换为幻灯片！这个工具非常适合快速掌握研究论文的核心概念。您可以在 [Demo](demo/) 目录中找到一些生成的幻灯片示例。

## 安装

需要 Python 3.10 或更高版本。

安装步骤：

1. 克隆此仓库：

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > 如果您之前未加上 `--recursive` 参数就进行了克隆，您可以通过执行以下命令来初始化子模块：
   > `git submodule update --init --recursive`

2. 安装必要的 Python 包（推荐使用 uv 以获得更快且更安全的依赖解析）：

   ```sh
   pip install uv
   uv pip install -r requirements.txt
   ```

   或者使用 pip：

   ```sh
   pip install -r requirements.txt
   ```

3. 安装包含 `pdflatex` 的 LaTeX 发行版。常见的选项包括：
   - [MikTeX](https://miktex.org/)（推荐 Windows 使用）
   - [TeX Live](https://www.tug.org/texlive/)（跨平台）

   安装完成后，确保 LaTeX 可执行文件已加入系统的 PATH 中。

   您可以选择性地执行 `pdflatex test.tex` 来测试是否可以编译示例 `test.tex`。检查 `test.pdf` 是否正确生成，并确认 `chktex` 和 `pdfcrop` 正常工作。

4. 设置环境变量（API 密钥等）：

   将 `.env.example` 复制为 `.env` 并填写您的 API 密钥与设置。

   ```sh
   cp .env.example .env
   ```

## Docker 设置

paper2slides 为 Streamlit Web 应用程序和 REST API 服务提供了 Docker 镜像。

### Streamlit Web 应用程序

为了避免在本地安装 LaTeX 和 Python 依赖，您可以使用 Docker 来运行 Web 界面。

1. 确保您的系统已安装 Docker。

2. 克隆仓库并进入目录：

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > 如果您之前未加上 `--recursive` 参数就进行了克隆，您可以通过执行以下命令来初始化子模块：
   > `git submodule update --init --recursive`

3. 在 `.env` 文件中设置您的 API 密钥（请参阅上方的设置章节）。例如：

   ```sh
   cp .env.example .env
   # 然后编辑 .env 填写您的密钥
   ```

4. 使用 Docker Compose 构建并运行 Streamlit 应用程序：

   ```sh
   docker-compose up paper2slides
   ```

   这会在 `http://localhost:8501` 启动 Streamlit 应用程序。

   `source` 和 `cache` 目录会作为 Volume 挂载，以保留生成的文件。

或者，手动构建并运行：

```sh
docker build -t paper2slides .
docker run -p 8501:8501 -v $(pwd)/source:/app/source -v $(pwd)/cache:/app/cache -e OPENAI_API_KEY=your-api-key paper2slides
```

### REST API 服务

若需通过程序访问或与其他应用程序集成，请使用 FastAPI 服务。

1. 构建并运行 API 服务：

   ```sh
   docker-compose up paper2slides-api -d
   ```

   这会在 `http://localhost:8000` 启动 API。

2. 访问 API 文档 `http://localhost:8000/docs` (Swagger UI) 或 `http://localhost:8000/redoc` (ReDoc)。

3. API 提供以下端点：
   - 从 arXiv 论文或上传的 PDF 生成幻灯片
   - 跟踪任务状态
   - 下载生成的幻灯片 (PDF/LaTeX)
   - 编辑幻灯片与生成演讲者备注
   - 多用户工作区隔离

## 快速开始

安装完成后，即可从任何 arXiv 论文生成幻灯片：

```sh
python paper2slides.py all 2505.18102
```

或从本地的 PDF 文件生成：

```sh
python paper2slides.py all --pdf /path/to/your/paper.pdf
```

对于像书籍这类的长文档，您可以指定页码范围，仅处理特定章节：

```sh
# 处理第 50-75 页（例如特定章节）
python paper2slides.py all --pdf /path/to/book.pdf --start-page 50 --end-page 75
```

这将自动下载论文（或处理您的 PDF）、生成幻灯片、编译成 PDF 并打开演示文稿。

## 使用方法

### CLI (命令行界面)

`paper2slides.py` 脚本提供了包含子命令的 CLI 界面：

```sh
# 从 arXiv 执行完整流程（最常见的用法）
python paper2slides.py all <arxiv_id>

# 从本地 PDF 执行完整流程
python paper2slides.py all --pdf /path/to/paper.pdf

# 仅从 arXiv 生成幻灯片 (Beamer)
python paper2slides.py generate <arxiv_id>

# 仅从本地 PDF 生成幻灯片
python paper2slides.py generate --pdf /path/to/paper.pdf

# 从特定页码范围生成幻灯片（例如书籍中的章节）
python paper2slides.py generate --pdf /path/to/book.pdf --start-page 50 --end-page 75

# 生成幻灯片 (Beamer) 并启用语法检查 (linting) 与 PDF 裁剪
python paper2slides.py generate <arxiv_id> --use_linter --use_pdfcrop

# 将幻灯片 (Beamer) 编译为 PDF
python paper2slides.py compile <arxiv_id>

# 执行完整流程但不自动打开 PDF
python paper2slides.py all <arxiv_id> --no-open
```

将 `<arxiv_id>` 替换为所需的 arXiv 论文 ID。
可以从 URL 中找到该 ID：例如 `https://arxiv.org/abs/xxxx.xxxx` 的 ID 为 `xxxx.xxxx`。

对于本地 PDF 文件，请使用 `--pdf` 参数并接上 PDF 文件的路径。

底层的 `tex2beamer.py` 和 `beamer2pdf.py` 脚本处理核心功能：

- `tex2beamer.py` 使用 `arxiv-to-prompt` 下载并处理 arXiv 论文，接着通过 OpenAI API 生成 Beamer 幻灯片
- `beamer2pdf.py` 使用 pdflatex 将 LaTeX 幻灯片编译为 PDF

发送给 LLM 的提示词 (Prompts) 和回复会记录在 `tex2beamer.log` 中。
Linter 输出（当使用 `--use_linter` 时）会存储在 `source/<arxiv_id>/linter.log` 中。

### 提示词 (Prompts)

现在可以通过 `prompts/config.yaml` 中的 YAML 架构系统来管理提示词。该文件包含：

- **模板变量**：如 `num_slides`、`max_items`、`figure_width` 等通用设置
- **阶段管理**：将 `initial`、`update` 和 `revise` 阶段的提示词分离
- **默认值**：受众、格式和尺寸等可设置的默认值
- **变量替换**：动态替换 `{variable}` 占位符

您可以通过编辑 `prompts/config.yaml` 自定义提示词。系统会自动处理图片路径插入及其他动态内容。`prompts/manager.py` 中的 `PromptManager` 类负责处理模板渲染和验证。

### Web 界面 (Web UI)

运行 Streamlit 应用程序享受点击操作体验：

```bash
streamlit run app.py
```

- 在侧边栏中选择“arXiv Paper”或“Upload PDF”模式。
- 若选择 arXiv：在侧边栏输入 arXiv ID（如 2505.18102）或搜索关键字。
- 若选择 PDF：直接从您的电脑上传 PDF 文件。
  - **页码范围选择**：上传 PDF 时，您可以选择性地指定页码范围，仅处理特定部分（例如书籍的一章）。对长篇文档非常实用。
- 点击“Run Full Pipeline”以生成幻灯片并编译 PDF，或使用“Generate Only” / “Compile Only”。
- 流程完成后，您可以在左侧面板交互式编辑幻灯片；更改将自动重新编译。

## 运作原理

流程首先从下载 arXiv 论文的源文件开始。通过 [arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt) 找出主要 LaTeX 文件并展平 (flattened)，将所有输入文件合并成单一文件 (`FLATTENED.tex`)。我们通过移除注释和附录来预处理这个合并的文件。这份预处理后的文件，连同制作良好幻灯片的指示，构成了我们的提示词 (prompt) 基础。

一个核心理念是使用 Beamer 制作幻灯片，让我们能完全留在 LaTeX 生态系统中。这个方法实质上将任务转变为了摘要练习：将冗长的 LaTeX 论文转换为简洁的 Beamer LaTeX。LLM 可以从图片的标题推断其内容并将其包含在幻灯片中，因此不需要视觉能力。

为了协助 LLM，我们建立了一个名为 `ADDITIONAL.tex` 的文件，其中包含所有必要的宏包、\newcommand 定义以及论文中使用的其他 LaTeX 设置。将此文件与 `\input{ADDITIONAL.tex}` 一同放入提示词中能缩短长度并使幻灯片生成更可靠，特别是对于具有许多自定义指令的理论论文而言。

LLM 从 LaTeX 源码生成 Beamer 代码，但由于第一次执行可能存在问题，我们会要求 LLM 自我检查并改进输出。可选的第三步是使用 Linter 检查生成的代码，并将结果传回给 LLM 进行进一步修正（这个 Linter 步骤的灵感来自 [The AI Scientist](https://www.arxiv.org/abs/2408.06292)）。最后，Beamer 代码通过 pdflatex 编译为 PDF 幻灯片。

统一的 `paper2slides.py` 脚本自动化了整个流程，单篇论文使用 GPT-4.1 通常在几分钟内即可完成。

> [!WARNING]
> 此脚本将从互联网 (arXiv) 下载文件、发送信息给 OpenAI API，并在本地端编译。请谨慎处理分享的内容与潜在风险。

> [!IMPORTANT]
> 在使用此工具时，请尊重 arXiv 论文的授权条款。arXiv 上的每篇论文都有特定的授权 (CC BY、CC BY-SA、CC BY-NC-SA、CC BY-NC-ND、arXiv 永久授权或 CC Zero) 来规范作品的使用、修改和分发方式。在从任何论文建立和分享幻灯片之前，请在论文的 arXiv 页面上检查其授权，确保您的使用符合条款。欲了解更多信息，请参见 [arXiv 授权文档](https://info.arxiv.org/help/license/index.html)。
