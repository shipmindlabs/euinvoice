"""Tests for the fields each VAT treatment requires."""

from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    Invoice,
    InvoiceLine,
    MissingRequiredField,
    Money,
    Party,
    VatCategory,
    check_required_fields,
)

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


def shifted_line() -> InvoiceLine:
    return line(rate="0", category=VatCategory.REVERSE_CHARGE)


def invoice(seller: Party, buyer: Party, lines, **kwargs) -> Invoice:
    return Invoice(
        number="INV-2026-0001",
        issue_date=date(2026, 3, 1),
        seller=seller,
        buyer=buyer,
        lines=lines,
        **kwargs,
    )


def names(missing) -> list[str]:
    return [field.field for field in missing]


class TestSellerIdentifier:
    def test_a_complete_domestic_invoice_misses_nothing(self):
        assert (
            check_required_fields(
                party("DE", "DE123456789"), party("DE", "DE987654321"), [line()]
            )
            == ()
        )

    def test_charging_vat_needs_the_seller_identifier(self):
        missing = check_required_fields(
            party("DE"), party("DE", "DE987654321"), [line()]
        )
        assert names(missing) == ["seller.vat_id"]

    def test_exempt_lines_do_not_need_the_seller_identifier(self):
        missing = check_required_fields(
            party("DE"), party("DE"), [line(rate="0", category=VatCategory.EXEMPT)]
        )
        assert missing == ()

    def test_the_invoice_refuses_to_be_built(self):
        with pytest.raises(MissingRequiredField):
            invoice(party("DE"), party("DE", "DE987654321"), [line()])


class TestReverseCharge:
    def test_the_buyer_identifier_is_required(self):
        missing = check_required_fields(
            party("DE", "DE123456789"), party("FR"), [shifted_line()]
        )
        assert "buyer.vat_id" in names(missing)

    def test_an_unvalidated_identifier_is_not_enough(self):
        missing = check_required_fields(
            party("DE", "DE123456789"),
            party("FR", "FR12345678901"),
            [shifted_line()],
        )
        assert "buyer.vat_id_validated" in names(missing)

    def test_an_identifier_without_a_member_state_is_not_enough(self):
        missing = check_required_fields(
            party("DE", "DE123456789"),
            party("FR", "ZZ12345678", validated=True),
            [shifted_line()],
        )
        assert "buyer.vat_id" in names(missing)

    def test_a_validated_cross_border_buyer_misses_nothing(self):
        missing = check_required_fields(
            party("DE", "DE123456789"),
            party("FR", "FR12345678901", validated=True),
            [shifted_line()],
        )
        assert missing == ()

    def test_a_domestic_reverse_charge_needs_the_note_written_out(self):
        missing = check_required_fields(
            party("DE", "DE123456789"), party("DE", "DE987654321"), [shifted_line()]
        )
        assert names(missing) == ["notes"]

    def test_a_written_note_completes_a_domestic_reverse_charge(self):
        missing = check_required_fields(
            party("DE", "DE123456789"),
            party("DE", "DE987654321"),
            [shifted_line()],
            DOMESTIC_NOTE,
        )
        assert missing == ()

    def test_the_invoice_refuses_to_be_built_without_the_note(self):
        with pytest.raises(MissingRequiredField):
            invoice(
                party("DE", "DE123456789"),
                party("DE", "DE987654321"),
                [shifted_line()],
            )

    def test_the_invoice_is_built_once_the_note_is_there(self):
        issued = invoice(
            party("DE", "DE123456789"),
            party("DE", "DE987654321"),
            [shifted_line()],
            notes=DOMESTIC_NOTE,
        )
        assert issued.is_reverse_charge
        assert issued.total_vat == Money.zero("EUR")


class TestReporting:
    def test_every_missing_field_is_reported_at_once(self):
        with pytest.raises(MissingRequiredField) as error:
            invoice(party("DE"), party("DE"), [shifted_line()])
        assert names(error.value.missing) == [
            "seller.vat_id",
            "buyer.vat_id",
            "notes",
        ]

    def test_the_message_names_the_field_and_the_rule(self):
        with pytest.raises(MissingRequiredField) as error:
            invoice(party("DE", "DE123456789"), party("DE"), [shifted_line()])
        message = str(error.value)
        assert "buyer.vat_id" in message
        assert "Art. 226(4)" in message

    def test_a_missing_field_reads_as_text(self):
        missing = check_required_fields(
            party("DE"), party("DE", "DE987654321"), [line()]
        )
        assert str(missing[0]).startswith("seller.vat_id: ")
        assert missing[0].legal_reference.endswith("Art. 226(3)")

    def test_the_error_is_a_value_error(self):
        assert issubclass(MissingRequiredField, ValueError)
