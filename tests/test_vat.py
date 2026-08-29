"""Tests for the VAT regime decision."""

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from euinvoice import (
    Address,
    Invoice,
    InvoiceLine,
    Money,
    Party,
    VatCategory,
    VatRegime,
    decide_vat_regime,
)


def party(
    country: str, vat_id: str | None = None, validated: bool = False
) -> Party:
    return Party(
        name=f"Party {country}",
        address=Address(
            line1="Main 1", postal_code="10000", city="Town", country=country
        ),
        vat_id=vat_id,
        vat_id_validated=validated,
    )


class TestPartyValidationFlag:
    def test_defaults_to_unvalidated(self):
        assert party("DE", "DE123456789").vat_id_validated is False

    def test_cannot_be_set_without_a_vat_id(self):
        with pytest.raises(ValueError):
            party("DE", None, validated=True)


class TestDomestic:
    def test_same_country_is_domestic(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("DE", "DE987654321", validated=True)
        )
        assert decision.regime is VatRegime.DOMESTIC
        assert decision.vat_category is VatCategory.STANDARD
        assert decision.charges_seller_vat
        assert decision.invoice_note is None

    def test_domestic_private_buyer_is_still_domestic(self):
        decision = decide_vat_regime(party("DE", "DE123456789"), party("DE"))
        assert decision.regime is VatRegime.DOMESTIC


class TestReverseCharge:
    def test_validated_buyer_in_another_member_state(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("FR", "FR12345678901", validated=True)
        )
        assert decision.regime is VatRegime.REVERSE_CHARGE
        assert decision.vat_category is VatCategory.REVERSE_CHARGE
        assert not decision.charges_seller_vat
        assert "reverse charge" in decision.invoice_note.lower()

    def test_greek_buyer_uses_the_el_prefix(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("GR", "EL123456789", validated=True)
        )
        assert decision.regime is VatRegime.REVERSE_CHARGE
        assert not any("issued by" in fact for fact in decision.facts)

    def test_identifier_from_another_state_is_recorded(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("FR", "NL123456789B01", validated=True)
        )
        assert decision.regime is VatRegime.REVERSE_CHARGE
        assert any("issued by NL" in fact for fact in decision.facts)


class TestPrivateBuyer:
    def test_cross_border_buyer_without_vat_id(self):
        decision = decide_vat_regime(party("DE", "DE123456789"), party("FR"))
        assert decision.regime is VatRegime.PRIVATE_BUYER
        assert decision.vat_category is VatCategory.STANDARD
        assert decision.charges_seller_vat

    def test_unvalidated_vat_id_does_not_shift_the_tax(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("FR", "FR12345678901")
        )
        assert decision.regime is VatRegime.PRIVATE_BUYER
        assert any("never validated" in fact for fact in decision.facts)

    def test_identifier_without_eu_prefix_does_not_shift_the_tax(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("FR", "ZZ12345678", validated=True)
        )
        assert decision.regime is VatRegime.PRIVATE_BUYER


class TestExport:
    def test_buyer_outside_the_eu(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("US", "US123456789", validated=True)
        )
        assert decision.regime is VatRegime.EXPORT
        assert decision.vat_category is VatCategory.ZERO_RATED
        assert not decision.charges_seller_vat

    def test_seller_outside_the_eu_is_out_of_scope(self):
        with pytest.raises(ValueError):
            decide_vat_regime(party("US", "US123456789"), party("DE"))


class TestExplanation:
    def test_explanation_carries_facts_and_legal_basis(self):
        decision = decide_vat_regime(
            party("DE", "DE123456789"), party("FR", "FR12345678901", validated=True)
        )
        text = decision.explain()
        assert "reverse-charge" in text
        assert "DE" in text and "FR" in text
        assert "Art. 196" in text
        assert len(decision.facts) >= 3

    def test_decision_is_frozen(self):
        decision = decide_vat_regime(party("DE", "DE123456789"), party("DE"))
        with pytest.raises(FrozenInstanceError):
            decision.regime = VatRegime.EXPORT


class TestInvoiceIntegration:
    def test_invoice_exposes_its_regime(self):
        invoice = Invoice(
            number="2026-0001",
            issue_date=date(2026, 3, 1),
            seller=party("DE", "DE123456789"),
            buyer=party("FR", "FR12345678901", validated=True),
            lines=[
                InvoiceLine(
                    description="Consulting",
                    quantity=Decimal(1),
                    unit_price=Money("100.00", "EUR"),
                    vat_rate=Decimal(0),
                    vat_category=VatCategory.REVERSE_CHARGE,
                )
            ],
        )
        assert invoice.vat_regime is VatRegime.REVERSE_CHARGE
        assert invoice.vat_decision.vat_category is VatCategory.REVERSE_CHARGE
        assert invoice.total_vat == Money.zero("EUR")
