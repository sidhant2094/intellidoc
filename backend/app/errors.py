"""User-facing errors. Messages are written for non-technical readers."""

from __future__ import annotations


class AnalysisError(Exception):
    def __init__(self, code: str, message: str, hint: str = "", status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.status = status

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


def not_pdf() -> AnalysisError:
    return AnalysisError(
        "invalid_file_type",
        "That file isn't a PDF.",
        "Choose a .pdf file. Word documents or images need to be exported to PDF first.",
        415,
    )


def too_large(limit_mb: int) -> AnalysisError:
    return AnalysisError(
        "file_too_large",
        f"This PDF is larger than the {limit_mb} MB limit.",
        "Try a smaller file, or split the PDF and analyze the part you need.",
        413,
    )


def malformed() -> AnalysisError:
    return AnalysisError(
        "malformed_pdf",
        "This PDF couldn't be opened — it may be damaged or incomplete.",
        "Re-download or re-export the PDF, then try again.",
    )


def encrypted() -> AnalysisError:
    return AnalysisError(
        "password_protected",
        "This PDF is password-protected.",
        "Open it in a PDF viewer, remove the password (or print to a new PDF), and upload that copy.",
    )


def too_many_pages(limit: int, count: int) -> AnalysisError:
    return AnalysisError(
        "too_many_pages",
        f"This PDF has {count} pages; the current limit is {limit}.",
        "Split the document and analyze the part you need.",
        413,
    )


def no_text(scanned: bool) -> AnalysisError:
    if scanned:
        return AnalysisError(
            "scanned_pdf",
            "This looks like a scanned PDF — its pages are images, so there's no text to analyze.",
            "OCR isn't available in this local setup. Run the PDF through an OCR tool "
            "(for example, macOS Preview → Export, or `ocrmypdf`) and upload the searchable copy.",
        )
    return AnalysisError(
        "no_text",
        "We couldn't find any extractable text in this PDF.",
        "Make sure the PDF contains real text (you can select it in a PDF viewer), then try again.",
    )
