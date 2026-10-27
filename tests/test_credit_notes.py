"""Credit notes: a correction names the document it corrects."""

from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    DocumentKind,
    Invoice,
    InvoiceDocument,
    InvoiceLine,
    MissingRequiredField,
    Money,
    Party,
    SupplyKind,
    VatCategory,
    VatRegime,
    check_required_fields,
    render_html,
)

CORRECTED = "INV-2026-0001"
DOMESTIC_NOTE = "Reverse charge - the recipient accounts for the VAT."


def party(country: str, vat_id: str | None = None, validated: bool = False) -> Party:
    return Party(
        name=f"Party {country}",
        address=Address(
            line1="Main 1", postal_code="10000", city="Town", country=country
        ),
        vat_id=vat_id,
        vat_id_validated=validated,
    )


def line(rate: str = "19", category: VatCategory = VatCategory.STANDARD) -> InvoiceLine:
    return InvoiceLine(
        description="Consulting",
        quantity=Decimal(1),
        unit_price=Money("100.00", "EUR"),
        vat_rate=Decimal(rate),
        vat_category=category,
    )


def issue(lines=None, buyer: Party | None = None, **kwargs) -> Invoice:
    return Invoice(
        number=kwargs.pop("number", "CN-2026-0007"),
        issue_date=date(2026, 4, 1),
        seller=party("DE", "DE123456789"),
        buyer=buyer if buyer is not None else party("DE", "DE987654321"),
        lines=lines if lines is not None else [line()],
        **kwargs,
    )


def credit_note(lines=None, buyer: Party | None = None, **kwargs) -> Invoice:
    kwargs.setdefault("corrects", CORRECTED)
    return issue(lines, buyer, kind=DocumentKind.CREDIT_NOTE, **kwargs)


def names(missing) -> list[str]:
    return [field.field for field in missing]


class TestTheReference:
    def test_a_document_is_an_invoice_unless_said_otherwise(self):
        issued = issue()
        assert issued.kind is DocumentKind.INVOICE
        assert not issued.is_credit_note
        assert issued.corrects is None

    def test_a_credit_note_names_what_it_corrects(self):
        note = credit_note()
        assert note.is_credit_note
        assert note.corrects == CORRECTED

    def test_a_credit_note_without_a_reference_is_refused(self):
        with pytest.raises(MissingRequiredField) as error:
            issue(kind=DocumentKind.CREDIT_NOTE)
        assert names(error.value.missing) == ["corrects"]
        assert error.value.missing[0].legal_reference.endswith("Art. 219")

    def test_a_blank_reference_names_nothing(self):
        with pytest.raises(MissingRequiredField):
            issue(kind=DocumentKind.CREDIT_NOTE, corrects="   ")

    def test_a_reference_is_stripped(self):
        assert credit_note(corrects=f"  {CORRECTED} ").corrects == CORRECTED

    def test_an_invoice_must_not_correct_anything(self):
        with pytest.raises(MissingRequiredField) as error:
            issue(corrects=CORRECTED)
        assert names(error.value.missing) == ["corrects"]
        assert error.value.missing[0].legal_reference.endswith("Art. 219")

    def test_the_check_runs_on_a_draft(self):
        missing = check_required_fields(
            party("DE", "DE123456789"),
            party("DE", "DE987654321"),
            [line()],
            kind=DocumentKind.CREDIT_NOTE,
        )
        assert names(missing) == ["corrects"]
        assert str(missing[0]).startswith("corrects: ")

    def test_the_kind_must_be_a_document_kind(self):
        with pytest.raises(TypeError):
            issue(kind="credit-note")

    def test_the_reference_must_be_text(self):
        with pytest.raises(TypeError):
            issue(kind=DocumentKind.CREDIT_NOTE, corrects=2026)


class TestAmountsAndRegime:
    def test_the_amounts_stay_positive(self):
        note = credit_note([line(), line(rate="7", category=VatCategory.REDUCED)])
        assert note.total_net == Money("200.00", "EUR")
        assert note.total_vat == Money("26.00", "EUR")
        assert note.total_gross == Money("226.00", "EUR")

    def test_a_domestic_credit_note_still_charges_vat(self):
        note = credit_note()
        assert note.vat_regime is VatRegime.DOMESTIC
        assert note.total_vat == Money("19.00", "EUR")

    def test_a_cross_border_credit_note_still_shifts_the_tax(self):
        note = credit_note(
            [line(rate="0", category=VatCategory.REVERSE_CHARGE)],
            buyer=party("FR", "FR12345678901", validated=True),
        )
        assert note.vat_regime is VatRegime.REVERSE_CHARGE
        assert note.total_vat == Money.zero("EUR")

    def test_a_credit_note_for_goods_stays_an_intra_community_supply(self):
        note = credit_note(
            [line(rate="0", category=VatCategory.ZERO_RATED)],
            buyer=party("FR", "FR12345678901", validated=True),
            supply_kind=SupplyKind.GOODS,
        )
        assert note.vat_regime is VatRegime.INTRA_COMMUNITY_SUPPLY
        assert note.total_vat == Money.zero("EUR")

    def test_a_domestic_shift_on_a_credit_note_still_needs_its_note(self):
        with pytest.raises(MissingRequiredField) as error:
            credit_note([line(rate="0", category=VatCategory.REVERSE_CHARGE)])
        assert names(error.value.missing) == ["notes"]

    def test_a_domestic_shift_is_complete_once_the_note_is_there(self):
        note = credit_note(
            [line(rate="0", category=VatCategory.REVERSE_CHARGE)],
            notes=DOMESTIC_NOTE,
        )
        assert note.is_credit_note
        assert note.is_reverse_charge


class TestPrinting:
    def test_the_document_carries_the_kind_and_the_reference(self):
        document = InvoiceDocument.from_invoice(credit_note())
        assert document.kind is DocumentKind.CREDIT_NOTE
        assert document.corrects == CORRECTED
        assert document.title == "Credit note CN-2026-0007"

    def test_an_invoice_keeps_its_title(self):
        document = InvoiceDocument.from_invoice(issue(number="2026-0042"))
        assert document.title == "Invoice 2026-0042"

    def test_the_page_prints_the_corrected_number(self):
        html = render_html(InvoiceDocument.from_invoice(credit_note()))
        assert "Credit note CN-2026-0007" in html
        assert f"Corrects invoice: {CORRECTED}" in html

    def test_an_invoice_prints_no_correction(self):
        html = render_html(InvoiceDocument.from_invoice(issue(number="2026-0042")))
        assert "Credit note" not in html
        assert "Corrects invoice" not in html
