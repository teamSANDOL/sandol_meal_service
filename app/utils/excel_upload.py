"""Response and input helpers for workbook upload routes."""

from typing import Any


def safe_upload_filename(filename: str) -> str:
    """Keep a display-only filename without path components or controls."""
    name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    normalized = "".join(character for character in name if character.isprintable())
    return normalized[:255] or "menu.xlsx"


def public_upload_metadata(result: dict[str, Any], *, is_latest: bool) -> dict[str, Any]:
    """Return sidecar fields safe and useful for the administrator file list."""
    fields = {
        "upload_id", "status", "upload_status", "analysis_status",
        "analysis_error_code", "analysis_error_message", "apply_status",
        "apply_error_code", "file_name", "file_size", "sha256", "parser_version",
        "uploaded_by", "uploaded_at", "period", "summary", "sync_status",
        "sync_error_code", "sync_error_message", "synced_at",
    }
    metadata = {key: result[key] for key in fields if key in result}
    metadata["is_latest"] = is_latest
    return metadata
