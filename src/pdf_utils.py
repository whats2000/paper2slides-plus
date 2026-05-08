"""PDF utility functions for extracting text and images from PDF files."""

import logging
import hashlib
import subprocess
import json
import shutil
from pathlib import Path
from PIL import Image
import io
import fitz  # PyMuPDF


def extract_text_from_pdf(
    pdf_path: str, start_page: int | None = None, end_page: int | None = None
) -> str:
    """
    Extract text content from a PDF file using PyMuPDF.

    Args:
        pdf_path: Path to the PDF file
        start_page: Starting page number (1-indexed, inclusive). If None, starts from page 1.
        end_page: Ending page number (1-indexed, inclusive). If None, goes to last page.

    Returns:
        Extracted text content
    """
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Validate and adjust page range (convert from 1-indexed to 0-indexed)
        start_idx = (start_page - 1) if start_page is not None else 0
        end_idx = end_page if end_page is not None else total_pages

        # Ensure valid range
        start_idx = max(0, min(start_idx, total_pages - 1))
        end_idx = max(start_idx + 1, min(end_idx, total_pages))

        logging.info(
            f"Extracting text from pages {start_idx + 1} to {end_idx} (out of {total_pages} total pages)"
        )

        text_content = []
        for page_num in range(start_idx, end_idx):
            page = doc.load_page(page_num)
            text_content.append(page.get_text())

        doc.close()
        return "\n\n".join(text_content)
    except Exception as e:
        logging.error(f"Failed to extract text from PDF: {e}")
        raise


def _check_pdffigures2_available() -> bool:
    """
    Check if pdffigures2 is available via Docker.

    Returns:
        True if pdffigures2 Docker service is running
    """
    # Check if Docker is available with pdffigures2 service
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "pdffigures2" in result.stdout:
            logging.info("pdffigures2 Docker service is available")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    logging.info("pdffigures2 not available, falling back to PyMuPDF")
    return False


def _check_yolo11_available() -> bool:
    """
    Check if YOLO11 Document Layout is available via Docker.

    Returns:
        True if YOLO11 Document Layout Docker service is running
    """
    # Check if Docker is available with yolo11-doc-layout service
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and "yolo11-doc-layout" in result.stdout:
            logging.info("YOLO11 Document Layout Docker service is available")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    logging.info("YOLO11 Document Layout not available")
    return False


def _extract_images_with_pdffigures2(pdf_path: str, output_dir: str) -> list[str]:
    """
    Extract images using pdffigures2 via Docker.

    Args:
        pdf_path: Path to the PDF file (host path)
        output_dir: Directory to save extracted images (host path)

    Returns:
        List of relative paths to extracted images
    """
    figures_dir = Path(output_dir) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # Create a temporary directory for pdffigures2 output
    temp_output_dir = Path(output_dir) / "temp_pdffigures2"
    temp_output_dir.mkdir(parents=True, exist_ok=True)

    metadata_file = temp_output_dir / "figures.json"

    try:
        # Convert host paths to Docker container paths
        # Docker volumes are mounted in docker-compose.yml:
        # - ./source:/data/source
        # - ./cache:/data/cache
        workspace_root = Path.cwd()
        pdf_path_abs = Path(pdf_path).resolve()
        temp_output_abs = temp_output_dir.resolve()

        try:
            pdf_rel = pdf_path_abs.relative_to(workspace_root)
            docker_pdf_path = f"/data/{pdf_rel.as_posix()}"

            output_rel = temp_output_abs.relative_to(workspace_root)
            docker_output_dir = f"/data/{output_rel.as_posix()}"
        except ValueError:
            logging.error("PDF or output path is outside workspace, cannot use Docker")
            return []

        # Ensure the temp directory exists in the container
        subprocess.run(
            [
                "docker-compose",
                "exec",
                "-T",
                "pdffigures2",
                "mkdir",
                "-p",
                docker_output_dir,
            ],
            capture_output=True,
            timeout=10,
        )

        # Run pdffigures2 in the Docker container
        # The JAR is already at /app/pdffigures2.jar inside the container
        # -m (--figure-prefix) and -d (--figure-data-prefix) are PREFIXES, not directories!
        # They should end with a trailing slash to specify a directory prefix
        cmd = [
            "docker-compose",
            "exec",
            "-T",
            "pdffigures2",
            "java",
            "-jar",
            "/app/pdffigures2.jar",
            docker_pdf_path,
            "-d",
            f"{docker_output_dir}/",
            "-m",
            f"{docker_output_dir}/",
        ]

        logging.info(f"Running pdffigures2 via Docker: {docker_pdf_path}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            logging.warning(f"pdffigures2 failed: {result.stderr}")
            return []

        logging.info("pdffigures2 extraction completed successfully")

        # Parse the JSON metadata - pdffigures2 creates filename.json in the output directory
        # Look for JSON files in the temp directory
        json_files = list(temp_output_dir.glob("*.json"))
        if not json_files:
            logging.warning("pdffigures2 metadata file not found")
            return []

        metadata_file = json_files[0]  # Use the first JSON file found

        with open(metadata_file, "r", encoding="utf-8") as f:
            figures_data = json.load(f)

        image_paths = []

        # Get all PNG files from temp directory
        all_png_files = sorted(temp_output_dir.glob("*.png"))

        # Move extracted figures to the figures directory with cleaner names
        for idx, (figure, png_file) in enumerate(zip(figures_data, all_png_files)):
            figure_type = figure.get("figType", "Figure")
            caption = figure.get("caption", "")

            # Copy to figures directory with a cleaner name
            new_filename = f"figure_{idx:03d}.png"
            dest_path = figures_dir / new_filename
            shutil.copy2(png_file, dest_path)

            relative_path = f"figures/{new_filename}"
            image_paths.append(relative_path)

            logging.info(f"Extracted {figure_type}: {relative_path}")
            if caption:
                logging.debug(f"  Caption: {caption[:100]}...")

        # Clean up temp directory
        shutil.rmtree(temp_output_dir, ignore_errors=True)

        logging.info(f"Total figures extracted with pdffigures2: {len(image_paths)}")
        return image_paths

    except subprocess.TimeoutExpired:
        logging.error("pdffigures2 timed out")
        return []
    except Exception as e:
        logging.error(f"Error running pdffigures2: {e}")
        return []


def _extract_images_with_yolo11(
    pdf_path: str,
    output_dir: str,
    start_page: int | None = None,
    end_page: int | None = None,
) -> list[str]:
    """
    Extract images using YOLO11 document layout model via Docker.

    Args:
        pdf_path: Path to the PDF file (host path)
        output_dir: Directory to save extracted images (host path)
        start_page: Starting page number (1-indexed, inclusive)
        end_page: Ending page number (1-indexed, inclusive)

    Returns:
        List of relative paths to extracted images
    """
    try:
        # Convert host paths to Docker container paths
        workspace_root = Path.cwd()
        pdf_path_abs = Path(pdf_path).resolve()
        output_abs = Path(output_dir).resolve()

        try:
            pdf_rel = pdf_path_abs.relative_to(workspace_root)
            # Use forward slashes for Docker paths
            docker_pdf_path = f"/data/{pdf_rel.as_posix()}"

            output_rel = output_abs.relative_to(workspace_root)
            # Use forward slashes for Docker paths
            docker_output_dir = f"/data/{output_rel.as_posix()}"
        except ValueError:
            logging.error("PDF or output path is outside workspace, cannot use Docker")
            return []

        # Build the command
        cmd = [
            "docker-compose",
            "exec",
            "-T",
            "yolo11-doc-layout",
            "python",
            "/app/yolo11_doc_layout_extract.py",
            docker_pdf_path,
            docker_output_dir,
        ]

        # Add optional page range arguments
        if start_page is not None:
            cmd.append(str(start_page))
            if end_page is not None:
                cmd.append(str(end_page))

        logging.info(f"Running YOLO11 via Docker: {docker_pdf_path}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,  # 5 minutes for longer papers
        )

        if result.returncode != 0:
            logging.warning(f"YOLO11 extraction failed: {result.stderr}")
            return []

        # Parse JSON output
        try:
            result_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse YOLO11 output: {e}")
            logging.debug(f"Output was: {result.stdout}")
            return []

        if not result_data.get("success", False):
            logging.warning(
                f"YOLO11 extraction failed: {result_data.get('error', 'Unknown error')}"
            )
            return []

        # Extract relative paths from results
        image_paths = [fig["relative_path"] for fig in result_data.get("figures", [])]

        logging.info(
            f"YOLO11 extracted {result_data.get('total_figures', 0)} figures from {result_data.get('pages_processed', 'all')} pages"
        )

        return image_paths

    except subprocess.TimeoutExpired:
        logging.error("YOLO11 extraction timed out")
        return []
    except Exception as e:
        logging.error(f"Error running YOLO11: {e}")
        return []


def extract_images_from_pdf(
    pdf_path: str,
    output_dir: str,
    start_page: int | None = None,
    end_page: int | None = None,
) -> list[str]:
    """
    Extract images from a PDF file. Uses YOLO11 for ML-based figure detection if available,
    otherwise tries pdffigures2, and finally falls back to PyMuPDF.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted images
        start_page: Starting page number (1-indexed, inclusive). If None, starts from page 1.
        end_page: Ending page number (1-indexed, inclusive). If None, goes to last page.

    Returns:
        List of relative paths to extracted images
    """
    # Try YOLO11 first (best accuracy with ML-based detection)
    if _check_yolo11_available():
        try:
            result = _extract_images_with_yolo11(
                pdf_path, output_dir, start_page, end_page
            )
            if result:
                logging.info(
                    f"Successfully extracted {len(result)} figures using YOLO11"
                )
                return result
            else:
                logging.info("YOLO11 returned no results, falling back to pdffigures2")
        except Exception as e:
            logging.warning(
                f"YOLO11 extraction failed: {e}, falling back to pdffigures2"
            )

    # Try pdffigures2 if no page range is specified (pdffigures2 doesn't support page ranges)
    if start_page is None and end_page is None:
        if _check_pdffigures2_available():
            try:
                result = _extract_images_with_pdffigures2(pdf_path, output_dir)
                if result:
                    logging.info(
                        f"Successfully extracted {len(result)} figures using pdffigures2"
                    )
                    return result
                else:
                    logging.info(
                        "pdffigures2 returned no results, falling back to PyMuPDF"
                    )
            except Exception as e:
                logging.warning(
                    f"pdffigures2 extraction failed: {e}, falling back to PyMuPDF"
                )
    else:
        logging.info(
            "Page range specified, skipping pdffigures2 (doesn't support page ranges)"
        )

    # Fallback to original PyMuPDF implementation
    logging.info("Using PyMuPDF for image extraction")
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        # Validate and adjust page range (convert from 1-indexed to 0-indexed)
        start_idx = (start_page - 1) if start_page is not None else 0
        end_idx = end_page if end_page is not None else total_pages

        # Ensure valid range
        start_idx = max(0, min(start_idx, total_pages - 1))
        end_idx = max(start_idx + 1, min(end_idx, total_pages))

        logging.info(
            f"Extracting images from pages {start_idx + 1} to {end_idx} (out of {total_pages} total pages)"
        )

        image_paths = []
        figures_dir = Path(output_dir) / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        image_count = 0

        for page_num in range(start_idx, end_idx):
            page = doc.load_page(page_num)
            image_list = page.get_images(full=True)

            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]

                # Skip very small images (likely logos or decorations)
                # Check image dimensions
                try:
                    img_pil = Image.open(io.BytesIO(image_bytes))
                    width, height = img_pil.size

                    # Skip images smaller than 100x100 pixels
                    if width < 100 or height < 100:
                        logging.debug(
                            f"Skipping small image on page {page_num + 1}: {width}x{height}"
                        )
                        continue

                    # Skip images with extreme aspect ratios (likely not figures)
                    aspect_ratio = max(width, height) / min(width, height)
                    if aspect_ratio > 10:
                        logging.debug(
                            f"Skipping image with extreme aspect ratio on page {page_num + 1}: {aspect_ratio}"
                        )
                        continue

                except Exception as e:
                    logging.warning(f"Could not check image dimensions: {e}")

                # Save image with a meaningful name
                image_filename = f"figure_{image_count:03d}.{image_ext}"
                image_path = figures_dir / image_filename

                with open(image_path, "wb") as img_file:
                    img_file.write(image_bytes)

                # Store relative path for LaTeX
                relative_path = f"figures/{image_filename}"
                image_paths.append(relative_path)
                image_count += 1

                logging.info(
                    f"Extracted image from page {page_num + 1}: {relative_path}"
                )

        doc.close()

        logging.info(f"Total images extracted: {len(image_paths)}")
        return image_paths

    except Exception as e:
        logging.error(f"Failed to extract images from PDF: {e}")
        return []


def generate_pdf_id(pdf_path: str) -> str:
    """
    Generate a unique ID for a PDF file based on its content hash.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        A unique identifier (first 12 chars of SHA256 hash)
    """
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    return f"pdf_{file_hash[:12]}"
