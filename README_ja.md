# paper2slides-plus

[English](README.md) | [繁體中文](README_zh-TW.md) | [简体中文](README_zh-CN.md) | [日本語](README_ja.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) ![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4.1-412991.svg) ![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg) ![arXiv](https://img.shields.io/badge/arXiv-papers-b31b1b.svg)

本プロジェクトは、オリジナルの [paper2slides](https://github.com/takashiishida/paper2slides) を基盤にさらに開発を進めたものです。原作者である [takashiishida](https://github.com/takashiishida) 氏の貢献に深く感謝します。オリジナルプロジェクトの更新が停止しているため、迅速なアップデートと新機能を提供するためのフォークとして本プロジェクトが作成されました。

## `paper2slides-plus` の新機能

1. **すべてのPDFからスライドへの変換を完全サポート**
2. **単一ページの編集サポート**
3. **正確なLaTeX構文フィードバック修正ループの追加**
4. **博士号レベルのスピーカーノート（発表者用原稿）**
5. **複数の論文のプロジェクト管理**
6. **編集のバージョン管理**
7. **カスタムLLMプロバイダー向けの `BASE_URL` の上書き**
8. **他のアプリケーションと統合するためのAPIバージョン**
9. **Dockerによる簡単なデプロイ**

---

LLMを使用して、任意のarXiv論文やPDFをスライドに変換します！研究論文の主要なアイデアを素早く把握するのに非常に役立ちます。生成されたスライドのいくつかの例は [Demo](demo/) ディレクトリにあります。

## インストール

Python 3.10 以上が必要です。

インストール手順:

1. 本リポジトリをクローンします:

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > `--recursive` フラグなしで既にクローンしている場合は、次のコマンドを実行してサブモジュールを初期化できます:
   > `git submodule update --init --recursive`

2. 必要なPythonパッケージをインストールします（より高速で安全な依存関係解決のために uv の使用を推奨）:

   ```sh
   pip install uv
   uv pip install -r requirements.txt
   ```

   または pip を使用する場合:

   ```sh
   pip install -r requirements.txt
   ```

3. `pdflatex` を含むLaTeXディストリビューションをインストールします。一般的な選択肢:
   - [MikTeX](https://miktex.org/)（Windows に推奨）
   - [TeX Live](https://www.tug.org/texlive/)（クロスプラットフォーム）

   インストール後、LaTeXのバイナリがシステムの PATH に含まれていることを確認してください。

   （オプション）`pdflatex test.tex` を実行して、サンプルの `test.tex` をコンパイルできるか確認してください。`test.pdf` が正しく生成されるか、また `chktex` と `pdfcrop` が機能しているか確認してください。

4. 環境変数（APIキーなど）を設定します:

   `.env.example` を `.env` にコピーし、APIキーと設定を記入してください。

   ```sh
   cp .env.example .env
   ```

## Docker セットアップ

paper2slides は Streamlit Web アプリケーションと REST API サービスの両方に Docker イメージを提供しています。

### Streamlit Web アプリ

ローカルへの LaTeX や Python 依存関係のインストールを避けるために、Web インターフェースに Docker を使用できます。

1. システムに Docker がインストールされていることを確認します。

2. リポジトリをクローンしてディレクトリに移動します:

   ```sh
   git clone --recursive https://github.com/whats2000/paper2slides-plus.git
   cd paper2slides-plus
   ```

   > [!NOTE]
   > `--recursive` フラグなしで既にクローンしている場合は、次のコマンドを実行してサブモジュールを初期化できます:
   > `git submodule update --init --recursive`

3. `.env` ファイルに API キーを設定します（上の構成セクションを参照）。例:

   ```sh
   cp .env.example .env
   # その後、.env を編集してキーを記入します
   ```

4. Docker Compose を使用して Streamlit アプリをビルドおよび実行します:

   ```sh
   docker-compose up paper2slides
   ```

   これにより、Streamlit アプリが `http://localhost:8501` で起動します。

   生成されたファイルを保持するために、`source` および `cache` ディレクトリがボリュームとしてマウントされます。

または、手動でビルドして実行する場合:

```sh
docker build -t paper2slides .
docker run -p 8501:8501 -v $(pwd)/source:/app/source -v $(pwd)/cache:/app/cache -e OPENAI_API_KEY=your-api-key paper2slides
```

### REST API サービス

プログラムからのアクセスや他のアプリケーションとの統合には、FastAPI サービスを使用します。

1. API サービスをビルドおよび実行します:

   ```sh
   docker-compose up paper2slides-api -d
   ```

   これにより、API が `http://localhost:8000` で起動します。

2. `http://localhost:8000/docs`（Swagger UI）または `http://localhost:8000/redoc`（ReDoc）で API ドキュメントにアクセスします。

3. API は以下のためのエンドポイントを提供します:
   - arXiv 論文またはアップロードされた PDF からのスライド生成
   - ジョブ状態の追跡
   - 生成されたスライドのダウンロード（PDF/LaTeX）
   - スライドの編集およびスピーカーノートの生成
   - マルチユーザーワークスペースの分離

## クイックスタート

インストール後、任意の arXiv 論文からスライドを生成できます:

```sh
python paper2slides.py all 2505.18102
```

またはローカルの PDF ファイルから生成する場合:

```sh
python paper2slides.py all --pdf /path/to/your/paper.pdf
```

書籍などの長いドキュメントの場合、ページ範囲を指定して特定の章のみを処理できます:

```sh
# 50〜75ページ（例えば特定の章）を処理する
python paper2slides.py all --pdf /path/to/book.pdf --start-page 50 --end-page 75
```

これにより、論文のダウンロード（または PDF の処理）、スライドの生成、PDF へのコンパイルが自動的に行われ、プレゼンテーションが開きます。

## 使い方

### CLI

`paper2slides.py` スクリプトは、サブコマンドを持つ CLI インターフェースを提供します:

```sh
# arXivからの完全なパイプライン（最も一般的な使い方）
python paper2slides.py all <arxiv_id>

# ローカルPDFからの完全なパイプライン
python paper2slides.py all --pdf /path/to/paper.pdf

# arXivからスライド（beamer）のみを生成
python paper2slides.py generate <arxiv_id>

# ローカルPDFからスライドを生成
python paper2slides.py generate --pdf /path/to/paper.pdf

# 特定のページ範囲からスライドを生成（例えば、書籍の章）
python paper2slides.py generate --pdf /path/to/book.pdf --start-page 50 --end-page 75

# Linter（構文推測）とPDFクロップを使用してスライド（beamer）を生成
python paper2slides.py generate <arxiv_id> --use_linter --use_pdfcrop

# スライド（beamer）をPDFにコンパイル
python paper2slides.py compile <arxiv_id>

# PDFを開かずに完全なパイプラインを実行
python paper2slides.py all <arxiv_id> --no-open
```

`<arxiv_id>` を希望する arXiv 論文IDに置き換えてください。
ID は URL から特定できます: `https://arxiv.org/abs/xxxx.xxxx` の ID は `xxxx.xxxx` です。

ローカルの PDF ファイルの場合は、`--pdf` フラグに続けて PDF ファイルのパスを指定します。

コア機能は、基盤となる `tex2beamer.py` および `beamer2pdf.py` スクリプトで処理されます:

- `tex2beamer.py` は、`arxiv-to-prompt` を使用して arXiv 論文をダウンロードして処理し、OpenAI API 経由で Beamer スライドを生成します。
- `beamer2pdf.py` は、pdflatex を使用して LaTeX スライドを PDF にコンパイルします。

LLM に送信されたプロンプトと応答は `tex2beamer.log` に記録されます。
Linter の出力（`--use_linter` が使用された場合）は `source/<arxiv_id>/linter.log` に保存されます。

### プロンプト

プロンプトは `prompts/config.yaml` 内の YAML ベースのシステムを通じて管理されるようになりました。このファイルには以下が含まれます:

- **テンプレート変数**: `num_slides`、`max_items`、`figure_width` などの共通設定
- **ステージの管理**: `initial`（初期）、`update`（更新）、`revise`（修正）ステージの個別のプロンプト
- **デフォルト値**: 対象者、書式設定、および寸法の構成可能なデフォルト値
- **変数置換**: `{variable}` プレースホルダーの動的な置換

`prompts/config.yaml` を編集してプロンプトをカスタマイズできます。システムは、図のパスの挿入やその他の動的コンテンツを自動的に処理します。`prompts/manager.py` 内の `PromptManager` クラスは、テンプレートのレンダリングと検証を処理します。

### Web UI

Streamlit アプリを実行して、ポイント＆クリックの体験をお楽しみください:

```bash
streamlit run app.py
```

- サイドバーで「arXiv Paper」または「Upload PDF」モードを選択します。
- arXivの場合: サイドバーに arXiv ID（例: 2505.18102）または検索クエリを入力します。
- PDFの場合: コンピュータから直接 PDF ファイルをアップロードします。
  - **ページ範囲の選択**: PDF をアップロードする際、特定のセクション（例: 本の1章）のみを処理するためにオプションでページ範囲を指定できます。これは長い文書に便利です。
- 「Run Full Pipeline」をクリックしてスライドを生成して PDF をコンパイルするか、「Generate Only」/「Compile Only」を使用します。
- パイプラインが完了した後、左側のパネルでスライドを対話的に編集できます。変更は自動的に再コンパイルされます。

## 仕組み

処理は、arXiv 論文のソースファイルのダウンロードから始まります。[arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt) を使用して主要な LaTeX ファイルを特定して展開（flattened）し、すべての入力ファイルを単一のドキュメント（`FLATTENED.tex`）に統合します。コメントと付録を削除することで、このマージされたファイルを前処理します。この前処理されたファイルと、優れたスライドを作成するための指示が、私たちのプロンプトの基盤となります。

1つの重要なアイデアは、スライドの作成に Beamer を使用して、完全に LaTeX エコシステム内に留まることです。このアプローチにより、本質的にタスクは要約の演習になります：長い LaTeX 論文を簡潔な Beamer LaTeX に変換します。LLM はキャプションから図の内容を推測してスライドに含めることができるため、視覚的な能力は必要ありません。

LLM を支援するために、すべての必要なパッケージ、\newcommand 定義、および論文で使用されるその他の LaTeX 設定を含む `ADDITIONAL.tex` というファイルを作成します。プロンプトで `\input{ADDITIONAL.tex}` を含めることでプロンプトが短くなり、特に多くのカスタムコマンドを持つ理論的な論文において、スライドの生成がより確実になります。

LLM は LaTeX ソースから Beamer コードを生成しますが、最初の実行では問題がある可能性があるため、LLM に出力を自己検査して改良するように要求します。オプションの3番目のステップでは、Linter を使用して生成されたコードをチェックし、その結果を LLM にフィードバックしてさらに修正を行います（この Linter ステップは [The AI Scientist](https://www.arxiv.org/abs/2408.06292) に触発されました）。最後に、Beamer コードは pdflatex を使用して PDF プレゼンテーションにコンパイルされます。

統合された `paper2slides.py` スクリプトによってプロセス全体が自動化され、1つの論文については GPT-4.1 を使用して通常数分以内で完了します。

> [!WARNING]
> このスクリプトは、インターネット（arXiv）からファイルをダウンロードし、OpenAI API に情報を送信し、ローカルでコンパイルします。共有されるコンテンツと潜在的なリスクに注意してください。

> [!IMPORTANT]
> このツールを使用する際は、arXiv 論文のライセンスを尊重してください。arXiv の各論文には特定のライセンス（CC BY、CC BY-SA、CC BY-NC-SA、CC BY-NC-ND、arXiv 永久ライセンス、または CC Zero）があり、作品の使用、変更、および配布の方法を規定しています。任意の論文からスライドを作成して共有する前に、arXiv ページのライセンスを確認し、これに準拠していることを確認してください。詳細については、[arXivのライセンスドキュメント](https://info.arxiv.org/help/license/index.html) を参照してください。
