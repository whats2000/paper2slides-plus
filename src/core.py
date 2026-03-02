# core.py
# This file contains the core orchestration logic for paper2slides,
# coordinating between specialized modules.

import logging
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

from .arxiv_utils import (
    search_arxiv,
    get_latex_from_arxiv_with_timeout,
    copy_image_assets_from_cache,
)
from .beamer_utils import (
    extract_frames_from_beamer,
    get_frame_by_number,
    get_preamble,
    replace_frame_in_beamer,
    replace_preamble,
)
from .compiler import (
    compile_latex,
    try_compile_with_fixes,
)
from .file_utils import read_file, find_image_files
from .latex_utils import (
    extract_definitions_and_usepackage_lines,
    build_additional_tex,
    save_additional_tex,
    save_latex_source,
    load_latex_source,
    add_additional_tex,
    sanitize_frametitles,
)
from .llm_client import (
    call_llm,
    prompt_manager,
)
# Import from specialized modules
from .pdf_utils import extract_text_from_pdf, extract_images_from_pdf, generate_pdf_id

load_dotenv(override=True)


def edit_slides(
    beamer_code: str,
    instruction: str,
    api_key: str,
    model_name: str,
    base_url: str | None = None,
    paper_id: str = "",
    use_paper_context: bool = True,
    workspace_dir: str | None = None,
) -> str | None:
    """
    Edits the Beamer code based on the user's instruction.
    
    Args:
        beamer_code: Current Beamer LaTeX code
        instruction: User's editing instruction
        api_key: API key for LLM
        model_name: Model name to use
        base_url: Optional base URL for API
        paper_id: Paper ID to load latex source from workspace
        use_paper_context: Whether to include original paper source as context (default True)
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
    """
    logging.info("Editing slides based on user instruction...")

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    # Load latex_source from workspace if requested
    latex_source = ""
    if use_paper_context and paper_id:
        latex_source = load_latex_source(workspace_dir)
        if latex_source:
            logging.info(f"Loaded original paper source for editing context (paper {paper_id})")
        else:
            logging.debug(f"No original paper source found for paper {paper_id}")

    # Use PromptManager to get prompts from YAML config (interactive_edit stage)
    system_message, user_prompt = prompt_manager.build_prompt(
        stage="interactive_edit",
        beamer_code=beamer_code,
        user_instructions=instruction,
        latex_source=latex_source,
    )

    try:
        content = call_llm(system_message, user_prompt, api_key, model_name, base_url)
        if not content:
            return None

        sanitized_content = sanitize_frametitles(content)

        # If paper_id is provided, try to compile and fix if needed
        if paper_id:
            logging.info("Attempting to compile edited slides...")
            compiled_code = try_compile_with_fixes(
                sanitized_content,
                paper_id,
                api_key,
                model_name,
                base_url,
                max_retries=3,
                use_paper_context=use_paper_context,
                workspace_dir=workspace_dir,
            )

            if compiled_code:
                logging.info("✓ Edit successful and compiled")
                return compiled_code
            else:
                logging.error("✗ Edit failed to compile after all fix attempts")
                return None
        else:
            # No paper_id, return without compiling
            return sanitized_content

    except Exception as e:
        logging.error(f"Error editing slides: {e}")
        return None


def edit_single_slide(
    beamer_code: str,
    frame_number: int,
    instruction: str,
    api_key: str,
    model_name: str,
    base_url: str | None = None,
    paper_id: str = "",
    use_paper_context: bool = True,
    workspace_dir: str | None = None,
) -> str | None:
    """
    Edits a specific slide/frame in the Beamer code based on the user's instruction.
    The specified frame is edited according to the instruction. If the instruction
    asks to split the frame, multiple frames will be created to replace the original.
    
    Args:
        beamer_code: Full Beamer LaTeX code
        frame_number: Frame number to edit (1-indexed, matching PDF page numbers)
        instruction: User's editing instruction (can include split instructions)
        api_key: API key for LLM
        model_name: Model name to use
        base_url: Optional base URL for API
        paper_id: Paper ID to load latex source from workspace
        use_paper_context: Whether to include original paper source as context (default True)
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        
    Returns:
        Updated full Beamer code with the frame edited (or split into multiple frames), or None on error
    """
    logging.info(f"Editing slide {frame_number} based on user instruction...")

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    # Load latex_source from workspace if requested
    latex_source = ""
    if use_paper_context and paper_id:
        latex_source = load_latex_source(workspace_dir)
        if latex_source:
            logging.info(f"Loaded original paper source for editing context (paper {paper_id})")
        else:
            logging.debug(f"No original paper source found for paper {paper_id}")

    # Special case: frame_number == 1 means edit the preamble (title configuration)
    if frame_number == 1:
        frame_content = get_preamble(beamer_code)
        if not frame_content:
            logging.error("Preamble not found in Beamer code")
            return None
        
        # Use preamble-specific prompt
        system_message, user_prompt = prompt_manager.build_prompt(
            stage="interactive_edit_preamble",
            beamer_code=beamer_code,
            frame_content=frame_content,
            user_instructions=instruction,
            latex_source=latex_source,
        )
    else:
        # Extract the specific frame (existing behavior)
        frame_content = get_frame_by_number(beamer_code, frame_number)
        if not frame_content:
            logging.error(f"Frame {frame_number} not found in Beamer code")
            return None

        # Use PromptManager to get prompts from YAML config (interactive_edit_single_slide stage)
        system_message, user_prompt = prompt_manager.build_prompt(
            stage="interactive_edit_single_slide",
            beamer_code=beamer_code,
            frame_number=frame_number,
            frame_content=frame_content,
            user_instructions=instruction,
            latex_source=latex_source,
        )

    try:
        edited_frame_content = call_llm(system_message, user_prompt, api_key, model_name, base_url)
        if not edited_frame_content:
            logging.error("Failed to extract edited frame from LLM response")
            return None

        # Sanitize the edited frame
        edited_frame_content = sanitize_frametitles(edited_frame_content)

        # Replace the frame or preamble in the full Beamer code
        if frame_number == 1:
            updated_beamer_code = replace_preamble(beamer_code, edited_frame_content)
            if not updated_beamer_code:
                logging.error("Failed to replace preamble in Beamer code")
                return None
        else:
            updated_beamer_code = replace_frame_in_beamer(beamer_code, frame_number, edited_frame_content)
            if not updated_beamer_code:
                logging.error(f"Failed to replace frame {frame_number} in Beamer code")
                return None

        # If paper_id is provided, try to compile and fix if needed
        if paper_id:
            logging.info("Attempting to compile edited slide...")
            compiled_code = try_compile_with_fixes(
                updated_beamer_code,
                paper_id,
                api_key,
                model_name,
                base_url,
                max_retries=3,
                use_paper_context=use_paper_context,
                workspace_dir=workspace_dir,
            )

            if compiled_code:
                logging.info("✓ Single slide edit successful and compiled")
                return compiled_code
            else:
                logging.error("✗ Single slide edit failed to compile after all fix attempts")
                return None
        else:
            # No paper_id, return without compiling
            return updated_beamer_code

    except Exception as e:
        logging.error(f"Error editing single slide: {e}")
        return None


def _generate_slides_with_stages(
    formatted_source: str,
    tex_files_directory: str,
    slides_tex_path: str,
    figure_paths: list[str],
    use_linter: bool,
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
) -> bool:
    """
    Generate slides in multiple stages from formatted source text.
    Args:
        formatted_source: Formatted source text (from PDF or LaTeX)
        tex_files_directory: Directory to save tex files
        slides_tex_path: Path to save generated slides.tex
        figure_paths: List of figure paths to allow
        use_linter: Whether to use ChkTeX linter
        api_key: OpenAI/DashScope API key
        model_name: Model to use for generation
        base_url: Optional base URL for API
    Returns:
        True if successful, False otherwise
    """
    # Stage 1: initial generation from source
    system_message, user_prompt = prompt_manager.build_prompt(
        stage='initial',
        latex_source=formatted_source,
        beamer_code="",
        linter_log="",
        figure_paths=figure_paths,
    )
    result = call_llm(system_message, user_prompt, api_key or "", model_name, base_url)
    if not result:
        logging.error("Failed to generate slides at stage 1")
        return False
    with open(slides_tex_path, "w", encoding="utf-8") as f:
        f.write(result)
    logging.info(f"Stage 1 completed. Slides saved to {slides_tex_path}")

    logging.info("Stage 2: refining slides with update prompt...")
    beamer_code = read_file(slides_tex_path)
    system_message, user_prompt = prompt_manager.build_prompt(
        stage='update',
        latex_source=formatted_source,
        beamer_code=beamer_code,
        linter_log="",
        figure_paths=figure_paths,
    )
    result = call_llm(system_message, user_prompt, api_key or "", model_name, base_url)
    if not result:
        logging.error("Failed to refine slides at stage 2")
        return False
    with open(slides_tex_path, "w", encoding="utf-8") as f:
        f.write(result)
    logging.info(f"Stage 2 completed. Slides saved to {slides_tex_path}")

    # Stage 3: Compile with fixes (if linter is enabled)
    if not use_linter:
        logging.info("Skipping linter and compilation stage. Generation complete.")
        return True

    logging.info("Stage 3: Attempting to compile and fix if needed...")
    # Extract paper_id from tex_files_directory
    paper_id = Path(tex_files_directory).name or Path(tex_files_directory).parts[-1]
    
    compiled_code = try_compile_with_fixes(
        result,
        paper_id,
        api_key or "",
        model_name or "",
        base_url,
        max_retries=3,
        use_paper_context=True,
        workspace_dir=tex_files_directory,
    )
    
    if compiled_code:
        with open(slides_tex_path, "w", encoding="utf-8") as f:
            f.write(compiled_code)
        logging.info(f"Stage 3 completed. Compiled slides saved to {slides_tex_path}")
        logging.info("All stages completed successfully.")
        return True
    else:
        logging.error("Failed to compile slides at stage 3")
        # Still save what we have, even if compilation failed
        logging.warning("Slides saved but may not compile correctly.")
        return False


def generate_slides(
    arxiv_id: str,
    use_linter: bool,
    use_pdfcrop: bool,
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    workspace_dir: str | None = None,
) -> bool:
    """
    Generate slides from an arXiv paper.
    
    Args:
        arxiv_id: arXiv paper ID
        use_linter: Whether to use ChkTeX linter
        use_pdfcrop: Whether to use pdfcrop (not currently used)
        api_key: OpenAI/DashScope API key
        model_name: Model to use for generation
        base_url: Optional base URL for API
        workspace_dir: Workspace directory path (defaults to source/{arxiv_id}/ if not provided)
        
    Returns:
        True if successful, False otherwise
    """
    # Use DEFAULT_MODEL from environment if model_name is not provided
    if model_name is None:
        model_name = os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{arxiv_id}/"

    # Define paths
    cache_dir = f"cache/{arxiv_id}"
    tex_files_directory = workspace_dir
    slides_tex_path = f"{tex_files_directory}slides.tex"

    # Create directories if not exist
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(tex_files_directory, exist_ok=True)

    # Fetch LaTeX source
    logging.info("Fetching LaTeX source from arXiv...")
    latex_source = get_latex_from_arxiv_with_timeout(arxiv_id, cache_dir)
    if latex_source is None:
        logging.error(
            "Failed to retrieve LaTeX source from arXiv within timeout. Aborting generation."
        )
        return False

    # Add arXiv URL comment at the top for reference
    latex_source = f"% arXiv URL: https://arxiv.org/abs/{arxiv_id}\n\n" + latex_source

    # Extract definitions and packages to build ADDITIONAL.tex
    logging.info("Extracting definitions and packages...")
    defs_pkgs = extract_definitions_and_usepackage_lines(latex_source)
    add_tex_contents = build_additional_tex(defs_pkgs)
    save_additional_tex(add_tex_contents, tex_files_directory)

    # Save the original LaTeX source for later reference during editing
    save_latex_source(latex_source, tex_files_directory)

    # Ensure figures and images referenced by the paper are available under source/<id>/
    try:
        copy_image_assets_from_cache(arxiv_id, cache_dir, tex_files_directory)
    except Exception as e:
        logging.debug(f"Copying image assets skipped due to error: {e}")

    # Add \input{ADDITIONAL.tex} if missing
    latex_source = add_additional_tex(latex_source)

    # Find images under source dir to restrict allowed figures
    figure_paths = find_image_files(tex_files_directory)

    logging.info("Stage 1: generating slides with LaTeX source...")
    return _generate_slides_with_stages(
        latex_source,
        tex_files_directory,
        slides_tex_path,
        figure_paths,
        use_linter,
        api_key,
        model_name,
        base_url,
    )


def generate_slides_from_latex_zip(
    zip_path: str,
    paper_id: str,
    use_linter: bool,
    use_pdfcrop: bool = False,
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    workspace_dir: str | None = None,
) -> bool:
    """
    Generate slides from a locally uploaded LaTeX project zip file.

    This is the same pipeline as generate_slides (arXiv) — the only difference
    is that the LaTeX source comes from the uploaded zip instead of being
    downloaded from arXiv.

    Args:
        zip_path: Path to the .zip file containing a LaTeX project
        paper_id: Unique identifier for this upload
        use_linter: Whether to use ChkTeX linter
        use_pdfcrop: Whether to use pdfcrop (currently unused)
        api_key: OpenAI/DashScope API key
        model_name: Model to use for generation
        base_url: Optional base URL for API
        workspace_dir: Workspace directory (defaults to source/{paper_id}/)

    Returns:
        True if successful, False otherwise
    """
    import tempfile
    import zipfile

    if model_name is None:
        model_name = os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")

    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    tex_files_directory = workspace_dir
    slides_tex_path = f"{tex_files_directory}slides.tex"
    os.makedirs(tex_files_directory, exist_ok=True)

    # Extract zip and find the main .tex file (same as arXiv fetch, but local)
    with tempfile.TemporaryDirectory() as extract_dir:
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)
        except zipfile.BadZipFile as e:
            logging.error(f"Failed to extract zip file: {e}")
            return False

        extract_path = Path(extract_dir)

        # Descend into a single-folder root if present (common zip layout)
        contents = list(extract_path.iterdir())
        if len(contents) == 1 and contents[0].is_dir():
            extract_path = contents[0]

        # Find the main .tex file: the one that contains \documentclass
        main_tex = None
        for f in sorted(extract_path.rglob("*.tex")):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                if r"\documentclass" in text:
                    main_tex = f
                    break
            except Exception:
                continue

        if main_tex is None:
            logging.error(r"No main .tex file with \documentclass found in the zip.")
            return False

        logging.info(f"Found main LaTeX file: {main_tex.name}")
        latex_source = main_tex.read_text(encoding="utf-8", errors="ignore")

        # Copy all image assets into workspace (mirrors copy_image_assets_from_cache)
        image_extensions = {".pdf", ".png", ".jpeg", ".jpg", ".eps", ".svg"}
        for img_file in extract_path.rglob("*"):
            if img_file.suffix.lower() in image_extensions and img_file.is_file():
                rel = img_file.relative_to(extract_path)
                dest = Path(tex_files_directory) / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(img_file, dest)
                except Exception as e:
                    logging.debug(f"Skipped asset {img_file}: {e}")

    # From here the flow is identical to generate_slides (arXiv path)
    logging.info("Extracting definitions and packages...")
    defs_pkgs = extract_definitions_and_usepackage_lines(latex_source)
    add_tex_contents = build_additional_tex(defs_pkgs)
    save_additional_tex(add_tex_contents, tex_files_directory)

    save_latex_source(latex_source, tex_files_directory)

    latex_source = add_additional_tex(latex_source)

    figure_paths = find_image_files(tex_files_directory)

    logging.info("Stage 1: generating slides from LaTeX zip source...")
    return _generate_slides_with_stages(
        latex_source,
        tex_files_directory,
        slides_tex_path,
        figure_paths,
        use_linter,
        api_key,
        model_name,
        base_url,
    )


def generate_slides_from_pdf(
    pdf_path: str,
    paper_id: str,
    use_linter: bool,
    use_pdfcrop: bool,
    api_key: str | None = None,
    model_name: str | None = None,
    base_url: str | None = None,
    dashscope_base_url: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
    workspace_dir: str | None = None,
) -> bool:
    """
    Generate slides from a local PDF file (not from arXiv).
    
    Args:
        pdf_path: Path to the PDF file
        paper_id: Unique identifier for this paper (will be generated if from uploaded PDF)
        use_linter: Whether to use ChkTeX linter
        use_pdfcrop: Whether to use pdfcrop (not used for direct PDF)
        api_key: OpenAI/DashScope API key
        model_name: Model to use for generation (defaults to DEFAULT_MODEL env var)
        base_url: Base URL for OpenAI-compatible API (overrides env)
        dashscope_base_url: Base URL for DashScope API (overrides env)
        start_page: Starting page number (1-indexed, inclusive). If None, starts from page 1.
        end_page: Ending page number (1-indexed, inclusive). If None, goes to last page.
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        
    Returns:
        True if successful, False otherwise
    """
    # Use DEFAULT_MODEL from environment if model_name is not provided
    if model_name is None:
        model_name = os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")
    # Set base URLs in environment if provided (for process_stage to use)
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url
    if dashscope_base_url:
        os.environ["DASHSCOPE_BASE_URL"] = dashscope_base_url

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    # Define paths
    tex_files_directory = workspace_dir
    slides_tex_path = f"{tex_files_directory}slides.tex"

    # Create directories if not exist
    os.makedirs(tex_files_directory, exist_ok=True)

    # Copy the original PDF to the workspace first (needed for Docker access)
    try:
        dest_pdf = Path(tex_files_directory) / "original_paper.pdf"
        shutil.copy2(pdf_path, dest_pdf)
        logging.info(f"Copied original PDF to {dest_pdf}")
        # Use the workspace copy for all subsequent operations
        pdf_path_for_processing = str(dest_pdf)
    except Exception as e:
        logging.warning(f"Failed to copy original PDF: {e}")
        pdf_path_for_processing = pdf_path

    # Extract text from PDF
    logging.info(f"Extracting text from PDF: {pdf_path_for_processing}")
    if start_page or end_page:
        page_range_msg = f" (pages {start_page or 1} to {end_page or 'end'})"
        logging.info(f"Using page range: {page_range_msg}")
    try:
        pdf_text = extract_text_from_pdf(pdf_path_for_processing, start_page, end_page)
        if not pdf_text.strip():
            logging.error("No text content extracted from PDF. The PDF might be image-based or empty.")
            return False
    except Exception as e:
        logging.error(f"Failed to extract text from PDF: {e}")
        return False

    # Extract images from PDF
    logging.info(f"Extracting images from PDF: {pdf_path_for_processing}")
    try:
        figure_paths = extract_images_from_pdf(pdf_path_for_processing, tex_files_directory, start_page, end_page)
        if figure_paths:
            logging.info(f"Successfully extracted {len(figure_paths)} images from PDF")
        else:
            logging.info("No images found in PDF (or all were too small)")
    except Exception as e:
        logging.warning(f"Failed to extract images from PDF: {e}")
        figure_paths = []

    # Create a minimal ADDITIONAL.tex (no LaTeX source to extract from)
    add_tex_contents = build_additional_tex([])
    save_additional_tex(add_tex_contents, tex_files_directory)

    # Since we don't have LaTeX source, we'll format the PDF text as the "source"
    # We'll wrap it in a way that makes it clear this is plain text from a PDF
    formatted_source = f"""% This is text extracted from a PDF file (not LaTeX source)
% The following content should be used to create presentation slides

{pdf_text}
"""

    # Save the extracted PDF text as the "original source" for later reference during editing
    save_latex_source(formatted_source, tex_files_directory)

    logging.info("Stage 1: generating slides from PDF text...")
    return _generate_slides_with_stages(
        formatted_source,
        tex_files_directory,
        slides_tex_path,
        figure_paths,
        use_linter,
        api_key,
        model_name,
        base_url,
    )


def generate_speaker_notes(
    paper_id: str,
    api_key: str,
    model_name: str,
    base_url: str | None = None,
    instruction: str = "",
    workspace_dir: str | None = None,
) -> dict[int, str] | None:
    """
    Generate speaker notes for all slides in a presentation using a single LLM call.
    
    Args:
        paper_id: Paper ID to load presentation and source from
        api_key: API key for LLM
        model_name: Model name to use
        base_url: Optional base URL for API
        instruction: Optional custom instruction for speaker note generation
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        
    Returns:
        Dictionary mapping frame number to speaker notes, or None on error
    """
    logging.info(f"Generating speaker notes for paper {paper_id}...")

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    # Load the slides and original paper source
    slides_tex_path = f"{workspace_dir}slides.tex"
    if not os.path.exists(slides_tex_path):
        logging.error(f"Slides file not found: {slides_tex_path}")
        return None

    with open(slides_tex_path, "r", encoding="utf-8") as f:
        beamer_code = f.read()

    # Load original paper source
    latex_source = load_latex_source(workspace_dir)
    if not latex_source:
        logging.warning(f"No original paper source found for paper {paper_id}")
        latex_source = ""

    # Extract all frames to know how many slides we have
    frames = extract_frames_from_beamer(beamer_code)
    if not frames:
        logging.error("No frames found in Beamer code")
        return None

    logging.info(f"Found {len(frames)} slides. Generating speaker notes in a single call...")

    # Use PromptManager to get prompts (no frame-specific info needed)
    system_message, user_prompt = prompt_manager.build_prompt(
        stage="generate_speaker_notes",
        beamer_code=beamer_code,
        latex_source=latex_source,
        user_instructions=instruction,
    )

    logging.debug("LLM user prompt for speaker notes:\n%s", user_prompt)

    try:
        # For speaker notes, we need the raw response text, not extracted code
        response = call_llm(
            system_message, 
            user_prompt, 
            api_key, 
            model_name, 
            base_url,
            extract_code=False  # Get raw text response instead of extracting code blocks
        )
        
        if not response:
            logging.error("Failed to generate speaker notes from LLM - empty response")
            return None
        
        if not response.strip():
            logging.error("Failed to generate speaker notes from LLM - response is whitespace only")
            return None

        # Parse the response to extract notes for each slide
        speaker_notes = {}

        # Split by [SLIDE N] markers
        import re
        pattern = r'\[SLIDE\s+(\d+)\]\s*\n(.*?)(?=\[SLIDE\s+\d+\]|\Z)'
        matches = re.findall(pattern, response, re.DOTALL)

        if not matches:
            # Maybe the LLM didn't follow the format exactly - try alternative patterns
            logging.warning("No [SLIDE N] markers found. Trying alternative formats...")
            
            # Try "Slide N:" format
            pattern2 = r'(?:Slide|SLIDE)\s+(\d+)[:\s]*\n(.*?)(?=(?:Slide|SLIDE)\s+\d+|\Z)'
            matches = re.findall(pattern2, response, re.DOTALL | re.IGNORECASE)
            
            if not matches:
                logging.error("Could not parse speaker notes from LLM response")
                logging.error(f"Response preview: {response[:1000]}...")
                return None

        for slide_num_str, notes_text in matches:
            slide_num = int(slide_num_str)
            notes = notes_text.strip()
            speaker_notes[slide_num] = notes

        # Verify we got notes for all slides
        if len(speaker_notes) != len(frames):
            logging.warning(f"Expected notes for {len(frames)} slides but got {len(speaker_notes)}")
            # Fill in missing slides with empty notes
            for i in range(1, len(frames) + 1):
                if i not in speaker_notes:
                    speaker_notes[i] = ""
                    logging.warning(f"No notes found for slide {i}")

        logging.info(f"✓ Speaker notes generation completed for {len(speaker_notes)} slides")
        return speaker_notes

    except Exception as e:
        logging.error(f"Error generating speaker notes: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return None


def save_speaker_notes(speaker_notes: dict[int, str], paper_id: str, workspace_dir: str | None = None) -> bool:
    """
    Save speaker notes to a JSON file in the project directory.
    
    Args:
        speaker_notes: Dictionary mapping frame number to speaker notes
        paper_id: Paper ID
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        
    Returns:
        True if successful, False otherwise
    """
    import json

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    notes_file = f"{workspace_dir}speaker_notes.json"

    try:
        with open(notes_file, "w", encoding="utf-8") as f:
            json.dump(speaker_notes, f, indent=2, ensure_ascii=False)
        logging.info(f"✓ Saved speaker notes to {notes_file}")
        return True
    except Exception as e:
        logging.error(f"Failed to save speaker notes: {e}")
        return False


def load_speaker_notes(paper_id: str, workspace_dir: str | None = None) -> dict[int, str] | None:
    """
    Load speaker notes from a JSON file in the project directory.
    
    Args:
        paper_id: Paper ID
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        
    Returns:
        Dictionary mapping frame number to speaker notes, or None if not found
    """
    import json

    # Determine workspace directory
    if workspace_dir is None:
        workspace_dir = f"source/{paper_id}/"

    notes_file = f"{workspace_dir}speaker_notes.json"

    if not os.path.exists(notes_file):
        logging.debug(f"No speaker notes file found: {notes_file}")
        return None

    try:
        with open(notes_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Convert string keys back to integers
        speaker_notes = {int(k): v for k, v in data.items()}
        logging.info(f"✓ Loaded speaker notes from {notes_file}")
        return speaker_notes
    except Exception as e:
        logging.error(f"Failed to load speaker notes: {e}")
        return None



# Re-export commonly used functions for backwards compatibility
__all__ = [
    'generate_slides',
    'generate_slides_from_pdf',
    'generate_slides_from_latex_zip',
    'edit_slides',
    'edit_single_slide',
    'compile_latex',
    'extract_frames_from_beamer',
    'get_frame_by_number',
    'replace_frame_in_beamer',
    'search_arxiv',
    'generate_pdf_id',
    'extract_text_from_pdf',
    'extract_images_from_pdf',
    'generate_speaker_notes',
    'save_speaker_notes',
    'load_speaker_notes',
]
