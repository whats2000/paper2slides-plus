"""
paper2slides source package

This package contains the core functionality for converting academic papers
to presentation slides.
"""

from .core import (
    generate_slides,
    generate_slides_from_pdf,
    compile_latex,
    search_arxiv,
    edit_slides,
    edit_single_slide,
    answer_question,
    extract_frames_from_beamer,
    generate_pdf_id,
)
from .history import get_history_manager

__all__ = [
    "generate_slides",
    "generate_slides_from_pdf",
    "compile_latex",
    "search_arxiv",
    "edit_slides",
    "edit_single_slide",
    "answer_question",
    "extract_frames_from_beamer",
    "generate_pdf_id",
    "get_history_manager",
]
