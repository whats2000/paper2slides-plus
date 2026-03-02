# paper2slides-plus

[English](README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md) | [日本語](README_ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1-412991.svg) ![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg) ![arXiv](https://img.shields.io/badge/arXiv-papers-b31b1b.svg)

本專案是基於原始 [paper2slides](https://github.com/takashiishida/paper2slides) 的進一步開發。我們非常感謝原作者 [takashiishida](https://github.com/takashiishida) 的貢獻，但由於該專案已停止更新，因此我們建立了這個分支，以提供快速的更新與新功能。

## `paper2slides-plus` 的新功能

1. **全面支援將任何 PDF 轉換為簡報**
2. **支援單頁編輯**
3. **新增正確的 LaTeX 語法回饋與修正循環**
4. **博士級別的講者備忘錄 (Speaker notes)**
5. **支援多篇論文的專案管理**
6. **編輯版本控制**
7. **支援自訂 LLM 供應商的 `BASE_URL` 覆寫**
8. **提供與其他應用程式整合的 API 版本**
9. **透過 Docker 輕鬆部署**

---

使用 LLM 將任何 arXiv 論文與 PDF 轉換為簡報！這個工具非常適合快速掌握研究論文的核心概念。您可以在 [Demo](demo/) 目錄中找到一些生成的簡報範例。

## 安裝

需要 Python 3.10 或以上版本。

安裝步驟：

1. 複製此儲存庫：

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > 如果您之前未加上 `--recursive` 參數就進行了複製，您可以透過執行以下命令來初始化子模組：
   > `git submodule update --init --recursive`

2. 安裝必要的 Python 套件（推薦使用 uv 以獲得更快且更安全的相依性解析）：

   ```sh
   pip install uv
   uv pip install -r requirements.txt
   ```

   或者使用 pip：

   ```sh
   pip install -r requirements.txt
   ```

3. 安裝包含 `pdflatex` 的 LaTeX 發行版。常見的選項包括：
   - [MikTeX](https://miktex.org/)（推薦 Windows 使用）
   - [TeX Live](https://www.tug.org/texlive/)（跨平台）

   安裝完成後，確保 LaTeX 執行檔已加入系統的 PATH 中。

   您可以選擇性地執行 `pdflatex test.tex` 來測試是否可以編譯範例 `test.tex`。檢查 `test.pdf` 是否正確生成，並確認 `chktex` 和 `pdfcrop` 正常運作。

4. 設定環境變數（API 金鑰等）：

   將 `.env.example` 複製為 `.env` 並填寫您的 API 金鑰與設定。

   ```sh
   cp .env.example .env
   ```

## Docker 設定

paper2slides 為 Streamlit 網路應用程式和 REST API 服務提供了 Docker 映像檔。

### Streamlit 網路應用程式

為了避免在本地安裝 LaTeX 和 Python 依賴，您可以使用 Docker 來運行網路介面。

1. 確保您的系統已安裝 Docker。

2. 複製儲存庫並進入目錄：

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > 如果您之前未加上 `--recursive` 參數就進行了複製，您可以透過執行以下命令來初始化子模組：
   > `git submodule update --init --recursive`

3. 在 `.env` 檔案中設定您的 API 金鑰（請參閱上方的設定章節）。例如：

   ```sh
   cp .env.example .env
   # 然後編輯 .env 填寫您的金鑰
   ```

4. 使用 Docker Compose 建置並執行 Streamlit 應用程式：

   ```sh
   docker-compose up paper2slides
   ```

   這會在 `http://localhost:8501` 啟動 Streamlit 應用程式。

   `source` 和 `cache` 目錄會作為 Volume 掛載，以保留生成的檔案。

或者，手動建置並執行：

```sh
docker build -t paper2slides .
docker run -p 8501:8501 -v $(pwd)/source:/app/source -v $(pwd)/cache:/app/cache -e OPENAI_API_KEY=your-api-key paper2slides
```

### REST API 服務

若需透過程式存取或與其他應用程式整合，請使用 FastAPI 服務。

1. 建置並執行 API 服務：

   ```sh
   docker-compose up paper2slides-api -d
   ```

   這會在 `http://localhost:8000` 啟動 API。

2. 存取 API 文件 `http://localhost:8000/docs` (Swagger UI) 或 `http://localhost:8000/redoc` (ReDoc)。

3. API 提供以下端點：
   - 從 arXiv 論文或上傳的 PDF 生成簡報
   - 追蹤任務狀態
   - 下載生成的簡報 (PDF/LaTeX)
   - 編輯簡報與生成講者備忘錄
   - 多用戶工作區隔離

## 快速開始

安裝完成後，即可從任何 arXiv 論文生成簡報：

```sh
python paper2slides.py all 2505.18102
```

或從本地的 PDF 檔案生成：

```sh
python paper2slides.py all --pdf /path/to/your/paper.pdf
```

對於像書籍這類的長文件，您可以指定頁碼範圍，僅處理特定章節：

```sh
# 處理第 50-75 頁（例如特定章節）
python paper2slides.py all --pdf /path/to/book.pdf --start-page 50 --end-page 75
```

這將自動下載論文（或處理您的 PDF）、生成簡報、編譯成 PDF 並開啟簡報檔。

## 使用方法

### CLI (命令列介面)

`paper2slides.py` 腳本提供了包含子命令的 CLI 介面：

```sh
# 從 arXiv 執行完整流程（最常見的用法）
python paper2slides.py all <arxiv_id>

# 從本地 PDF 執行完整流程
python paper2slides.py all --pdf /path/to/paper.pdf

# 僅從 arXiv 生成簡報 (Beamer)
python paper2slides.py generate <arxiv_id>

# 僅從本地 PDF 生成簡報
python paper2slides.py generate --pdf /path/to/paper.pdf

# 從特定頁碼範圍生成簡報（例如書籍中的章節）
python paper2slides.py generate --pdf /path/to/book.pdf --start-page 50 --end-page 75

# 生成簡報 (Beamer) 並啟用語法檢查 (linting) 與 PDF 裁剪
python paper2slides.py generate <arxiv_id> --use_linter --use_pdfcrop

# 將簡報 (Beamer) 編譯為 PDF
python paper2slides.py compile <arxiv_id>

# 執行完整流程但不自動開啟 PDF
python paper2slides.py all <arxiv_id> --no-open
```

將 `<arxiv_id>` 替換為所需的 arXiv 論文 ID。
可以從 URL 中找到該 ID：例如 `https://arxiv.org/abs/xxxx.xxxx` 的 ID 為 `xxxx.xxxx`。

對於本地 PDF 檔案，請使用 `--pdf` 參數並接上 PDF 檔案的路徑。

底層的 `tex2beamer.py` 和 `beamer2pdf.py` 腳本處理核心功能：

- `tex2beamer.py` 使用 `arxiv-to-prompt` 下載並處理 arXiv 論文，接著透過 OpenAI API 生成 Beamer 簡報
- `beamer2pdf.py` 使用 pdflatex 將 LaTeX 簡報編譯為 PDF

發送給 LLM 的提示詞 (Prompts) 和回覆會記錄在 `tex2beamer.log` 中。
Linter 輸出（當使用 `--use_linter` 時）會儲存在 `source/<arxiv_id>/linter.log` 中。

### 提示詞 (Prompts)

現在可以透過 `prompts/config.yaml` 中的 YAML 架構系統來管理提示詞。該檔案包含：

- **模板變數**：如 `num_slides`、`max_items`、`figure_width` 等通用設定
- **階段管理**：將 `initial`、`update` 和 `revise` 階段的提示詞分離
- **預設值**：受眾、格式和尺寸等可設定的預設值
- **變數替換**：動態替換 `{variable}` 佔位符

您可以透過編輯 `prompts/config.yaml` 自訂提示詞。系統會自動處理圖片路徑插入及其他動態內容。`prompts/manager.py` 中的 `PromptManager` 類別負責處理模板渲染和驗證。

### Web 介面 (Web UI)

執行 Streamlit 應用程式享受點擊操作體驗：

```bash
streamlit run app.py
```

- 在側邊欄中選擇「arXiv Paper」或「Upload PDF」模式。
- 若選擇 arXiv：在側邊欄輸入 arXiv ID（如 2505.18102）或搜尋關鍵字。
- 若選擇 PDF：直接從您的電腦上傳 PDF 檔案。
  - **頁碼範圍選擇**：上傳 PDF 時，您可以選擇性地指定頁碼範圍，僅處理特定部分（例如書籍的一章）。對長篇文件非常實用。
- 點擊「Run Full Pipeline」以生成簡報並編譯 PDF，或使用「Generate Only」/「Compile Only」。
- 流程完成後，您可以在左側面板互動式編輯簡報；更改將自動重新編譯。

## 運作原理

流程首先從下載 arXiv 論文的原始檔開始。透過 [arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt) 找出主要 LaTeX 檔案並展平 (flattened)，將所有輸入檔合併成單一文件 (`FLATTENED.tex`)。我們透過移除註解和附錄來預處理這個合併的檔案。這份預處理後的檔案，連同製作良好簡報的指示，構成了我們的提示詞 (prompt) 基礎。

一個核心理念是使用 Beamer 製作簡報，讓我們能完全留在 LaTeX 生態系中。這個方法實質上將任務轉變成了摘要練習：將冗長的 LaTeX 論文轉換為簡潔的 Beamer LaTeX。LLM 可以從圖片的標題推斷其內容並將其包含在簡報中，因此不需要視覺能力。

為了協助 LLM，我們建立了一個名為 `ADDITIONAL.tex` 的檔案，其中包含所有必要的套件、\newcommand 定義以及論文中使用的其他 LaTeX 設定。將此檔案與 `\input{ADDITIONAL.tex}` 一同放入提示詞中能縮短長度並使簡報生成更可靠，特別是對於具有許多自訂指令的理論論文而言。

LLM 從 LaTeX 原始碼生成 Beamer 程式碼，但由於第一次執行可能存在問題，我們會要求 LLM 自我檢視並改進輸出。可選的第三步是使用 Linter 檢查生成的程式碼，並將結果回傳給 LLM 進行進一步修正（這個 Linter 步驟的靈感來自 [The AI Scientist](https://www.arxiv.org/abs/2408.06292)）。最後，Beamer 程式碼透過 pdflatex 編譯為 PDF 簡報。

統一的 `paper2slides.py` 腳本自動化了整個流程，單篇論文使用 GPT-4.1 通常在幾分鐘內即可完成。

> [!WARNING]
> 此腳本將從網際網路 (arXiv) 下載檔案、傳送資訊給 OpenAI API，並在本地端編譯。請謹慎處理分享的內容與潛在風險。

> [!IMPORTANT]
> 在使用此工具時，請尊重 arXiv 論文的授權條款。arXiv 上的每篇論文都有特定的授權 (CC BY、CC BY-SA、CC BY-NC-SA、CC BY-NC-ND、arXiv 永久授權或 CC Zero) 來規範作品的使用、修改和散布方式。在從任何論文建立和分享簡報之前，請在論文的 arXiv 頁面上檢查其授權，確保您的使用符合條款。欲了解更多資訊，請參見 [arXiv 授權文件](https://info.arxiv.org/help/license/index.html)。
