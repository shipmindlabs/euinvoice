"""Invoice PDFs for EU sellers with VAT handling and sequential numbering."""

from .invoice import Invoice, InvoiceLine, VatBreakdownRow
from .money import CurrencyMismatch, Money
from .numbering import (
    CounterKey,
    CounterStore,
    InMemoryCounterStore,
    IssuedNumber,
    NumberingError,
    NumberSeries,
    Period,
    SequentialNumbering,
)
from .parties import Address, Party
from .vat import (
    EU_COUNTRIES,
    VatCategory,
    VatDecision,
    VatRegime,
    decide_vat_regime,
)

__version__ = "0.1.0"

__all__ = [
    "Address",
    "CounterKey",
    "CounterStore",
    "CurrencyMismatch",
    "EU_COUNTRIES",
    "InMemoryCounterStore",
    "Invoice",
    "InvoiceLine",
    "IssuedNumber",
    "Money",
    "NumberSeries",
    "NumberingError",
    "Party",
    "Period",
    "SequentialNumbering",
    "VatBreakdownRow",
    "VatCategory",
    "VatDecision",
    "VatRegime",
    "__version__",
    "decide_vat_regime",
]
