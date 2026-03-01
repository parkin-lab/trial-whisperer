from difflib import ndiff
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def extract_text(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception:
            return ""

    if suffix == ".docx":
        try:
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception:
            return ""

    return ""


def summarize_diff(old_text: str, new_text: str) -> str:
    old_lines = [line.strip() for line in old_text.splitlines() if line.strip()]
    new_lines = [line.strip() for line in new_text.splitlines() if line.strip()]

    changes = list(ndiff(old_lines, new_lines))
    added = [line[2:] for line in changes if line.startswith("+ ")]
    removed = [line[2:] for line in changes if line.startswith("- ")]

    summary_lines = [
        f"Added lines: {len(added)}",
        f"Removed lines: {len(removed)}",
    ]

    if added:
        summary_lines.append("Sample additions: " + " | ".join(added[:5]))
    if removed:
        summary_lines.append("Sample removals: " + " | ".join(removed[:5]))

    return "\n".join(summary_lines)
