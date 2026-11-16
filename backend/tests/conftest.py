"""Synthetic PDFs with known structure and page placement."""

from __future__ import annotations

import pymupdf
import pytest

from app.gemini import client as gclient
from app.gemini.config import GeminiSettings
from app.gemini.embeddings import cache as embed_cache
from app.session import store as session_store


@pytest.fixture(autouse=True)
def no_real_gemini():
    """Never touch the real API in tests, even if backend/.env has a key."""
    off = GeminiSettings(api_key="", enabled=False, model="m", embedding_model="e",
                         embedding_dim=64, timeout_s=5, daily_limit=0)
    gclient.set_service(gclient.GeminiService(off))
    embed_cache.clear()
    session_store.clear()
    yield
    gclient.set_service(gclient.GeminiService(off))

FILLER = (
    "Teams often revisit these decisions as the organisation grows and its priorities shift over time. "
    "Clear ownership and written guidance help new members understand the reasoning behind each choice. "
)

SECTIONS = [
    # (page, level, title, body)
    (1, 1, "1 Introduction",
     "This handbook describes how the Orchard platform is built and operated. It is written for engineers "
     "joining the team and for managers who need a high level overview of the product. " + FILLER * 2),
    (1, 2, "1.1 Audience",
     "Readers should be comfortable with basic web concepts. No prior knowledge of Orchard is assumed. " + FILLER),
    (2, 1, "2 Deployment Architecture",
     "Orchard is deployed as three stateless services behind a regional load balancer. Each service runs in "
     "containers on a managed Kubernetes cluster, and deployments roll out gradually using blue green releases. "
     "Database migrations must be backwards compatible because old and new containers run side by side during a "
     "rollout. The deployment pipeline blocks a release if latency regresses by more than ten percent. " + FILLER),
    (3, 1, "3 Pricing and Billing",
     "Customers are billed monthly. Invoices are generated on the first business day and include usage based "
     "charges for storage and bandwidth. Refunds are handled by the finance team within thirty days. " + FILLER),
    (4, 1, "4 Security Practices",
     "All traffic is encrypted with TLS. Access to production requires hardware security keys and is reviewed "
     "every quarter. Secrets are stored in a dedicated vault and rotated automatically. " + FILLER),
]

CODE = ["def deploy(service):", "    build(service)", "    rollout(service, strategy='blue-green')"]


def _write_doc(with_outline: bool) -> bytes:
    doc = pymupdf.open()
    pages: dict[int, pymupdf.Page] = {}
    cursor: dict[int, float] = {}
    toc = []
    doc.set_metadata({"title": "Orchard Engineering Handbook"})
    for page_no, level, title, body in SECTIONS:
        if page_no not in pages:
            pages[page_no] = doc.new_page(width=595, height=842)
            cursor[page_no] = 72
        page = pages[page_no]
        y = cursor[page_no]
        size = 18 if level == 1 else 14
        page.insert_text((72, y + size), title, fontsize=size, fontname="hebo")
        y += size + 14
        rect = pymupdf.Rect(72, y, 523, 800)
        leftover = page.insert_textbox(rect, body, fontsize=10.5, fontname="helv", lineheight=1.3)
        assert leftover >= 0, "fixture text overflowed"
        used = rect.height - leftover
        y += used + 18
        if title.startswith("2 "):
            for i, line in enumerate(CODE):
                page.insert_text((80, y + 12 * i), line, fontsize=9.5, fontname="cour")
            y += 12 * len(CODE) + 18
        if title.startswith("3 "):
            y = _draw_table(page, y)
        cursor[page_no] = y
        toc.append([level, title, page_no])
    if with_outline:
        doc.set_toc(toc)
    data = doc.tobytes()
    doc.close()
    return data


def _draw_table(page: pymupdf.Page, y: float) -> float:
    page.insert_text((72, y + 10), "Table 1: Monthly plan prices", fontsize=10, fontname="helv")
    y += 18
    rows = [["Plan", "Price", "Storage"], ["Starter", "$10", "50 GB"], ["Team", "$40", "500 GB"], ["Scale", "$120", "5 TB"]]
    x0, cw, rh = 72, 120, 18
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            rect = pymupdf.Rect(x0 + c * cw, y + r * rh, x0 + (c + 1) * cw, y + (r + 1) * rh)
            page.draw_rect(rect, color=(0, 0, 0), width=0.6)
            page.insert_text((rect.x0 + 4, rect.y1 - 5), cell, fontsize=9.5, fontname="helv")
    return y + len(rows) * rh + 16


@pytest.fixture(scope="session")
def handbook_pdf() -> bytes:
    return _write_doc(with_outline=False)


@pytest.fixture(scope="session")
def handbook_outline_pdf() -> bytes:
    return _write_doc(with_outline=True)


@pytest.fixture(scope="session")
def encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "secret text")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    return data


@pytest.fixture(scope="session")
def scanned_pdf() -> bytes:
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 560), False)
    pix.set_rect(pix.irect, (235, 235, 235))
    for _ in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(20, 20, 575, 822), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture(scope="session")
def blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data
