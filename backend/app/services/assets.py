from __future__ import annotations

import re
import shutil
from pathlib import Path

from fastapi import UploadFile
from docx import Document
from loguru import logger
from pypdf import PdfReader

from app.core.config import get_settings


def safe_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip()
    if cleaned != filename:
        logger.debug("Sanitized filename original={} sanitized={}", filename, cleaned or "uploaded-file")
    return cleaned or "uploaded-file"


async def save_upload(episode_id: str, upload: UploadFile, asset_type: str) -> tuple[Path, str | None]:
    settings = get_settings()
    target_dir = settings.uploads_dir / episode_id / asset_type
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(upload.filename or "uploaded-file")
    target_path = _dedupe_path(target_dir / filename)
    logger.info(
        "Saving upload episode_id={} asset_type={} filename={} content_type={} target_path={}",
        episode_id,
        asset_type,
        filename,
        upload.content_type,
        target_path,
    )
    with target_path.open("wb") as output:
        shutil.copyfileobj(upload.file, output)
    extracted_text = extract_text(target_path, upload.content_type)
    logger.info(
        "Upload saved episode_id={} asset_type={} path={} extracted_text={}",
        episode_id,
        asset_type,
        target_path,
        bool(extracted_text),
    )
    return target_path, extracted_text


def extract_text(path: Path, content_type: str | None = None) -> str | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf" or content_type == "application/pdf":
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages).strip() or None
            logger.debug("Extracted PDF text path={} extracted={}", path, bool(text))
            return text
        if suffix == ".docx":
            document = Document(str(path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip() or None
            logger.debug("Extracted DOCX text path={} extracted={}", path, bool(text))
            return text
        if suffix in {".txt", ".md", ".csv", ".vtt", ".srt"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            logger.debug("Extracted text file content path={} length={}", path, len(text))
            return text
    except Exception as exc:
        logger.warning("Text extraction failed path={} content_type={} error={}", path, content_type, exc)
        return None
    logger.debug("No text extractor available path={} content_type={}", path, content_type)
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
            logger.debug("Deduped upload path original={} candidate={}", path, candidate)
            return candidate
        index += 1
