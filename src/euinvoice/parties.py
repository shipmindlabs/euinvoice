"""Seller and buyer identities as they appear on an invoice."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Address", "Party"]

_VAT_PREFIXES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "EL",
        "ES",
        "FI",
        "FR",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "XI",
    }
)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    return text


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


@dataclass(frozen=True, slots=True)
class Address:
    """A postal address; the country drives the VAT treatment."""

    line1: str
    postal_code: str
    city: str
    country: str
    line2: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "line1", _required_text(self.line1, "line1"))
        object.__setattr__(
            self, "postal_code", _required_text(self.postal_code, "postal_code")
        )
        object.__setattr__(self, "city", _required_text(self.city, "city"))
        object.__setattr__(self, "line2", _optional_text(self.line2, "line2"))
        country = _required_text(self.country, "country").upper()
        if len(country) != 2 or not country.isalpha():
            raise ValueError(
                f"country must be an ISO 3166-1 alpha-2 code, got {self.country!r}"
            )
        object.__setattr__(self, "country", country)

    def __str__(self) -> str:
        parts = [self.line1]
        if self.line2:
            parts.append(self.line2)
        parts.append(f"{self.postal_code} {self.city}")
        parts.append(self.country)
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class Party:
    """A seller or buyer. A party without a VAT identifier is a private buyer."""

    name: str
    address: Address
    vat_id: str | None = None
    registration_number: str | None = None
    email: str | None = None
    vat_id_validated: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        if not isinstance(self.address, Address):
            raise TypeError("address must be an Address")
        object.__setattr__(
            self,
            "registration_number",
            _optional_text(self.registration_number, "registration_number"),
        )
        object.__setattr__(self, "email", _optional_text(self.email, "email"))
        if not isinstance(self.vat_id_validated, bool):
            raise TypeError("vat_id_validated must be a bool")
        if self.vat_id is None:
            if self.vat_id_validated:
                raise ValueError("vat_id_validated needs a vat_id to validate")
        else:
            raw = _required_text(self.vat_id, "vat_id")
            vat_id = "".join(ch for ch in raw if ch.isalnum()).upper()
            if len(vat_id) < 4:
                raise ValueError(
                    f"vat_id is not a plausible VAT identifier: {self.vat_id!r}"
                )
            object.__setattr__(self, "vat_id", vat_id)

    @property
    def country(self) -> str:
        return self.address.country

    @property
    def is_business(self) -> bool:
        return self.vat_id is not None

    @property
    def vat_country(self) -> str | None:
        """Country prefix of the VAT identifier, when it carries a known one."""
        if self.vat_id is None:
            return None
        prefix = self.vat_id[:2]
        return prefix if prefix in _VAT_PREFIXES else None
