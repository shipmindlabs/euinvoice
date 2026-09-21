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

## Issuing invoices in the EU without surprises

An invoice goes wrong in two directions: it can state something the rules do
not allow, or it can state something the seller never checked. The package
draws that line in one place. What follows from the data is derived and cannot
be overridden; what needs a fact from outside is asked for by name and refused
until it arrives.

### What it decides for you

- **The regime.** Seller country, buyer country and whether the buyer's
  identifier was validated give one of `DOMESTIC`, `PRIVATE_BUYER`,
  `REVERSE_CHARGE` or `EXPORT`, together with the facts behind it and the
  article it rests on.
- **Every total.** Line net, line VAT, the breakdown per rate bucket and the
  three invoice totals are properties, never fields. There is no way to write
  a total that disagrees with its lines, because there is nothing to write to.
- **Where the rounding falls.** VAT is taken per line, half up, at the minor
  unit of the currency: two places for EUR, none for JPY, three for TND. Ten
  lines of 0.10 EUR at 19% carry 0.20 EUR of VAT, not the 0.19 EUR that the
  same rate on the total would give, and the breakdown adds up either way.
- **Which fields the treatment requires.** Shifting the tax needs the buyer's
  identifier and a note in words; an exempt line needs a reason. `Invoice`
  runs that check on itself and refuses to exist with a gap in it.
- **When the statutory note is already implied.** A cross-border supply to a
  validated buyer and an export print their note by themselves; a domestic
  reverse charge has to write it out, and a payment term does not pass for it.
- **The next number in a series.** One counter per series and period, restarted
  when the period rolls over, checked against the number before it so that a
  store which skips or repeats is reported rather than believed.

### What it refuses to guess

- **The VAT rate.** Rates differ by member state and by what is being sold,
  and they change. The package takes the rate you pass and only checks it
  against the category: a taxable line needs a positive rate, an untaxed one
  needs zero. There is no rate table here, and a stale rate table is worse
  than none.
- **Whether an identifier is real.** `vat_id_validated` records a check you
  made against VIES or whatever your process is; nothing in this package
  touches the network. An identifier nobody verified leaves the tax with the
  seller, which is the safe direction to be wrong in.
- **Where the place of supply moved to.** Distance selling and the One Stop
  Shop can put the supply in the buyer's country. That follows from how you
  are registered and what you sell, so the decision notes it as a fact and
  stops.
- **Why a line is exempt.** It insists on a reason and prints what you wrote;
  the provision depends on the supply, and choosing one for you would be
  guessing at the part an auditor actually reads.
- **Currencies.** `Money` is bound to one currency and two currencies never
  combine. There are no exchange rates and no conversion.
- **How the page is printed.** The HTML is plain and the styling is one sheet
  you can replace; no PDF engine ships with the package, so the caller brings
  the renderer. What comes out is a human-readable document, not a structured
  e-invoice in UBL, Factur-X or XRechnung.

### Not tax advice

What is encoded here are the ordinary cases of the VAT Directive: a supply
between two parties, taxed where the Directive puts it, documented the way
Art. 226 asks for. Member states derogate, and the special schemes — margin
schemes, triangulation, construction services, distance-selling thresholds,
local registration duties — are not modelled at all. The legal references a
decision carries are there so an invoice can be defended, not so it can be
issued unread.

This is a library, and the output is a document rather than an opinion. Have
the treatment confirmed by someone accountable for it before you issue at
scale, and read the warranty clause in the licence for what is promised here:
nothing.

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

## Required fields

A treatment asks for more than the amounts it is printed on. Shifting the tax
needs the buyer's VAT identifier, verified when it comes from another member
state, and a note saying that the recipient accounts for the VAT; an exempt or
zero-rated line needs the reason it bears none. `Invoice` runs the check on
itself and refuses to be built with anything missing, so a gap shows up at
issuing time rather than at the auditor's desk.

```python
from euinvoice import MissingRequiredField, check_required_fields

for field in check_required_fields(seller, buyer, lines, notes):
    print(field)
# notes: the invoice must state that the recipient accounts for the VAT; ...
#        (Directive 2006/112/EC, Art. 226(11a))
```

Run it on a draft and it lists everything that is still missing at once, each
with the rule that asks for it; `MissingRequiredField` carries the same list in
`error.missing`.

The note is only required where the parties do not already imply it: a
cross-border supply to a validated buyer prints the statutory note by itself,
while a domestic reverse charge has to write it out. A note counts when it
states the shift in one of the wordings in `REVERSE_CHARGE_WORDINGS`, the
official languages of the Union, compared with accents, case and hyphens
ignored. A payment term sitting in `notes` therefore does not pass for it.

```python
from euinvoice import states_reverse_charge

states_reverse_charge("Steuerschuldnerschaft des Leistungsempfängers")  # True
states_reverse_charge("Payment within 14 days")                         # False
```

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

## Rendering

`InvoiceDocument` is the print view of an invoice: parties as address blocks,
lines with their totals worked out, the VAT breakdown and the note the regime
asks for. `render_html` turns it into one standalone page.

```python
from euinvoice import InvoiceDocument, render_html, render_pdf

document = InvoiceDocument.from_invoice(invoice)
html = render_html(document)
```

The markup is plain and all styling sits in one sheet, so a different look is
`render_html(document, stylesheet=my_css)` rather than a fork of the template;
`DEFAULT_STYLESHEET` is a starting point to copy from.

Turning that HTML into PDF is a plugin: the package ships no engine, so
installing it never drags a browser into your image. A renderer is anything
with `render(html) -> bytes`.

```python
class WeasyPrintRenderer:
    def render(self, html: str) -> bytes:
        from weasyprint import HTML

        return HTML(string=html).write_pdf()


pdf = render_pdf(invoice, WeasyPrintRenderer())
```

`render_pdf` accepts an `Invoice` or a prepared `InvoiceDocument` and checks
the PDF header on the way out, so a renderer that hands back an error page or
a file path raises `RenderingError` here instead of at the point where someone
opens the file.

## Development

```bash
pip install -e .
pytest
```

## License

MIT

---

Maintained by [Shipmind Labs](https://shipmindlabs.com).
