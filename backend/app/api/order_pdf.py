"""Renders a freeze order as a formal memorandum.

ReportLab, because it is pure Python: no system libraries, no headless browser,
no Docker. "Two commands, no keys, runs air-gapped" is a selling point to
anyone who has worked in a bank, and a PDF generator is not worth spending it.

DETERMINISM. The same order must produce byte-identical bytes. Two things would
otherwise leak the wall clock into the file:

* the `/CreationDate` and `/ModDate` entries, and
* the document `/ID`, which ReportLab derives from a digest that includes the
  timestamp.

Both are fixed by pinning `_timeStamp` on the document to the case's own
complaint moment, which is itself fixed by the seeded dataset. `invariant=1`
handles the remainder.
"""

from __future__ import annotations

import hashlib
import io
import time

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import TimeStamp
from reportlab.pdfbase.pdfdoc import DummyDoc, PDFText
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.api.orders import FreezeOrderResponse, issued_timestamp
from app.config import settings

# --------------------------------------------------------------------- style
# Print, not screen: the console's dark palette would waste a cartridge and
# read as a screenshot rather than as a document. Navy and greys only -- the
# three money colours are a screen language and have no meaning on paper.
INK = colors.HexColor("#111111")
NAVY = colors.HexColor("#0B2E4F")
STEEL = colors.HexColor("#3E5C78")
RULE = colors.HexColor("#B9C4CE")
MUTED = colors.HexColor("#555F68")
BAND = colors.HexColor("#EEF2F6")

PAGE_MARGIN = 16 * mm
HEADER_HEIGHT = 26 * mm
FOOTER_HEIGHT = 16 * mm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "body": ParagraphStyle(
            "body", parent=base, fontName="Helvetica", fontSize=8.5,
            leading=11.5, textColor=INK, alignment=TA_JUSTIFY,
        ),
        "title": ParagraphStyle(
            "title", parent=base, fontName="Helvetica-Bold", fontSize=13,
            leading=15, textColor=NAVY, spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName="Helvetica-Bold", fontSize=9.5,
            leading=12, textColor=NAVY, spaceBefore=6, spaceAfter=3,
        ),
        "label": ParagraphStyle(
            "label", parent=base, fontName="Helvetica", fontSize=6.6,
            leading=8, textColor=MUTED,
        ),
        "value": ParagraphStyle(
            "value", parent=base, fontName="Helvetica-Bold", fontSize=8.5,
            leading=10.5, textColor=INK,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base, fontName="Helvetica", fontSize=7.2,
            leading=9, textColor=INK,
        ),
        "cellsmall": ParagraphStyle(
            "cellsmall", parent=base, fontName="Helvetica", fontSize=6.8,
            leading=8.4, textColor=MUTED,
        ),
        "flag": ParagraphStyle(
            "flag", parent=base, fontName="Helvetica-Bold", fontSize=6.4,
            leading=8, textColor=NAVY,
        ),
        "small": ParagraphStyle(
            "small", parent=base, fontName="Helvetica", fontSize=6.8,
            leading=8.6, textColor=MUTED,
        ),
    }


def _rupees(value: float) -> str:
    """Indian digit grouping: 12,67,134 rather than 1,267,134."""
    negative = value < 0
    whole = f"{abs(value):.0f}"
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join([*parts, tail])
    return f"{'-' if negative else ''}Rs {whole}"


def _pinned_timestamp(epoch: float) -> TimeStamp:
    """A ReportLab timestamp fixed to `epoch`, in UTC.

    ReportLab's own `TimeStamp` reads the wall clock unless `invariant` or the
    reproducible-builds `SOURCE_DATE_EPOCH` is set, and both of those force one
    global constant date. This case has a better date available -- its own
    complaint moment -- so the fields are overridden directly rather than
    mutating process-wide state that other requests share.
    """
    stamp = TimeStamp(invariant=1)
    moment = time.gmtime(epoch)
    stamp.t = epoch
    stamp.lt = moment
    stamp.YMDhms = tuple(moment)[:6]
    stamp.dhh = 0
    stamp.dmm = 0
    stamp.tzname = "UTC"
    return stamp


def _pinned_document_id(seed: str) -> bytes:
    """The PDF `/ID` array, derived from the order rather than from memory.

    ReportLab fingerprints the file with a running digest that absorbs, among
    other things, the *name* of the output file -- and for an in-memory buffer
    that name is synthesised from the object's address, which differs on every
    call. That one field was the last thing keeping two renders of the same
    order from being byte-identical.
    """
    digest = hashlib.sha256(seed.encode("utf-8")).digest()[:16]
    rendered = PDFText(digest, enc="raw").format(DummyDoc())
    return (
        b"\n["
        + rendered
        + rendered
        + b"]\n% ReportLab generated PDF document -- digest (opensource)\n"
    )


class _OrderCanvas(Canvas):
    """A canvas whose clock and fingerprint are the case's, not the machine's."""

    #: Both set by `render_order` before the build.
    fixed_timestamp: float = 0.0
    fixed_document_id: str = ""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("invariant", 1)
        super().__init__(*args, **kwargs)
        # Drives /CreationDate and /ModDate.
        self._doc._timeStamp = _pinned_timestamp(self.fixed_timestamp)
        # Short-circuits the digest in PDFDocument.ID().
        self._doc._ID = _pinned_document_id(self.fixed_document_id)


def render_order(order: FreezeOrderResponse) -> bytes:
    """The whole memorandum, as PDF bytes."""
    styles = _styles()
    buffer = io.BytesIO()

    # The fingerprint covers everything that distinguishes one rendering from
    # another, so two different orders never collide on a document id.
    fingerprint = "|".join(
        [
            order.order_id,
            order.case_id,
            order.policy,
            str(order.budget_k),
            str(order.innocence_budget),
            str(order.adaptive_adversary),
            *(bank.bank_id for bank in order.banks),
        ]
    )
    canvas_class = type(
        "_PinnedCanvas",
        (_OrderCanvas,),
        {
            "fixed_timestamp": issued_timestamp(order),
            "fixed_document_id": fingerprint,
        },
    )

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN + HEADER_HEIGHT,
        bottomMargin=PAGE_MARGIN + FOOTER_HEIGHT,
        title=f"Freeze instruction {order.order_id}",
        author=f"{order.issuing_authority} ({order.issued_by})",
        subject=f"Case {order.case_id}",
        creator=settings.service_name,
    )

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
        showBoundary=0,
    )
    doc.addPageTemplates(
        [
            PageTemplate(
                id="order",
                frames=[frame],
                onPage=lambda canvas, _doc: _furniture(canvas, order, styles),
            )
        ]
    )

    story: list = []
    story.extend(_preamble(order, styles))
    for bank in order.banks:
        # Sections flow rather than each taking a page. A bank downloading its
        # own instruction gets a one-page document because the order was built
        # with only its section in it; the all-banks bundle stays compact
        # instead of running to seven mostly-empty pages.
        story.extend(_bank_section(order, bank, styles))
    story.extend(_signature_block(order, styles))

    doc.build(story, canvasmaker=canvas_class)
    return buffer.getvalue()


def _furniture(canvas: Canvas, order: FreezeOrderResponse, styles) -> None:
    """Masthead and footer, repeated on every page."""
    width, height = A4

    # --- header ---------------------------------------------------------
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, height - 12 * mm, width, 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(PAGE_MARGIN, height - 7.6 * mm, order.issuing_authority.upper())
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(
        width - PAGE_MARGIN, height - 7.6 * mm, order.issuing_desk
    )

    _crest(canvas, width - PAGE_MARGIN - 74 * mm, height - 9.6 * mm, 6.4 * mm)

    canvas.setFillColor(INK)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(PAGE_MARGIN, height - 20 * mm, order.classification)
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(
        PAGE_MARGIN, height - 22.5 * mm, width - PAGE_MARGIN, height - 22.5 * mm
    )
    canvas.restoreState()

    # --- footer ---------------------------------------------------------
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(PAGE_MARGIN, 16 * mm, width - PAGE_MARGIN, 16 * mm)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 6.2)
    # The notice, on every page, not only the first.
    canvas.drawString(PAGE_MARGIN, 12.4 * mm, order.disclaimer)
    canvas.drawString(
        PAGE_MARGIN,
        9.4 * mm,
        f"{order.classification}  ·  Order {order.order_id}  ·  Case {order.case_id}",
    )
    canvas.drawRightString(
        A4[0] - PAGE_MARGIN, 9.4 * mm, f"Page {canvas.getPageNumber()}"
    )
    canvas.restoreState()


def _crest(canvas: Canvas, x: float, y: float, size: float) -> None:
    """The same neutral crest the console draws. Not the State Emblem."""
    canvas.saveState()
    canvas.setStrokeColor(colors.white)
    canvas.setLineWidth(0.5)
    radius = size / 2
    canvas.circle(x + radius, y + radius, radius, stroke=1, fill=0)
    canvas.circle(x + radius, y + radius, radius * 0.22, stroke=1, fill=0)
    for index in range(8):
        from math import cos, pi, sin

        angle = index * pi / 4
        canvas.line(
            x + radius + cos(angle) * radius * 0.32,
            y + radius + sin(angle) * radius * 0.32,
            x + radius + cos(angle) * radius * 0.95,
            y + radius + sin(angle) * radius * 0.95,
        )
    canvas.restoreState()


def _preamble(order: FreezeOrderResponse, styles) -> list:
    """Title, the reference grid, and the statutory-style opening paragraph."""
    story: list = [
        Paragraph(order.issuing_authority, styles["h2"]),
        Paragraph("FREEZE INSTRUCTION — IMMEDIATE", styles["title"]),
        Spacer(1, 3 * mm),
    ]

    fields = [
        ("CASE ID", order.case_id),
        ("ORDER ID", order.order_id),
        ("COMPLAINT REF", order.complaint_ref),
        ("ISSUED (IST)", order.issued_at.strftime("%d %b %Y, %H:%M")),
        ("AMOUNT REPORTED", _rupees(order.amount_inr)),
        ("REPORTING BANK", f"{order.reporting_bank} · {order.victim_district}"),
    ]
    # Weighted rather than equal: the two reference strings are long and wrap
    # into an unreadable mess at one-sixth of the page each.
    usable = A4[0] - 2 * PAGE_MARGIN
    grid = Table(
        [
            [Paragraph(label, styles["label"]) for label, _ in fields],
            [Paragraph(value, styles["value"]) for _, value in fields],
        ],
        colWidths=[
            usable * 0.21, usable * 0.13, usable * 0.21,
            usable * 0.16, usable * 0.15, usable * 0.14,
        ],
        hAlign="LEFT",
    )
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 1), (-1, 1), 0.6, RULE),
            ]
        )
    )
    story.append(grid)
    story.append(Spacer(1, 3.5 * mm))

    story.append(
        Paragraph(
            f"Pursuant to complaint <b>{order.complaint_ref}</b> reported to "
            f"<b>{order.reporting_bank}</b> at T+{order.complaint_delay_minutes} "
            f"minutes, alleging fraudulent transfer of "
            f"<b>{_rupees(order.amount_inr)}</b>, the accounts scheduled below "
            "have been identified as holding or forwarding traced proceeds of "
            "the said complaint. Each holding institution is instructed to give "
            "effect to the action stated against each account at the time "
            "stated, and to acknowledge execution to the issuing desk. "
            "Instructions marked "
            f"<b>{'REQUIRES SECOND APPROVAL'}</b> shall not be executed on the "
            "authority of the issuing officer alone.",
            styles["body"],
        )
    )
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"Basis of selection: {order.policy_label}, freeze authority K = "
            f"{order.budget_k}, harm limit B = {order.innocence_budget:g}, "
            f"adversary model: {'adaptive' if order.adaptive_adversary else 'passive'}. "
            f"{order.total_instructions} instructions to "
            f"{len(order.banks)} institution(s), of which "
            f"{order.total_requires_second_approval} require second approval.",
            styles["small"],
        )
    )
    story.append(Spacer(1, 4 * mm))
    return story


def _bank_section(order: FreezeOrderResponse, bank, styles) -> list:
    """One institution's instruction: heading, totals, and the schedule."""
    header = Table(
        [
            [
                Paragraph(f"TO: {bank.bank_name}", styles["h2"]),
                Paragraph(
                    f"{bank.instructions} instruction(s) · "
                    f"{_rupees(bank.amount_at_risk_inr)} traced · order "
                    f"{bank.order_id}",
                    styles["small"],
                ),
            ]
        ],
        colWidths=[(A4[0] - 2 * PAGE_MARGIN) * 0.4, (A4[0] - 2 * PAGE_MARGIN) * 0.6],
        hAlign="LEFT",
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )

    head = [
        Paragraph(text, styles["label"])
        for text in (
            "#", "ACCOUNT", "ACTION", "ISSUE", "TRACED", "EXP. RECOVERY",
            "p(MULE)", "JUSTIFICATION",
        )
    ]

    rows: list = [head]
    flagged: list[int] = []
    for row in bank.rows:
        justification = "; ".join(row.reason_codes) or "—"
        if row.requires_second_approval:
            # Spelled out rather than marked with a symbol: the standard PDF
            # fonts encode Latin-1 only, and a glyph the reader substitutes for
            # a box is a poor way to carry the one warning on the page.
            justification += " — REQUIRES SECOND APPROVAL"
            flagged.append(len(rows))
        rows.append(
            [
                Paragraph(str(row.rank), styles["cell"]),
                Paragraph(row.account_ref, styles["cell"]),
                Paragraph(row.instruction, styles["cell"]),
                Paragraph(f"T+{row.issue_at_minute}", styles["cell"]),
                Paragraph(_rupees(row.amount_at_risk_inr), styles["cell"]),
                Paragraph(_rupees(row.expected_recovery_inr), styles["cell"]),
                Paragraph(f"{row.p_mule:.2f}", styles["cell"]),
                Paragraph(justification, styles["cellsmall"]),
            ]
        )

    usable = A4[0] - 2 * PAGE_MARGIN
    table = Table(
        rows,
        colWidths=[
            usable * 0.03, usable * 0.085, usable * 0.185, usable * 0.055,
            usable * 0.09, usable * 0.10, usable * 0.065, usable * 0.39,
        ],
        repeatRows=1,
        hAlign="LEFT",
    )
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, STEEL),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
        ("ALIGN", (4, 1), (6, -1), "RIGHT"),
    ]
    for index in flagged:
        style.append(("BACKGROUND", (0, index), (-1, index), BAND))
    table.setStyle(TableStyle(style))

    # Heading and schedule stay together where they fit; a long schedule still
    # splits across pages rather than being forced onto one.
    return [KeepTogether([header, Spacer(1, 1.5 * mm), table]), Spacer(1, 4 * mm)]


def _signature_block(order: FreezeOrderResponse, styles) -> list:
    """Who issued it, who countersigned, and where the signature would go."""
    usable = A4[0] - 2 * PAGE_MARGIN
    block = Table(
        [
            [
                Paragraph("ISSUED BY", styles["label"]),
                Paragraph("COUNTERSIGNED BY", styles["label"]),
                Paragraph("DIGITAL SIGNATURE", styles["label"]),
            ],
            [
                Paragraph(
                    f"Officer {order.issued_by}<br/>{order.issuing_desk}",
                    styles["value"],
                ),
                Paragraph("________________________<br/>Name and designation", styles["cell"]),
                Paragraph(
                    "[ signature block — not signed in prototype ]", styles["cellsmall"]
                ),
            ],
        ],
        colWidths=[usable / 3] * 3,
        hAlign="LEFT",
    )
    block.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
            ]
        )
    )

    return [
        Spacer(1, 6 * mm),
        block,
        Spacer(1, 3 * mm),
        Paragraph(
            f"Audit reference {order.order_id} · case {order.case_id} · "
            f"seed {settings.master_seed} · this document is reproducible: the "
            "same case and settings render byte-identical output.",
            styles["small"],
        ),
        Paragraph(order.disclaimer, styles["small"]),
    ]
