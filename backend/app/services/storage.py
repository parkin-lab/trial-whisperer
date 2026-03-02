"""Local filesystem storage service for protocol document upload/download/delete."""

from pathlib import Path

from app.config import get_settings

settings = get_settings()


async def upload_file(trial_id: str, version: int, filename: str, contents: bytes) -> str:
    """
    Upload file to local filesystem.
    Returns absolute storage path.
    """
    uploads_root = Path(settings.uploads_dir)
    local_dir = uploads_root / trial_id
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"v{version}_{filename}"
    local_path.write_bytes(contents)
    return str(local_path.resolve())


async def download_file(storage_path_or_local: str) -> tuple[bytes, str]:
    """
    Download file from local filesystem.
    Returns (contents, filename).
    """
    local_path = Path(storage_path_or_local)
    return local_path.read_bytes(), local_path.name


async def delete_file(storage_path_or_local: str) -> None:
    """Delete file from local filesystem (best-effort)."""
    try:
        Path(storage_path_or_local).unlink(missing_ok=True)
    except Exception:
        pass


def get_local_path_for_extraction(storage_path_or_local: str, contents: bytes) -> str:
    """Return local storage path for extraction."""
    del contents
    return storage_path_or_local
