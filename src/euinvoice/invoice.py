"""The invoice document: parties, lines, and totals derived from the lines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Sequence

from .money import CurrencyMismatch, Money, to_decimal
from .parties import Party

__all__ = ["Invoice", "InvoiceLine", "VatBreakdownRow", "VatCategory"]

_HUNDRED = Decimal(100)


class VatCategory(Enum):
    """How a line is treated for VAT purposes."""

    STANDARD = "standard"
    REDUCED = "reduced"
    ZERO_RATED = "zero-rated"
    EXEMPT = "exempt"
    REVERSE_CHARGE = "reverse-charge"

    @property
    def is_taxable(self) -> bool:
        return self in (VatCategory.STANDARD, VatCategory.REDUCED)


@dataclass(frozen=True, slots=True)
class VatBreakdownRow:
    """One rate bucket of an invoice, as printed under the totals."""

    category: VatCategory
    rate: Decimal
    net: Money
    vat: Money

    @property
    def gross(self) -> Money:
        return self.net + self.vat


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """A single billed position. Its totals are derived, not supplied."""

    description: str
    quantity: Decimal
    unit_price: Money
    vat_rate: Decimal = Decimal(0)
    vat_category: VatCategory = VatCategory.STANDARD
    unit: str = "unit"

    def __post_init__(self) -> None:
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description must be a non-empty string")
        object.__setattr__(self, "description", self.description.strip())

        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit must be a non-empty string")
        object.__setattr__(self, "unit", self.unit.strip())

        quantity = to_decimal(self.quantity)
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        object.__setattr__(self, "quantity", quantity)

        if not isinstance(self.unit_price, Money):
            raise TypeError("unit_price must be a Money")
        if self.unit_price.amount < 0:
            raise ValueError("unit_price must not be negative")

        if not isinstance(self.vat_category, VatCategory):
            raise TypeError("vat_category must be a VatCategory")

        rate = to_decimal(self.vat_rate)
        if not Decimal(0) <= rate <= _HUNDRED:
            raise ValueError("vat_rate must be a percentage between 0 and 100")
        if self.vat_category.is_taxable and rate == 0:
            raise ValueError(
                f"a {self.vat_category.value} line needs a positive VAT rate"
            )
        if not self.vat_category.is_taxable and rate != 0:
            raise ValueError(
                f"a {self.vat_category.value} line must carry a zero VAT rate"
            )
        object.__setattr__(self, "vat_rate", rate)

    @property
    def currency(self) -> str:
        return self.unit_price.currency

    @property
    def net(self) -> Money:
        return (self.unit_price * self.quantity).rounded()

    @property
    def vat(self) -> Money:
        return Money(self.net.amount * self.vat_rate / _HUNDRED, self.currency).rounded()

    @property
    def gross(self) -> Money:
        return self.net + self.vat


@dataclass(frozen=True, slots=True)
class Invoice:
    """An invoice. Every total is computed from ``lines`` on access."""

    number: str
    issue_date: date
    seller: Party
    buyer: Party
    lines: Sequence[InvoiceLine]
    due_date: date | None = None
    supply_date: date | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.number, str) or not self.number.strip():
            raise ValueError("number must be a non-empty string")
        object.__setattr__(self, "number", self.number.strip())

        if not isinstance(self.issue_date, date):
            raise TypeError("issue_date must be a date")
        if not isinstance(self.seller, Party):
            raise TypeError("seller must be a Party")
        if not isinstance(self.buyer, Party):
            raise TypeError("buyer must be a Party")

        lines = tuple(self.lines)
        if not lines:
            raise ValueError("an invoice needs at least one line")
        for line in lines:
            if not isinstance(line, InvoiceLine):
                raise TypeError("every line must be an InvoiceLine")
        currency = lines[0].currency
        for line in lines:
            if line.currency != currency:
                raise CurrencyMismatch(
                    f"invoice lines mix {currency} and {line.currency}"
                )
        object.__setattr__(self, "lines", lines)

        if self.due_date is not None:
            if not isinstance(self.due_date, date):
                raise TypeError("due_date must be a date")
            if self.due_date < self.issue_date:
                raise ValueError("due_date cannot precede issue_date")
        if self.supply_date is not None and not isinstance(self.supply_date, date):
            raise TypeError("supply_date must be a date")

        if self.notes is not None:
            if not isinstance(self.notes, str):
                raise TypeError("notes must be a string")
            object.__setattr__(self, "notes", self.notes.strip() or None)

        categories = {line.vat_category for line in lines}
        if VatCategory.REVERSE_CHARGE in categories:
            if any(category.is_taxable for category in categories):
                raise ValueError(
                    "reverse-charge lines cannot be mixed with taxable lines"
                )
            if self.buyer.vat_id is None:
                raise ValueError(
                    "a reverse-charge invoice requires the buyer's VAT identifier"
                )

    @property
    def currency(self) -> str:
        return self.lines[0].currency

    @property
    def total_net(self) -> Money:
        total = Money.zero(self.currency)
        for line in self.lines:
            total = total + line.net
        return total

    @property
    def total_vat(self) -> Money:
        total = Money.zero(self.currency)
        for line in self.lines:
            total = total + line.vat
        return total

    @property
    def total_gross(self) -> Money:
        return self.total_net + self.total_vat

    @property
    def vat_breakdown(self) -> tuple[VatBreakdownRow, ...]:
        """Net and VAT per rate bucket, in the order the rates first appear."""
        buckets: dict[tuple[VatCategory, Decimal], list[Money]] = {}
        zero = Money.zero(self.currency)
        for line in self.lines:
            key = (line.vat_category, line.vat_rate)
            bucket = buckets.setdefault(key, [zero, zero])
            bucket[0] = bucket[0] + line.net
            bucket[1] = bucket[1] + line.vat
        return tuple(
            VatBreakdownRow(category=category, rate=rate, net=net, vat=vat)
            for (category, rate), (net, vat) in buckets.items()
        )

    @property
    def is_reverse_charge(self) -> bool:
        return any(
            line.vat_category is VatCategory.REVERSE_CHARGE for line in self.lines
        )
