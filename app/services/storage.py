import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import Settings

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


@dataclass
class StoredFile:
    filename: str
    content_type: str
    file_ext: str
    file_size: int
    sha256: str
    storage_path: str


def sanitize_filename(name: str) -> str:
    base = Path(name or "document.txt").name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip()
    return cleaned or "document.txt"


async def save_upload_file(upload: UploadFile, settings: Settings) -> StoredFile:
    safe_name = sanitize_filename(upload.filename or "")
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    raw_bytes = await upload.read()
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb} MB.",
        )

    digest = hashlib.sha256(raw_bytes).hexdigest()
    dest_dir = Path(settings.upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex[:12]}_{safe_name}"
    dest_path = dest_dir / unique_name
    dest_path.write_bytes(raw_bytes)

    return StoredFile(
        filename=safe_name,
        content_type=upload.content_type or "application/octet-stream",
        file_ext=ext,
        file_size=len(raw_bytes),
        sha256=digest,
        storage_path=dest_path.as_posix(),
    )


def delete_stored_file(storage_path: str) -> None:
    path = Path(storage_path)
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)
