"""
Supabase Storage service for protocol document upload/download/delete.
Falls back to local filesystem when SUPABASE_URL is not configured (dev mode).
"""

import os
from pathlib import Path

from app.config import get_settings

settings = get_settings()


def _get_client():
    if not settings.supabase_url or not settings.supabase_service_key:
        return None
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


def storage_path(trial_id: str, version: int, filename: str) -> str:
    """Returns the canonical storage path for a protocol document."""
    return f"{trial_id}/v{version}_{filename}"


async def upload_file(trial_id: str, version: int, filename: str, contents: bytes) -> str:
    """
    Upload file to Supabase Storage or local filesystem.
    Returns the storage path (used for download later).
    """
    path = storage_path(trial_id, version, filename)
    client = _get_client()

    if client is None:
        # Local fallback
        local_dir = Path(settings.uploads_dir) / trial_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"v{version}_{filename}"
        local_path.write_bytes(contents)
        return str(local_path)

    bucket = settings.supabase_storage_bucket
    # upsert=True to handle retries
    client.storage.from_(bucket).upload(
        path=path,
        file=contents,
        file_options={"upsert": "true"},
    )
    return path


async def download_file(storage_path_or_local: str) -> tuple[bytes, str]:
    """
    Download file from Supabase Storage or local filesystem.
    Returns (contents, filename).
    """
    client = _get_client()
    filename = Path(storage_path_or_local).name

    if client is None or storage_path_or_local.startswith("/") or os.path.exists(storage_path_or_local):
        # Local path
        contents = Path(storage_path_or_local).read_bytes()
        return contents, filename

    bucket = settings.supabase_storage_bucket
    contents = client.storage.from_(bucket).download(storage_path_or_local)
    return contents, filename


async def delete_file(storage_path_or_local: str) -> None:
    """Delete file from storage (best-effort)."""
    client = _get_client()
    if client is None or storage_path_or_local.startswith("/") or os.path.exists(storage_path_or_local):
        try:
            Path(storage_path_or_local).unlink(missing_ok=True)
        except Exception:
            pass
        return
    bucket = settings.supabase_storage_bucket
    try:
        client.storage.from_(bucket).remove([storage_path_or_local])
    except Exception:
        pass


def get_local_path_for_extraction(storage_path_or_local: str, contents: bytes) -> str:
    """
    For document text extraction (pdfplumber/python-docx need a file path),
    write contents to a temp file and return the path.
    Caller is responsible for cleanup.
    """
    import tempfile

    suffix = Path(storage_path_or_local).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(contents)
    tmp.flush()
    tmp.close()
    return tmp.name
