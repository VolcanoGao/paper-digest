from __future__ import annotations

import io
import urllib.request

from pypdf import PdfReader


def download_first_page_text(
    pdf_url: str, max_chars: int = 2500, timeout: int = 30
) -> str:
    """Return first-page text of a PDF, or "" on any error.

    Caller is expected to cache the result on the paper row so we never
    re-download the same PDF.
    """
    try:
        req = urllib.request.Request(
            pdf_url, headers={"User-Agent": "paper-digest/0.2 (+arxiv)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        reader = PdfReader(io.BytesIO(data))
        if not reader.pages:
            return ""
        text = reader.pages[0].extract_text() or ""
        return text.strip()[:max_chars]
    except Exception:
        return ""
