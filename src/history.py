"""
Version history management for Paper2Slides.
Saves working versions after successful PDF compilations.
Allows reverting to previous working versions when LLM edits fail.
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict


class VersionHistory:
    """Manages version history for a paper's slides - saves only after successful compiles."""

    def __init__(self, paper_id: str, workspace_dir: str | None = None):
        """
        Initialize version history for a specific paper.

        Args:
            paper_id: The paper ID (e.g., arxiv ID or generated PDF ID)
            workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)
        """
        self.paper_id = paper_id
        # Determine workspace directory
        if workspace_dir is None:
            workspace_dir = f"source/{paper_id}/"
        self.history_dir = Path(workspace_dir) / "edit_history"
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def save_version(
        self, tex_content: str, description: str = "Successful compile"
    ) -> bool:
        """
        Save a new version after successful compilation.

        Args:
            tex_content: The LaTeX content to save
            description: Description of this version

        Returns:
            True if successful, False otherwise
        """
        try:
            timestamp = datetime.now()
            # Use timestamp as filename for easy sorting
            timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

            version_data = {
                "timestamp": timestamp.isoformat(),
                "description": description,
                "tex_content": tex_content,
            }

            version_file = self.history_dir / f"version_{timestamp_str}.json"
            with open(version_file, "w", encoding="utf-8") as f:
                json.dump(version_data, f, indent=2)

            logging.info(f"Saved version: {description} at {timestamp_str}")
            return True

        except Exception as e:
            logging.error(f"Failed to save version: {e}")
            return False

    def list_versions(self) -> List[Dict]:
        """
        List all saved versions, newest first.

        Returns:
            List of version dictionaries with metadata (without full tex_content)
        """
        versions = []
        if not self.history_dir.exists():
            return versions

        # Read all version files and sort by recorded timestamp (newest first)
        entries = []
        for version_file in self.history_dir.glob("version_*.json"):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    ts = data.get("timestamp")
                    # Try to parse timestamp to datetime for reliable sorting
                    try:
                        parsed_ts = datetime.fromisoformat(ts) if ts else None
                    except Exception:
                        parsed_ts = None

                    entries.append(
                        (
                            version_file.name,
                            parsed_ts,
                            data.get("description", "Unknown"),
                        )
                    )
            except Exception as e:
                logging.error(f"Failed to read version file {version_file}: {e}")

        # Sort by parsed timestamp descending (None values go last)
        entries.sort(key=lambda x: x[1] or datetime.min, reverse=True)

        for filename, parsed_ts, desc in entries:
            versions.append(
                {
                    "filename": filename,
                    "timestamp": parsed_ts.isoformat() if parsed_ts else "",
                    "description": desc,
                }
            )

        return versions

    def get_latest_version(self) -> Optional[str]:
        """
        Get the most recent working version.

        Returns:
            LaTeX content of the latest version, or None if no history exists
        """
        versions = self.list_versions()
        if not versions:
            return None

        latest_file = self.history_dir / versions[0]["filename"]
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tex_content")
        except Exception as e:
            logging.error(f"Failed to read latest version: {e}")
            return None

    def get_version_by_filename(self, filename: str) -> Optional[str]:
        """
        Get a specific version by filename.

        Args:
            filename: The version filename (e.g., "version_20250107_143022.json")

        Returns:
            LaTeX content if found, None otherwise
        """
        version_file = self.history_dir / filename
        if not version_file.exists():
            return None

        try:
            with open(version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tex_content")
        except Exception as e:
            logging.error(f"Failed to read version {filename}: {e}")
            return None

    def restore_version(self, filename: str, slides_tex_path: str) -> bool:
        """
        Restore a specific version to slides.tex.

        Args:
            filename: The version filename to restore
            slides_tex_path: Path to slides.tex file

        Returns:
            True if successful, False otherwise
        """
        content = self.get_version_by_filename(filename)
        if content is None:
            logging.error(f"Version {filename} not found")
            return False

        try:
            with open(slides_tex_path, "w", encoding="utf-8") as f:
                f.write(content)
            logging.info(f"Restored version {filename} to {slides_tex_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to restore version: {e}")
            return False

    def delete_version(self, filename: str) -> bool:
        """
        Delete a specific saved version file.

        Args:
            filename: The version filename to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        version_file = self.history_dir / filename
        if not version_file.exists():
            logging.warning(f"Version file {filename} does not exist")
            return False

        try:
            version_file.unlink()
            logging.info(f"Deleted history file {filename}")
            return True
        except Exception as e:
            logging.error(f"Failed to delete version {filename}: {e}")
            return False

    def has_history(self) -> bool:
        """Check if any version history exists."""
        return len(self.list_versions()) > 0

    def clear_history(self, preserve_current: Optional[str] = None) -> bool:
        """
        Clear all version history for this paper, preserving the initial version and optionally the current active version.

        Args:
            preserve_current: Filename of the currently active version to preserve (optional)

        Returns:
            True if successful, False otherwise
        """
        try:
            if not self.history_dir.exists():
                return True

            # Get all versions to identify versions to preserve
            versions = self.list_versions()
            versions_to_preserve = []

            # Find the initial version (oldest with "Initial version" description)
            if versions:
                oldest_version = versions[-1]
                if oldest_version["description"].startswith("Initial version"):
                    versions_to_preserve.append(oldest_version["filename"])

            # Add current version if specified and different from initial
            if preserve_current and preserve_current not in versions_to_preserve:
                versions_to_preserve.append(preserve_current)

            # Read content of versions to preserve
            preserved_data = {}
            for filename in versions_to_preserve:
                version_file = self.history_dir / filename
                if version_file.exists():
                    try:
                        with open(version_file, "r", encoding="utf-8") as f:
                            preserved_data[filename] = json.load(f)
                    except Exception as e:
                        logging.error(
                            f"Failed to read version to preserve {filename}: {e}"
                        )

            # Clear the directory
            shutil.rmtree(self.history_dir)
            self.history_dir.mkdir(parents=True, exist_ok=True)

            # Restore preserved versions
            for filename, data in preserved_data.items():
                version_file = self.history_dir / filename
                try:
                    with open(version_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    logging.error(
                        f"Failed to restore preserved version {filename}: {e}"
                    )

            preserved_count = len(preserved_data)
            logging.info(
                f"Cleared history for paper {self.paper_id}, preserved {preserved_count} version(s)"
            )
            return True
        except Exception as e:
            logging.error(f"Failed to clear history: {e}")
            return False


def get_history_manager(
    paper_id: str, workspace_dir: str | None = None
) -> VersionHistory:
    """
    Get a version history manager for a specific paper.

    Args:
        paper_id: The paper ID
        workspace_dir: Workspace directory path (defaults to source/{paper_id}/ if not provided)

    Returns:
        VersionHistory instance
    """
    return VersionHistory(paper_id, workspace_dir)
