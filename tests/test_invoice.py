"""Tests for the invoice model."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    CurrencyMismatch,
    Invoice,
    InvoiceLine,
    Money,
    Party,
    VatCategory,
)


def make_seller() -> Party:
    return Party(
        name="Nordwind GmbH",
        address=Address(
            line1="Hafenstrasse 1", postal_code="20359", city="Hamburg", country="de"
        ),
        vat_id="DE 123 456 789",
    )


def make_buyer(vat_id: str | None = "DE987654321") -> Party:
    return Party(
        name="Suedlicht AG",
        address=Address(
            line1="Maximilianstrasse 4",
            postal_code="80539",
            city="Munich",
            country="DE",
        ),
        vat_id=vat_id,
    )


def make_line(
    unit_price: str,
    quantity: str = "1",
    rate: str = "19",
    category: VatCategory = VatCategory.STANDARD,
    currency: str = "EUR",
) -> InvoiceLine:
    return InvoiceLine(
        description="Consulting",
        quantity=Decimal(quantity),
        unit_price=Money(unit_price, currency),
        vat_rate=Decimal(rate),
        vat_category=category,
    )


def make_invoice(lines, buyer: Party | None = None, **kwargs) -> Invoice:
    return Invoice(
        number="2026-0001",
        issue_date=date(2026, 3, 1),
        seller=make_seller(),
        buyer=buyer if buyer is not None else make_buyer(),
        lines=lines,
        **kwargs,
    )


class TestMoney:
    def test_rejects_float(self):
        with pytest.raises(TypeError):
            Money(19.99, "EUR")

    def test_normalises_currency(self):
        assert Money("10", "eur").currency == "EUR"

    def test_rejects_malformed_currency(self):
        with pytest.raises(ValueError):
            Money("10", "EURO")

    def test_arithmetic_requires_one_currency(self):
        with pytest.raises(CurrencyMismatch):
            Money("1", "EUR") + Money("1", "USD")

    def test_rounds_half_up_to_minor_unit(self):
        assert Money("1.005", "EUR").rounded().amount == Decimal("1.01")

    def test_is_frozen(self):
        amount = Money("1", "EUR")
        with pytest.raises(FrozenInstanceError):
            amount.amount = Decimal("999")


class TestParty:
    def test_vat_id_is_normalised(self):
        assert make_seller().vat_id == "DE123456789"

    def test_country_is_upper_cased(self):
        assert make_seller().address.country == "DE"

    def test_private_buyer_has_no_vat_id(self):
        assert not make_buyer(vat_id=None).is_business


class TestInvoiceLine:
    def test_totals_are_computed(self):
        line = make_line("120.00", quantity="7.5")
        assert line.net == Money("900.00", "EUR")
        assert line.vat == Money("171.00", "EUR")
        assert line.gross == Money("1071.00", "EUR")

    def test_totals_cannot_be_passed_in(self):
        with pytest.raises(TypeError):
            InvoiceLine(
                description="Consulting",
                quantity=Decimal(1),
                unit_price=Money("1.00", "EUR"),
                vat_rate=Decimal("19"),
                net=Money("999.00", "EUR"),
            )

    def test_vat_is_rounded_per_line(self):
        assert make_line("33.33").vat == Money("6.33", "EUR")

    def test_taxable_category_needs_a_positive_rate(self):
        with pytest.raises(ValueError):
            make_line("10.00", rate="0")

    def test_exempt_category_needs_a_zero_rate(self):
        with pytest.raises(ValueError):
            make_line("10.00", rate="19", category=VatCategory.EXEMPT)

    def test_quantity_must_be_positive(self):
        with pytest.raises(ValueError):
            make_line("10.00", quantity="0")


class TestInvoice:
    def test_totals_sum_the_lines(self):
        invoice = make_invoice(
            [make_line("100.00", rate="19"), make_line("50.00", rate="7")]
        )
        assert invoice.total_net == Money("150.00", "EUR")
        assert invoice.total_vat == Money("22.50", "EUR")
        assert invoice.total_gross == Money("172.50", "EUR")

    def test_vat_breakdown_sums_to_total_vat(self):
        invoice = make_invoice(
            [
                make_line("33.33"),
                make_line("66.67"),
                make_line("50.00", rate="7"),
            ]
        )
        total = Money.zero("EUR")
        for row in invoice.vat_breakdown:
            total = total + row.vat
        assert len(invoice.vat_breakdown) == 2
        assert total == invoice.total_vat

    def test_totals_cannot_be_passed_in(self):
        with pytest.raises(TypeError):
            make_invoice([make_line("10.00")], total_net=Money("999.00", "EUR"))

    def test_mixed_currencies_are_rejected(self):
        with pytest.raises(CurrencyMismatch):
            make_invoice([make_line("10.00"), make_line("10.00", currency="USD")])

    def test_requires_at_least_one_line(self):
        with pytest.raises(ValueError):
            make_invoice([])

    def test_due_date_cannot_precede_issue_date(self):
        with pytest.raises(ValueError):
            make_invoice([make_line("10.00")], due_date=date(2026, 2, 1))

    def test_reverse_charge_requires_buyer_vat_id(self):
        line = make_line("100.00", rate="0", category=VatCategory.REVERSE_CHARGE)
        with pytest.raises(ValueError):
            make_invoice([line], buyer=make_buyer(vat_id=None))

    def test_reverse_charge_cannot_mix_with_taxable_lines(self):
        with pytest.raises(ValueError):
            make_invoice(
                [
                    make_line("100.00"),
                    make_line(
                        "100.00", rate="0", category=VatCategory.REVERSE_CHARGE
                    ),
                ]
            )

    def test_reverse_charge_invoice_carries_no_vat(self):
        invoice = make_invoice(
            [make_line("100.00", rate="0", category=VatCategory.REVERSE_CHARGE)],
            notes="Reverse charge - the recipient accounts for the VAT.",
        )
        assert invoice.is_reverse_charge
        assert invoice.total_vat == Money.zero("EUR")
        assert invoice.total_gross == invoice.total_net

    def test_lines_are_stored_as_a_tuple(self):
        assert isinstance(make_invoice([make_line("10.00")]).lines, tuple)

    def test_is_frozen(self):
        invoice = make_invoice([make_line("10.00")])
        with pytest.raises(FrozenInstanceError):
            invoice.number = "2026-0002"
