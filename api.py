#!/usr/bin/env python3
"""
FastAPI service for paper2slides - Generate slides from academic papers via HTTP API

This service provides REST endpoints to:
- Generate slides from arXiv papers
- Generate slides from uploaded PDF files
- Download generated PDF presentations
- Check generation status

Usage:
    uvicorn api:app --host 0.0.0.0 --port 8000

API Documentation available at:
    http://localhost:8000/docs (Swagger UI)
    http://localhost:8000/redoc (ReDoc)
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.compiler import compile_latex
from src.core import (
    generate_slides,
    generate_slides_from_pdf,
    generate_slides_from_latex_zip,
    generate_pdf_id,
    edit_slides,
    edit_single_slide,
    generate_speaker_notes,
    save_speaker_notes,
    load_speaker_notes,
)
from src.file_utils import read_file

# Load environment variables
load_dotenv(override=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# FastAPI app initialization
app = FastAPI(
    title="paper2slides API",
    description="Generate presentation slides from academic papers (arXiv or PDF)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Job status tracking
class JobStatus(str, Enum):
    PENDING = "pending"
    GENERATING = "generating"
    COMPILING = "compiling"
    COMPLETED = "completed"
    FAILED = "failed"

# Job index file location
API_WORKSPACES_DIR = "api_workspaces"
JOB_INDEX_FILE = os.path.join(API_WORKSPACES_DIR, "job_index.json")

# Job index management functions
def load_job_index() -> dict[tuple[str, str], dict[str, Any]]:
    """Load job index from disk, or scan workspace directories if index doesn't exist"""
    os.makedirs(API_WORKSPACES_DIR, exist_ok=True)
    
    if os.path.exists(JOB_INDEX_FILE):
        try:
            with open(JOB_INDEX_FILE, 'r', encoding='utf-8') as f:
                data: dict[str, dict[str, Any]] = json.load(f)
                # Convert string keys back to tuples
                result: dict[tuple[str, str], dict[str, Any]] = {
                    (a, b): v
                    for k, v in data.items()
                    for a, b in [k.split("||")]
                }
                return result
        except Exception as e:
            logger.warning(f"Failed to load job index: {e}. Scanning workspace directories...")
    
    # Scan workspace directories to rebuild index
    return scan_workspace_directories()

def scan_workspace_directories() -> dict[tuple[str, str], dict[str, Any]]:
    """Scan api_workspaces directory to discover existing jobs"""
    exist_jobs = {}
    
    if not os.path.exists(API_WORKSPACES_DIR):
        return exist_jobs
    
    # Iterate through user directories
    for user_dir in os.listdir(API_WORKSPACES_DIR):
        user_path = os.path.join(API_WORKSPACES_DIR, user_dir)
        
        # Skip files (like job_index.json)
        if not os.path.isdir(user_path):
            continue
        
        user_id = user_dir
        
        # Iterate through paper directories
        for paper_dir in os.listdir(user_path):
            paper_path = os.path.join(user_path, paper_dir)
            
            if not os.path.isdir(paper_path):
                continue
            
            paper_id = paper_dir
            workspace_dir = f"{API_WORKSPACES_DIR}/{user_id}/{paper_id}/"
            
            # Determine job status based on files present
            slides_pdf = os.path.join(paper_path, "slides.pdf")
            slides_tex = os.path.join(paper_path, "slides.tex")
            
            if os.path.exists(slides_pdf):
                status = JobStatus.COMPLETED
                pdf_ready = True
            elif os.path.exists(slides_tex):
                status = JobStatus.FAILED  # Has tex but no PDF
                pdf_ready = False
            else:
                status = JobStatus.FAILED  # Incomplete job
                pdf_ready = False
            
            # Get timestamps
            created_at = datetime.fromtimestamp(os.path.getctime(paper_path)).isoformat()
            updated_at = datetime.fromtimestamp(os.path.getmtime(paper_path)).isoformat()
            
            job_key = (user_id, paper_id)
            exist_jobs[job_key] = {
                "user_id": user_id,
                "paper_id": paper_id,
                "workspace_dir": workspace_dir,
                "status": status,
                "message": f"Discovered from workspace scan (status: {status})",
                "source_type": "unknown",
                "created_at": created_at,
                "updated_at": updated_at,
                "error": None,
                "pdf_ready": pdf_ready,
            }
    
    logger.info(f"Scanned workspace and found {len(exist_jobs)} existing exist_jobs")
    return exist_jobs

def save_job_index(jobs_to_save: dict[tuple[str, str], dict[str, Any]]):
    """Save job index to disk"""
    try:
        # Convert tuple keys to strings for JSON serialization
        data = {'||'.join(k): v for k, v in jobs_to_save.items()}
        
        with open(JOB_INDEX_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save job index: {e}")

def get_job(user_id: str, paper_id: str) -> Optional[dict[str, Any]]:
    """Get a job from the index"""
    job_key = (user_id, paper_id)
    return jobs.get(job_key)

def update_job_index(user_id: str, paper_id: str, updates: dict[str, Any]):
    """Update a job in the index and save to disk"""
    job_key = (user_id, paper_id)
    if job_key in jobs:
        jobs[job_key].update(updates)
        jobs[job_key]["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_job_index(jobs)

# Load jobs from disk on startup
jobs: dict[tuple[str, str], dict[str, Any]] = load_job_index()
logger.info(f"Loaded {len(jobs)} jobs from index")

# Request/Response Models
class ArxivGenerateRequest(BaseModel):
    """Request model for generating slides from arXiv paper"""
    arxiv_id: str = Field(..., description="arXiv paper ID (e.g., 2505.18102)", json_schema_extra={"example": "2505.18102"})
    user_id: str = Field(..., description="User ID for multi-user isolation")
    api_key: Optional[str] = Field(default=None, description="OpenAI/LLM API key (optional, uses server default if not provided)")
    use_linter: bool = Field(default=True, description="Use ChkTeX linter for validation")
    use_pdfcrop: bool = Field(default=False, description="Use pdfcrop to trim figures")
    model_name: Optional[str] = Field(default=None, description="LLM model to use (defaults to env DEFAULT_MODEL)")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL for OpenAI-compatible APIs")

class PDFGenerateRequest(BaseModel):
    """Request model for generating slides from PDF (multipart form data)"""
    use_linter: bool = Field(default=True, description="Use ChkTeX linter for validation")
    use_pdfcrop: bool = Field(default=False, description="Use pdfcrop to trim figures")
    start_page: Optional[int] = Field(default=None, description="Starting page number (1-indexed, inclusive)")
    end_page: Optional[int] = Field(default=None, description="Ending page number (1-indexed, inclusive)")
    model_name: Optional[str] = Field(default=None, description="LLM model to use")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")

class JobResponse(BaseModel):
    """Response model for job creation"""
    user_id: str = Field(..., description="User ID for workspace isolation (reuse this for subsequent requests)")
    paper_id: str = Field(..., description="Paper/document identifier")
    status: JobStatus = Field(..., description="Current job status")
    message: str = Field(..., description="Status message")
    created_at: str = Field(..., description="Job creation timestamp")

class JobStatusResponse(BaseModel):
    """Response model for job status query"""
    user_id: str
    paper_id: str
    status: JobStatus
    message: str
    created_at: str
    updated_at: str
    workspace_dir: str
    error: Optional[str] = None
    pdf_ready: bool = False

class EditSlidesRequest(BaseModel):
    """Request model for editing entire slide deck"""
    instruction: str = Field(..., description="Editing instruction for the LLM")
    api_key: Optional[str] = Field(default=None, description="API key (optional, uses server default if not provided)")
    model_name: Optional[str] = Field(default=None, description="LLM model to use")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    use_paper_context: bool = Field(default=True, description="Include original paper context during editing")

class EditSingleSlideRequest(BaseModel):
    """Request model for editing a specific slide"""
    slide_number: int = Field(..., description="Slide/frame number to edit (1-indexed)", ge=1)
    instruction: str = Field(..., description="Editing instruction for the LLM")
    api_key: Optional[str] = Field(default=None, description="API key (optional)")
    model_name: Optional[str] = Field(default=None, description="LLM model to use")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    use_paper_context: bool = Field(default=True, description="Include original paper context")

class SpeakerNotesRequest(BaseModel):
    """Request model for generating speaker notes"""
    instruction: str = Field(default="", description="Optional custom instruction for speaker note generation")
    api_key: Optional[str] = Field(default=None, description="API key (optional)")
    model_name: Optional[str] = Field(default=None, description="LLM model to use")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")

# Helper functions
def create_job(paper_id: str, source_type: str, user_id: Optional[str] = None) -> tuple[str, str, str]:
    """Create a new job entry and return (user_id, paper_id, workspace_dir)"""
    if not user_id:
        user_id = f"user_{uuid.uuid4().hex[:8]}"
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Create user-specific workspace directory in api_workspaces (with trailing slash to match core.py style)
    workspace_dir = f"{API_WORKSPACES_DIR}/{user_id}/{paper_id}/"
    os.makedirs(workspace_dir, exist_ok=True)
    
    job_key = (user_id, paper_id)
    jobs[job_key] = {
        "user_id": user_id,
        "paper_id": paper_id,
        "workspace_dir": workspace_dir,
        "status": JobStatus.PENDING,
        "message": f"Job created for {source_type}",
        "source_type": source_type,
        "created_at": timestamp,
        "updated_at": timestamp,
        "error": None,
        "pdf_ready": False,
    }
    
    # Save index to disk
    save_job_index(jobs)
    
    return user_id, paper_id, workspace_dir

def update_job(user_id: str, paper_id: str, status: JobStatus, message: str, error: Optional[str] = None):
    """Update job status"""
    updates: dict[
        str, Any
    ] = {
        "status": status,
        "message": message,
    }
    
    if error:
        updates["error"] = error
    
    if status == JobStatus.COMPLETED:
        updates["pdf_ready"] = True
    
    update_job_index(user_id, paper_id, updates)

def get_workspace_dir(user_id: str, paper_id: str) -> str:
    """Get the workspace directory for a given job"""
    job_key = (user_id, paper_id)
    if job_key not in jobs:
        raise HTTPException(status_code=404, detail=f"Job ({user_id}, {paper_id}) not found")

    job = jobs[job_key]

    if job["status"] != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Job must be completed before generating speaker notes. Current status: {job['status']}"
        )

    workspace_dir = job["workspace_dir"]

    return workspace_dir

async def generate_slides_task(
    user_id: str,
    paper_id: str,
    workspace_dir: str,
    source_type: str,
    api_key: Optional[str] = None,
    pdf_path: Optional[str] = None,
    zip_path: Optional[str] = None,
    use_linter: bool = True,
    use_pdfcrop: bool = False,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
):
    """Background task to generate slides in user-specific workspace"""
    try:
        update_job(user_id, paper_id, JobStatus.GENERATING, "Generating slides from source...")
        
        # Use provided API key or fall back to environment variable
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("API key not provided and OPENAI_API_KEY not set in environment")
        
        # Generate slides based on source type, directly into workspace_dir
        if source_type == "arxiv":
            # For arXiv, generate directly in workspace_dir
            logger.info(f"Generating slides for arXiv paper {paper_id} in workspace {workspace_dir}")
            success = await asyncio.to_thread(
                generate_slides,
                paper_id,
                use_linter,
                use_pdfcrop,
                api_key,
                model_name,
                base_url,
                workspace_dir,  # Pass workspace_dir to generate_slides
            )
        elif source_type == "pdf":
            # For PDF, generate directly in workspace_dir
            logger.info(f"Generating slides for PDF {paper_id} in workspace {workspace_dir}")
            success = await asyncio.to_thread(
                generate_slides_from_pdf,
                pdf_path,
                paper_id,
                use_linter,
                use_pdfcrop,
                api_key,
                model_name,
                base_url,
                None,  # dashscope_base_url
                start_page,
                end_page,
                workspace_dir,  # Pass workspace_dir to generate_slides_from_pdf
            )
        elif source_type == "latex_zip":
            # LaTeX ZIP: same pipeline as arXiv, just from a local zip
            logger.info(f"Generating slides for LaTeX zip {paper_id} in workspace {workspace_dir}")
            success = await asyncio.to_thread(
                generate_slides_from_latex_zip,
                zip_path,
                paper_id,
                use_linter,
                use_pdfcrop,
                api_key,
                model_name,
                base_url,
                workspace_dir,
            )
        else:
            raise ValueError(f"Unknown source type: {source_type}")
        
        if not success:
            # Check if slides.tex exists to provide better error message
            slides_path = os.path.join(workspace_dir, "slides.tex")
            if not os.path.exists(slides_path):
                raise RuntimeError(f"Slide generation failed - slides.tex not created. Check LLM API logs.")
            else:
                raise RuntimeError("Slide generation failed - LLM returned unsuccessful status")
        
        update_job(user_id, paper_id, JobStatus.COMPILING, "Compiling LaTeX to PDF...")
        
        # Compile slides to PDF in workspace directory
        if not os.path.exists(workspace_dir):
            raise FileNotFoundError(f"Workspace directory not found at {workspace_dir}")
        
        tex_filename = "slides.tex"  # Just the filename, not the full path
        compile_success = await asyncio.to_thread(compile_latex, tex_filename, workspace_dir)
        
        if not compile_success:
            raise RuntimeError("PDF compilation failed")
        
        # Check if PDF was generated
        pdf_path_check = os.path.join(workspace_dir, "slides.pdf")
        if not os.path.exists(pdf_path_check):
            raise FileNotFoundError(f"Generated PDF not found at {pdf_path_check}")
        
        update_job(user_id, paper_id, JobStatus.COMPLETED, "Slides generated successfully!")
        logger.info(f"Job ({user_id}, {paper_id}) completed successfully in {workspace_dir}")
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Job ({user_id}, {paper_id}) failed: {error_msg}")
        update_job(user_id, paper_id, JobStatus.FAILED, "Generation failed", error=error_msg)

# API Endpoints
@app.get("/", tags=["Health"])
async def root():
    """API health check endpoint"""
    return {
        "service": "paper2slides API",
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
    }

@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check with environment info"""
    return {
        "status": "healthy",
        "default_api_key_configured": bool(os.getenv("OPENAI_API_KEY")),
        "default_model": os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14"),
        "supports_custom_api_keys": True,
        "active_jobs": len([j for j in jobs.values() if j["status"] in [JobStatus.PENDING, JobStatus.GENERATING, JobStatus.COMPILING]]),
        "completed_jobs": len([j for j in jobs.values() if j["status"] == JobStatus.COMPLETED]),
    }

@app.post("/generate/arxiv", response_model=JobResponse, tags=["Generate"])
async def generate_from_arxiv(
    request: ArxivGenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    Generate slides from an arXiv paper.
    
    This endpoint starts a background job to:
    1. Download the paper from arXiv
    2. Generate Beamer slides using LLM
    3. Compile slides to PDF
    
    Returns a job_id to track progress and download the result.
    """
    try:
        paper_id = request.arxiv_id
        user_id, paper_id, workspace_dir = create_job(paper_id, "arxiv", request.user_id)
        
        # Start background task
        background_tasks.add_task(
            generate_slides_task,
            user_id=user_id,
            paper_id=paper_id,
            workspace_dir=workspace_dir,
            source_type="arxiv",
            api_key=request.api_key,
            use_linter=request.use_linter,
            use_pdfcrop=request.use_pdfcrop,
            model_name=request.model_name,
            base_url=request.base_url,
        )
        
        job_key = (user_id, paper_id)
        return JobResponse(
            user_id=user_id,
            paper_id=paper_id,
            status=JobStatus.PENDING,
            message=f"Job created for arXiv paper {paper_id}",
            created_at=jobs[job_key]["created_at"],
        )
        
    except Exception as e:
        logger.error(f"Failed to create arxiv job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/pdf", response_model=JobResponse, tags=["Generate"])
async def generate_from_pdf(
    background_tasks: BackgroundTasks,
    user_id: str = Query(..., description="User ID for isolation"),
    file: UploadFile = File(..., description="PDF file to process"),
    api_key: Optional[str] = Query(default=None, description="OpenAI/LLM API key"),
    use_linter: bool = Query(default=True, description="Use ChkTeX linter"),
    use_pdfcrop: bool = Query(default=False, description="Use pdfcrop"),
    start_page: Optional[int] = Query(default=None, description="Starting page (1-indexed)"),
    end_page: Optional[int] = Query(default=None, description="Ending page (1-indexed)"),
    model_name: Optional[str] = Query(default=None, description="LLM model"),
    base_url: Optional[str] = Query(default=None, description="Custom API base URL"),
):
    """
    Generate slides from an uploaded PDF file.
    
    This endpoint:
    1. Accepts a PDF file upload
    2. Extracts text and images from the PDF
    3. Generates Beamer slides using LLM
    4. Compiles slides to PDF
    
    Optionally specify page range to process only a portion of the PDF (useful for books/long documents).
    
    Returns a job_id to track progress and download the result.
    """
    try:
        # Validate file type
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_pdf_path = tmp_file.name
        
        # Generate unique paper_id for this PDF
        paper_id = generate_pdf_id(tmp_pdf_path)
        assigned_user_id, paper_id, workspace_dir = create_job(paper_id, "pdf", user_id)
        
        # Start background task
        background_tasks.add_task(
            generate_slides_task,
            user_id=assigned_user_id,
            paper_id=paper_id,
            workspace_dir=workspace_dir,
            source_type="pdf",
            api_key=api_key,
            pdf_path=tmp_pdf_path,
            use_linter=use_linter,
            use_pdfcrop=use_pdfcrop,
            model_name=model_name,
            base_url=base_url,
            start_page=start_page,
            end_page=end_page,
        )
        
        job_key = (assigned_user_id, paper_id)
        return JobResponse(
            user_id=assigned_user_id,
            paper_id=paper_id,
            status=JobStatus.PENDING,
            message=f"Job created for uploaded PDF (paper_id: {paper_id})",
            created_at=jobs[job_key]["created_at"],
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create PDF job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/latex-zip", response_model=JobResponse, tags=["Generate"])
async def generate_from_latex_zip(
    background_tasks: BackgroundTasks,
    user_id: str = Query(..., description="User ID for isolation"),
    file: UploadFile = File(..., description="LaTeX project zip file to process"),
    api_key: Optional[str] = Query(default=None, description="OpenAI/LLM API key"),
    use_linter: bool = Query(default=True, description="Use ChkTeX linter"),
    use_pdfcrop: bool = Query(default=False, description="Use pdfcrop"),
    model_name: Optional[str] = Query(default=None, description="LLM model"),
    base_url: Optional[str] = Query(default=None, description="Custom API base URL"),
):
    """
    Generate slides from an uploaded LaTeX project zip file.

    This is the same pipeline as /generate/arxiv — the only difference is that
    the LaTeX source comes from the uploaded zip instead of being downloaded from
    arXiv. The zip must contain a main .tex file with a \\documentclass directive.
    Images/figures inside the zip are copied automatically.

    Returns a job_id to track progress and download the result.
    """
    try:
        if not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only zip files are supported")

        # Save uploaded zip to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            content = await file.read()
            tmp_file.write(content)
            tmp_zip_path = tmp_file.name

        # Derive a stable paper_id from the zip's content hash
        import hashlib
        zip_hash = hashlib.sha256(content).hexdigest()[:12]
        paper_id = f"zip_{zip_hash}"

        assigned_user_id, paper_id, workspace_dir = create_job(paper_id, "latex_zip", user_id)

        background_tasks.add_task(
            generate_slides_task,
            user_id=assigned_user_id,
            paper_id=paper_id,
            workspace_dir=workspace_dir,
            source_type="latex_zip",
            api_key=api_key,
            zip_path=tmp_zip_path,
            use_linter=use_linter,
            use_pdfcrop=use_pdfcrop,
            model_name=model_name,
            base_url=base_url,
        )

        job_key = (assigned_user_id, paper_id)
        return JobResponse(
            user_id=assigned_user_id,
            paper_id=paper_id,
            status=JobStatus.PENDING,
            message=f"Job created for LaTeX zip upload (paper_id: {paper_id})",
            created_at=jobs[job_key]["created_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create LaTeX zip job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status/{user_id}/{paper_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(user_id: str, paper_id: str):
    """
    Get the status of a generation job.
    
    Use this endpoint to poll for job completion after calling /generate/arxiv or /generate/pdf.
    """
    job_key = (user_id, paper_id)
    if job_key not in jobs:
        raise HTTPException(status_code=404, detail=f"Job ({user_id}, {paper_id}) not found")
    
    job = jobs[job_key]
    
    return JobStatusResponse(
        user_id=job["user_id"],
        paper_id=job["paper_id"],
        status=job["status"],
        message=job["message"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        workspace_dir=job["workspace_dir"],
        error=job.get("error"),
        pdf_ready=job["pdf_ready"],
    )

@app.get("/jobs/{user_id}", tags=["Jobs"])
async def list_jobs(
    user_id: str,
    status: Optional[JobStatus] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=1000, description="Maximum number of jobs to return"),
):
    """
    List jobs for a specific user with optional status filtering.
    """
    # Filter by user_id first
    job_list = [j for j in jobs.values() if j["user_id"] == user_id]
    
    # Filter by status if specified
    if status:
        job_list = [j for j in job_list if j["status"] == status]
    
    # Sort by creation time (newest first)
    job_list.sort(key=lambda x: x["created_at"], reverse=True)
    
    # Apply limit
    job_list = job_list[:limit]
    
    return {
        "total": len(job_list),
        "jobs": job_list,
    }

@app.get("/download/{user_id}/{paper_id}", tags=["Download"])
async def download_pdf(user_id: str, paper_id: str):
    """
    Download the generated PDF for a completed job.
    
    Only works for jobs with status='completed'. Returns the slides.pdf file.
    """
    workspace_dir = get_workspace_dir(user_id, paper_id)
    pdf_path = os.path.join(workspace_dir, "slides.pdf")
    
    if not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=404,
            detail=f"PDF file not found at {pdf_path}"
        )
    
    # Return PDF file with appropriate headers
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{paper_id}_slides.pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{paper_id}_slides.pdf"',
        }
    )

@app.get("/download/{user_id}/{paper_id}/tex", tags=["Download"])
async def download_tex(user_id: str, paper_id: str):
    """
    Download the generated LaTeX source (.tex) file for a completed job.
    
    Useful for manual editing or debugging.
    """
    workspace_dir = get_workspace_dir(user_id, paper_id)
    tex_path = os.path.join(workspace_dir, "slides.tex")
    
    if not os.path.exists(tex_path):
        raise HTTPException(
            status_code=404,
            detail=f"TeX file not found at {tex_path}"
        )
    
    return FileResponse(
        tex_path,
        media_type="application/x-tex",
        filename=f"{paper_id}_slides.tex",
        headers={
            "Content-Disposition": f'attachment; filename="{paper_id}_slides.tex"',
        }
    )

@app.delete("/jobs/{user_id}/{paper_id}", tags=["Jobs"])
async def delete_job(user_id: str, paper_id: str):
    """
    Delete a job and its associated files.
    
    This removes the job from the tracking system and optionally cleans up generated files.
    """
    job_key = (user_id, paper_id)
    if job_key not in jobs:
        raise HTTPException(status_code=404, detail=f"Job ({user_id}, {paper_id}) not found")
    
    job = jobs[job_key]
    workspace_dir = job["workspace_dir"]
    
    # Remove job from tracking
    del jobs[job_key]
    save_job_index(jobs)  # Save after deletion
    
    # Optionally clean up generated files
    if os.path.exists(workspace_dir):
        try:
            shutil.rmtree(workspace_dir)
            logger.info(f"Deleted workspace directory: {workspace_dir}")
        except Exception as e:
            logger.warning(f"Failed to delete workspace directory {workspace_dir}: {e}")
    
    return {
        "message": f"Job ({user_id}, {paper_id}) deleted successfully",
        "user_id": user_id,
        "paper_id": paper_id,
    }

@app.post("/edit/{user_id}/{paper_id}", tags=["Edit"])
async def edit_slides_endpoint(
    user_id: str,
    paper_id: str,
    request: EditSlidesRequest,
):
    """
    Edit the entire slide deck for a completed job.
    
    This endpoint allows you to provide natural language instructions to modify the slides.
    The slides will be regenerated and recompiled automatically.
    """
    workspace_dir = get_workspace_dir(user_id, paper_id)
    
    # Read current slides
    slides_path = os.path.join(workspace_dir, "slides.tex")
    if not os.path.exists(slides_path):
        raise HTTPException(status_code=404, detail="Slides file not found")
    
    try:
        beamer_code = read_file(slides_path)
        
        # Get API key
        api_key = request.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="API key required")
        
        model_name = request.model_name or os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")
        
        # Edit slides
        edited_code = await asyncio.to_thread(
            edit_slides,
            beamer_code,
            request.instruction,
            api_key,
            model_name,
            request.base_url,
            paper_id,
            request.use_paper_context,
            workspace_dir,
        )
        
        if not edited_code:
            raise HTTPException(status_code=500, detail="Failed to edit slides")
        
        # Save edited slides
        with open(slides_path, "w", encoding="utf-8") as f:
            f.write(edited_code)
        
        # Recompile
        compile_success = await asyncio.to_thread(compile_latex, "slides.tex", workspace_dir)
        
        if not compile_success:
            return {
                "success": False,
                "message": "Slides edited but compilation failed",
                "user_id": user_id,
                "paper_id": paper_id,
            }
        
        return {
            "success": True,
            "message": "Slides edited and recompiled successfully",
            "user_id": user_id,
            "paper_id": paper_id,
        }
        
    except Exception as e:
        logger.error(f"Failed to edit slides for job ({user_id}, {paper_id}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/edit/{user_id}/{paper_id}/slide/{slide_number}", tags=["Edit"])
async def edit_single_slide_endpoint(
    user_id: str,
    paper_id: str,
    slide_number: int,
    request: EditSingleSlideRequest,
):
    """
    Edit a specific slide in the presentation.
    
    Provide the slide number (1-indexed) and instructions for editing that specific slide.
    """
    workspace_dir = get_workspace_dir(user_id, paper_id)
    
    # Read current slides
    slides_path = os.path.join(workspace_dir, "slides.tex")
    if not os.path.exists(slides_path):
        raise HTTPException(status_code=404, detail="Slides file not found")
    
    try:
        beamer_code = read_file(slides_path)
        
        # Get API key
        api_key = request.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="API key required")
        
        model_name = request.model_name or os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")
        
        # Edit single slide
        edited_code = await asyncio.to_thread(
            edit_single_slide,
            beamer_code,
            slide_number,
            request.instruction,
            api_key,
            model_name,
            request.base_url,
            paper_id,
            request.use_paper_context,
            workspace_dir,
        )
        
        if not edited_code:
            raise HTTPException(status_code=500, detail=f"Failed to edit slide {slide_number}")
        
        # Save edited slides
        with open(slides_path, "w", encoding="utf-8") as f:
            f.write(edited_code)
        
        # Recompile
        compile_success = await asyncio.to_thread(compile_latex, "slides.tex", workspace_dir)
        
        if not compile_success:
            return {
                "success": False,
                "message": f"Slide {slide_number} edited but compilation failed",
                "user_id": user_id,
                "paper_id": paper_id,
            }
        
        return {
            "success": True,
            "message": f"Slide {slide_number} edited and recompiled successfully",
            "user_id": user_id,
            "paper_id": paper_id,
        }
        
    except Exception as e:
        logger.error(f"Failed to edit slide {slide_number} for job ({user_id}, {paper_id}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/speaker-notes/{user_id}/{paper_id}", tags=["Speaker Notes"])
async def generate_speaker_notes_endpoint(
    user_id: str,
    paper_id: str,
    request: SpeakerNotesRequest,
):
    """
    Generate speaker notes for all slides in the presentation.
    
    Returns a JSON object mapping slide numbers to speaker notes.
    """
    workspace_dir = get_workspace_dir(user_id, paper_id)
    
    try:
        # Get API key
        api_key = request.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=400, detail="API key required")
        
        model_name = request.model_name or os.getenv("DEFAULT_MODEL", "gpt-4.1-2025-04-14")
        
        # Generate speaker notes
        notes = await asyncio.to_thread(
            generate_speaker_notes,
            paper_id,
            api_key,
            model_name,
            request.base_url,
            request.instruction,
            workspace_dir,
        )
        
        if not notes:
            raise HTTPException(status_code=500, detail="Failed to generate speaker notes")
        
        # Save speaker notes
        save_speaker_notes(notes, paper_id, workspace_dir)
        
        return {
            "success": True,
            "message": "Speaker notes generated successfully",
            "user_id": user_id,
            "paper_id": paper_id,
            "notes": notes,
        }
        
    except Exception as e:
        logger.error(f"Failed to generate speaker notes for job ({user_id}, {paper_id}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/speaker-notes/{user_id}/{paper_id}", tags=["Speaker Notes"])
async def get_speaker_notes_endpoint(user_id: str, paper_id: str):
    """
    Retrieve previously generated speaker notes for a job.
    
    Returns the speaker notes if they exist, or 404 if not found.
    """
    job_key = (user_id, paper_id)
    if job_key not in jobs:
        raise HTTPException(status_code=404, detail=f"Job ({user_id}, {paper_id}) not found")
    
    job = jobs[job_key]
    
    try:
        notes = load_speaker_notes(paper_id, job.get("workspace_dir"))
        
        if not notes:
            raise HTTPException(status_code=404, detail="Speaker notes not found for this job")
        
        return {
            "success": True,
            "user_id": user_id,
            "paper_id": paper_id,
            "notes": notes,
        }
        
    except Exception as e:
        logger.error(f"Failed to load speaker notes for job ({user_id}, {paper_id}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Run with: uvicorn api:app --reload --host 0.0.0.0 --port 8000
# For Docker: API runs on port 8000 inside container, map via -p HOST_PORT:8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
