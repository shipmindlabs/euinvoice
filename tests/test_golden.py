"""Golden invoices: one per VAT regime, with the numbers they are issued under."""

from datetime import date
from decimal import Decimal

from euinvoice import (
    Address,
    CounterKey,
    InMemoryCounterStore,
    Invoice,
    InvoiceDocument,
    InvoiceLine,
    Money,
    NumberSeries,
    Party,
    SequentialNumbering,
    VatCategory,
    VatRegime,
    render_html,
)

DOMESTIC_SHIFT_NOTE = "Steuerschuldnerschaft des Leistungsempfängers."
REVERSE_CHARGE_NOTE = (
    "Reverse charge - VAT to be accounted for by the recipient "
    "(Directive 2006/112/EC, Art. 196)."
)
EXPORT_NOTE = (
    "Export outside the EU - no EU VAT charged (Directive 2006/112/EC, Art. 146)."
)


def address(country: str) -> Address:
    return Address(line1="Main 1", postal_code="10000", city="Town", country=country)


def seller() -> Party:
    return Party(name="Nordwind GmbH", address=address("DE"), vat_id="DE123456789")


def buyer(country: str, vat_id: str | None = None, validated: bool = False) -> Party:
    return Party(
        name=f"Buyer {country}",
        address=address(country),
        vat_id=vat_id,
        vat_id_validated=validated,
    )


def line(
    unit_price: str,
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


def invoice(
    to: Party,
    lines,
    *,
    number: str = "INV-2026-0001",
    issue_date: date = date(2026, 3, 1),
    **kwargs,
) -> Invoice:
    return Invoice(
        number=number,
        issue_date=issue_date,
        seller=seller(),
        buyer=to,
        lines=lines,
        **kwargs,
    )


def breakdown(issued: Invoice) -> list[tuple]:
    return [(row.category, row.rate, row.net, row.vat) for row in issued.vat_breakdown]


def page(issued: Invoice) -> str:
    return render_html(InvoiceDocument.from_invoice(issued))


class TestDomestic:
    def test_seller_charges_its_own_vat_at_two_rates(self):
        issued = invoice(
            to=buyer("DE", "DE987654321"),
            lines=[
                line("120.00", quantity="7.5"),
                line("250.00", rate="7", category=VatCategory.REDUCED,
                     description="Travel"),
            ],
        )
        assert issued.vat_regime is VatRegime.DOMESTIC
        assert issued.vat_decision.charges_seller_vat
        assert issued.total_net == Money("1150.00", "EUR")
        assert issued.total_vat == Money("188.50", "EUR")
        assert issued.total_gross == Money("1338.50", "EUR")
        assert breakdown(issued) == [
            (
                VatCategory.STANDARD,
                Decimal("19"),
                Money("900.00", "EUR"),
                Money("171.00", "EUR"),
            ),
            (
                VatCategory.REDUCED,
                Decimal("7"),
                Money("250.00", "EUR"),
                Money("17.50", "EUR"),
            ),
        ]

    def test_the_page_shows_the_totals_and_no_regime_note(self):
        issued = invoice(to=buyer("DE", "DE987654321"), lines=[line("100.00")])
        document = InvoiceDocument.from_invoice(issued)
        assert document.vat_note is None
        html = render_html(document)
        assert "119.00 EUR" in html
        assert "DE123456789" in html


class TestPrivateBuyer:
    def test_a_buyer_without_an_identifier_is_charged_seller_vat(self):
        issued = invoice(to=buyer("FR"), lines=[line("100.00")])
        assert issued.vat_regime is VatRegime.PRIVATE_BUYER
        assert issued.total_vat == Money("19.00", "EUR")
        assert issued.total_gross == Money("119.00", "EUR")
        assert "Art. 45" in issued.vat_decision.legal_reference
        assert InvoiceDocument.from_invoice(issued).vat_note is None

    def test_an_unvalidated_identifier_does_not_shift_the_tax(self):
        issued = invoice(to=buyer("FR", "FR12345678901"), lines=[line("100.00")])
        assert issued.vat_regime is VatRegime.PRIVATE_BUYER
        assert issued.total_vat == Money("19.00", "EUR")
        assert "Art. 18" in issued.vat_decision.legal_reference


class TestReverseCharge:
    def test_a_validated_buyer_abroad_carries_the_tax(self):
        issued = invoice(
            to=buyer("FR", "FR12345678901", validated=True),
            lines=[
                line("400.00", quantity="2", rate="0",
                     category=VatCategory.REVERSE_CHARGE)
            ],
        )
        assert issued.vat_regime is VatRegime.REVERSE_CHARGE
        assert issued.is_reverse_charge
        assert issued.total_net == Money("800.00", "EUR")
        assert issued.total_vat == Money.zero("EUR")
        assert issued.total_gross == issued.total_net
        assert breakdown(issued) == [
            (
                VatCategory.REVERSE_CHARGE,
                Decimal(0),
                Money("800.00", "EUR"),
                Money.zero("EUR"),
            )
        ]

    def test_the_page_prints_the_statutory_note(self):
        issued = invoice(
            to=buyer("FR", "FR12345678901", validated=True),
            lines=[line("400.00", rate="0", category=VatCategory.REVERSE_CHARGE)],
        )
        document = InvoiceDocument.from_invoice(issued)
        assert document.vat_note == REVERSE_CHARGE_NOTE
        assert document.lines[0].vat_label == "Reverse charge"
        assert "Art. 196" in render_html(document)

    def test_a_domestic_shift_prints_the_note_the_seller_wrote(self):
        issued = invoice(
            to=buyer("DE", "DE987654321"),
            lines=[line("400.00", rate="0", category=VatCategory.REVERSE_CHARGE)],
            notes=DOMESTIC_SHIFT_NOTE,
        )
        assert issued.vat_regime is VatRegime.DOMESTIC
        assert issued.is_reverse_charge
        assert issued.total_vat == Money.zero("EUR")
        document = InvoiceDocument.from_invoice(issued)
        assert document.vat_note is None
        assert document.notes == DOMESTIC_SHIFT_NOTE
        assert DOMESTIC_SHIFT_NOTE in render_html(document)


class TestExport:
    def test_no_eu_vat_leaves_the_union(self):
        issued = invoice(
            to=buyer("US"),
            lines=[line("1000.00", rate="0", category=VatCategory.ZERO_RATED)],
        )
        assert issued.vat_regime is VatRegime.EXPORT
        assert issued.vat_decision.vat_category is VatCategory.ZERO_RATED
        assert issued.total_net == Money("1000.00", "EUR")
        assert issued.total_vat == Money.zero("EUR")
        document = InvoiceDocument.from_invoice(issued)
        assert document.vat_note == EXPORT_NOTE
        assert document.lines[0].vat_label == "Zero-rated"


class TestNumberedRun:
    def test_a_run_of_invoices_is_numbered_gaplessly(self):
        store = InMemoryCounterStore()
        numbers = SequentialNumbering(NumberSeries("INV"), store)
        issued = []
        for day in (1, 2, 3):
            number = numbers.next_number(date(2026, 3, day))
            issued.append(
                invoice(
                    to=buyer("DE", "DE987654321"),
                    lines=[line("100.00")],
                    number=number.number,
                    issue_date=number.issue_date,
                )
            )
        assert [one.number for one in issued] == [
            "INV-2026-0001",
            "INV-2026-0002",
            "INV-2026-0003",
        ]
        assert store.current(CounterKey("INV", "2026")) == 3

    def test_the_counter_restarts_with_the_year(self):
        numbers = SequentialNumbering(NumberSeries("INV"), InMemoryCounterStore())
        last = numbers.next_number(date(2026, 12, 31))
        first = numbers.next_number(date(2027, 1, 2))
        assert last.number == "INV-2026-0001"
        assert first.number == "INV-2027-0001"

    def test_the_regime_does_not_touch_the_number(self):
        numbers = SequentialNumbering(NumberSeries("INV"), InMemoryCounterStore())
        drafts = [
            (buyer("DE", "DE987654321"), [line("100.00")]),
            (
                buyer("US"),
                [line("100.00", rate="0", category=VatCategory.ZERO_RATED)],
            ),
            (
                buyer("FR", "FR12345678901", validated=True),
                [line("100.00", rate="0", category=VatCategory.REVERSE_CHARGE)],
            ),
        ]
        issued = []
        for to, lines in drafts:
            number = numbers.next_number(date(2026, 3, 1))
            issued.append(
                invoice(
                    to=to,
                    lines=lines,
                    number=number.number,
                    issue_date=number.issue_date,
                )
            )
        assert [one.number for one in issued] == [
            "INV-2026-0001",
            "INV-2026-0002",
            "INV-2026-0003",
        ]
        assert [one.vat_regime for one in issued] == [
            VatRegime.DOMESTIC,
            VatRegime.EXPORT,
            VatRegime.REVERSE_CHARGE,
        ]
        for one in issued:
            assert one.number in page(one)
