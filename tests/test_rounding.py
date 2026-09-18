"""Rounding: VAT is taken line by line, which is not the same as taking it once."""

from datetime import date
from decimal import Decimal

from euinvoice import (
    Address,
    Invoice,
    InvoiceLine,
    Money,
    Party,
    VatCategory,
)


def party(name: str, vat_id: str) -> Party:
    return Party(
        name=name,
        address=Address(
            line1="Main 1", postal_code="10000", city="Town", country="DE"
        ),
        vat_id=vat_id,
    )


def line(
    unit_price: str,
    quantity: str = "1",
    rate: str = "19",
    currency: str = "EUR",
) -> InvoiceLine:
    return InvoiceLine(
        description="Consulting",
        quantity=Decimal(quantity),
        unit_price=Money(unit_price, currency),
        vat_rate=Decimal(rate),
        vat_category=VatCategory.STANDARD,
    )


def invoice(lines) -> Invoice:
    return Invoice(
        number="INV-2026-0001",
        issue_date=date(2026, 3, 1),
        seller=party("Nordwind GmbH", "DE123456789"),
        buyer=party("Suedlicht AG", "DE987654321"),
        lines=lines,
    )


def vat_taken_once(net: Money, rate: str) -> Money:
    """What the invoice would carry if VAT were taken on the total instead."""
    return Money(net.amount * Decimal(rate) / Decimal(100), net.currency).rounded()


class TestPerLineVersusPerInvoice:
    def test_small_lines_round_up_one_by_one(self):
        issued = invoice([line("0.10") for _ in range(10)])
        assert issued.total_net == Money("1.00", "EUR")
        assert issued.total_vat == Money("0.20", "EUR")
        assert vat_taken_once(issued.total_net, "19") == Money("0.19", "EUR")
        assert issued.total_vat != vat_taken_once(issued.total_net, "19")

    def test_small_lines_round_down_one_by_one(self):
        issued = invoice([line("0.07") for _ in range(13)])
        assert issued.total_net == Money("0.91", "EUR")
        assert issued.total_vat == Money("0.13", "EUR")
        assert vat_taken_once(issued.total_net, "19") == Money("0.17", "EUR")

    def test_the_breakdown_sums_to_the_invoice_vat(self):
        issued = invoice(
            [
                line("33.33"),
                line("0.07"),
                line("66.67"),
                line("19.99", rate="7"),
                line("0.07", rate="7"),
            ]
        )
        total = Money.zero("EUR")
        for row in issued.vat_breakdown:
            total = total + row.vat
        assert len(issued.vat_breakdown) == 2
        assert total == issued.total_vat

    def test_the_gross_is_the_sum_of_the_line_grosses(self):
        issued = invoice([line("0.10"), line("33.33"), line("19.99", rate="7")])
        total = Money.zero("EUR")
        for one in issued.lines:
            total = total + one.gross
        assert total == issued.total_gross


class TestHalfUp:
    def test_half_a_cent_of_vat_rounds_up(self):
        assert line("0.50").vat == Money("0.10", "EUR")

    def test_less_than_half_a_cent_of_vat_rounds_down(self):
        assert line("0.20", rate="7").vat == Money("0.01", "EUR")

    def test_a_line_is_rounded_before_its_vat_is_taken(self):
        one = line("0.005")
        assert one.net == Money("0.01", "EUR")
        assert one.vat == Money.zero("EUR")
        assert one.gross == Money("0.01", "EUR")

    def test_the_quantity_is_multiplied_before_the_line_is_rounded(self):
        together = line("0.005", quantity="3")
        assert together.net == Money("0.02", "EUR")

        apart = invoice([line("0.005") for _ in range(3)])
        assert apart.total_net == Money("0.03", "EUR")


class TestMinorUnits:
    def test_a_zero_decimal_currency_rounds_to_whole_units(self):
        issued = invoice([line("105", rate="10", currency="JPY")])
        assert issued.total_net == Money("105", "JPY")
        assert issued.total_vat == Money("11", "JPY")
        assert str(issued.total_gross) == "116 JPY"

    def test_a_three_decimal_currency_keeps_three(self):
        issued = invoice([line("1.0005", currency="TND")])
        assert issued.total_net == Money("1.001", "TND")
        assert issued.total_vat == Money("0.190", "TND")
        assert str(issued.total_gross) == "1.191 TND"
