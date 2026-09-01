# euinvoice

Invoice PDFs for EU sellers: domestic VAT, private buyers and reverse charge, with sequential numbering.

## Installation

```bash
pip install euinvoice
```

## Usage

```python
from datetime import date
from decimal import Decimal

from euinvoice import Address, Invoice, InvoiceLine, Money, Party, VatCategory

seller = Party(
    name="Nordwind GmbH",
    address=Address(
        line1="Hafenstrasse 1", postal_code="20359", city="Hamburg", country="DE"
    ),
    vat_id="DE123456789",
)
buyer = Party(
    name="Suedlicht AG",
    address=Address(
        line1="Maximilianstrasse 4", postal_code="80539", city="Munich", country="DE"
    ),
    vat_id="DE987654321",
)

invoice = Invoice(
    number="2026-0001",
    issue_date=date(2026, 3, 1),
    seller=seller,
    buyer=buyer,
    lines=[
        InvoiceLine(
            description="Consulting",
            quantity=Decimal("7.5"),
            unit_price=Money("120.00", "EUR"),
            vat_rate=Decimal("19"),
            vat_category=VatCategory.STANDARD,
            unit="hour",
        ),
    ],
)

print(invoice.total_net)    # 900.00 EUR
print(invoice.total_vat)    # 171.00 EUR
print(invoice.total_gross)  # 1071.00 EUR
```

All models are frozen dataclasses and every amount is a `Decimal` bound to a
currency. Line and invoice totals are computed from the lines on access, so a
stored total can never drift away from what it is made of. VAT is rounded per
line, which keeps `invoice.vat_breakdown` adding up exactly to `total_vat`.

A line with `VatCategory.REVERSE_CHARGE` shifts the tax to the buyer: such
lines carry a zero rate, require the buyer's VAT identifier, and cannot be
mixed with taxable lines on the same invoice.

## VAT regimes

The regime follows from the seller country, the buyer country and whether the
buyer's VAT identifier has been validated (`Party(vat_id_validated=True)`):

| Seller | Buyer | Buyer VAT id | Regime |
| --- | --- | --- | --- |
| DE | DE | anything | `DOMESTIC` |
| DE | FR | validated | `REVERSE_CHARGE` |
| DE | FR | missing or unvalidated | `PRIVATE_BUYER` |
| DE | US | anything | `EXPORT` |

```python
from euinvoice import decide_vat_regime

decision = decide_vat_regime(seller, buyer)

print(decision.regime)        # VatRegime.DOMESTIC
print(decision.vat_category)  # VatCategory.STANDARD
print(decision.invoice_note)  # text for the invoice footer, or None
print(decision.explain())     # facts and legal basis, line by line
```

A decision carries the facts it was made from and the article it rests on, so
an invoice can still be defended in an audit years after it was issued.
`invoice.vat_decision` runs the same rules on the invoice's own parties.

## Sequential numbering

Numbers are drawn per series and per period: the counter restarts at one when
the period rolls over and never restarts inside one.

```python
from datetime import date

from euinvoice import (
    InMemoryCounterStore,
    NumberSeries,
    Period,
    SequentialNumbering,
)

numbering = SequentialNumbering(
    NumberSeries("INV", Period.YEARLY), InMemoryCounterStore()
)

issued = numbering.next_number(date(2026, 3, 1))

print(issued.number)   # INV-2026-0001
print(issued.counter)  # 1
print(issued.key)      # CounterKey(series='INV', period='2026')
```

The counter store is a port, so the caller owns the transaction: keep one row
per `CounterKey` and update it in the same transaction that writes the
invoice, and a rolled back invoice gives its number back instead of leaving a
gap. `InMemoryCounterStore` is there for tests and single-process use.

```python
class PostgresCounterStore:
    def __init__(self, connection):
        self._connection = connection

    def next_count(self, key):
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO invoice_counters (series, period, count) "
                "VALUES (%s, %s, 1) "
                "ON CONFLICT (series, period) DO UPDATE "
                "SET count = invoice_counters.count + 1 "
                "RETURNING count",
                (key.series, key.period),
            )
            return cursor.fetchone()[0]
```

A store returns the stored count plus one, starting at one, and never hands
the same value out twice. `SequentialNumbering` checks every value against the
one before it and raises `NumberingError` on a skip or a repeat, so a broken
adapter fails at the first bad number rather than at the next audit.

## Development

```bash
pip install -e .
pytest
```

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
