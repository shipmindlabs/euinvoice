"""The print view of an invoice: a document model, HTML, and a renderer port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape
from typing import Protocol, runtime_checkable

from .invoice import Invoice, InvoiceLine, VatBreakdownRow
from .money import Money
from .parties import Party
from .vat import EU_COUNTRIES, VatCategory

__all__ = [
    "DEFAULT_STYLESHEET",
    "DocumentLine",
    "DocumentParty",
    "InvoiceDocument",
    "PdfRenderer",
    "RenderingError",
    "render_html",
    "render_pdf",
]


class RenderingError(RuntimeError):
    """Raised when a PDF renderer does not hand back a PDF."""


_CATEGORY_LABELS = {
    VatCategory.STANDARD: "Standard rate",
    VatCategory.REDUCED: "Reduced rate",
    VatCategory.ZERO_RATED: "Zero-rated",
    VatCategory.EXEMPT: "Exempt",
    VatCategory.REVERSE_CHARGE: "Reverse charge",
}


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _format_rate(rate: Decimal) -> str:
    return f"{_format_decimal(rate)}%"


def _format_money(amount: Money) -> str:
    return str(amount)


def _format_date(day: date) -> str:
    return day.isoformat()


@dataclass(frozen=True, slots=True)
class DocumentParty:
    """A party as it is printed: a name, address lines and identifiers."""

    name: str
    address_lines: tuple[str, ...]
    vat_id: str | None = None
    registration_number: str | None = None
    email: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "address_lines", tuple(self.address_lines))

    @classmethod
    def from_party(cls, party: Party) -> DocumentParty:
        if not isinstance(party, Party):
            raise TypeError("party must be a Party")
        return cls(
            name=party.name,
            address_lines=tuple(str(party.address).split("\n")),
            vat_id=party.vat_id,
            registration_number=party.registration_number,
            email=party.email,
        )


@dataclass(frozen=True, slots=True)
class DocumentLine:
    """One billed position with its totals already worked out."""

    description: str
    quantity: Decimal
    unit: str
    unit_price: Money
    vat_rate: Decimal
    vat_category: VatCategory
    net: Money
    vat: Money

    @classmethod
    def from_line(cls, line: InvoiceLine) -> DocumentLine:
        if not isinstance(line, InvoiceLine):
            raise TypeError("line must be an InvoiceLine")
        return cls(
            description=line.description,
            quantity=line.quantity,
            unit=line.unit,
            unit_price=line.unit_price,
            vat_rate=line.vat_rate,
            vat_category=line.vat_category,
            net=line.net,
            vat=line.vat,
        )

    @property
    def vat_label(self) -> str:
        """What goes in the VAT column: a rate, or why there is none."""
        if self.vat_category.is_taxable:
            return _format_rate(self.vat_rate)
        return _CATEGORY_LABELS[self.vat_category]


@dataclass(frozen=True, slots=True)
class InvoiceDocument:
    """An invoice reduced to what a page shows, with nothing left to compute."""

    number: str
    issue_date: date
    seller: DocumentParty
    buyer: DocumentParty
    lines: tuple[DocumentLine, ...]
    vat_breakdown: tuple[VatBreakdownRow, ...]
    total_net: Money
    total_vat: Money
    total_gross: Money
    due_date: date | None = None
    supply_date: date | None = None
    vat_note: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(self, "vat_breakdown", tuple(self.vat_breakdown))

    @property
    def currency(self) -> str:
        return self.total_net.currency

    @property
    def title(self) -> str:
        return f"Invoice {self.number}"

    @classmethod
    def from_invoice(cls, invoice: Invoice) -> InvoiceDocument:
        """Build the print view of ``invoice``, totals and VAT note included."""
        if not isinstance(invoice, Invoice):
            raise TypeError("invoice must be an Invoice")
        return cls(
            number=invoice.number,
            issue_date=invoice.issue_date,
            seller=DocumentParty.from_party(invoice.seller),
            buyer=DocumentParty.from_party(invoice.buyer),
            lines=tuple(DocumentLine.from_line(line) for line in invoice.lines),
            vat_breakdown=invoice.vat_breakdown,
            total_net=invoice.total_net,
            total_vat=invoice.total_vat,
            total_gross=invoice.total_gross,
            due_date=invoice.due_date,
            supply_date=invoice.supply_date,
            vat_note=_vat_note(invoice),
            notes=invoice.notes,
        )


def _vat_note(invoice: Invoice) -> str | None:
    # A seller outside the EU has no regime to derive, and no note to print.
    if invoice.seller.country not in EU_COUNTRIES:
        return None
    return invoice.vat_decision.invoice_note


@runtime_checkable
class PdfRenderer(Protocol):
    """The port that turns rendered HTML into PDF bytes.

    Keeping this a port is what lets the package stay dependency free: the
    caller brings the engine that can already lay out HTML, and the library
    never has to agree with it on fonts, page boxes or a browser binary.
    """

    def render(self, html: str) -> bytes: ...


DEFAULT_STYLESHEET = """\
@page { size: A4; margin: 20mm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10pt; color: #111; }
h1 { font-size: 18pt; margin: 0 0 3mm 0; }
h2 { font-size: 9pt; text-transform: uppercase; letter-spacing: 0.4pt;
     color: #555; margin: 0 0 2mm 0; }
.meta span { margin-right: 6mm; }
.parties { display: flex; margin: 8mm 0; }
.party { width: 50%; padding-right: 8mm; }
.party p { margin: 0 0 1mm 0; }
table { width: 100%; border-collapse: collapse; }
table.lines th, table.lines td { padding: 2mm 1mm; text-align: left;
     border-bottom: 0.3mm solid #ddd; }
table.lines .amount { text-align: right; }
table.totals { width: 60%; margin: 6mm 0 0 auto; }
table.totals th { text-align: left; font-weight: normal; padding: 1mm; }
table.totals td { text-align: right; padding: 1mm; }
table.totals .grand-total th, table.totals .grand-total td {
     font-weight: bold; border-top: 0.5mm solid #111; }
.vat-note { margin-top: 8mm; font-weight: bold; }
.notes { margin-top: 4mm; color: #444; white-space: pre-wrap; }
"""


def _party_html(party: DocumentParty, role: str, heading: str) -> str:
    address = "<br>".join(escape(line) for line in party.address_lines)
    parts = [
        f'<div class="party {role}">',
        f"<h2>{escape(heading)}</h2>",
        f'<p class="name">{escape(party.name)}</p>',
        f'<p class="address">{address}</p>',
    ]
    if party.vat_id:
        parts.append(f'<p class="vat-id">VAT ID: {escape(party.vat_id)}</p>')
    if party.registration_number:
        parts.append(
            '<p class="registration">Reg. no: '
            f"{escape(party.registration_number)}</p>"
        )
    if party.email:
        parts.append(f'<p class="email">{escape(party.email)}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def _line_html(line: DocumentLine) -> str:
    quantity = f"{_format_decimal(line.quantity)} {line.unit}"
    return (
        '<tr class="line">'
        f"<td>{escape(line.description)}</td>"
        f'<td class="amount">{escape(quantity)}</td>'
        f'<td class="amount">{escape(_format_money(line.unit_price))}</td>'
        f'<td class="amount">{escape(line.vat_label)}</td>'
        f'<td class="amount">{escape(_format_money(line.net))}</td>'
        "</tr>"
    )


def _vat_row_html(row: VatBreakdownRow) -> str:
    if row.category.is_taxable:
        label = f"VAT {_format_rate(row.rate)}"
    else:
        label = _CATEGORY_LABELS[row.category]
    label = f"{label} on {_format_money(row.net)}"
    return (
        '<tr class="vat-row">'
        f"<th>{escape(label)}</th>"
        f"<td>{escape(_format_money(row.vat))}</td>"
        "</tr>"
    )


def render_html(document: InvoiceDocument, *, stylesheet: str | None = None) -> str:
    """Render ``document`` as a standalone HTML page.

    The markup is plain and the styling lives in one sheet, so a caller who
    wants a different look passes its own ``stylesheet`` instead of forking
    the template.
    """
    if not isinstance(document, InvoiceDocument):
        raise TypeError("document must be an InvoiceDocument")
    css = DEFAULT_STYLESHEET if stylesheet is None else stylesheet
    if not isinstance(css, str):
        raise TypeError("stylesheet must be a string")

    meta = [f"<span>Issue date: {escape(_format_date(document.issue_date))}</span>"]
    if document.supply_date is not None:
        meta.append(
            f"<span>Supply date: {escape(_format_date(document.supply_date))}</span>"
        )
    if document.due_date is not None:
        meta.append(
            f"<span>Due date: {escape(_format_date(document.due_date))}</span>"
        )

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(document.title)}</title>",
        f"<style>\n{css}</style>",
        "</head>",
        "<body>",
        '<header class="invoice-header">',
        f"<h1>{escape(document.title)}</h1>",
        '<p class="meta">' + "".join(meta) + "</p>",
        "</header>",
        '<section class="parties">',
        _party_html(document.seller, "seller", "Seller"),
        _party_html(document.buyer, "buyer", "Buyer"),
        "</section>",
        '<table class="lines">',
        "<thead><tr><th>Description</th><th>Quantity</th>"
        "<th>Unit price</th><th>VAT</th><th>Net</th></tr></thead>",
        "<tbody>",
    ]
    parts.extend(_line_html(line) for line in document.lines)
    parts.extend(
        [
            "</tbody>",
            "</table>",
            '<table class="totals">',
            "<tbody>",
            '<tr class="net-total"><th>Net total</th>'
            f"<td>{escape(_format_money(document.total_net))}</td></tr>",
        ]
    )
    parts.extend(_vat_row_html(row) for row in document.vat_breakdown)
    parts.extend(
        [
            '<tr class="vat-total"><th>VAT total</th>'
            f"<td>{escape(_format_money(document.total_vat))}</td></tr>",
            '<tr class="grand-total"><th>Total</th>'
            f"<td>{escape(_format_money(document.total_gross))}</td></tr>",
            "</tbody>",
            "</table>",
        ]
    )
    if document.vat_note:
        parts.append(f'<p class="vat-note">{escape(document.vat_note)}</p>')
    if document.notes:
        parts.append(f'<p class="notes">{escape(document.notes)}</p>')
    parts.extend(["</body>", "</html>", ""])
    return "\n".join(parts)


def render_pdf(
    source: Invoice | InvoiceDocument,
    renderer: PdfRenderer,
    *,
    stylesheet: str | None = None,
) -> bytes:
    """Render an invoice to PDF bytes through ``renderer``.

    What comes back is checked for the PDF header, so a renderer that returns
    an error page or a file path is caught here rather than by whoever opens
    the file later.
    """
    if not isinstance(renderer, PdfRenderer):
        raise TypeError("renderer must implement render(html) -> bytes")
    document = (
        source
        if isinstance(source, InvoiceDocument)
        else InvoiceDocument.from_invoice(source)
    )
    result = renderer.render(render_html(document, stylesheet=stylesheet))
    if not isinstance(result, (bytes, bytearray)):
        raise RenderingError(
            f"the renderer returned {type(result).__name__}, not bytes"
        )
    pdf = bytes(result)
    if not pdf.startswith(b"%PDF-"):
        raise RenderingError("the renderer returned data that is not a PDF")
    return pdf
