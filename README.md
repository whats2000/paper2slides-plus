# paper2slides-plus

[English](README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md) | [日本語](README_ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1-412991.svg) ![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg) ![arXiv](https://img.shields.io/badge/arXiv-papers-b31b1b.svg)

This project is a further development based on the original [paper2slides](https://github.com/takashiishida/paper2slides). We appreciate the original [takashiishida](https://github.com/takashiishida)'s work, but as it has stopped updating, this fork was created to provide rapid updates and new functionality.

## New Features in `paper2slides-plus`

1. **Fully support any PDF to slides**
2. **Support single page editing**
3. **Add correct LaTeX syntax feedback correction loop**
4. **Speaker notes at PhD level**
5. **Project management for multiple papers**
6. **Edit version control**
7. **`BASE_URL` overwrite for custom LLM providers**
8. **An API version for integration with other apps**
9. **Docker for easy deployment**

---

Transform any arXiv papers and PDFs into slides using LLMs! This tool is useful for quickly grasping the main ideas of research papers. Some examples of generated slides are in the [Demo](demo/) directory.

## Installation

Python 3.10 or higher is required.

To install:

1. Clone this repository:

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > If you already cloned the repository without the `--recursive` flag, you can initialize the submodules by running:
   > `git submodule update --init --recursive`

2. Install the required Python packages (using uv for faster and safer dependency resolution):

   ```sh
   pip install uv
   uv pip install -r requirements.txt
   ```

   Or using pip:

   ```sh
   pip install -r requirements.txt
   ```

3. Install a LaTeX distribution that includes `pdflatex`. Popular options include:
   - [MikTeX](https://miktex.org/) (recommended for Windows)
   - [TeX Live](https://www.tug.org/texlive/) (cross-platform)

   After installation, ensure the LaTeX binaries are in your system's PATH.

   Optionally check if you can compile the sample `test.tex` by `pdflatex test.tex`. Check if `test.pdf` is generated correctly. Optionally check `chktex` and `pdfcrop` are working.

4. Configure environment variables (API keys, etc.):

   Copy `.env.example` to `.env` and fill in your API keys and settings.

   ```sh
   cp .env.example .env
   ```

## Docker Setup

paper2slides provides Docker images for both the Streamlit web application and the REST API service.

### Streamlit Web App

To avoid installing LaTeX and Python dependencies locally, you can use Docker for the web interface.

1. Ensure Docker is installed on your system.

2. Clone the repository and navigate to the directory:

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > If you already cloned the repository without the `--recursive` flag, you can initialize the submodules by running:
   > `git submodule update --init --recursive`

3. Set up your API keys in a `.env` file (see Configuration section above). For example:

   ```sh
   cp .env.example .env
   # Then edit .env with your keys
   ```

4. Build and run the Streamlit app using Docker Compose:

   ```sh
   docker-compose up paper2slides
   ```

   This will start the Streamlit app on `http://localhost:8501`.

   The `source` and `cache` directories are mounted as volumes to persist generated files.

Alternatively, build and run manually:

```sh
docker build -t paper2slides .
docker run -p 8501:8501 -v $(pwd)/source:/app/source -v $(pwd)/cache:/app/cache -e OPENAI_API_KEY=your-api-key paper2slides
```

### REST API Service

For programmatic access or integration with other applications, use the FastAPI service.

1. Build and run the API service:

   ```sh
   docker-compose up paper2slides-api -d
   ```

   This will start the API on `http://localhost:8000`.

2. Access the API documentation at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc).

3. The API provides endpoints for:
   - Generating slides from arXiv papers or uploaded PDFs
   - Tracking job status
   - Downloading generated slides (PDF/LaTeX)
   - Editing slides and generating speaker notes
   - Multi-user workspace isolation

## Quick Start

Once installed, generate slides from any arXiv paper:

```sh
python paper2slides.py all 2505.18102
```

Or from a local PDF file:

```sh
python paper2slides.py all --pdf /path/to/your/paper.pdf
```

For long documents like books, you can specify a page range to process only a specific chapter:

```sh
# Process pages 50-75 (e.g., a specific chapter)
python paper2slides.py all --pdf /path/to/book.pdf --start-page 50 --end-page 75
```

This will download the paper (or process your PDF), generate slides, compile to PDF, and open the presentation automatically.

## Usage

### CLI

The `paper2slides.py` script provides a CLI interface with subcommands:

```sh
# Full pipeline from arXiv (most common usage)
python paper2slides.py all <arxiv_id>

# Full pipeline from local PDF
python paper2slides.py all --pdf /path/to/paper.pdf

# Generate slides (beamer) only from arXiv
python paper2slides.py generate <arxiv_id>

# Generate slides from local PDF
python paper2slides.py generate --pdf /path/to/paper.pdf

# Generate slides from a specific page range (e.g., chapter in a book)
python paper2slides.py generate --pdf /path/to/book.pdf --start-page 50 --end-page 75

# Generate slides (beamer) with linting and PDF cropping
python paper2slides.py generate <arxiv_id> --use_linter --use_pdfcrop

# Compile slides (beamer) to PDF
python paper2slides.py compile <arxiv_id>

# Full pipeline without opening PDF
python paper2slides.py all <arxiv_id> --no-open
```

Replace `<arxiv_id>` with the desired arXiv paper ID.
The ID can be identified from the URL: the ID for `https://arxiv.org/abs/xxxx.xxxx` is `xxxx.xxxx`.

For local PDF files, use the `--pdf` flag followed by the path to your PDF file.

The underlying `tex2beamer.py` and `beamer2pdf.py` scripts handle the core functionality:

- `tex2beamer.py` downloads and processes the arXiv paper using `arxiv-to-prompt`, then generates Beamer slides via OpenAI API
- `beamer2pdf.py` compiles the LaTeX slides to PDF using pdflatex

The prompts sent to the LLM and responses are logged to `tex2beamer.log`.
Linter output (when `--use_linter` is used) is saved to `source/<arxiv_id>/linter.log`.

### Prompts

The prompts are now managed through a YAML-based system in `prompts/config.yaml`. This file contains:

- **Template variables**: Common settings like `num_slides`, `max_items`, `figure_width`, etc.
- **Stage management**: Separate prompts for `initial`, `update`, and `revise` stages
- **Default values**: Configurable defaults for audience, formatting, and dimensions
- **Variable substitution**: Dynamic replacement of `{variable}` placeholders

You can customize the prompts by editing `prompts/config.yaml`. The system automatically handles figure path insertion and other dynamic content. The `PromptManager` class in `prompts/manager.py` handles template rendering and validation.

### Web UI

Run the Streamlit app for a point-and-click experience:

```bash
streamlit run app.py
```

- Choose between "arXiv Paper" or "Upload PDF" mode in the sidebar.
- For arXiv: Enter an arXiv ID (e.g., 2505.18102) or a search query in the sidebar.
- For PDF: Upload a PDF file directly from your computer.
  - **Page Range Selection**: When uploading a PDF, you can optionally specify a page range to process only a specific section (e.g., a chapter from a book). This is useful for long documents.
- Click "Run Full Pipeline" to generate slides and compile the PDF, or use "Generate Only" / "Compile Only".
- After the pipeline completes, you can interactively edit the slides in the left panel; changes are recompiled automatically.

## How does it work?

The process begins by downloading the source files of an arXiv paper. The main LaTeX file is identified and flattened, merging all input files into a single document (`FLATTENED.tex`) with [arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt). We preprocess this merged file by removing comments and the appendix. This preprocessed file, along with instructions for creating good slides, forms the basis of our prompt.

One key idea is to use Beamer for slide creation, allowing us to stay entirely within the LaTeX ecosystem. This approach essentially turns the task into a summarization exercise: converting a long LaTeX paper into concise Beamer LaTeX. The LLM can infer the content of figures from their captions and include them in the slides, eliminating the need for vision capabilities.

To aid the LLM, we create a file called `ADDITIONAL.tex`, which contains all necessary packages, \newcommand definitions, and other LaTeX settings used in the paper. Including this file with `\input{ADDITIONAL.tex}` in the prompt shortens it and makes generating slides more reliable, particularly for theoretical papers with many custom commands.

The LLM generates Beamer code from the LaTeX source, but since the first run may have issues, we ask the LLM to self-inspect and refine the output. Optionally, a third step involves using a linter to check the generated code, with the results fed back to the LLM for further corrections (this linter step was inspired by [The AI Scientist](https://www.arxiv.org/abs/2408.06292)). Finally, the Beamer code is compiled into a PDF presentation using pdflatex.

The unified `paper2slides.py` script automates the entire process, typically completing in less than a few minutes with GPT-4.1 for a single paper.

> [!WARNING]
> The script will download files from the internet (arXiv), send information to the OpenAI API, and compile locally. Please be cautious about the content being shared and the potential risks.

> [!IMPORTANT]
> Please respect the license of arXiv papers when using this tool. Each paper on arXiv has a specific license (CC BY, CC BY-SA, CC BY-NC-SA, CC BY-NC-ND, arXiv perpetual license, or CC Zero) that governs how the work can be used, modified, and distributed. Before creating and sharing slides from any paper, check the paper's license on its arXiv page and ensure your use complies with the license terms. For more information, see [arXiv's license documentation](https://info.arxiv.org/help/license/index.html).
