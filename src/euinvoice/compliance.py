"""The fields a VAT treatment requires, checked before an invoice exists."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

from .parties import Party
from .vat import EU_COUNTRIES, VatCategory, VatRegime, decide_vat_regime

if TYPE_CHECKING:
    from .invoice import InvoiceLine

__all__ = [
    "MissingRequiredField",
    "REVERSE_CHARGE_WORDINGS",
    "RequiredField",
    "check_required_fields",
    "states_reverse_charge",
]

_SUPPLIER_ID = "Directive 2006/112/EC, Art. 226(3)"
_CUSTOMER_ID = "Directive 2006/112/EC, Art. 226(4)"
_EXEMPTION_REASON = "Directive 2006/112/EC, Art. 226(11)"
_REVERSE_CHARGE_NOTE = "Directive 2006/112/EC, Art. 226(11a)"
_CUSTOMER_STATUS = "Implementing Regulation (EU) 282/2011, Art. 18"

_UNTAXED_CATEGORIES = frozenset({VatCategory.EXEMPT, VatCategory.ZERO_RATED})

REVERSE_CHARGE_WORDINGS = (
    "reverse charge",
    "autoliquidation",
    "autoliquidación",
    "autoliquidação",
    "inversión del sujeto pasivo",
    "inversione contabile",
    "Steuerschuldnerschaft des Leistungsempfängers",
    "btw verlegd",
    "verlegging van de heffing",
    "IVA devido pelo adquirente",
    "odwrotne obciążenie",
    "omvänd betalningsskyldighet",
    "omvendt betalingspligt",
    "käännetty verovelvollisuus",
    "přenesení daňové povinnosti",
    "prenesenie daňovej povinnosti",
    "taxare inversă",
    "fordított adózás",
    "αντίστροφη επιβάρυνση",
    "обратно начисляване",
    "prijenos porezne obveze",
    "obrnjena davčna obveznost",
    "pöördmaksustamine",
    "apgrieztā maksāšana",
    "atvirkštinis apmokestinimas",
    "muirear aisiompaithe",
    "ħlas bil-maqlub",
)


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


def _normalised(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.replace("-", " ").split())


_NORMALISED_WORDINGS = tuple(_normalised(text) for text in REVERSE_CHARGE_WORDINGS)


def states_reverse_charge(text: str | None) -> bool:
    """Whether ``text`` says that the recipient accounts for the VAT.

    Art. 226(11a) asks for the statement in words, and every official language
    has its own. ``REVERSE_CHARGE_WORDINGS`` holds the ones recognised here;
    accents, case and hyphens are ignored, so a note typed without them counts.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    normalised = _normalised(text)
    return any(wording in normalised for wording in _NORMALISED_WORDINGS)


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
    leaves_vat_off = bool(categories & _UNTAXED_CATEGORIES)

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

    if shifts_vat:
        missing.extend(_reverse_charge_fields(seller, buyer, notes))

    if leaves_vat_off and not _carries_exemption_reason(seller, buyer, notes):
        missing.append(
            RequiredField(
                "notes",
                "an exempt or zero-rated line must carry the reason it bears "
                "no VAT, either the provision it rests on or a plain "
                "statement of the exemption",
                _EXEMPTION_REASON,
            )
        )

    return tuple(missing)


def _reverse_charge_fields(
    seller: Party, buyer: Party, notes: str | None
) -> list[RequiredField]:
    missing: list[RequiredField] = []
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

    if states_reverse_charge(notes) or _regime_states_reverse_charge(seller, buyer):
        return missing

    if notes is not None and notes.strip():
        requirement = (
            "the note on the invoice says nothing about the shift; it has to "
            "state that the recipient accounts for the VAT, in one of the "
            "wordings in REVERSE_CHARGE_WORDINGS"
        )
    else:
        requirement = (
            "the invoice must state that the recipient accounts for the "
            "VAT; the parties do not imply that note here, so it has to "
            "be written out"
        )
    missing.append(RequiredField("notes", requirement, _REVERSE_CHARGE_NOTE))
    return missing


def _regime_note(seller: Party, buyer: Party) -> str | None:
    # A seller outside the EU has no regime to derive, and so no note either.
    if seller.country not in EU_COUNTRIES:
        return None
    return decide_vat_regime(seller, buyer).invoice_note


def _regime_states_reverse_charge(seller: Party, buyer: Party) -> bool:
    if seller.country not in EU_COUNTRIES:
        return False
    return decide_vat_regime(seller, buyer).regime is VatRegime.REVERSE_CHARGE


def _carries_exemption_reason(
    seller: Party, buyer: Party, notes: str | None
) -> bool:
    # An exemption reference is free text, so any note the seller wrote counts.
    if notes is not None and notes.strip():
        return True
    return _regime_note(seller, buyer) is not None
