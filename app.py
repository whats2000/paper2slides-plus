import base64
import datetime
import logging
import os
import re
import tempfile
import shutil
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from dotenv import load_dotenv

from src.core import (
    generate_slides,
    generate_slides_from_pdf,
    generate_slides_from_latex_zip,
    compile_latex,
    search_arxiv,
    edit_slides,
    edit_single_slide,
    extract_frames_from_beamer,
    get_frame_by_number,
    replace_frame_in_beamer,
    generate_pdf_id,
    generate_speaker_notes,
    save_speaker_notes,
    load_speaker_notes,
)
from src.beamer_utils import get_preamble, replace_preamble
from src.history import get_history_manager


def extract_title_from_latex(latex_file_path: str) -> str:
    """
    Extract the title from a LaTeX file.
    Looks for \title[short]{full} or \title{full} patterns.
    
    Args:
        latex_file_path: Path to the LaTeX file
        
    Returns:
        The extracted title, or the filename if title not found
    """
    try:
        with open(latex_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for \title command
        title_match = re.search(r'\\title(?:\[[^\]]*\])?\{([^}]+)\}', content)
        if title_match:
            title = title_match.group(1)
            # Clean up LaTeX commands and extra whitespace
            title = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', title)  # Remove LaTeX commands
            title = re.sub(r'\\[a-zA-Z]+', '', title)  # Remove simple LaTeX commands
            title = title.strip()
            return title
        
        return None
    except Exception as e:
        logging.warning(f"Failed to extract title from {latex_file_path}: {e}")
        return None


def get_existing_projects():
    """
    Scan the source directory for existing projects.
    Returns a list of dictionaries with project information.
    """
    source_dir = Path("source")
    if not source_dir.exists():
        return []
    
    projects = []
    for project_dir in source_dir.iterdir():
        if project_dir.is_dir():
            slides_tex = project_dir / "slides.tex"
            slides_pdf = project_dir / "slides.pdf"
            
            if slides_tex.exists():
                # Extract title from the LaTeX file
                title = extract_title_from_latex(str(slides_tex))
                
                project_info = {
                    "id": project_dir.name,
                    "title": title,
                    "has_tex": True,
                    "has_pdf": slides_pdf.exists(),
                    "pdf_path": str(slides_pdf) if slides_pdf.exists() else None,
                    "tex_path": str(slides_tex),
                    "modified_time": slides_tex.stat().st_mtime if slides_tex.exists() else 0,
                }
                projects.append(project_info)
    
    # Sort by modification time (newest first)
    projects.sort(key=lambda x: x["modified_time"], reverse=True)
    return projects


def get_single_page_edit_source(beamer_code: str, frame_number: int) -> tuple[str | None, str, str]:
    """
    Extract single-page edit source using the same logic as AI single-slide editing.

    Page 1 maps to preamble editing; other pages map to frame extraction.
    Returns (source_content, editor_label, editor_help).
    """
    if frame_number == 1:
        return (
            get_preamble(beamer_code),
            "Slide 1 source (preamble)",
            "For slide 1, manual edits apply to the preamble (title/author/theme configuration).",
        )

    return (
        get_frame_by_number(beamer_code, frame_number),
        f"Slide {frame_number} source",
        "Manual edits apply only to the currently selected slide source.",
    )


def apply_single_page_source_edit(beamer_code: str, frame_number: int, edited_source: str) -> str | None:
    """
    Apply single-page source edits using the same replacement logic as AI single-slide editing.

    Page 1 updates preamble; other pages replace the selected frame.
    """
    if frame_number == 1:
        return replace_preamble(beamer_code, edited_source)

    return replace_frame_in_beamer(beamer_code, frame_number, edited_source)


def get_current_viewer_page(total_frames: int | None = None) -> int:
    """
    Resolve the current page from viewer state for editing context.

    Prefer the slider value when available, and keep selected_frame_number synchronized.
    """
    current_page = st.session_state.get(
        "pdf_page_slider",
        st.session_state.get("selected_frame_number", 1),
    )

    if total_frames and total_frames > 0:
        current_page = max(1, min(int(current_page), total_frames))
    else:
        current_page = max(1, int(current_page))

    st.session_state.selected_frame_number = current_page
    return current_page


def append_chat_message(role: str, content: str, display: bool = True):
    """
    Append a message to the chat history and optionally display it.
    
    Args:
        role: The role of the message sender ("user" or "assistant")
        content: The content of the message
        display: Whether to display the message immediately (default True)
    """
    st.session_state.messages.append({"role": role, "content": content})
    if display:
        with st.chat_message(role):
            st.markdown(content)


def display_pdf(file_path):
    with open(file_path, "rb") as f:
        base64_pdf = base64.b64encode(f.read()).decode("utf-8")
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)


def display_pdf_as_images(file_path: str, paper_id: str = None, enable_inline_edit: bool = False):
    """
    Display PDF as images with optional inline editing and speaker notes.
    
    Args:
        file_path: Path to the PDF file
        paper_id: Paper ID for editing (required if enable_inline_edit is True)
        enable_inline_edit: Whether to show inline edit boxes beside each page
    """
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        st.error(f"Failed to open PDF: {e}")
        return None

    page_count = doc.page_count
    st.caption(f"Total Pages: {page_count}")
    
    # Load speaker notes if available
    speaker_notes = None
    if paper_id:
        speaker_notes = load_speaker_notes(paper_id)

    # Heuristic: render all if small doc, otherwise let user choose
    render_all_default = page_count <= 15
    render_all = st.checkbox("Display all pages", value=render_all_default)

    zoom = 2.0
    mat = fitz.Matrix(zoom, zoom)

    if render_all:
        # Full display mode with inline edit boxes
        for i in range(page_count):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            if enable_inline_edit:
                # Create two columns: one for image, one for edit box
                col_img, col_edit = st.columns([3, 1])
                with col_img:
                    st.image(pix.tobytes("png"), width='stretch', caption=f"Page {i+1}")
                with col_edit:
                    st.markdown(f"**Edit Page {i+1}**")
                    edit_instruction = st.text_area(
                        "Quick edit:",
                        key=f"edit_page_{i+1}",
                        placeholder="Enter edit instruction...",
                        label_visibility="collapsed",
                        height=100
                    )
                    if st.button("✏️ Edit", key=f"btn_edit_{i+1}", width='stretch'):
                        if edit_instruction.strip():
                            # Store edit request in session state
                            st.session_state.pending_edit = {
                                "frame_number": i + 1,
                                "instruction": edit_instruction,
                                "mode": "single"
                            }
                            st.rerun()
            else:
                st.image(pix.tobytes("png"), width='stretch', caption=f"Page {i+1}")
    else:
        # Single page display mode - the slider determines which page to edit
        default_page = st.session_state.get("selected_frame_number", 1)
        default_page = min(default_page, page_count)
        
        page_num = st.slider(
            "Page", 
            min_value=1, 
            max_value=page_count, 
            value=default_page,
            key="pdf_page_slider"
        )
        
        # Update selected frame number to match slider
        st.session_state.selected_frame_number = page_num
        
        page = doc.load_page(page_num - 1)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        st.image(pix.tobytes("png"), width='stretch', caption=f"Page {page_num}")
        
        # Display speaker notes in single page mode
        if speaker_notes is not None and paper_id:
            current_notes = speaker_notes.get(page_num, "")
            
            edited_notes = st.text_area(
                f"Speaker notes for slide {page_num}",
                value=current_notes,
                height=250,
                key=f"speaker_notes_{page_num}",
                placeholder="Speaker notes will appear here after generation. You can also edit them manually.",
                help="These notes provide supplementary information for the presenter."
            )
            
            # Save button for edited notes
            if edited_notes != current_notes:
                if st.button("💾 Save Notes", key=f"save_notes_{page_num}"):
                    speaker_notes[page_num] = edited_notes
                    if save_speaker_notes(speaker_notes, paper_id):
                        st.success("Notes saved!")
                        st.rerun()
                    else:
                        st.error("Failed to save notes")

    doc.close()
    return page_count


def get_arxiv_id_from_query(query: str) -> str | None:
    """
    Resolve query to arxiv_id, similar to paper2slides.py get_arxiv_id function.
    If query is already a valid arXiv ID, return it directly.
    Otherwise, perform search and let user select from results.
    """
    # Regex to check for valid arXiv ID format
    arxiv_id_pattern = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
    if arxiv_id_pattern.match(query):
        logging.info(f"Valid arXiv ID provided: {query}")
        return query

    # If not a direct ID, we need to search and let user choose
    # This will be handled by the UI search flow
    return None


def run_generate_step(paper_id: str, api_key: str, model_name: str, pdf_path: str | None = None, start_page: int | None = None, end_page: int | None = None, use_linter: bool = False, latex_zip_path: str | None = None) -> bool:
    """
    Step 1: Generate slides from arXiv paper, local PDF, or LaTeX zip

    Args:
        paper_id: arXiv ID or generated ID for uploaded PDF/zip
        api_key: API key for LLM
        model_name: Model name
        pdf_path: Path to uploaded PDF file (None for arXiv papers / zip uploads)
        start_page: Starting page number (1-indexed, inclusive) for PDF processing
        end_page: Ending page number (1-indexed, inclusive) for PDF processing
        use_linter: Whether to enable the linter for auto-fixing LaTeX issues (default False)
        latex_zip_path: Path to uploaded LaTeX zip file (None for arXiv/PDF sources)
    """
    logging.info("=" * 60)
    if latex_zip_path:
        logging.info("GENERATING SLIDES FROM UPLOADED LATEX ZIP")
    elif pdf_path:
        logging.info("GENERATING SLIDES FROM UPLOADED PDF")
        if start_page or end_page:
            logging.info(f"Page range: {start_page or 1} to {end_page or 'end'}")
    else:
        logging.info("GENERATING SLIDES FROM ARXIV PAPER")
    logging.info("=" * 60)

    if latex_zip_path:
        success = generate_slides_from_latex_zip(
            zip_path=latex_zip_path,
            paper_id=paper_id,
            use_linter=use_linter,
            api_key=api_key,
            model_name=model_name,
            base_url=st.session_state.openai_base_url if st.session_state.openai_base_url else None,
        )
    elif pdf_path:
        success = generate_slides_from_pdf(
            pdf_path=pdf_path,
            paper_id=paper_id,
            use_linter=use_linter,
            use_pdfcrop=False,
            api_key=api_key,
            model_name=model_name,
            base_url=st.session_state.openai_base_url if st.session_state.openai_base_url else None,
            start_page=start_page,
            end_page=end_page,
        )
    else:
        success = generate_slides(
            arxiv_id=paper_id,
            use_linter=use_linter,
            use_pdfcrop=False,
            api_key=api_key,
            model_name=model_name,
            base_url=st.session_state.openai_base_url if st.session_state.openai_base_url else None,
        )

    if success:
        logging.info("✓ Slide generation completed successfully")
    else:
        logging.error("✗ Slide generation failed")

    return success


def run_compile_step(paper_id: str, pdflatex_path: str, save_history: bool = True) -> bool:
    """
    Step 2: Compile LaTeX slides to PDF (equivalent to cmd_compile)
    
    Args:
        paper_id: Paper ID
        pdflatex_path: Path to pdflatex compiler
        save_history: Whether to save version history after successful compile (default True)
    """
    logging.info("=" * 60)
    logging.info("COMPILING SLIDES TO PDF")
    logging.info("=" * 60)

    success = compile_latex(
        tex_file_path="slides.tex",
        output_directory=f"source/{paper_id}/",
        pdflatex_path=pdflatex_path,
        save_history=save_history,
    )

    if success:
        logging.info("✓ PDF compilation completed successfully")
    else:
        logging.error("✗ PDF compilation failed")

    return success


def ensure_initial_history(paper_id: str) -> None:
    """
    Ensure that an initial history version exists for a project.
    If no history exists yet, save the current slides.tex as the initial version.
    
    Args:
        paper_id: The paper ID
    """
    try:
        history = get_history_manager(paper_id)
        if not history.has_history():
            # No history exists yet - save initial version
            slides_tex_path = f"source/{paper_id}/slides.tex"
            if os.path.exists(slides_tex_path):
                with open(slides_tex_path, 'r', encoding='utf-8') as f:
                    tex_content = f.read()
                history.save_version(tex_content, "Initial version (before edits)")
                logging.info("Saved initial version to history")
    except Exception as e:
        logging.warning(f"Failed to ensure initial history: {e}")


def run_full_pipeline(
    paper_id: str,
    api_key: str,
    model_name: str,
    pdflatex_path: str,
    pdf_path: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> bool:
    """
    Full pipeline: generate + compile (equivalent to cmd_all, minus opening PDF)
    
    Args:
        paper_id: arXiv ID or generated ID for uploaded PDF
        api_key: API key for LLM
        model_name: Model name
        pdflatex_path: Path to pdflatex compiler
        pdf_path: Path to uploaded PDF file (None for arXiv papers)
        start_page: Starting page number (1-indexed, inclusive) for PDF processing
        end_page: Ending page number (1-indexed, inclusive) for PDF processing
    """
    logging.info("=" * 60)
    logging.info("RUNNING FULL PAPER2SLIDES PIPELINE")
    logging.info("=" * 60)

    # Step 1: Generate slides
    if not run_generate_step(paper_id, api_key, model_name, pdf_path, start_page, end_page, use_linter=True):
        logging.error("Pipeline failed at slide generation step")
        return False

    # Step 2: Compile to PDF
    if not run_compile_step(paper_id, pdflatex_path):
        logging.error("Pipeline failed at PDF compilation step")
        return False

    # Step 3: Verify PDF exists (we don't auto-open in webui)
    pdf_output_path = f"source/{paper_id}/slides.pdf"
    if os.path.exists(pdf_output_path):
        logging.info("=" * 60)
        logging.info("✓ PIPELINE COMPLETED SUCCESSFULLY")
        logging.info("=" * 60)
        return True
    else:
        logging.error("PDF not found after compilation")
        return False


def main():
    st.set_page_config(layout="wide")

    st.title("📄 Paper2Slides")

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "arxiv_id" not in st.session_state:
        st.session_state.arxiv_id = None
    if "paper_id" not in st.session_state:
        st.session_state.paper_id = None
    if "uploaded_pdf_path" not in st.session_state:
        st.session_state.uploaded_pdf_path = None
    if "latex_zip_path" not in st.session_state:
        st.session_state.latex_zip_path = None
    if "input_mode" not in st.session_state:
        st.session_state.input_mode = "arxiv"  # "arxiv", "upload", "latex_zip", or "load"
    if "pdf_path" not in st.session_state:
        st.session_state.pdf_path = None
    if "pipeline_status" not in st.session_state:
        st.session_state.pipeline_status = (
            "ready"  # ready, generating, compiling, completed, failed
        )
    if "pdflatex_path" not in st.session_state:
        st.session_state.pdflatex_path = "pdflatex"
    if "openai_api_key" not in st.session_state:

        load_dotenv(override=True)
        st.session_state.openai_api_key = os.getenv("OPENAI_API_KEY", "")
    if "model_name" not in st.session_state:
        load_dotenv(override=True)
        st.session_state.model_name = os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")
    if "openai_base_url" not in st.session_state:
        load_dotenv(override=True)
        st.session_state.openai_base_url = os.getenv("OPENAI_BASE_URL", "")

    if "paper_title" not in st.session_state:
        st.session_state.paper_title = None
    if "paper_authors" not in st.session_state:
        st.session_state.paper_authors = None

    if "run_full_pipeline" not in st.session_state:
        st.session_state.run_full_pipeline = False
    
    # Single-slide editing mode
    if "edit_mode" not in st.session_state:
        st.session_state.edit_mode = "single"  # "single" or "full"
    if "selected_frame_number" not in st.session_state:
        st.session_state.selected_frame_number = 1
    if "total_frames" not in st.session_state:
        st.session_state.total_frames = 0
    if "pending_edit" not in st.session_state:
        st.session_state.pending_edit = None
        st.session_state.total_frames = 0
    
    # Page range for PDF processing
    if "pdf_start_page" not in st.session_state:
        st.session_state.pdf_start_page = None
    if "pdf_end_page" not in st.session_state:
        st.session_state.pdf_end_page = None

    # Configure logger
    if "logger_configured" not in st.session_state:
        logger = logging.getLogger()
        if not logger.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
        st.session_state.logger_configured = True

    # Sidebar for paper search and settings
    with st.sidebar:
        st.header("Paper Input")
        
        # Input mode selection
        input_mode = st.radio(
            "Choose input method:",
            options=["arXiv Paper", "Upload PDF", "Upload LaTeX ZIP", "Load Previous Project"],
            index=(
                0 if st.session_state.input_mode == "arxiv" else
                1 if st.session_state.input_mode == "upload" else
                2 if st.session_state.input_mode == "latex_zip" else
                3
            ),
            key="input_mode_radio"
        )
        
        new_mode = (
            "arxiv" if input_mode == "arXiv Paper" else
            "upload" if input_mode == "Upload PDF" else
            "latex_zip" if input_mode == "Upload LaTeX ZIP" else
            "load"
        )
        if new_mode != st.session_state.input_mode:
            # Clear source paths that belong to the previous mode
            st.session_state.uploaded_pdf_path = None
            st.session_state.latex_zip_path = None
            st.session_state.arxiv_id = None
            st.session_state.paper_id = None
            st.session_state.pdf_path = None
            st.session_state.pipeline_status = "ready"
            st.session_state.messages = []
            st.session_state.input_mode = new_mode
        
        if st.session_state.input_mode == "arxiv":
            # arXiv search
            query = st.text_input("Enter arXiv ID or search query:", key="query_input")
            
            if st.button("Search Papers", key="search_button"):
                st.session_state.arxiv_id = None
                st.session_state.paper_id = None
                st.session_state.uploaded_pdf_path = None
                st.session_state.pdf_path = None
                st.session_state.messages = []
                st.session_state.pipeline_status = "ready"
                st.session_state.paper_title = None
                st.session_state.paper_authors = None

                # Check if query is direct arxiv_id or needs search
                direct_id = get_arxiv_id_from_query(query)
                if direct_id:
                    results = search_arxiv(direct_id)
                    if results and len(results) == 1:
                        result = results[0]
                        st.session_state.arxiv_id = result.get_short_id()
                        st.session_state.paper_id = result.get_short_id()
                        st.session_state.paper_title = result.title
                        st.session_state.paper_authors = [a.name for a in result.authors]
                    else:
                        st.warning("Invalid arXiv ID or paper not found.")
                else:
                    results = search_arxiv(query)
                    if results:
                        st.session_state.search_results = results
                    else:
                        st.warning("No papers found.")

            # Show search results for selection
            if "search_results" in st.session_state:
                st.subheader("Search Results")
                for i, result in enumerate(st.session_state.search_results):
                    if st.button(
                        f"**{result.title[:60]}...** by {result.authors[0].name} et al.",
                        key=f"select_{i}",
                    ):
                        st.session_state.arxiv_id = result.get_short_id()
                        st.session_state.paper_id = result.get_short_id()
                        st.session_state.paper_title = result.title
                        st.session_state.paper_authors = [a.name for a in result.authors]
                        del st.session_state.search_results
                        st.rerun()
            
            # Show selected paper info
            if st.session_state.arxiv_id and 'paper_title' in st.session_state:
                st.success(f"Selected: **{st.session_state.paper_title}** by {st.session_state.paper_authors[0]} et al.")
        
        elif st.session_state.input_mode == "upload":
            # PDF upload
            uploaded_file = st.file_uploader(
                "Upload a PDF file",
                type=["pdf"],
                key="pdf_uploader"
            )
            
            if uploaded_file is not None and ("uploaded_file_name" not in st.session_state or st.session_state.uploaded_file_name != uploaded_file.name):
                # Save uploaded file to a temporary location
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name
                
                # Generate a unique ID for this PDF
                paper_id = generate_pdf_id(tmp_path)
                
                # Update session state
                st.session_state.uploaded_pdf_path = tmp_path
                st.session_state.paper_id = paper_id
                st.session_state.arxiv_id = None
                st.session_state.pdf_path = None
                st.session_state.messages = []
                st.session_state.pipeline_status = "ready"
                st.session_state.uploaded_file_name = uploaded_file.name
                
                st.success(f"PDF uploaded successfully! ID: {paper_id}")
            
            # Page range selection (only show if a PDF is uploaded)
            if uploaded_file is not None:
                st.subheader("📖 Page Range (Optional)")
                st.caption("Specify a page range for processing long documents (e.g., a specific chapter). Leave empty to process the entire PDF.")
                
                # Get total pages from the PDF
                if st.session_state.uploaded_pdf_path:
                    try:
                        doc = fitz.open(st.session_state.uploaded_pdf_path)
                        total_pages = len(doc)
                        doc.close()
                        st.info(f"Total pages in PDF: {total_pages}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            start_page = st.number_input(
                                "Start Page",
                                min_value=1,
                                max_value=total_pages,
                                value=None,
                                placeholder="1",
                                help="First page to process (1-indexed). Leave empty to start from page 1.",
                                key="start_page_input"
                            )
                        with col2:
                            end_page = st.number_input(
                                "End Page",
                                min_value=1,
                                max_value=total_pages,
                                value=None,
                                placeholder=f"{total_pages}",
                                help="Last page to process (1-indexed, inclusive). Leave empty to process until the last page.",
                                key="end_page_input"
                            )
                        
                        # Validate page range
                        if start_page is not None and end_page is not None and start_page > end_page:
                            st.error("⚠️ Start page must be less than or equal to end page.")
                        else:
                            st.session_state.pdf_start_page = start_page
                            st.session_state.pdf_end_page = end_page
                            if start_page or end_page:
                                st.success(f"✓ Will process pages {start_page or 1} to {end_page or total_pages}")
                    except Exception as e:
                        st.error(f"Failed to read PDF: {e}")
        
        elif st.session_state.input_mode == "latex_zip":
            # LaTeX project ZIP upload — same pipeline as arXiv, just from a local source
            uploaded_zip = st.file_uploader(
                "Upload a LaTeX project zip",
                type=["zip"],
                key="latex_zip_uploader",
                help="Upload a .zip containing a LaTeX project with a main .tex file (\\documentclass). Images/figures inside the zip are copied automatically.",
            )

            if uploaded_zip is not None and (
                "uploaded_zip_name" not in st.session_state
                or st.session_state.uploaded_zip_name != uploaded_zip.name
            ):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
                    tmp_file.write(uploaded_zip.getvalue())
                    tmp_zip_path = tmp_file.name

                # Derive a stable paper_id from the zip's content hash
                import hashlib
                zip_hash = hashlib.sha256(uploaded_zip.getvalue()).hexdigest()[:12]
                paper_id = f"zip_{zip_hash}"

                st.session_state.latex_zip_path = tmp_zip_path
                st.session_state.paper_id = paper_id
                st.session_state.arxiv_id = None
                st.session_state.uploaded_pdf_path = None
                st.session_state.pdf_path = None
                st.session_state.messages = []
                st.session_state.pipeline_status = "ready"
                st.session_state.uploaded_zip_name = uploaded_zip.name

                st.success(f"ZIP uploaded! ID: {paper_id}")

            if st.session_state.latex_zip_path:
                st.info(f"📦 {st.session_state.get('uploaded_zip_name', 'zip file')} ready")

        else:
            # Load previous project
            existing_projects = get_existing_projects()
            
            if not existing_projects:
                st.info("No previous projects found. Generate slides from an arXiv paper or uploaded PDF first.")
            else:
                st.subheader("Select a Previous Project")
                st.caption(f"Found {len(existing_projects)} project(s)")
                
                # Create options for the selectbox with formatted display
                project_options = {}
                for project in existing_projects:
                    status_icon = "✅" if project["has_pdf"] else "📝"
                    status_text = "Ready" if project["has_pdf"] else "Needs compilation"
                    mod_time = datetime.datetime.fromtimestamp(project["modified_time"])
                    time_str = mod_time.strftime("%Y-%m-%d %H:%M")
                    
                    # Use title if available, otherwise fall back to ID
                    display_name = project.get("title") or project["id"]
                    display_text = f"{status_icon} {display_name} ({status_text}, {time_str})"
                    project_options[display_text] = project
                
                # Add a placeholder option
                options_list = ["-- Select a project --"] + list(project_options.keys())
                
                selected_display = st.selectbox(
                    "Choose a project:",
                    options=options_list,
                    key="project_selector",
                    help="Select a previous project to load and edit. Projects are sorted by modification time (newest first)."
                )
                
                # Load/Remove buttons
                if selected_display != "-- Select a project --":
                    col1, col2 = st.columns([5, 1])
                    with col1:
                        if st.button("📂 Load Selected Project", key="load_project_btn", use_container_width=True):
                            project = project_options[selected_display]
                            
                            # Load the project
                            st.session_state.paper_id = project["id"]
                            st.session_state.arxiv_id = None
                            st.session_state.uploaded_pdf_path = None
                            st.session_state.messages = []
                            
                            if project["has_pdf"]:
                                # Project is ready for editing
                                st.session_state.pipeline_status = "completed"
                                st.session_state.pdf_path = project["pdf_path"]
                                
                                # Ensure initial history exists when loading project
                                ensure_initial_history(project["id"])
                            else:
                                # Project needs compilation
                                st.session_state.pipeline_status = "ready"
                                st.session_state.pdf_path = None
                            
                            st.rerun()
                    with col2:
                        with st.popover("🗑️", help="Remove this project", use_container_width=True):
                            st.write("Confirm deletion?")
                            project = project_options[selected_display]
                            if st.button("Delete", type="primary", key=f"confirm_remove_{project['id']}", use_container_width=True):
                                project_dir = os.path.join("source", project["id"])
                                if os.path.exists(project_dir):
                                    shutil.rmtree(project_dir)
                                    st.rerun()

        st.header("Pipeline Settings")
        st.session_state.openai_api_key = st.text_input(
            "API Key (OpenAI or DashScope)",
            type="password",
            value=st.session_state.openai_api_key,
        )
        st.caption(
            "If left empty, keys from .env are used: OPENAI_API_KEY > DASHSCOPE_API_KEY."
        )
        st.session_state.model_name = st.text_input(
            "Model Name (e.g., gpt-4.1-2025-04-14 or qwen-plus)",
            value=st.session_state.model_name,
        )
        st.caption(
            "Default model from .env (DEFAULT_MODEL). Can be overridden here."
        )
        st.session_state.openai_base_url = st.text_input(
            "Base URL (e.g., https://api.openai.com/v1)",
            value=st.session_state.openai_base_url,
            placeholder="https://api.openai.com/v1"
        )
        st.caption(
            "Default base URL from .env (OPENAI_BASE_URL). Leave empty to use .env value, or default OpenAI API if not set."
        )
        st.session_state.pdflatex_path = st.text_input(
            "Path to pdflatex compiler", value=st.session_state.pdflatex_path
        )

        # Pipeline control buttons
        st.header("Pipeline Control")

        # Pipeline execution buttons (only show if paper_id is selected)
        if st.session_state.paper_id:
            if st.session_state.input_mode == "arxiv":
                st.success(f"Selected arXiv: {st.session_state.paper_id}")
            elif st.session_state.input_mode == "upload":
                st.success(f"Selected PDF: {st.session_state.paper_id}")
            elif st.session_state.input_mode == "latex_zip":
                st.success(f"Selected ZIP: {st.session_state.paper_id}")
            else:
                st.success(f"Loaded Project: {st.session_state.paper_id}")

            # Only allow running if not currently processing
            can_run = st.session_state.pipeline_status in [
                "ready",
                "completed",
                "failed",
            ]
            
            # Disable generation buttons if in "load" mode (project already exists)
            is_loaded_project = st.session_state.input_mode == "load"

            if st.button(
                "🚀 Run Full Pipeline",
                key="run_full",
                disabled=not can_run or is_loaded_project,
                help="Generate slides + Compile PDF (equivalent to 'python paper2slides.py all <arxiv_id>')" if not is_loaded_project else "Disabled: Project already exists. Use 'Compile Only' if needed.",
            ):
                st.session_state.pipeline_status = "generating"
                st.session_state.pdf_path = None
                st.session_state.run_full_pipeline = True
                st.rerun()

            col1, col2 = st.columns(2)
            with col1:
                if st.button(
                    "📝 Generate Only",
                    key="run_generate",
                    disabled=not can_run or is_loaded_project,
                    help="Generate slides only (equivalent to 'python paper2slides.py generate <arxiv_id>')" if not is_loaded_project else "Disabled: Project already exists.",
                ):
                    st.session_state.pipeline_status = "generating"
                    st.session_state.pdf_path = None
                    st.session_state.run_full_pipeline = False
                    st.rerun()

            with col2:
                slides_exist = os.path.exists(
                    f"source/{st.session_state.paper_id}/slides.tex"
                )
                if st.button(
                    "🔨 Compile Only",
                    key="run_compile",
                    disabled=not can_run or not slides_exist,
                    help="Compile existing slides to PDF (equivalent to 'python paper2slides.py compile <paper_id>')",
                ):
                    st.session_state.pipeline_status = "compiling"
                    st.session_state.run_full_pipeline = False
                    st.rerun()

    # Main area for chat and PDF viewer
    col1, col2 = st.columns(2)

    with col1:
        st.header("Interactive Editing")

        # Only allow editing if pipeline is completed and PDF exists
        if (
            st.session_state.pipeline_status == "completed"
            and st.session_state.paper_id
            and os.path.exists(f"source/{st.session_state.paper_id}/slides.tex")
        ):
            # Ensure initial history exists before showing editing UI
            ensure_initial_history(st.session_state.paper_id)
            
            # Version History Section
            history = get_history_manager(st.session_state.paper_id)
            versions = history.list_versions()
            
            if versions:
                with st.expander(f"📜 Version History ({len(versions)} saved versions)", expanded=False):
                    st.caption("Versions are automatically saved after each successful compile. Click any version to restore it.")
                    
                    # Track which version is currently loaded (default to latest if not set)
                    current_version_key = f"current_version_{st.session_state.paper_id}"
                    if current_version_key not in st.session_state and versions:
                        st.session_state[current_version_key] = versions[0]['filename']
                    
                    for idx, version in enumerate(versions):
                        # Parse timestamp for display
                        try:
                            ts = datetime.datetime.fromisoformat(version['timestamp'])
                            time_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            time_str = version['timestamp']
                        
                        # Check if this is the currently loaded version
                        is_current = st.session_state.get(current_version_key) == version['filename']
                        
                        col_info, col_btn = st.columns([3, 1])
                        with col_info:
                            if is_current:
                                st.markdown(f"**✅ Active:** {time_str}")
                            elif idx == 0:
                                st.markdown(f"**Latest:** {time_str}")
                            else:
                                st.markdown(f"**{idx + 1}.** {time_str}")
                            st.caption(version['description'])
                        
                        with col_btn:
                            # Show restore button for all versions except the current one
                            if not is_current:
                                if st.button("Restore", key=f"restore_{version['filename']}"):
                                    slides_tex_path = f"source/{st.session_state.paper_id}/slides.tex"
                                    if history.restore_version(version['filename'], slides_tex_path):
                                        # Update the current version tracker
                                        st.session_state[current_version_key] = version['filename']
                                        
                                        st.success("✅ Restored! Recompiling...")
                                        # Recompile after restore WITHOUT saving to history (to avoid duplicate)
                                        if run_compile_step(
                                            st.session_state.paper_id,
                                            st.session_state.pdflatex_path,
                                            save_history=False  # Don't save history when restoring
                                        ):
                                            st.session_state.pdf_path = (
                                                f"source/{st.session_state.paper_id}/slides.pdf"
                                            )
                                            st.rerun()
                                        else:
                                            st.error("Failed to recompile after restore.")
                                    else:
                                        st.error("Failed to restore version.")
                            else:
                                st.caption("📍 Current")

                            # Delete (two-step confirm) - but protect initial version and current version
                            # The initial version is always the last in the list (oldest)
                            is_initial = (idx == len(versions) - 1) and version['description'].startswith("Initial version")
                            
                            if not is_initial and not is_current:
                                delete_key = f"delete_pending_{version['filename']}"
                                if st.session_state.get(delete_key):
                                    st.write("⚠️ Confirm delete?")
                                    if st.button("Confirm", key=f"confirm_delete_{version['filename']}", width='stretch'):
                                        if history.delete_version(version['filename']):
                                            st.success("Deleted.")
                                        else:
                                            st.error("Failed to delete.")
                                        # Clear the pending flag and refresh
                                        st.session_state[delete_key] = False
                                        st.rerun()
                                    if st.button("Cancel", key=f"cancel_delete_{version['filename']}", width='stretch'):
                                        st.session_state[delete_key] = False
                                        st.rerun()
                                else:
                                    if st.button("Delete", key=f"delete_{version['filename']}", width='stretch'):
                                        st.session_state[delete_key] = True
                            elif is_initial:
                                # Initial version - show a lock icon
                                st.caption("🔒")
                        
                        if idx < len(versions) - 1:
                            st.divider()

                    # Clear-all history control (two-step confirm)
                    st.divider()
                    clear_key = f"clear_history_pending_{st.session_state.paper_id}"
                    if st.button("Clear all saved versions", key=f"clear_all_{st.session_state.paper_id}"):
                        st.session_state[clear_key] = True

                    if st.session_state.get(clear_key):
                        st.warning("⚠️ This will permanently delete all saved working versions for this project. The initial version and currently active version will be preserved.")
                        if st.button("Confirm clear all", key=f"confirm_clear_{st.session_state.paper_id}"):
                            # Get current version to preserve
                            current_version_key = f"current_version_{st.session_state.paper_id}"
                            current_version = st.session_state.get(current_version_key)
                            
                            if history.clear_history(preserve_current=current_version):
                                st.success("All saved working versions deleted. Initial and current versions preserved.")
                            else:
                                st.error("Failed to clear history.")
                            st.session_state[clear_key] = False
                            st.rerun()
                        if st.button("Cancel", key=f"cancel_clear_{st.session_state.paper_id}"):
                            st.session_state[clear_key] = False
                            st.rerun()
            
            st.divider()
            
            # Read slides to get total frame count
            slides_tex_path = f"source/{st.session_state.paper_id}/slides.tex"
            with open(slides_tex_path, "r", encoding='utf8') as f:
                beamer_code = f.read()
            
            frames = extract_frames_from_beamer(beamer_code)
            st.session_state.total_frames = len(frames)
            
            # Edit mode selection
            st.subheader("Edit Mode")
            edit_mode = st.radio(
                "Choose editing scope:",
                options=["Edit Current Page", "Edit All Slides"],
                index=0 if st.session_state.get("edit_mode", "single") == "single" else 1,
                key="edit_mode_radio",
                horizontal=True,
                help="Single page mode: edits only the page shown in slider. All slides: edits entire presentation."
            )
            st.session_state.edit_mode = "single" if edit_mode == "Edit Current Page" else "full"
            
            # Paper context toggle (near editing mode for better UX)
            if "use_paper_context" not in st.session_state:
                st.session_state.use_paper_context = True
            st.session_state.use_paper_context = st.checkbox(
                "📝 Use original paper context when editing",
                value=st.session_state.use_paper_context,
                help="When enabled, the LLM will have access to the original paper source during editing, which helps maintain accuracy and consistency with the paper's content and notation. Disable to reduce token usage.",
                key="use_paper_context_toggle"
            )
            
            # Show info based on mode
            if st.session_state.edit_mode == "single":
                current_page = get_current_viewer_page(st.session_state.total_frames)
                st.info(f"🎯 Editing will only affect slide {current_page} (current page in viewer)")
            else:
                st.info("📄 Editing will affect all slides in the presentation")

            with st.expander("✏️ Edit Source (manual)", expanded=False):
                st.caption("Directly edit LaTeX source. Changes are saved to slides.tex and compiled.")

                current_page = get_current_viewer_page(st.session_state.total_frames)
                file_mtime = int(os.path.getmtime(slides_tex_path)) if os.path.exists(slides_tex_path) else 0

                if st.session_state.edit_mode == "full":
                    editor_value = beamer_code
                    editor_label = "Full slides.tex"
                    editor_help = "Manual edits apply to the entire presentation source."
                    editor_key = f"manual_source_full_{st.session_state.paper_id}_{file_mtime}"
                else:
                    source_content, editor_label, editor_help = get_single_page_edit_source(
                        beamer_code,
                        current_page,
                    )
                    if not source_content:
                        if current_page == 1:
                            st.error("Could not find preamble source for slide 1.")
                        else:
                            st.error(f"Could not find source for slide {current_page}.")
                        editor_value = ""
                    else:
                        editor_value = source_content
                    editor_key = f"manual_source_single_{st.session_state.paper_id}_{current_page}_{file_mtime}"

                edited_source = st.text_area(
                    editor_label,
                    value=editor_value,
                    height=360,
                    key=editor_key,
                    help=editor_help,
                )

                if st.button("💾 Save Source Changes", key=f"save_source_changes_{st.session_state.edit_mode}"):
                    if st.session_state.edit_mode == "full":
                        if edited_source == beamer_code:
                            st.info("No changes detected in slides.tex.")
                        else:
                            with open(slides_tex_path, "w", encoding="utf-8") as f:
                                f.write(edited_source)

                            st.info("Saved source changes. Recompiling PDF...")
                            if run_compile_step(
                                st.session_state.paper_id,
                                st.session_state.pdflatex_path,
                            ):
                                history_mgr = get_history_manager(st.session_state.paper_id)
                                latest_versions = history_mgr.list_versions()
                                if latest_versions:
                                    current_version_key = f"current_version_{st.session_state.paper_id}"
                                    st.session_state[current_version_key] = latest_versions[0]["filename"]

                                st.success("✅ Source updated and PDF recompiled successfully!")
                                st.session_state.pdf_path = (
                                    f"source/{st.session_state.paper_id}/slides.pdf"
                                )
                                st.rerun()
                            else:
                                st.error("Failed to recompile PDF after saving source edits.")
                    else:
                        current_source, _, _ = get_single_page_edit_source(beamer_code, current_page)
                        if not current_source:
                            if current_page == 1:
                                st.error("Could not find preamble source for slide 1.")
                            else:
                                st.error(f"Could not find source for slide {current_page}.")
                        elif edited_source == current_source:
                            if current_page == 1:
                                st.info("No changes detected for slide 1 preamble source.")
                            else:
                                st.info(f"No changes detected for slide {current_page} source.")
                        else:
                            updated_beamer_code = apply_single_page_source_edit(
                                beamer_code,
                                current_page,
                                edited_source,
                            )
                            if not updated_beamer_code:
                                if current_page == 1:
                                    st.error("Failed to apply source update to slide 1 preamble.")
                                else:
                                    st.error(f"Failed to apply source update to slide {current_page}.")
                            else:
                                with open(slides_tex_path, "w", encoding="utf-8") as f:
                                    f.write(updated_beamer_code)

                                if current_page == 1:
                                    st.info("Saved slide 1 preamble source changes. Recompiling PDF...")
                                else:
                                    st.info(f"Saved slide {current_page} source changes. Recompiling PDF...")

                                if run_compile_step(
                                    st.session_state.paper_id,
                                    st.session_state.pdflatex_path,
                                ):
                                    history_mgr = get_history_manager(st.session_state.paper_id)
                                    latest_versions = history_mgr.list_versions()
                                    if latest_versions:
                                        current_version_key = f"current_version_{st.session_state.paper_id}"
                                        st.session_state[current_version_key] = latest_versions[0]["filename"]

                                    if current_page == 1:
                                        st.success("✅ Slide 1 preamble source updated and PDF recompiled successfully!")
                                    else:
                                        st.success(f"✅ Slide {current_page} source updated and PDF recompiled successfully!")
                                    st.session_state.pdf_path = (
                                        f"source/{st.session_state.paper_id}/slides.pdf"
                                    )
                                    st.rerun()
                                else:
                                    st.error("Failed to recompile PDF after saving source edits.")

            st.divider()

            # Display chat messages
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # Chat input
            if prompt := st.chat_input("Your instructions to edit the slides..."):
                # Determine which frame to edit
                current_frame = get_current_viewer_page(st.session_state.total_frames)
                
                # Add message with appropriate prefix
                if st.session_state.edit_mode == "single":
                    append_chat_message("user", f"[Page {current_frame}] {prompt}")
                else:
                    append_chat_message("user", f"[All Slides] {prompt}")

                with st.chat_message("assistant"):
                    if st.session_state.edit_mode == "single":
                        with st.spinner(f"Editing slide {current_frame}..."):
                            slides_tex_path = (
                                f"source/{st.session_state.paper_id}/slides.tex"
                            )
                            with open(slides_tex_path, "r", encoding='utf-8') as f:
                                beamer_code = f.read()

                            # Edit single slide based on current page
                            new_beamer_code = edit_single_slide(
                                beamer_code,
                                current_frame,
                                prompt,
                                st.session_state.openai_api_key,
                                st.session_state.model_name,
                                st.session_state.openai_base_url if st.session_state.openai_base_url else None,
                                paper_id=st.session_state.paper_id,
                                use_paper_context=st.session_state.use_paper_context,
                            )
                            edit_message = f"Edited slide {current_frame}"
                    else:
                        with st.spinner("Editing all slides..."):
                            slides_tex_path = (
                                f"source/{st.session_state.paper_id}/slides.tex"
                            )
                            with open(slides_tex_path, "r", encoding='utf-8') as f:
                                beamer_code = f.read()

                            # Edit all slides
                            new_beamer_code = edit_slides(
                                beamer_code,
                                prompt,
                                st.session_state.openai_api_key,
                                st.session_state.model_name,
                                st.session_state.openai_base_url if st.session_state.openai_base_url else None,
                                paper_id=st.session_state.paper_id,
                                use_paper_context=st.session_state.use_paper_context,
                            )
                            edit_message = "Edited all slides"

                    if new_beamer_code:
                        with open(slides_tex_path, "w", encoding='utf-8') as f:
                            f.write(new_beamer_code)
                        st.info(f"{edit_message}. Recompiling PDF with changes...")
                        if run_compile_step(
                            st.session_state.paper_id,
                            st.session_state.pdflatex_path,
                        ):
                            # Update current version tracker to the latest (newly saved) version
                            history_mgr = get_history_manager(st.session_state.paper_id)
                            latest_versions = history_mgr.list_versions()
                            if latest_versions:
                                current_version_key = f"current_version_{st.session_state.paper_id}"
                                st.session_state[current_version_key] = latest_versions[0]['filename']
                            
                            st.success(f"✅ {edit_message}. PDF recompiled successfully!")
                            st.session_state.pdf_path = (
                                f"source/{st.session_state.paper_id}/slides.pdf"
                            )
                            st.rerun()
                        else:
                            st.error("Failed to recompile PDF.")
                    else:
                        st.error("Failed to edit slides.")
            
            # Handle pending edit from inline edit boxes (full page view)
            if st.session_state.get("pending_edit"):
                edit_info = st.session_state.pending_edit
                st.session_state.pending_edit = None  # Clear it
                
                # Append to chat history
                append_chat_message("user", f"[Page {edit_info['frame_number']}] {edit_info['instruction']}", display=False)
                
                with st.spinner(f"Editing slide {edit_info['frame_number']}..."):
                    slides_tex_path = f"source/{st.session_state.paper_id}/slides.tex"
                    with open(slides_tex_path, "r", encoding='utf-8') as f:
                        beamer_code = f.read()

                    new_beamer_code = edit_single_slide(
                        beamer_code,
                        edit_info['frame_number'],
                        edit_info['instruction'],
                        st.session_state.openai_api_key,
                        st.session_state.model_name,
                        st.session_state.openai_base_url if st.session_state.openai_base_url else None,
                        paper_id=st.session_state.paper_id,
                        use_paper_context=st.session_state.use_paper_context,
                    )
                    
                    if new_beamer_code:
                        with open(slides_tex_path, "w", encoding='utf-8') as f:
                            f.write(new_beamer_code)
                        
                        if run_compile_step(
                            st.session_state.paper_id,
                            st.session_state.pdflatex_path,
                        ):
                            # Update current version tracker to the latest (newly saved) version
                            history_mgr = get_history_manager(st.session_state.paper_id)
                            latest_versions = history_mgr.list_versions()
                            if latest_versions:
                                current_version_key = f"current_version_{st.session_state.paper_id}"
                                st.session_state[current_version_key] = latest_versions[0]['filename']
                            
                            # Append assistant response to chat history
                            append_chat_message("assistant", f"✅ Edited slide {edit_info['frame_number']} successfully!", display=False)
                            
                            st.success(f"✅ Edited slide {edit_info['frame_number']} successfully!")
                            st.session_state.pdf_path = (
                                f"source/{st.session_state.paper_id}/slides.pdf"
                            )
                            st.rerun()
                        else:
                            append_chat_message("assistant", f"❌ Failed to recompile PDF after editing slide {edit_info['frame_number']}.", display=False)
                            st.error("Failed to recompile PDF.")
                    else:
                        append_chat_message("assistant", f"❌ Failed to edit slide {edit_info['frame_number']}.", display=False)
                        st.error("Failed to edit slide.")
        else:
            st.info(
                "Interactive editing will be available after successful pipeline completion."
            )

    with col2:
        st.header("Pipeline Status & Results")

        # Execute pipeline based on status
        if (
            st.session_state.pipeline_status == "generating"
            and st.session_state.paper_id
        ):
            with st.spinner("🔄 Running slide generation..."):
                success = run_generate_step(
                    st.session_state.paper_id,
                    st.session_state.openai_api_key,
                    st.session_state.model_name,
                    # Only pass pdf/zip path when in the matching mode
                    st.session_state.uploaded_pdf_path if st.session_state.input_mode == "upload" else None,
                    st.session_state.pdf_start_page,
                    st.session_state.pdf_end_page,
                    latex_zip_path=st.session_state.latex_zip_path if st.session_state.input_mode == "latex_zip" else None,
                )

                if success:
                    st.success("✅ Slide generation completed!")
                    # Check if this was part of full pipeline or generate-only
                    if st.session_state.get("run_full_pipeline", False):
                        st.session_state.pipeline_status = "compiling"
                    else:
                        st.session_state.pipeline_status = "completed"
                else:
                    st.error("❌ Slide generation failed!")
                    st.session_state.pipeline_status = "failed"
                st.rerun()

        elif (
            st.session_state.pipeline_status == "compiling"
            and st.session_state.paper_id
        ):
            with st.spinner("🔄 Compiling PDF..."):
                success = run_compile_step(
                    st.session_state.paper_id, st.session_state.pdflatex_path
                )

                if success:
                    st.success("✅ PDF compilation completed!")
                    st.session_state.pipeline_status = "completed"
                    st.session_state.pdf_path = (
                        f"source/{st.session_state.paper_id}/slides.pdf"
                    )
                    
                    # Ensure initial history exists after first successful compile
                    ensure_initial_history(st.session_state.paper_id)
                else:
                    st.error("❌ PDF compilation failed!")
                    st.session_state.pipeline_status = "failed"
                st.rerun()

        # Show PDF if available
        if (
            st.session_state.pdf_path
            and os.path.exists(st.session_state.pdf_path)
            and st.session_state.pipeline_status == "completed"
        ):

            st.subheader("📄 Generated Slides")
            
            # Buttons row: Download PDF, Generate Speaker Notes, Download Speaker Notes
            col_pdf, col_gen_notes, col_dl_notes = st.columns(3)
            
            with col_pdf:
                # Extract title from the LaTeX file for the filename
                slides_tex_path = f"source/{st.session_state.paper_id}/slides.tex"
                title = extract_title_from_latex(slides_tex_path)
                if title:
                    # Sanitize title for filename (remove special characters)
                    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
                    filename = f"{safe_title}_slides.pdf"
                else:
                    filename = f"{st.session_state.paper_id}_slides.pdf"
                
                with open(st.session_state.pdf_path, "rb") as f:
                    st.download_button(
                        "📥 Download as PDF",
                        f,
                        file_name=filename,
                        mime="application/pdf",
                    )
            
            with col_gen_notes:
                if st.button("🎤 Generate Speaker Notes", key="generate_speaker_notes"):
                    st.session_state.generating_speaker_notes = True
                    st.rerun()
            
            # Add optional custom instruction for speaker notes
            with st.expander("⚙️ Custom Speaker Notes Instructions (Optional)"):
                st.session_state.speaker_notes_instruction = st.text_area(
                    "Custom instructions for speaker notes generation:",
                    value=st.session_state.get("speaker_notes_instruction", ""),
                    placeholder="e.g., 'Focus on explaining the mathematical intuition' or 'Keep notes brief, under 2 sentences per slide'",
                    help="Provide custom instructions to guide how the speaker notes should be generated. Leave empty to use default style.",
                    key="speaker_notes_instruction_input",
                )
            
            with col_dl_notes:
                # Check if speaker notes exist
                notes_file = f"source/{st.session_state.paper_id}/speaker_notes.json"
                if os.path.exists(notes_file):
                    speaker_notes = load_speaker_notes(st.session_state.paper_id)
                    if speaker_notes:
                        # Extract title from the LaTeX file for the filename
                        slides_tex_path = f"source/{st.session_state.paper_id}/slides.tex"
                        title = extract_title_from_latex(slides_tex_path)
                        if title:
                            # Sanitize title for filename (remove special characters)
                            safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
                            notes_filename = f"{safe_title}_speaker_notes.txt"
                        else:
                            notes_filename = f"{st.session_state.paper_id}_speaker_notes.txt"
                        
                        # Format notes as text for download
                        notes_text = f"Speaker Notes for {title or st.session_state.paper_id}\n"
                        notes_text += "=" * 60 + "\n\n"
                        for slide_num in sorted(speaker_notes.keys()):
                            notes_text += f"Slide {slide_num}:\n"
                            notes_text += f"{speaker_notes[slide_num]}\n\n"
                            notes_text += "-" * 60 + "\n\n"
                        
                        st.download_button(
                            "📥 Download Speaker Notes",
                            notes_text,
                            file_name=notes_filename,
                            mime="text/plain",
                        )
                else:
                    st.button("📥 Download Speaker Notes", disabled=True, help="Generate speaker notes first")
            
            # Handle speaker notes generation
            if st.session_state.get("generating_speaker_notes", False):
                st.session_state.generating_speaker_notes = False
                
                with st.spinner("🔄 Generating speaker notes for all slides... This may take a moment."):
                    speaker_notes = generate_speaker_notes(
                        st.session_state.paper_id,
                        st.session_state.openai_api_key,
                        st.session_state.model_name,
                        st.session_state.openai_base_url if st.session_state.openai_base_url else None,
                        instruction=st.session_state.get("speaker_notes_instruction", ""),
                    )
                    
                    if speaker_notes:
                        if save_speaker_notes(speaker_notes, st.session_state.paper_id):
                            st.success(f"✅ Speaker notes generated successfully for {len(speaker_notes)} slides!")
                            st.rerun()
                        else:
                            st.error("❌ Failed to save speaker notes")
                    else:
                        st.error("❌ Failed to generate speaker notes")
            
            display_pdf_as_images(
                st.session_state.pdf_path,
                paper_id=st.session_state.paper_id,
                enable_inline_edit=True
            )

        elif st.session_state.pipeline_status == "ready":
            st.info("🎯 Select a paper and run the pipeline to generate slides.")
        elif st.session_state.pipeline_status == "failed":
            st.error("❌ Pipeline failed. Check the logs above for details.")
        else:
            st.info("📄 Generated PDF will be displayed here when ready.")


if __name__ == "__main__":
    main()
