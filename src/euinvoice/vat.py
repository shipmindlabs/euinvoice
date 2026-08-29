"""How a supply is taxed: the VAT regime and the reasoning behind it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .parties import Party

__all__ = [
    "EU_COUNTRIES",
    "VatCategory",
    "VatDecision",
    "VatRegime",
    "decide_vat_regime",
]

EU_COUNTRIES = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GR",
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
    }
)


def _vat_prefix(country: str) -> str:
    """The VAT identifier prefix a member state issues for its country code."""
    return "EL" if country == "GR" else country


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


class VatRegime(Enum):
    """The tax treatment of a supply between two parties."""

    DOMESTIC = "domestic"
    PRIVATE_BUYER = "private-buyer"
    REVERSE_CHARGE = "reverse-charge"
    EXPORT = "export"

    @property
    def charges_seller_vat(self) -> bool:
        return self in (VatRegime.DOMESTIC, VatRegime.PRIVATE_BUYER)


@dataclass(frozen=True, slots=True)
class VatDecision:
    """A regime together with the facts and the rule it was derived from."""

    regime: VatRegime
    vat_category: VatCategory
    seller_country: str
    buyer_country: str
    buyer_vat_id: str | None
    buyer_vat_id_validated: bool
    legal_reference: str
    facts: tuple[str, ...]
    invoice_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", tuple(self.facts))

    @property
    def charges_seller_vat(self) -> bool:
        return self.regime.charges_seller_vat

    def explain(self) -> str:
        """The decision as text, for the audit trail or the invoice footer."""
        lines = [f"VAT regime: {self.regime.value}"]
        lines.extend(f"- {fact}" for fact in self.facts)
        lines.append(f"Legal basis: {self.legal_reference}")
        return "\n".join(lines)


def decide_vat_regime(seller: Party, buyer: Party) -> VatDecision:
    """Decide how a supply from ``seller`` to ``buyer`` is taxed.

    The regime follows from the seller country, the buyer country and whether
    the buyer's VAT identifier was validated. The returned decision carries the
    facts it was made from, so the invoice can still be defended years later.
    """
    if not isinstance(seller, Party):
        raise TypeError("seller must be a Party")
    if not isinstance(buyer, Party):
        raise TypeError("buyer must be a Party")

    seller_country = seller.country
    buyer_country = buyer.country
    if seller_country not in EU_COUNTRIES:
        raise ValueError(
            "the seller must be established in the EU, "
            f"got {seller_country}"
        )

    facts = [
        f"Seller is established in {seller_country}.",
        f"Buyer is established in {buyer_country}.",
    ]
    if buyer.vat_id is None:
        facts.append("Buyer quoted no VAT identifier.")
    elif buyer.vat_id_validated:
        facts.append(f"Buyer quoted VAT identifier {buyer.vat_id}, validated.")
    else:
        facts.append(f"Buyer quoted VAT identifier {buyer.vat_id}, not validated.")

    def decided(
        regime: VatRegime,
        category: VatCategory,
        legal_reference: str,
        invoice_note: str | None = None,
    ) -> VatDecision:
        return VatDecision(
            regime=regime,
            vat_category=category,
            seller_country=seller_country,
            buyer_country=buyer_country,
            buyer_vat_id=buyer.vat_id,
            buyer_vat_id_validated=buyer.vat_id_validated,
            legal_reference=legal_reference,
            facts=tuple(facts),
            invoice_note=invoice_note,
        )

    if buyer_country == seller_country:
        facts.append(
            "Both parties are in the same country, so the supply is domestic "
            "and the seller charges its own VAT; a VAT identifier does not "
            "change that."
        )
        return decided(
            VatRegime.DOMESTIC,
            VatCategory.STANDARD,
            "Directive 2006/112/EC, Art. 193 (the supplier accounts for the VAT)",
        )

    if buyer_country not in EU_COUNTRIES:
        facts.append(
            "The buyer is outside the EU, so the supply falls outside the "
            "scope of EU VAT."
        )
        return decided(
            VatRegime.EXPORT,
            VatCategory.ZERO_RATED,
            "Directive 2006/112/EC, Art. 146 (exports are exempt with credit)",
            "Export outside the EU - no EU VAT charged "
            "(Directive 2006/112/EC, Art. 146).",
        )

    if buyer.vat_id is None:
        facts.append(
            "A buyer without a VAT identifier is treated as a private person, "
            "so the seller charges its own VAT."
        )
        facts.append(
            "Distance selling and the One Stop Shop can move the place of "
            "supply to the buyer's country; that is a registration choice and "
            "is not decided here."
        )
        return decided(
            VatRegime.PRIVATE_BUYER,
            VatCategory.STANDARD,
            "Directive 2006/112/EC, Art. 45 (supplies to non-taxable persons)",
        )

    if not buyer.vat_id_validated:
        facts.append(
            "The identifier was never validated, and an unproven identifier "
            "cannot carry the tax over to the buyer."
        )
        return decided(
            VatRegime.PRIVATE_BUYER,
            VatCategory.STANDARD,
            "Implementing Regulation (EU) 282/2011, Art. 18 "
            "(evidence of the customer's status)",
        )

    if buyer.vat_country is None:
        facts.append(
            "The identifier carries no EU member state prefix, so it does not "
            f"prove a taxable person in {buyer_country}."
        )
        return decided(
            VatRegime.PRIVATE_BUYER,
            VatCategory.STANDARD,
            "Implementing Regulation (EU) 282/2011, Art. 18 "
            "(evidence of the customer's status)",
        )

    if buyer.vat_country != _vat_prefix(buyer_country):
        facts.append(
            f"The identifier was issued by {buyer.vat_country} while the "
            f"buyer's address is in {buyer_country}."
        )
    facts.append(
        "Both parties are taxable persons in different member states, so the "
        "buyer accounts for the VAT."
    )
    return decided(
        VatRegime.REVERSE_CHARGE,
        VatCategory.REVERSE_CHARGE,
        "Directive 2006/112/EC, Art. 44 and Art. 196 (reverse charge)",
        "Reverse charge - VAT to be accounted for by the recipient "
        "(Directive 2006/112/EC, Art. 196).",
    )
