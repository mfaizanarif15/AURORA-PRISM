from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import UploadFile
from pypdf import PdfReader
from docx import Document

from app.core.config import get_settings


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip()
    return cleaned or "uploaded-file"


async def save_upload(episode_id: str, upload: UploadFile, asset_type: str) -> tuple[Path, str | None]:
    settings = get_settings()
    target_dir = settings.uploads_dir / episode_id / asset_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(upload.filename or "uploaded-file")
    target_path = _dedupe_path(target_dir / filename)
    with target_path.open("wb") as output:
        shutil.copyfileobj(upload.file, output)
    extracted_text = extract_text(target_path, upload.content_type)
    return target_path, extracted_text


def extract_text(path: Path, content_type: str | None = None) -> str | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf" or content_type == "application/pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip() or None
        if suffix == ".docx":
            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs).strip() or None
        if suffix in {".txt", ".md", ".csv", ".vtt", ".srt"}:
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    return None


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
