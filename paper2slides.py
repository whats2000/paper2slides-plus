#!/usr/bin/env python3
"""
paper2slides - Unified CLI for generating presentation slides from academic papers

This script provides a unified interface for the paper2slides pipeline with subcommands:
- generate: Generate Beamer slides from arXiv paper (tex2beamer.py)
- compile: Compile LaTeX slides to PDF (beamer2pdf.py)
- all: Full pipeline (generate + compile + open PDF)

Usage examples:
    python paper2slides.py all 2505.18102
    python paper2slides.py generate 2505.18102 --use_linter
    python paper2slides.py compile 2505.18102
"""

import argparse
import logging
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

from src.core import generate_slides_from_pdf, generate_pdf_id

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_command(command: list, description: str, cwd: str = None) -> int:
    """
    Run a command and handle errors gracefully.

    Args:
        command: Command to run as list of strings
        description: Human-readable description for logging
        cwd: Working directory (optional)

    Returns:
        Return code of the command
    """
    logger.info(f"Running: {description}")
    logger.debug(f"Command: {' '.join(command)}")

    try:
        result = subprocess.run(command, cwd=cwd, check=True)
        logger.info(f"✓ {description} completed successfully")
        return result.returncode
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ {description} failed with return code {e.returncode}")
        return e.returncode
    except FileNotFoundError:
        logger.error(f"✗ Command not found: {command[0]}")
        return 1


def open_pdf(pdf_path: str) -> bool:
    """
    Open PDF file using the system's default PDF viewer.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found: {pdf_path}")
        return False

    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", pdf_path], check=True)
        elif system == "Linux":
            subprocess.run(["xdg-open", pdf_path], check=True)
        elif system == "Windows":
            os.startfile(pdf_path)
        else:
            logger.warning(
                f"Unsupported platform: {system}. Cannot open PDF automatically."
            )
            return False

        logger.info(f"✓ Opened PDF: {pdf_path}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to open PDF: {e}")
        return False


def get_arxiv_id(query: str) -> str | None:
    """
    Search for a paper on arXiv and return the selected arXiv ID.
    If the query is already a valid arXiv ID, it returns it directly.
    Otherwise, it performs a search and prompts the user to select from the top 3 results.
    """
    # Regex to check for valid arXiv ID format
    arxiv_id_pattern = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
    if arxiv_id_pattern.match(query):
        logger.info(f"Valid arXiv ID provided: {query}")
        return query

    # Lazy import to avoid requiring arxiv for compile-only usage
    try:
        import arxiv  # type: ignore
    except Exception:
        logger.error(
            "The 'arxiv' package is required for searching by query. Install it with 'pip install arxiv' or provide a direct arXiv ID."
        )
        return None

    logger.info(f"Searching arXiv for: '{query}'")
    try:
        client = arxiv.Client()
        search = arxiv.Search(
            query=query, max_results=3, sort_by=arxiv.SortCriterion.Relevance
        )
        results = list(client.results(search))

        if not results:
            logger.error("No papers found for your query.")
            return None

        print("Found the following papers:")
        for i, result in enumerate(results):
            print(
                f"[{i + 1}] {result.title} (by {', '.join(author.name for author in result.authors)})"
            )

        while True:
            try:
                choice = int(input("Please select a paper (1, 2, or 3): "))
                if 1 <= choice <= len(results):
                    chosen_paper = results[choice - 1]
                    # The arxiv ID is in the pdf_url, e.g., http://arxiv.org/pdf/2305.18290v1 -> 2305.18290
                    return chosen_paper.get_short_id()
                else:
                    print("Invalid choice. Please enter a number between 1 and 3.")
            except ValueError:
                print("Invalid input. Please enter a number.")
    except Exception as e:
        logger.error(f"An error occurred while searching arXiv: {e}")
        return None


def cmd_generate(args) -> int:
    """
    Generate Beamer slides from arXiv paper or local PDF file.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code
    """
    logger.info("=" * 60)

    # Check if PDF file is provided
    if hasattr(args, "pdf") and args.pdf:
        pdf_path = args.pdf
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found: {pdf_path}")
            return 1

        logger.info("GENERATING SLIDES FROM PDF FILE")
        logger.info("=" * 60)

        # Generate a unique ID for the PDF
        paper_id = generate_pdf_id(pdf_path)
        logger.info(f"Generated paper ID: {paper_id}")

        success = generate_slides_from_pdf(
            pdf_path=pdf_path,
            paper_id=paper_id,
            use_linter=args.use_linter if hasattr(args, "use_linter") else False,
            use_pdfcrop=args.use_pdfcrop if hasattr(args, "use_pdfcrop") else False,
            api_key=args.api_key if hasattr(args, "api_key") else None,
            model_name=args.model if hasattr(args, "model") and args.model else None,
            base_url=args.base_url if hasattr(args, "base_url") else None,
            dashscope_base_url=args.dashscope_base_url
            if hasattr(args, "dashscope_base_url")
            else None,
            start_page=getattr(args, "start_page", None),
            end_page=getattr(args, "end_page", None),
        )

        if success:
            logger.info(f"✓ Slides generated successfully in source/{paper_id}/")
            # Store paper_id for compile step
            args.paper_id = paper_id
            return 0
        else:
            logger.error("✗ Slide generation failed")
            return 1

    # Otherwise, handle arXiv paper
    logger.info("GENERATING SLIDES FROM ARXIV PAPER")
    logger.info("=" * 60)

    if not hasattr(args, "arxiv_id"):
        arxiv_id = get_arxiv_id(args.query)
        if not arxiv_id:
            return 1
        args.arxiv_id = arxiv_id  # for compatibility with downstream functions

    # Build tex2beamer command
    command = ["python", "tex2beamer.py", "--arxiv_id", args.arxiv_id]

    if args.use_linter:
        command.append("--use_linter")
    if args.use_pdfcrop:
        command.append("--use_pdfcrop")
    if args.api_key:
        command.append(f"--api_key={args.api_key}")
    if args.model:
        command.append(f"--model={args.model}")

    return run_command(command, "slide generation (tex2beamer.py)")


def cmd_compile(args) -> int:
    """
    Compile LaTeX slides to PDF (wraps beamer2pdf.py).

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code
    """
    logger.info("=" * 60)
    logger.info("COMPILING SLIDES TO PDF")
    logger.info("=" * 60)

    # In compile, we assume the files are already there, so we need an ID.
    # The fuzzy search is for generation. If user wants to compile, they should know the ID.
    command = [
        "python",
        "beamer2pdf.py",
        args.query,
    ]  # Here query should be an arxiv_id
    return run_command(command, "PDF compilation (beamer2pdf.py)")


def cmd_all(args) -> int:
    """
    Run the full pipeline: generate slides + compile to PDF + open PDF.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code
    """
    logger.info("=" * 60)
    logger.info("RUNNING FULL PAPER2SLIDES PIPELINE")
    logger.info("=" * 60)

    # Determine paper_id based on input type
    if hasattr(args, "pdf") and args.pdf:
        # PDF file provided
        if not os.path.exists(args.pdf):
            logger.error(f"PDF file not found: {args.pdf}")
            return 1
        paper_id = generate_pdf_id(args.pdf)
        logger.info(f"Generated paper ID from PDF: {paper_id}")
    else:
        # ArXiv paper
        if not hasattr(args, "arxiv_id"):
            arxiv_id = get_arxiv_id(args.query)
            if not arxiv_id:
                return 1
            args.arxiv_id = arxiv_id
        paper_id = args.arxiv_id

    # Step 1: Generate slides
    exit_code = cmd_generate(args)
    if exit_code != 0:
        logger.error("Pipeline failed at slide generation step")
        return exit_code

    # Update args with paper_id if it was generated from PDF
    if hasattr(args, "paper_id"):
        paper_id = args.paper_id

    # Step 2: Compile to PDF
    # Temporarily set query to paper_id for compile step
    original_query = args.query if hasattr(args, "query") else None
    args.query = paper_id
    exit_code = cmd_compile(args)
    if original_query:
        args.query = original_query

    if exit_code != 0:
        logger.error("Pipeline failed at PDF compilation step")
        return exit_code

    # Step 3: Open PDF (if requested and compilation succeeded)
    if not args.no_open:
        pdf_path = f"source/{paper_id}/slides.pdf"
        open_pdf(pdf_path)

    logger.info("=" * 60)
    logger.info("✓ PIPELINE COMPLETED SUCCESSFULLY")
    logger.info("=" * 60)

    return 0


def create_parser() -> argparse.ArgumentParser:
    """
    Create the argument parser with subcommands.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="paper2slides",
        description="Generate presentation slides from academic papers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from arXiv (default - most common usage)
  python paper2slides.py all 2505.18102

  # Full pipeline from local PDF
  python paper2slides.py all --pdf /path/to/paper.pdf

  # Generate slides only from arXiv
  python paper2slides.py generate 2505.18102

  # Generate slides from PDF with linting
  python paper2slides.py generate --pdf /path/to/paper.pdf --use_linter

  # Compile existing slides to PDF
  python paper2slides.py compile 2505.18102

  # Full pipeline without opening PDF
  python paper2slides.py all 2505.18102 --no-open

Running without subcommand defaults to 'all':
  python paper2slides.py 2505.18102  # same as 'all 2505.18102'
        """,
    )

    # Global options
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Generate subcommand
    parser_generate = subparsers.add_parser(
        "generate",
        help="Generate Beamer slides from arXiv paper or PDF file",
        description="Generate Beamer slides from an arXiv paper or local PDF file using LLM",
    )
    parser_generate.add_argument(
        "query",
        type=str,
        nargs="?",
        default=None,
        help="ArXiv ID or search query for the paper (not needed with --pdf)",
    )
    parser_generate.add_argument(
        "--pdf",
        type=str,
        default=None,
        help="Path to a local PDF file to generate slides from",
    )
    parser_generate.add_argument(
        "--use_linter",
        action="store_true",
        help="Use ChkTeX linter for LaTeX validation",
    )
    parser_generate.add_argument(
        "--use_pdfcrop", action="store_true", help="Use pdfcrop to trim figure margins"
    )
    parser_generate.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="API key to use (overrides env). If omitted, uses OPENAI_API_KEY or DASHSCOPE_API_KEY.",
    )
    parser_generate.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name to use (e.g., gpt-4.1-2025-04-14 or qwen-plus).",
    )
    parser_generate.add_argument(
        "--start-page",
        type=int,
        default=None,
        help="Starting page number for PDF processing (1-indexed, inclusive). Only applicable with --pdf.",
    )
    parser_generate.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Ending page number for PDF processing (1-indexed, inclusive). Only applicable with --pdf.",
    )
    parser_generate.set_defaults(func=cmd_generate)

    # Compile subcommand
    parser_compile = subparsers.add_parser(
        "compile",
        help="Compile LaTeX slides to PDF",
        description="Compile existing Beamer slides to PDF using pdflatex",
    )
    parser_compile.add_argument(
        "query", type=str, help="ArXiv ID (to locate slides.tex in source/ARXIV_ID/)"
    )
    parser_compile.set_defaults(func=cmd_compile)

    # All subcommand (full pipeline)
    parser_all = subparsers.add_parser(
        "all",
        help="Run full pipeline: generate + compile + open PDF",
        description="Complete pipeline: generate slides, compile to PDF, and open result",
    )
    parser_all.add_argument(
        "query",
        type=str,
        nargs="?",
        default=None,
        help="ArXiv ID or search query for the paper (not needed with --pdf)",
    )
    parser_all.add_argument(
        "--pdf",
        type=str,
        default=None,
        help="Path to a local PDF file to generate slides from",
    )
    parser_all.add_argument(
        "--use_linter",
        action="store_true",
        help="Use ChkTeX linter for LaTeX validation",
    )
    parser_all.add_argument(
        "--use_pdfcrop", action="store_true", help="Use pdfcrop to trim figure margins"
    )
    parser_all.add_argument(
        "--no-open", action="store_true", help="Skip opening the PDF after compilation"
    )
    parser_all.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="API key to use (overrides env). If omitted, uses OPENAI_API_KEY or DASHSCOPE_API_KEY.",
    )
    parser_all.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name to use (e.g., gpt-4.1-2025-04-14 or qwen-plus).",
    )
    parser_all.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="Base URL for OpenAI-compatible API (overrides OPENAI_BASE_URL env). Examples: https://api.deepseek.com/v1, http://localhost:8000/v1",
    )
    parser_all.add_argument(
        "--dashscope_base_url",
        type=str,
        default=None,
        help="Base URL for DashScope API (overrides DASHSCOPE_BASE_URL env).",
    )
    parser_all.add_argument(
        "--start-page",
        type=int,
        default=None,
        help="Starting page number for PDF processing (1-indexed, inclusive). Only applicable with --pdf.",
    )
    parser_all.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Ending page number for PDF processing (1-indexed, inclusive). Only applicable with --pdf.",
    )
    parser_all.set_defaults(func=cmd_all)

    return parser


def main():
    """Main entry point."""
    parser = create_parser()

    # Handle convenience: if first arg is not a subcommand or global flag,
    # treat it as arxiv_id for the 'all' command
    if len(sys.argv) > 1 and sys.argv[1] not in [
        "generate",
        "compile",
        "all",
        "-h",
        "--help",
        "--verbose",
        "-v",
    ]:
        # Insert 'all' as the subcommand
        sys.argv.insert(1, "all")

    # If no command specified, show help
    if len(sys.argv) == 1:
        parser.print_help()
        return 1

    # Parse arguments
    args = parser.parse_args()

    # Configure logging level
    if hasattr(args, "verbose") and args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate that the command has a function to call
    if not hasattr(args, "func"):
        parser.print_help()
        return 1

    # Validate that either query or --pdf is provided for generate/all commands
    if hasattr(args, "func") and args.func in [cmd_generate, cmd_all]:
        if not getattr(args, "pdf", None) and not getattr(args, "query", None):
            logger.error(
                "Error: Either provide an arXiv ID/query or use --pdf to specify a PDF file"
            )
            return 1

    # Check if required files exist
    script_dir = Path(__file__).parent
    tex2beamer_path = script_dir / "tex2beamer.py"
    beamer2pdf_path = script_dir / "beamer2pdf.py"

    if args.command in ["generate", "all"] and not tex2beamer_path.exists():
        logger.error(f"Required file not found: {tex2beamer_path}")
        return 1

    if args.command in ["compile", "all"] and not beamer2pdf_path.exists():
        logger.error(f"Required file not found: {beamer2pdf_path}")
        return 1

    # Execute the command
    try:
        return args.func(args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
