"""Tests for sequential invoice numbering."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    CounterKey,
    InMemoryCounterStore,
    Invoice,
    InvoiceLine,
    Money,
    NumberingError,
    NumberSeries,
    Party,
    Period,
    SequentialNumbering,
    VatCategory,
)


def numbering(series: NumberSeries | None = None, store=None) -> SequentialNumbering:
    return SequentialNumbering(
        series if series is not None else NumberSeries("INV"),
        store if store is not None else InMemoryCounterStore(),
    )


class FixedStore:
    """A store that hands out prepared values, however wrong."""

    def __init__(self, values) -> None:
        self._values = list(values)

    def next_count(self, key):
        return self._values.pop(0)


def party(country: str, vat_id: str | None = None) -> Party:
    return Party(
        name=f"Party {country}",
        address=Address(
            line1="Main 1", postal_code="10000", city="Town", country=country
        ),
        vat_id=vat_id,
    )


class TestNumberSeries:
    def test_formats_prefix_period_and_padded_counter(self):
        assert NumberSeries("INV").format(7, date(2026, 3, 1)) == "INV-2026-0007"

    def test_padding_and_separator_are_configurable(self):
        series = NumberSeries("R", padding=6, separator="/")
        assert series.format(7, date(2026, 3, 1)) == "R/2026/000007"

    def test_continuous_series_carries_no_period(self):
        series = NumberSeries("INV", Period.CONTINUOUS)
        assert series.format(7, date(2026, 3, 1)) == "INV-0007"

    def test_monthly_token(self):
        series = NumberSeries("INV", Period.MONTHLY)
        assert series.format(1, date(2026, 3, 1)) == "INV-202603-0001"

    def test_quarterly_token(self):
        series = NumberSeries("INV", Period.QUARTERLY)
        assert series.format(1, date(2026, 11, 30)) == "INV-2026Q4-0001"

    def test_prefix_must_not_be_empty(self):
        with pytest.raises(ValueError):
            NumberSeries("   ")

    def test_padding_must_be_positive(self):
        with pytest.raises(ValueError):
            NumberSeries("INV", padding=0)

    def test_is_frozen(self):
        series = NumberSeries("INV")
        with pytest.raises(FrozenInstanceError):
            series.prefix = "CN"


class TestCounterKeys:
    def test_key_names_the_series_and_the_period(self):
        key = NumberSeries("INV").key_for(date(2026, 3, 1))
        assert key == CounterKey("INV", "2026")
        assert str(key) == "INV:2026"

    def test_continuous_key_has_no_period(self):
        key = NumberSeries("INV", Period.CONTINUOUS).key_for(date(2026, 3, 1))
        assert str(key) == "INV"

    def test_dates_in_one_period_share_a_key(self):
        series = NumberSeries("INV")
        assert series.key_for(date(2026, 1, 1)) == series.key_for(date(2026, 12, 31))

    def test_dates_in_different_months_split_a_monthly_series(self):
        series = NumberSeries("INV", Period.MONTHLY)
        assert series.key_for(date(2026, 3, 31)) != series.key_for(date(2026, 4, 1))


class TestSequentialNumbering:
    def test_counts_up_without_gaps(self):
        numbers = numbering()
        issued = [numbers.next_number(date(2026, 3, 1)).number for _ in range(3)]
        assert issued == ["INV-2026-0001", "INV-2026-0002", "INV-2026-0003"]

    def test_counter_restarts_in_the_next_period(self):
        numbers = numbering()
        numbers.next_number(date(2026, 12, 31))
        assert numbers.next_number(date(2027, 1, 2)).number == "INV-2027-0001"

    def test_continuous_series_never_restarts(self):
        numbers = numbering(NumberSeries("INV", Period.CONTINUOUS))
        numbers.next_number(date(2026, 12, 31))
        assert numbers.next_number(date(2027, 1, 2)).number == "INV-0002"

    def test_series_do_not_share_a_counter(self):
        store = InMemoryCounterStore()
        sales = numbering(NumberSeries("INV"), store)
        credits = numbering(NumberSeries("CN"), store)
        sales.next_number(date(2026, 3, 1))
        sales.next_number(date(2026, 3, 2))
        assert credits.next_number(date(2026, 3, 1)).counter == 1

    def test_resumes_from_persisted_counts(self):
        store = InMemoryCounterStore({CounterKey("INV", "2026"): 41})
        issued = numbering(store=store).next_number(date(2026, 3, 1))
        assert issued.number == "INV-2026-0042"
        assert store.current(CounterKey("INV", "2026")) == 42

    def test_issued_number_carries_its_origin(self):
        issued = numbering().next_number(date(2026, 3, 1))
        assert issued.counter == 1
        assert issued.key == CounterKey("INV", "2026")
        assert issued.issue_date == date(2026, 3, 1)
        assert str(issued) == issued.number

    def test_issue_date_must_be_a_date(self):
        with pytest.raises(TypeError):
            numbering().next_number("2026-03-01")

    def test_store_must_implement_the_port(self):
        with pytest.raises(TypeError):
            SequentialNumbering(NumberSeries("INV"), object())


class TestStoreContract:
    def test_a_repeated_counter_is_rejected(self):
        numbers = numbering(store=FixedStore([1, 1]))
        numbers.next_number(date(2026, 3, 1))
        with pytest.raises(NumberingError):
            numbers.next_number(date(2026, 3, 1))

    def test_a_skipped_counter_is_rejected(self):
        numbers = numbering(store=FixedStore([1, 3]))
        numbers.next_number(date(2026, 3, 1))
        with pytest.raises(NumberingError):
            numbers.next_number(date(2026, 3, 1))

    def test_counters_start_at_one(self):
        with pytest.raises(NumberingError):
            numbering(store=FixedStore([0])).next_number(date(2026, 3, 1))

    def test_a_non_integer_counter_is_rejected(self):
        with pytest.raises(NumberingError):
            numbering(store=FixedStore(["1"])).next_number(date(2026, 3, 1))


class TestInvoiceIntegration:
    def test_an_issued_number_goes_on_the_invoice(self):
        issued = numbering().next_number(date(2026, 3, 1))
        invoice = Invoice(
            number=issued.number,
            issue_date=issued.issue_date,
            seller=party("DE", "DE123456789"),
            buyer=party("DE", "DE987654321"),
            lines=[
                InvoiceLine(
                    description="Consulting",
                    quantity=Decimal(1),
                    unit_price=Money("100.00", "EUR"),
                    vat_rate=Decimal("19"),
                    vat_category=VatCategory.STANDARD,
                )
            ],
        )
        assert invoice.number == "INV-2026-0001"
