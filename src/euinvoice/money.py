"""Money: an exact amount bound to a single currency."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Union

__all__ = ["CurrencyMismatch", "Money", "minor_unit_exponent", "to_decimal"]

Numeric = Union[Decimal, int, str]

_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)

_THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})


class CurrencyMismatch(ValueError):
    """Raised when amounts in different currencies are combined."""


def minor_unit_exponent(currency: str) -> int:
    """Number of decimal places the currency is booked in."""
    code = currency.upper()
    if code in _ZERO_DECIMAL_CURRENCIES:
        return 0
    if code in _THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def to_decimal(value: Numeric) -> Decimal:
    """Convert an accepted numeric input to Decimal.

    Floats are rejected: binary fractions cannot represent tax amounts exactly.
    """
    if isinstance(value, bool):
        raise TypeError("bool is not a valid numeric value")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"not a valid decimal value: {value!r}") from exc
    else:
        raise TypeError(f"expected Decimal, int or str, got {type(value).__name__}")
    if not result.is_finite():
        raise ValueError("value must be finite")
    return result


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in a single currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")
        code = self.currency.strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(
                f"currency must be a 3-letter ISO 4217 code, got {self.currency!r}"
            )
        object.__setattr__(self, "currency", code)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    @property
    def exponent(self) -> int:
        return minor_unit_exponent(self.currency)

    def rounded(self) -> Money:
        """The amount snapped to the minor unit of its currency, half up."""
        quantum = Decimal(1).scaleb(-self.exponent)
        return Money(
            self.amount.quantize(quantum, rounding=ROUND_HALF_UP), self.currency
        )

    def is_zero(self) -> bool:
        return self.amount == 0

    def _require_same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatch(
                f"{self.currency} and {other.currency} cannot be combined"
            )

    def __add__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._require_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Numeric) -> Money:
        return Money(self.amount * to_decimal(factor), self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount >= other.amount

    def __str__(self) -> str:
        return f"{self.rounded().amount} {self.currency}"
