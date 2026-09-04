from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from client.config import ClientConfig

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".txt", ".csv", ".json", ".md", ".py", ".js", ".html", ".css", ".xml", ".log"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class FileManager:
    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._allowed_exts = set(config.allowed_extensions.split(","))

    def validate_file(self, filename: str, size: int) -> tuple[bool, str]:
        if size > self._config.max_upload_size:
            max_mb = self._config.max_upload_size / (1024 * 1024)
            return False, f"File too large. Maximum size: {max_mb:.0f}MB"

        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in self._allowed_exts:
            return False, f"File type '.{ext}' not allowed"

        return True, "ok"

    def extract_text(self, filename: str, content: bytes) -> Optional[str]:
        ext = Path(filename).suffix.lower()

        if ext in TEXT_EXTENSIONS:
            try:
                return content.decode("utf-8", errors="replace")
            except Exception:
                return None

        if ext in PDF_EXTENSIONS:
            return self._extract_pdf_text(content)

        if ext in DOCX_EXTENSIONS:
            return self._extract_docx_text(content)

        if ext == ".csv":
            try:
                return content.decode("utf-8", errors="replace")
            except Exception:
                return None

        return None

    def _extract_pdf_text(self, content: bytes) -> Optional[str]:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(content))
            text_parts = []
            for page in reader.pages[:20]:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n".join(text_parts)[:10000]
        except ImportError:
            logger.warning("PyPDF2 not installed, cannot extract PDF text")
            return f"[PDF file: {len(content)} bytes - text extraction unavailable]"
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return None

    def _extract_docx_text(self, content: bytes) -> Optional[str]:
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            text_parts = []
            for para in doc.paragraphs[:200]:
                if para.text.strip():
                    text_parts.append(para.text)
            return "\n".join(text_parts)[:10000]
        except ImportError:
            logger.warning("python-docx not installed, cannot extract DOCX text")
            return f"[DOCX file: {len(content)} bytes - text extraction unavailable]"
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return None

    def get_file_info(self, filename: str, size: int) -> dict:
        ext = Path(filename).suffix.lower()
        return {
            "name": filename,
            "extension": ext,
            "size": size,
            "size_human": self._human_size(size),
            "type": self._get_type(ext),
        }

    def _get_type(self, ext: str) -> str:
        if ext in TEXT_EXTENSIONS:
            return "text"
        if ext in PDF_EXTENSIONS:
            return "pdf"
        if ext in DOCX_EXTENSIONS:
            return "document"
        if ext in IMAGE_EXTENSIONS:
            return "image"
        return "unknown"

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}TB"
