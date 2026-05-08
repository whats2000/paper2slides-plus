#!/usr/bin/env python3
"""
YOLO11 Document Layout Figure Extraction Script for Docker Container
Extracts figures from PDF pages using YOLO11 document layout model.
"""

import sys
import json
from pathlib import Path
from ultralytics import YOLO
import pymupdf  # PyMuPDF for PDF to image conversion
import cv2
import numpy as np

# Model path (pre-downloaded in the Docker image)
MODEL_PATH = "/app/models/yolo11n_doc_layout.pt"


def has_text_between(box1, box2, text_boxes):
    """
    Check if there's any text between two picture boxes.

    Args:
        box1, box2: (x1, y1, x2, y2, confidence) tuples for pictures
        text_boxes: List of (x1, y1, x2, y2) tuples for text regions

    Returns:
        True if text exists between the boxes
    """
    x1_1, y1_1, x2_1, y2_1, _ = box1
    x1_2, y1_2, x2_2, y2_2, _ = box2

    # Create bounding box that encompasses both pictures
    region_x1 = min(x1_1, x1_2)
    region_y1 = min(y1_1, y1_2)
    region_x2 = max(x2_1, x2_2)
    region_y2 = max(y2_1, y2_2)

    # Check if any text box overlaps with the region between the two pictures
    for tx1, ty1, tx2, ty2 in text_boxes:
        # Check if text box is within or overlaps the region
        if not (
            tx2 < region_x1 or tx1 > region_x2 or ty2 < region_y1 or ty1 > region_y2
        ):
            # Text overlaps the region - check if it's actually between the pictures
            # (not inside either picture box)
            text_in_box1 = not (tx2 < x1_1 or tx1 > x2_1 or ty2 < y1_1 or ty1 > y2_1)
            text_in_box2 = not (tx2 < x1_2 or tx1 > x2_2 or ty2 < y1_2 or ty1 > y2_2)

            if not text_in_box1 and not text_in_box2:
                # Text is in the region but not inside either picture box
                return True

    return False


def merge_pictures_without_text_between(picture_boxes, text_boxes):
    """
    Merge picture boxes on same page if there's no text between them.

    Args:
        picture_boxes: List of (x1, y1, x2, y2, confidence) tuples for pictures
        text_boxes: List of (x1, y1, x2, y2) tuples for text regions

    Returns:
        List of merged picture boxes
    """
    if len(picture_boxes) == 0:
        return []

    # Create groups by merging pictures without text between them
    merged_groups = []
    used = [False] * len(picture_boxes)

    for i in range(len(picture_boxes)):
        if used[i]:
            continue

        # Start new group
        group = [i]
        used[i] = True

        # Keep expanding group by finding pictures without text between
        changed = True
        while changed:
            changed = False
            for j in range(len(picture_boxes)):
                if used[j]:
                    continue

                # Check if this picture can be merged with any picture in the group
                can_merge = False
                for idx in group:
                    if not has_text_between(
                        picture_boxes[idx], picture_boxes[j], text_boxes
                    ):
                        can_merge = True
                        break

                if can_merge:
                    group.append(j)
                    used[j] = True
                    changed = True

        merged_groups.append(group)

    # Convert groups to merged bounding boxes
    result = []
    for group in merged_groups:
        group_boxes = [picture_boxes[i] for i in group]
        x1 = min(b[0] for b in group_boxes)
        y1 = min(b[1] for b in group_boxes)
        x2 = max(b[2] for b in group_boxes)
        y2 = max(b[3] for b in group_boxes)
        conf = max(b[4] for b in group_boxes)
        result.append((x1, y1, x2, y2, conf))

    return result


def extract_figures_from_pdf(
    pdf_path: str, output_dir: str, start_page: int = None, end_page: int = None
) -> dict:
    """
    Extract figures from PDF using YOLO11 document layout detection.

    Args:
        pdf_path: Path to the input PDF file
        output_dir: Directory to save extracted figures
        start_page: Starting page number (1-indexed, inclusive)
        end_page: Ending page number (1-indexed, inclusive)

    Returns:
        Dictionary with extraction results
    """
    try:
        # Load YOLO model
        model = YOLO(MODEL_PATH)

        # Open PDF
        pdf_document = pymupdf.open(pdf_path)
        total_pages = len(pdf_document)

        # Validate page range
        start_idx = (start_page - 1) if start_page is not None else 0
        end_idx = end_page if end_page is not None else total_pages

        start_idx = max(0, min(start_idx, total_pages - 1))
        end_idx = max(start_idx + 1, min(end_idx, total_pages))

        # Create output directory
        output_path = Path(output_dir)
        figures_dir = output_path / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        extracted_figures = []
        figure_count = 0

        # Process each page
        for page_num in range(start_idx, end_idx):
            page = pdf_document.load_page(page_num)

            # Convert page to image (higher DPI for better detection)
            pix = page.get_pixmap(dpi=200)
            img_data = pix.pil_image()

            # Convert PIL to numpy array for YOLO
            img_array = np.array(img_data)

            # Run YOLO inference
            results = model.predict(img_array, imgsz=1280, conf=0.3, verbose=False)

            # Collect picture and text detections for this page
            page_pictures = []
            page_texts = []

            for result in results:
                boxes = result.boxes
                for i, box in enumerate(boxes):
                    class_id = int(box.cls[0])
                    class_name = result.names[class_id]
                    confidence = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                    # Collect pictures
                    if class_name.lower() == "picture":
                        page_pictures.append((x1, y1, x2, y2, confidence))
                    # Collect text regions
                    elif class_name.lower() == "text":
                        page_texts.append((x1, y1, x2, y2))

            # Merge pictures on same page if no text between them
            merged_boxes = merge_pictures_without_text_between(
                page_pictures, page_texts
            )

            # Extract merged figures
            for x1, y1, x2, y2, confidence in merged_boxes:
                # Extract the region
                cropped_img = img_array[y1:y2, x1:x2]

                # Skip small images
                height, width = cropped_img.shape[:2]
                if width < 100 or height < 100:
                    continue

                # Save the figure
                figure_filename = f"figure_{figure_count:03d}.png"
                figure_path = figures_dir / figure_filename
                cv2.imwrite(
                    str(figure_path), cv2.cvtColor(cropped_img, cv2.COLOR_RGB2BGR)
                )

                extracted_figures.append(
                    {
                        "filename": figure_filename,
                        "relative_path": f"figures/{figure_filename}",
                        "page": page_num + 1,
                        "confidence": confidence,
                        "bbox": [x1, y1, x2, y2],
                        "size": [width, height],
                    }
                )
                figure_count += 1

        pdf_document.close()

        # Return results as JSON
        return {
            "success": True,
            "total_figures": figure_count,
            "figures": extracted_figures,
            "pages_processed": f"{start_idx + 1}-{end_idx}",
            "total_pages": total_pages,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python yolo11_extract.py <pdf_path> <output_dir> [start_page] [end_page]"
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = sys.argv[2]
    start_page = int(sys.argv[3]) if len(sys.argv) > 3 else None
    end_page = int(sys.argv[4]) if len(sys.argv) > 4 else None

    result = extract_figures_from_pdf(pdf_path, output_dir, start_page, end_page)
    print(json.dumps(result, indent=2))
