"""The fields a VAT treatment requires, checked before an invoice exists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from .parties import Party
from .vat import EU_COUNTRIES, VatCategory, VatRegime, decide_vat_regime

if TYPE_CHECKING:
    from .invoice import InvoiceLine

__all__ = ["MissingRequiredField", "RequiredField", "check_required_fields"]

_SUPPLIER_ID = "Directive 2006/112/EC, Art. 226(3)"
_CUSTOMER_ID = "Directive 2006/112/EC, Art. 226(4)"
_REVERSE_CHARGE_NOTE = "Directive 2006/112/EC, Art. 226(11a)"
_CUSTOMER_STATUS = "Implementing Regulation (EU) 282/2011, Art. 18"


@dataclass(frozen=True, slots=True)
class RequiredField:
    """A field the VAT treatment asks for, with the rule that asks for it."""

    field: str
    requirement: str
    legal_reference: str

    def __str__(self) -> str:
        return f"{self.field}: {self.requirement} ({self.legal_reference})"


class MissingRequiredField(ValueError):
    """Raised when an invoice omits a field its VAT treatment requires."""

    def __init__(self, missing: Sequence[RequiredField]) -> None:
        self.missing = tuple(missing)
        listed = "; ".join(str(field) for field in self.missing)
        super().__init__(f"the invoice is missing required fields: {listed}")


def check_required_fields(
    seller: Party,
    buyer: Party,
    lines: Sequence[InvoiceLine],
    notes: str | None = None,
) -> tuple[RequiredField, ...]:
    """Every required field this supply still lacks, in reading order.

    Run it on a draft to see what an invoice needs before there is one.
    ``Invoice`` runs it on itself and refuses to be built with anything
    missing, so a gap shows up at issuing time rather than in an audit.
    """
    if not isinstance(seller, Party):
        raise TypeError("seller must be a Party")
    if not isinstance(buyer, Party):
        raise TypeError("buyer must be a Party")

    categories = {line.vat_category for line in lines}
    charges_vat = any(category.is_taxable for category in categories)
    shifts_vat = VatCategory.REVERSE_CHARGE in categories

    missing: list[RequiredField] = []
    if seller.vat_id is None and (charges_vat or shifts_vat):
        missing.append(
            RequiredField(
                "seller.vat_id",
                "a seller that charges VAT or shifts it to the buyer must "
                "state the identifier it supplies under",
                _SUPPLIER_ID,
            )
        )

    if not shifts_vat:
        return tuple(missing)

    if buyer.vat_id is None:
        missing.append(
            RequiredField(
                "buyer.vat_id",
                "the recipient who becomes liable for the tax must be "
                "identified by its VAT identifier",
                _CUSTOMER_ID,
            )
        )
    elif buyer.country != seller.country:
        if not buyer.vat_id_validated:
            missing.append(
                RequiredField(
                    "buyer.vat_id_validated",
                    "an identifier from another member state must be verified "
                    "before the tax can be shifted",
                    _CUSTOMER_STATUS,
                )
            )
        elif buyer.vat_country is None:
            missing.append(
                RequiredField(
                    "buyer.vat_id",
                    "the identifier names no member state, so it does not "
                    "prove a taxable person abroad",
                    _CUSTOMER_STATUS,
                )
            )

    if not _carries_reverse_charge_note(seller, buyer, notes):
        missing.append(
            RequiredField(
                "notes",
                "the invoice must state that the recipient accounts for the "
                "VAT; the parties do not imply that note here, so it has to "
                "be written out",
                _REVERSE_CHARGE_NOTE,
            )
        )
    return tuple(missing)


def _carries_reverse_charge_note(
    seller: Party, buyer: Party, notes: str | None
) -> bool:
    if notes is not None and notes.strip():
        return True
    # A seller outside the EU has no regime to derive, and so no note either.
    if seller.country not in EU_COUNTRIES:
        return False
    return decide_vat_regime(seller, buyer).regime is VatRegime.REVERSE_CHARGE
