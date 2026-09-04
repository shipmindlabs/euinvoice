"""Tests for the document model, the HTML template and the renderer port."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    DEFAULT_STYLESHEET,
    Invoice,
    InvoiceDocument,
    InvoiceLine,
    Money,
    Party,
    RenderingError,
    VatCategory,
    render_html,
    render_pdf,
)


class FakeRenderer:
    """A renderer that records the HTML it was given."""

    def __init__(self, result=b"%PDF-1.7\nfake") -> None:
        self.result = result
        self.html: str | None = None

    def render(self, html: str) -> bytes:
        self.html = html
        return self.result


def party(country: str, vat_id: str | None = None, validated: bool = False) -> Party:
    return Party(
        name=f"Party {country}",
        address=Address(
            line1="Main 1", postal_code="10000", city="Town", country=country
        ),
        vat_id=vat_id,
        vat_id_validated=validated,
    )


def line(
    unit_price: str = "100.00",
    quantity: str = "1",
    rate: str = "19",
    category: VatCategory = VatCategory.STANDARD,
    description: str = "Consulting",
) -> InvoiceLine:
    return InvoiceLine(
        description=description,
        quantity=Decimal(quantity),
        unit_price=Money(unit_price, "EUR"),
        vat_rate=Decimal(rate),
        vat_category=category,
        unit="hour",
    )


def invoice(lines=None, buyer: Party | None = None, **kwargs) -> Invoice:
    return Invoice(
        number="INV-2026-0001",
        issue_date=date(2026, 3, 1),
        seller=party("DE", "DE123456789"),
        buyer=buyer if buyer is not None else party("DE", "DE987654321"),
        lines=lines if lines is not None else [line()],
        **kwargs,
    )


class TestDocumentModel:
    def test_carries_the_invoice_head(self):
        document = InvoiceDocument.from_invoice(
            invoice(due_date=date(2026, 3, 31), supply_date=date(2026, 2, 28))
        )
        assert document.number == "INV-2026-0001"
        assert document.issue_date == date(2026, 3, 1)
        assert document.due_date == date(2026, 3, 31)
        assert document.supply_date == date(2026, 2, 28)
        assert document.currency == "EUR"

    def test_parties_become_printable_blocks(self):
        document = InvoiceDocument.from_invoice(invoice())
        assert document.seller.name == "Party DE"
        assert document.seller.vat_id == "DE123456789"
        assert document.buyer.address_lines == ("Main 1", "10000 Town", "DE")

    def test_line_totals_come_from_the_invoice(self):
        document = InvoiceDocument.from_invoice(
            invoice([line("120.00", quantity="7.5")])
        )
        assert len(document.lines) == 1
        assert document.lines[0].net == Money("900.00", "EUR")
        assert document.lines[0].vat == Money("171.00", "EUR")
        assert document.lines[0].vat_label == "19%"

    def test_totals_match_the_invoice(self):
        source = invoice([line("100.00"), line("50.00", rate="7")])
        document = InvoiceDocument.from_invoice(source)
        assert document.total_net == source.total_net
        assert document.total_vat == source.total_vat
        assert document.total_gross == source.total_gross
        assert len(document.vat_breakdown) == 2

    def test_reverse_charge_note_is_carried_over(self):
        document = InvoiceDocument.from_invoice(
            invoice(
                [line(rate="0", category=VatCategory.REVERSE_CHARGE)],
                buyer=party("FR", "FR12345678901", validated=True),
            )
        )
        assert "reverse charge" in document.vat_note.lower()
        assert document.lines[0].vat_label == "Reverse charge"

    def test_domestic_invoice_carries_no_note(self):
        assert InvoiceDocument.from_invoice(invoice()).vat_note is None

    def test_requires_an_invoice(self):
        with pytest.raises(TypeError):
            InvoiceDocument.from_invoice("INV-2026-0001")

    def test_is_frozen(self):
        document = InvoiceDocument.from_invoice(invoice())
        with pytest.raises(FrozenInstanceError):
            document.number = "INV-2026-0002"


class TestHtml:
    def test_renders_a_whole_page(self):
        html = render_html(InvoiceDocument.from_invoice(invoice()))
        assert html.startswith("<!DOCTYPE html>")
        assert html.rstrip().endswith("</html>")

    def test_shows_number_parties_and_totals(self):
        html = render_html(
            InvoiceDocument.from_invoice(invoice([line("120.00", quantity="7.5")]))
        )
        assert "INV-2026-0001" in html
        assert "DE123456789" in html
        assert "Party DE" in html
        assert "1071.00 EUR" in html

    def test_one_row_per_line(self):
        html = render_html(
            InvoiceDocument.from_invoice(
                invoice([line("100.00"), line("50.00", rate="7")])
            )
        )
        assert html.count('<tr class="line">') == 2

    def test_escapes_text_from_the_invoice(self):
        html = render_html(
            InvoiceDocument.from_invoice(
                invoice([line(description="Design <b>& copy</b>")])
            )
        )
        assert "<b>" not in html.split("<body>", 1)[1]
        assert "&lt;b&gt;" in html

    def test_carries_the_default_stylesheet(self):
        html = render_html(InvoiceDocument.from_invoice(invoice()))
        assert DEFAULT_STYLESHEET in html

    def test_stylesheet_can_be_replaced(self):
        html = render_html(
            InvoiceDocument.from_invoice(invoice()), stylesheet="body { color: red; }"
        )
        assert "body { color: red; }" in html
        assert DEFAULT_STYLESHEET not in html

    def test_requires_a_document(self):
        with pytest.raises(TypeError):
            render_html(invoice())


class TestPdfRendering:
    def test_hands_the_html_to_the_renderer(self):
        renderer = FakeRenderer()
        pdf = render_pdf(invoice(), renderer)
        assert pdf == b"%PDF-1.7\nfake"
        assert "INV-2026-0001" in renderer.html

    def test_accepts_a_prepared_document(self):
        renderer = FakeRenderer()
        document = InvoiceDocument.from_invoice(invoice())
        assert render_pdf(document, renderer).startswith(b"%PDF-")

    def test_stylesheet_reaches_the_renderer(self):
        renderer = FakeRenderer()
        render_pdf(invoice(), renderer, stylesheet="body { color: red; }")
        assert "body { color: red; }" in renderer.html

    def test_renderer_must_implement_the_port(self):
        with pytest.raises(TypeError):
            render_pdf(invoice(), object())

    def test_a_renderer_returning_text_is_rejected(self):
        with pytest.raises(RenderingError):
            render_pdf(invoice(), FakeRenderer(result="/tmp/invoice.pdf"))

    def test_bytes_that_are_not_a_pdf_are_rejected(self):
        with pytest.raises(RenderingError):
            render_pdf(invoice(), FakeRenderer(result=b"<html>error</html>"))
